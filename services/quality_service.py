from __future__ import annotations

from dataclasses import dataclass


BLOCKED_HISTORY_SNIPPETS = (
    "Сервис LLM временно недоступен",
    "Пока доступны /price",
    "My apologies, I seem to be stuck in crypto-test mode",
)


OOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical": ("диагноз", "лечение", "таблетк", "дозировк", "симптом", "prescription", "diagnosis"),
    "legal": ("юрид", "закон", "иск", "договор", "суд", "attorney", "legal advice"),
    "financial": ("куда вложить", "инвестир", "кредит", "ипотек", "trading signal", "buy now"),
}


@dataclass(frozen=True)
class ResponseQuality:
    score: float
    reasons: tuple[str, ...]


def sanitize_history(history: list[dict[str, str]], max_items: int) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history:
        role = (item.get("role") or "").strip()
        content = " ".join((item.get("content") or "").split()).strip()
        if role not in {"user", "assistant"}:
            continue
        if not content:
            continue
        if any(snippet in content for snippet in BLOCKED_HISTORY_SNIPPETS):
            continue
        if len(content) > 1800:
            content = content[:1800].rstrip() + "..."
        cleaned.append({"role": role, "content": content})
    return cleaned[-max_items:]


def detect_ood_topic(text: str) -> str | None:
    t = (text or "").lower()
    for topic, words in OOD_KEYWORDS.items():
        if any(word in t for word in words):
            return topic
    return None


def ood_fallback_message(topic: str, lang: str) -> str:
    if lang == "en":
        if topic == "medical":
            return "I cannot provide medical prescriptions. I can help structure questions for a licensed doctor."
        if topic == "legal":
            return "I cannot provide legal advice. I can help prepare questions for a qualified lawyer."
        if topic == "financial":
            return "I cannot provide investment directives. I can help compare options and list risks."
        return "I may be outside my reliable scope. I can help structure your request."

    if topic == "medical":
        return "Я не даю медицинские назначения. Могу помочь структурировать вопросы для профильного врача."
    if topic == "legal":
        return "Я не даю юридические рекомендации. Могу помочь подготовить вопросы для юриста."
    if topic == "financial":
        return "Я не даю инвестиционных указаний. Могу помочь сравнить варианты и риски."
    return "Запрос вне надежной зоны. Могу помочь структурировать задачу."


def score_response(text: str, lang: str) -> ResponseQuality:
    response = (text or "").strip()
    if not response:
        return ResponseQuality(score=0.0, reasons=("empty",))

    score = 1.0
    reasons: list[str] = []

    if len(response) < 20:
        score -= 0.35
        reasons.append("too_short")

    cyr = sum(1 for ch in response if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    lat = sum(1 for ch in response if "a" <= ch.lower() <= "z")
    if lang == "ru" and (cyr == 0 or lat > cyr):
        score -= 0.45
        reasons.append("lang_mismatch")

    low = response.lower()
    if "i do not have a response yet" in low:
        score -= 0.6
        reasons.append("empty_default")
    if "временно недоступ" in low:
        score -= 0.4
        reasons.append("service_reply")

    parts = [p.strip().lower() for p in low.replace("?", ".").replace("!", ".").split(".") if p.strip()]
    if len(parts) >= 2 and len(set(parts)) <= max(1, len(parts) // 2):
        score -= 0.25
        reasons.append("repetition")

    score = max(0.0, min(1.0, score))
    return ResponseQuality(score=score, reasons=tuple(reasons))
