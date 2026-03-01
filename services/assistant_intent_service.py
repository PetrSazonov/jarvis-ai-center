import asyncio
import json
import logging
from dataclasses import dataclass, field

from core.settings import Settings
from services.http_service import ExternalAPIError
from services.llm_service import build_prompt, call_ollama


logger = logging.getLogger("purecompanybot")


@dataclass(frozen=True)
class AssistantIntent:
    intent: str
    confidence: float
    need_clarification: bool = False
    clarifying_question: str = ""
    args: dict[str, str] = field(default_factory=dict)


INTENT_CHAT = "chat"
INTENT_PRICE = "tool_price"
INTENT_WEATHER = "tool_weather"
INTENT_DIGEST = "tool_digest"
INTENT_STATUS = "tool_status"
INTENT_TODAY = "tool_today"
INTENT_ROUTE = "tool_route"
INTENT_PROFILE = "tool_profile"

_ALLOWED_INTENTS = {
    INTENT_CHAT,
    INTENT_PRICE,
    INTENT_WEATHER,
    INTENT_DIGEST,
    INTENT_STATUS,
    INTENT_TODAY,
    INTENT_ROUTE,
    INTENT_PROFILE,
}

_EXTERNAL_TO_INTERNAL_INTENTS = {
    "chat": INTENT_CHAT,
    "price": INTENT_PRICE,
    "weather": INTENT_WEATHER,
    "digest": INTENT_DIGEST,
    "status": INTENT_STATUS,
    "today": INTENT_TODAY,
    "route": INTENT_ROUTE,
    "profile": INTENT_PROFILE,
    "todo": INTENT_CHAT,
    "subs": INTENT_CHAT,
    "fit": INTENT_CHAT,
}

_LEGACY_TO_INTERNAL_INTENTS = {
    INTENT_CHAT: INTENT_CHAT,
    INTENT_PRICE: INTENT_PRICE,
    INTENT_WEATHER: INTENT_WEATHER,
    INTENT_DIGEST: INTENT_DIGEST,
    INTENT_STATUS: INTENT_STATUS,
    INTENT_TODAY: INTENT_TODAY,
    INTENT_ROUTE: INTENT_ROUTE,
    INTENT_PROFILE: INTENT_PROFILE,
}

