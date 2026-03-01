from datetime import datetime
from dataclasses import replace
from uuid import uuid4

from aiogram import F, Router, types

from db import (
    get_conversation_history,
    memory_get,
    memory_build_context,
    save_conversation_history,
    set_cache_value,
    user_settings_get_full,
    user_settings_set_response_profile,
)
from handlers.context import AppContext
from services.assistant_intent_service import INTENT_CHAT, detect_assistant_intent
from services.assistant_tools_service import run_assistant_tool
from services.http_service import ExternalAPIError
from services.llm_service import build_prompt, call_ollama
from services.messages import t
from services.quality_service import (
    detect_ood_topic,
    ood_fallback_message,
    sanitize_history,
    score_response,
)
from services.routing import RouteType, determine_route, should_persist_history
from services.time_service import format_now_lines, is_date_or_time_question
from services.ux_service import memory_chips_markup


def _request_id() -> str:
    return uuid4().hex[:12]


def _cache_key_last_user(user_id: int) -> str:
    return f"ux:last_user:{user_id}"


def _cache_key_last_assistant(user_id: int) -> str:
    return f"ux:last_assistant:{user_id}"


def _remember_last_turn(*, user_id: int, user_text: str | None = None, assistant_text: str | None = None) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    if user_text:
        set_cache_value(_cache_key_last_user(user_id), user_text[:2000], now_iso)
    if assistant_text:
        set_cache_value(_cache_key_last_assistant(user_id), assistant_text[:3000], now_iso)


def _local_chat_fallback(text: str) -> str | None:
    t = (text or "").strip().lower()
    if t in {"тут?", "тут", "ты тут", "ты здесь", "здесь?", "here?", "you here"}:
        return "chat_fallback_here"
    if "как я могу помочь тебе стать лучше" in t:
        return "chat_fallback_improve"
    if len(t) > 20:
        return "chat_fallback_structure"
    return None


def _confidence_threshold(mode: str) -> float:
    value = (mode or "normal").strip().lower()
    if value == "fast":
        return 0.4
    if value == "precise":
        return 0.7
    return 0.55


def _estimate_confidence(
    text: str,
    llm_response: str,
    lang: str,
    *,
    base_score: float | None = None,
) -> tuple[float, bool]:
    score = base_score if base_score is not None else score_response(llm_response, lang).score
    user_text = (text or "").strip()
    words = [w for w in user_text.split() if w.strip()]
    low = user_text.lower()
    ambiguous_markers = ("это", "такое", "там", "сюда", "туда", "this", "that", "there")
    if len(words) <= 3:
        score -= 0.2
    if len(user_text) <= 12:
        score -= 0.15
    if "?" not in user_text and len(words) <= 5:
        score -= 0.1
    if any(marker in low for marker in ambiguous_markers):
        score -= 0.1
    score = max(0.0, min(1.0, score))
    need_clarification = score < 0.999 and (len(words) <= 2 or any(marker in low for marker in ambiguous_markers))
    return score, need_clarification


def _clarifying_question(text: str, lang: str) -> str:
    base = (text or "").strip()
    if lang == "en":
        return f"Can you clarify your target result and constraints for: '{base}'?"
    return f"Уточните цель и ограничения для запроса: «{base}»."


def _profile_style_context(profile: dict[str, object], lang: str) -> str:
    style = str(profile.get("response_style") or "balanced")
    density = str(profile.get("response_density") or "auto")
    day_mode = str(profile.get("day_mode") or "workday")
    lines: list[str] = []
    if style == "direct":
        lines.append("Preferred style: direct and pragmatic.")
    elif style == "soft":
        lines.append("Preferred style: calm and supportive.")
    if density == "short":
        lines.append("Preferred response density: very concise.")
    elif density == "detailed":
        lines.append("Preferred response density: detailed.")
    if day_mode:
        lines.append(f"Current day mode: {day_mode}.")
    if not lines:
        return ""
    return "\n".join(lines)


