from datetime import datetime
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from aiogram import F, Router, types

from db import (
    get_cache_value,
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
from services.rag_service import resolve_rag_for_query
from services.routing import RouteType, determine_route, should_persist_history
from services.time_service import format_now_lines, is_date_or_time_question
from services.ux_service import memory_chips_markup


def _request_id() -> str:
    return uuid4().hex[:12]


def _cache_key_last_user(user_id: int) -> str:
    return f"ux:last_user:{user_id}"


def _cache_key_last_assistant(user_id: int) -> str:
    return f"ux:last_assistant:{user_id}"


def _cache_key_pending_clarify(user_id: int) -> str:
    return f"chat:pending_clarify:{user_id}"


def _remember_last_turn(*, user_id: int, user_text: str | None = None, assistant_text: str | None = None) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    if user_text:
        set_cache_value(_cache_key_last_user(user_id), user_text[:2000], now_iso)
    if assistant_text:
        set_cache_value(_cache_key_last_assistant(user_id), assistant_text[:3000], now_iso)


def _set_pending_clarification(
    *,
    user_id: int,
    original_user_query: str,
    clarifying_question: str,
    reason: str,
) -> None:
    payload = {
        "pending_clarification": True,
        "original_user_query": (original_user_query or "").strip()[:2000],
        "clarifying_question": (clarifying_question or "").strip()[:600],
        "reason": (reason or "unknown").strip()[:32],
    }
    set_cache_value(
        _cache_key_pending_clarify(user_id),
        json.dumps(payload, ensure_ascii=False),
        datetime.now().isoformat(timespec="seconds"),
    )


def _clear_pending_clarification(user_id: int) -> None:
    set_cache_value(
        _cache_key_pending_clarify(user_id),
        "",
        datetime.now().isoformat(timespec="seconds"),
    )


def _get_pending_clarification(user_id: int) -> dict[str, str] | None:
    row = get_cache_value(_cache_key_pending_clarify(user_id))
    if not row or not row[0]:
        return None
    raw_value = str(row[0]).strip()
    if not raw_value:
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not bool(payload.get("pending_clarification")):
        return None
    original_user_query = str(payload.get("original_user_query") or "").strip()
    if not original_user_query:
        return None
    updated_at_raw = str(row[1] or "").strip()
    if updated_at_raw:
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
            if datetime.now() - updated_at > timedelta(minutes=20):
                _clear_pending_clarification(user_id)
                return None
        except ValueError:
            pass
    return {
        "original_user_query": original_user_query,
        "clarifying_question": str(payload.get("clarifying_question") or "").strip(),
        "reason": str(payload.get("reason") or "").strip(),
    }


_CLARIFY_SHORT_ACKS = {
    "да",
    "нет",
    "ага",
    "угу",
    "ок",
    "окей",
    "в целом",
    "вообще",
    "для меня",
    "скорее",
    "yes",
    "no",
    "ok",
    "okay",
    "in general",
    "for me",
}

_CLARIFY_CONTEXT_MARKERS = (
    "в целом",
    "для меня",
    "вообще",
    "скорее",
    "про ",
    "о ",
    "about ",
    "for me",
    "my ",
)

_NEW_TOPIC_PREFIXES = (
    "сколько ",
    "какой ",
    "какая ",
    "какие ",
    "когда ",
    "кто ",
    "где ",
    "куда ",
    "как ",
    "что ",
    "почему ",
    "зачем ",
    "when ",
    "what ",
    "why ",
    "how ",
)

_NEW_TOPIC_VERBS = (
    "расскажи",
    "покажи",
    "сделай",
    "дай",
    "объясни",
    "напиши",
    "show",
    "tell",
    "give",
    "explain",
    "write",
)

_NEW_TOPIC_FACT_HINTS = (
    "погода",
    "курс",
    "биткоин",
    "btc",
    "eth",
    "доллар",
    "евро",
    "бензин",
    "новост",
    "date",
    "time",
    "weather",
    "price",
    "news",
)


def _looks_like_new_standalone_query(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    if low.startswith("/"):
        return True
    words = [w for w in low.split() if w]
    if "?" in low:
        return True
    if low.startswith(_NEW_TOPIC_PREFIXES):
        return True
    if len(words) >= 8:
        return True
    if len(words) >= 2 and low.startswith(_NEW_TOPIC_VERBS):
        return True
    if len(words) >= 2 and any(marker in low for marker in _NEW_TOPIC_FACT_HINTS):
        return True
    return False


def _is_contextual_clarification_reply(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    if _looks_like_new_standalone_query(low):
        return False
    if low in _CLARIFY_SHORT_ACKS:
        return True
    if any(marker in low for marker in _CLARIFY_CONTEXT_MARKERS):
        return True
    words = [w for w in low.split() if w]
    return len(words) <= 5 and len(low) <= 48


def _compose_clarified_query(*, original_query: str, clarification_reply: str, lang: str) -> str:
    if lang == "en":
        return f"{original_query}\n\nUser clarification: {clarification_reply}"
    return f"{original_query}\n\nУточнение пользователя: {clarification_reply}"


def _should_answer_with_general_caveat(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    words = [w for w in low.split() if w]
    if len(words) < 3 or len(words) > 20:
        return False
    risk_markers = (
        "диагноз",
        "лечение",
        "medical",
        "юрид",
        "закон",
        "legal",
        "инвест",
        "кредит",
        "finance",
        "security",
        "взлом",
    )
    fact_markers = (
        "дата",
        "время",
        "курс",
        "погода",
        "новост",
        "date",
        "time",
        "price",
        "weather",
        "news",
    )
    if any(marker in low for marker in risk_markers):
        return False
    if any(marker in low for marker in fact_markers):
        return False
    return True


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
        raw_text = message.text or ""
        text = raw_text
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
        pending_clarification = _get_pending_clarification(uid) if uid > 0 else None
        if uid > 0 and pending_clarification:
            if _is_contextual_clarification_reply(raw_text):
                text = _compose_clarified_query(
                    original_query=pending_clarification["original_user_query"],
                    clarification_reply=raw_text.strip(),
                    lang=lang,
                )
                ctx.logger.info(
                    "event=clarify_merge request_id=%s user_id=%s reason=%s",
                    rid,
                    uid,
                    pending_clarification.get("reason", "unknown"),
                )
            else:
                ctx.logger.info("event=clarify_clear_new_topic request_id=%s user_id=%s", rid, uid)
            _clear_pending_clarification(uid)
        if uid > 0:
            _remember_last_turn(user_id=uid, user_text=raw_text)
            if text != raw_text:
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
            if uid > 0:
                _clear_pending_clarification(uid)
            return

        if decision.route_type == RouteType.DATE_TIME:
            if uid > 0:
                _clear_pending_clarification(uid)
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
                if uid > 0:
                    _set_pending_clarification(
                        user_id=uid,
                        original_user_query=raw_text,
                        clarifying_question=intent.clarifying_question,
                        reason="intent",
                    )
                    _remember_last_turn(user_id=uid, assistant_text=clarify)
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
                        _clear_pending_clarification(uid)
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

        rag_payload = {
            "personal": False,
            "context": "",
            "citations_block": "",
            "block_message": None,
        }
        if uid > 0:
            rag_payload = await resolve_rag_for_query(user_id=uid, query=text, lang=lang)
            block_message = rag_payload.get("block_message")
            if isinstance(block_message, str) and block_message.strip():
                if uid > 0:
                    _remember_last_turn(user_id=uid, assistant_text=block_message)
                await message.reply(block_message, reply_markup=chips)
                return
            rag_context = str(rag_payload.get("context") or "").strip()
            if rag_context:
                extra_context = (
                    f"{extra_context}\n{rag_context}\n"
                    "If you use personal data, include citations as [1], [2], ... and do not invent sources."
                ).strip()

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
            if _should_answer_with_general_caveat(raw_text):
                if lang == "en":
                    llm_response = f"In general: {llm_response}"
                else:
                    llm_response = f"Если в целом: {llm_response}"
            else:
                clarify = _clarifying_question(text, lang)
                if show_confidence:
                    clarify = f"{t(lang, 'chat_clarify_prefix')}\n{clarify}\n\n{t(lang, 'chat_confidence_line', score=confidence)}"
                else:
                    clarify = f"{t(lang, 'chat_clarify_prefix')}\n{clarify}"
                if uid > 0:
                    _set_pending_clarification(
                        user_id=uid,
                        original_user_query=raw_text,
                        clarifying_question=clarify,
                        reason="quality",
                    )
                    _remember_last_turn(user_id=uid, assistant_text=clarify)
                await message.reply(clarify, reply_markup=chips)
                return

        citations_block = str(rag_payload.get("citations_block") or "").strip()
        if bool(rag_payload.get("personal")) and citations_block:
            llm_response = f"{llm_response}\n\n{citations_block}"

        if show_confidence:
            llm_response = f"{llm_response}\n\n{t(lang, 'chat_confidence_line', score=confidence)}"
        if uid > 0:
            _clear_pending_clarification(uid)
            active_session = memory_get(user_id=uid, key="active_session")
            if active_session:
                llm_response = f"{llm_response}\n\n🧵 Session: {active_session}"
            _remember_last_turn(user_id=uid, assistant_text=llm_response)
        await message.reply(llm_response, reply_markup=chips)

    return router