_REQUIRED_JSON_KEYS = {
    "intent",
    "confidence",
    "need_clarification",
    "clarifying_question",
    "args",
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _should_try_llm_classifier(text: str) -> bool:
    clean = (text or "").strip().lower()
    if not clean:
        return False
    if len(clean) > 72:
        return False
    words = [w for w in clean.split() if w]
    if len(words) > 12:
        return False
    if len(words) <= 4:
        return True

    verb_hints = (
        "покажи",
        "дай",
        "сделай",
        "проверь",
        "построй",
        "открой",
        "show",
        "give",
        "check",
        "build",
        "open",
    )
    topic_hints = (
        "погод",
        "курс",
        "рынок",
        "доллар",
        "евро",
        "бензин",
        "новост",
        "дайдж",
        "status",
        "weather",
        "price",
        "digest",
        "route",
    )
    return clean.startswith(verb_hints) or any(hint in clean for hint in topic_hints)


def _heuristic(text: str, lang: str) -> AssistantIntent:
    lower = (text or "").strip().lower()
    if not lower:
        return AssistantIntent(intent=INTENT_CHAT, confidence=1.0)

    if any(x in lower for x in ("что ты помнишь", "мой профиль", "покажи профиль", "profile", "what do you remember")):
        return AssistantIntent(intent=INTENT_PROFILE, confidence=0.94)

    if any(x in lower for x in ("дайджест", "новост", "digest", "headlines")):
        return AssistantIntent(intent=INTENT_DIGEST, confidence=0.9)

    if any(x in lower for x in ("погода", "температур", "weather", "осадки")):
        return AssistantIntent(intent=INTENT_WEATHER, confidence=0.92)

    if any(x in lower for x in ("статус", "проверь сервис", "health", "services status")):
        return AssistantIntent(intent=INTENT_STATUS, confidence=0.87)

    if any(
        x in lower
        for x in (
            "биткоин",
            "bitcoin",
            "ethereum",
            "eth",
            "btc",
            "крипт",
            "курс",
            "доллар",
            "евро",
            "бензин",
            "рынок",
            "price",
        )
    ):
        return AssistantIntent(intent=INTENT_PRICE, confidence=0.9)

    if any(x in lower for x in ("фокус дня", "план на день", "today", "что сегодня")):
        return AssistantIntent(intent=INTENT_TODAY, confidence=0.82)

    if any(x in lower for x in ("маршрут", "route", "как доехать", "ехать до")):
        if any(x in lower for x in ("дом", "домой", "home")):
            return AssistantIntent(intent=INTENT_ROUTE, confidence=0.9, args={"target": "home"})
        if any(x in lower for x in ("работ", "офис", "work")):
            return AssistantIntent(intent=INTENT_ROUTE, confidence=0.9, args={"target": "work"})
        question = "Уточни маршрут: до дома или до работы?" if lang == "ru" else "Clarify route target: home or work?"
        return AssistantIntent(
            intent=INTENT_ROUTE,
            confidence=0.45,
            need_clarification=True,
            clarifying_question=question,
        )

    return AssistantIntent(intent=INTENT_CHAT, confidence=0.6)


def _extract_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            value = json.loads(raw[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _normalize_payload(payload: dict, *, lang: str) -> AssistantIntent:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    missing = _REQUIRED_JSON_KEYS.difference(payload.keys())
    if missing:
        raise ValueError(f"payload missing keys: {sorted(missing)}")

    intent_raw = payload.get("intent")
    if not isinstance(intent_raw, str):
        raise ValueError("intent must be string")
    intent_key = intent_raw.strip().lower()
    if intent_key in _EXTERNAL_TO_INTERNAL_INTENTS:
        intent = _EXTERNAL_TO_INTERNAL_INTENTS[intent_key]
    else:
        intent = _LEGACY_TO_INTERNAL_INTENTS.get(intent_key, INTENT_CHAT)
    if intent not in _ALLOWED_INTENTS:
        intent = INTENT_CHAT

    confidence_raw = payload.get("confidence")
    try:
        confidence = _clamp(float(confidence_raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc

    need_clarification_raw = _to_bool(payload.get("need_clarification"))
    if need_clarification_raw is None:
        raise ValueError("need_clarification must be bool-like")
    need_clarification = need_clarification_raw

    question_raw = payload.get("clarifying_question")
    if question_raw is None:
        clarifying_question = ""
    elif isinstance(question_raw, str):
        clarifying_question = question_raw.strip()
    else:
        raise ValueError("clarifying_question must be string")

    args = payload.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("args must be object")

    clean_args: dict[str, str] = {}
    target_raw = args.get("target")
    if target_raw is not None:
        target = str(target_raw).strip().lower()
        if target in {"home", "work"}:
            clean_args["target"] = target

    if need_clarification and not clarifying_question:
        clarifying_question = (
            "Уточни, пожалуйста, что именно нужно сделать."
            if lang == "ru"
            else "Please clarify what exactly should be done."
        )

    return AssistantIntent(
        intent=intent,
        confidence=confidence,
        need_clarification=need_clarification,
        clarifying_question=clarifying_question,
        args=clean_args,
    )


async def detect_assistant_intent(*, text: str, settings: Settings, mode: str, lang: str) -> AssistantIntent:
    heuristic = _heuristic(text, lang)
    if heuristic.intent != INTENT_CHAT or heuristic.need_clarification:
        return heuristic
    if not _should_try_llm_classifier(text):
        return heuristic

    user_message = (
        "Classify user request into assistant intent.\n"
        "Return strict JSON object only.\n"
        "Schema:\n"
        "{\n"
        '  "intent": "chat|price|weather|digest|status|today|route|profile|todo|subs|fit",\n'
        '  "confidence": 0.0,\n'
        '  "need_clarification": false,\n'
        '  "clarifying_question": "",\n'
        '  "args": {"target": "home|work"}\n'
        "}\n"
        "Rules:\n"
        "1) Output only valid JSON object.\n"
        "2) Do not invent extra keys.\n"
        "3) If uncertain, use intent=chat.\n"
        "4) For route requests set args.target to home or work.\n\n"
        f"User text: {text}"
    )
    prompt = build_prompt(
        history=[],
        user_message=user_message,
        settings=settings,
        mode=mode,
        profile="classifier",
    )

    try:
        raw = await asyncio.wait_for(
            call_ollama(prompt, settings, mode=mode, profile="classifier"),
            timeout=4.5,
        )
    except (ExternalAPIError, asyncio.TimeoutError, Exception) as exc:
        logger.info(
            "event=intent_classifier_fallback reason=api_or_timeout mode=%s error=%s",
            mode,
            exc.__class__.__name__,
        )
        return heuristic

    payload = _extract_json_object(raw)
    if not payload:
        logger.info("event=intent_classifier_fallback reason=json_parse_failed mode=%s", mode)
        return heuristic

    try:
        normalized = _normalize_payload(payload, lang=lang)
    except ValueError:
        logger.info("event=intent_classifier_fallback reason=json_validation_failed mode=%s", mode)
        return heuristic

    logger.info(
        "event=intent_classifier_result mode=%s intent=%s confidence=%.3f parse_ok=true",
        mode,
        normalized.intent,
        normalized.confidence,
    )
    return normalized