def _adaptive_profile_suggestion(text: str) -> tuple[str | None, str | None]:
    raw = (text or "").strip().lower()
    if not raw:
        return None, None
    style: str | None = None
    density: str | None = None
    if any(x in raw for x in ("кратко", "без воды", "коротко", "short", "brief")):
        density = "short"
    elif any(x in raw for x in ("подробно", "детально", "развернуто", "detailed")):
        density = "detailed"
    if any(x in raw for x in ("жестко", "прямо", "по делу", "direct")):
        style = "direct"
    elif any(x in raw for x in ("мягче", "спокойно", "soft")):
        style = "soft"
    return style, density


def build_chat_router(ctx: AppContext) -> Router:
    router = Router(name="chat")
    router.message.filter(F.chat.type == "private")

    @router.message()
    async def chat(message: types.Message) -> None:
        rid = _request_id()
        uid = message.from_user.id if message.from_user else 0
        text = message.text or ""
        profile = user_settings_get_full(uid) if uid > 0 else {}
        user_mode = str(profile.get("llm_mode") or "normal")
        show_confidence = bool(profile.get("show_confidence"))
        lang = str(profile.get("lang") or ctx.settings.default_lang)
        timezone_name = str(profile.get("timezone_name") or ctx.settings.timezone_name) if (profile.get("timezone_name") or ctx.settings.timezone_name) else None
        weather_city = str(profile.get("weather_city") or ctx.settings.weather_city)
        runtime_settings = replace(
            ctx.settings,
            default_lang=lang,
            timezone_name=timezone_name,
            weather_city=weather_city,
        )
        chips = memory_chips_markup() if uid > 0 else None
        if uid > 0:
            _remember_last_turn(user_id=uid, user_text=text)

        if uid > 0 and bool(profile.get("cognitive_profile", True)):
            suggested_style, suggested_density = _adaptive_profile_suggestion(text)
            current_style = str(profile.get("response_style") or "balanced")
            current_density = str(profile.get("response_density") or "auto")
            next_style = suggested_style or current_style
            next_density = suggested_density or current_density
            if next_style != current_style or next_density != current_density:
                user_settings_set_response_profile(
                    user_id=uid,
                    response_style=next_style,
                    response_density=next_density,
                    updated_at=datetime.now().isoformat(timespec="seconds"),
                )
                profile["response_style"] = next_style
                profile["response_density"] = next_density

        decision = determine_route(
            text=text,
            known_commands=ctx.known_commands,
            is_date_time_question=is_date_or_time_question(text),
        )

        ctx.logger.info(
            "event=route_decision request_id=%s user_id=%s route=%s command=%s",
            rid,
            uid,
            decision.route_type.value,
            decision.command,
        )

        if decision.route_type in {RouteType.KNOWN_COMMAND, RouteType.EMPTY}:
            return

        if decision.route_type == RouteType.DATE_TIME:
            line1, line2 = format_now_lines(runtime_settings.timezone_name, lang)
            await message.reply(f"{line1}\n{line2}")
            return

        if decision.route_type == RouteType.PLAIN_TEXT:
            intent = await detect_assistant_intent(
                text=text,
                settings=runtime_settings,
                mode=user_mode,
                lang=lang,
            )
            threshold = _confidence_threshold(user_mode)
            if intent.need_clarification and intent.clarifying_question and intent.confidence < threshold:
                clarify = f"{t(lang, 'chat_clarify_prefix')}\n{intent.clarifying_question}"
                if show_confidence:
                    clarify = f"{clarify}\n\n{t(lang, 'chat_confidence_line', score=intent.confidence)}"
                await message.reply(clarify, reply_markup=chips)
                return

            if intent.intent != INTENT_CHAT and intent.confidence >= max(0.45, threshold - 0.1):
                tool = await run_assistant_tool(
                    intent=intent.intent,
                    settings=runtime_settings,
                    user_id=uid,
                    lang=lang,
                    args=intent.args,
                )
                if tool:
                    text_out = tool.text
                    if show_confidence:
                        text_out = f"{text_out}\n\n{t(lang, 'chat_confidence_line', score=intent.confidence)}"
                    if uid > 0:
                        _remember_last_turn(user_id=uid, assistant_text=text_out)
                    await message.reply(
                        text_out,
                        parse_mode=tool.parse_mode,
                        disable_web_page_preview=tool.disable_web_page_preview,
                        reply_markup=chips,
                    )
                    return

        history = []
        if message.from_user and should_persist_history(decision):
            history = sanitize_history(
                get_conversation_history(message.from_user.id),
                max_items=ctx.settings.max_history_messages,
            )

        ood_topic = detect_ood_topic(text)
        if ood_topic:
            ctx.logger.info(
                "event=ood_gate request_id=%s user_id=%s topic=%s",
                rid,
                uid,
                ood_topic,
            )
            await message.reply(ood_fallback_message(ood_topic, lang))
            return

        extra_context = memory_build_context(user_id=uid, limit=8) if uid > 0 else ""
        if uid > 0:
            active_session = memory_get(user_id=uid, key="active_session")
            if active_session:
                extra_context = f"{extra_context}\nActive context session: {active_session}".strip()
        style_context = _profile_style_context(profile, lang)
        if style_context:
            extra_context = f"{extra_context}\n{style_context}".strip()
        prompt = build_prompt(
            history=history,
            user_message=text,
            settings=runtime_settings,
            mode=user_mode,
            extra_context=extra_context,
            profile="advisor",
        )

        try:
            llm_response = await call_ollama(prompt, runtime_settings, mode=user_mode, profile="advisor")
        except ExternalAPIError as exc:
            ctx.logger.warning(
                "event=api_error request_id=%s user_id=%s service=%s kind=%s status=%s",
                rid,
                uid,
                exc.service,
                exc.kind,
                exc.status_code,
            )
            local_reply = _local_chat_fallback(text)
            if local_reply:
                reply_text = t(lang, local_reply)
                if uid > 0:
                    _remember_last_turn(user_id=uid, assistant_text=reply_text)
                await message.reply(reply_text, reply_markup=chips)
                return
            unavailable = t(lang, "llm_unavailable")
            if uid > 0:
                _remember_last_turn(user_id=uid, assistant_text=unavailable)
            await message.reply(unavailable, reply_markup=chips)
            return

        quality = score_response(llm_response, lang)
        if message.from_user and should_persist_history(decision):
            if quality.score < 0.45:
                ctx.logger.warning(
                    "event=llm_response_low_quality request_id=%s user_id=%s score=%.2f reasons=%s",
                    rid,
                    uid,
                    quality.score,
                    ",".join(quality.reasons),
                )
            if quality.score < 0.25:
                llm_response = t(lang, "llm_low_quality")

            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": llm_response})
            history = history[-ctx.settings.max_history_messages :]
            save_conversation_history(message.from_user.id, history)

        confidence, need_clarify = _estimate_confidence(
            text,
            llm_response,
            lang,
            base_score=quality.score,
        )
        threshold = _confidence_threshold(user_mode)
        if confidence < threshold and need_clarify:
            clarify = _clarifying_question(text, lang)
            if show_confidence:
                clarify = f"{t(lang, 'chat_clarify_prefix')}\n{clarify}\n\n{t(lang, 'chat_confidence_line', score=confidence)}"
            else:
                clarify = f"{t(lang, 'chat_clarify_prefix')}\n{clarify}"
            if uid > 0:
                _remember_last_turn(user_id=uid, assistant_text=clarify)
            await message.reply(clarify, reply_markup=chips)
            return

        if show_confidence:
            llm_response = f"{llm_response}\n\n{t(lang, 'chat_confidence_line', score=confidence)}"
        if uid > 0:
            active_session = memory_get(user_id=uid, key="active_session")
            if active_session:
                llm_response = f"{llm_response}\n\n🧵 Session: {active_session}"
            _remember_last_turn(user_id=uid, assistant_text=llm_response)
        await message.reply(llm_response, reply_markup=chips)

    return router



