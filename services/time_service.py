import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATE_TIME_PATTERNS = [
    r"\bwhat('?s| is)?\s+(today'?s\s+)?date\b",
    r"\bwhat\s+time\s+is\s+it\b",
    r"\bкакое\s+сегодня\s+число\b",
    r"\bкакая\s+сегодня\s+дата\b",
    r"\bкоторый\s+час\b",
    r"\bсколько\s+времени\b",
]


def is_date_or_time_question(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in DATE_TIME_PATTERNS)


def now_dt(timezone_name: str | None) -> datetime:
    if not timezone_name:
        return datetime.now()
    try:
        return datetime.now(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        return datetime.now()


def format_now_lines(timezone_name: str | None, lang: str) -> tuple[str, str]:
    now = now_dt(timezone_name)
    if lang == "en":
        return (f"Now: {now.strftime('%H:%M')}", f"Today: {now.strftime('%Y-%m-%d')}")
    return (f"Сейчас: {now.strftime('%H:%M')}", f"Сегодня: {now.strftime('%d.%m.%Y')}")
