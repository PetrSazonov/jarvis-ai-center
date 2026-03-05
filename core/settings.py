from dataclasses import dataclass
from datetime import date, datetime
import os
import re


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_time_list(raw: str) -> tuple[str, ...]:
    items = [x.strip() for x in raw.split(",") if x.strip()]
    valid: list[str] = []
    for item in items:
        if not re.fullmatch(r"\d{2}:\d{2}", item):
            continue
        hh, mm = item.split(":")
        h = int(hh)
        m = int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            valid.append(f"{h:02d}:{m:02d}")
    return tuple(valid)


def _parse_birth_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%d.%m.%Y").date()


def _parse_mm_dd(raw: str) -> tuple[int, int]:
    value = raw.strip()
    if not re.fullmatch(r"\d{2}-\d{2}", value):
        raise RuntimeError("MOTO_SEASON_START must be in MM-DD format, e.g. 04-15")
    month, day = value.split("-")
    m = int(month)
    d = int(day)
    if not (1 <= m <= 12 and 1 <= d <= 31):
        raise RuntimeError("MOTO_SEASON_START has invalid month/day")
    return m, d


@dataclass(frozen=True)
class Settings:
    bot_token: str
    coingecko_vs: str
    price_currencies: tuple[str, ...]
    ollama_api_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    max_history_messages: int
    system_prompt: str
    default_lang: str
    enable_crypto_watcher: bool
    log_level: str
    timezone_name: str | None
    weather_city: str
    home_address: str | None
    work_address: str | None
    enable_auto_digest: bool
    digest_times: tuple[str, ...]
    digest_chat_id: int | None
    birth_date: date
    moto_season_start_mmdd: tuple[int, int]
    fuel95_source_url: str
    fuel95_moscow_rub: float | None
    feedback_min_chars: int
    style_mode: str
    fitness_vault_chat_id: int | None = None
    fitness_admin_user_id: int | None = None
    fitness_log_chat_id: int | None = None
    enable_prewarm: bool = True
    prewarm_interval_seconds: int = 600
    enable_task_reminders: bool = True
    task_reminder_interval_seconds: int = 45
    enable_llm_enhancer: bool = False
    llm_enhancer_timeout_seconds: float = 3.5
    ollama_soft_timeout_seconds: float = 25.0


DEFAULT_SYSTEM_PROMPT = (
    "You are a local AI companion. Keep responses practical, concise, and helpful. "
    "You can adopt a communication style inspired by public figures, but do not claim "
    "to be them or provide fabricated personal experiences."
)


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN") or os.getenv("\ufeffBOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not found in .env")

    max_history = int(os.getenv("MAX_HISTORY_MESSAGES") or "24")
    if max_history <= 0:
        raise RuntimeError("MAX_HISTORY_MESSAGES must be > 0")

    default_lang = (os.getenv("DEFAULT_LANG") or "ru").lower()
    if default_lang not in {"ru", "en"}:
        raise RuntimeError("DEFAULT_LANG must be 'ru' or 'en'")

    digest_times = _parse_time_list(os.getenv("DIGEST_TIMES") or "07:00,14:00,21:00")
    if not digest_times:
        raise RuntimeError("DIGEST_TIMES must contain at least one valid HH:MM value")

    digest_chat_raw = os.getenv("DIGEST_CHAT_ID")
    digest_chat_id = int(digest_chat_raw) if digest_chat_raw else None

    birth_raw = os.getenv("BIRTH_DATE") or "15.12.1984"
    birth_date = _parse_birth_date(birth_raw)
    moto_mmdd = _parse_mm_dd(os.getenv("MOTO_SEASON_START") or "04-15")
    fuel95_raw = os.getenv("FUEL95_MOSCOW_RUB")
    fuel95_value = float(fuel95_raw) if fuel95_raw else None
    feedback_min_chars = int(os.getenv("FEEDBACK_MIN_CHARS") or "280")
    if feedback_min_chars < 0:
        raise RuntimeError("FEEDBACK_MIN_CHARS must be >= 0")
    style_mode = (os.getenv("STYLE_MODE") or "neutral").strip().lower()
    if style_mode not in {"neutral", "rogan_like"}:
        raise RuntimeError("STYLE_MODE must be 'neutral' or 'rogan_like'")
    fitness_vault_chat_id_raw = (os.getenv("FITNESS_VAULT_CHAT_ID") or "").strip()
    fitness_admin_user_id_raw = (os.getenv("FITNESS_ADMIN_USER_ID") or "").strip()
    fitness_log_chat_id_raw = (os.getenv("FITNESS_LOG_CHAT_ID") or "").strip()
    fitness_vault_chat_id = int(fitness_vault_chat_id_raw) if fitness_vault_chat_id_raw else None
    fitness_admin_user_id = int(fitness_admin_user_id_raw) if fitness_admin_user_id_raw else None
    fitness_log_chat_id = int(fitness_log_chat_id_raw) if fitness_log_chat_id_raw else None
    prewarm_interval_seconds = int(os.getenv("PREWARM_INTERVAL_SECONDS") or "600")
    if prewarm_interval_seconds < 60:
        raise RuntimeError("PREWARM_INTERVAL_SECONDS must be >= 60")
    task_reminder_interval_seconds = int(os.getenv("TASK_REMINDER_INTERVAL_SECONDS") or "45")
    if task_reminder_interval_seconds < 20:
        raise RuntimeError("TASK_REMINDER_INTERVAL_SECONDS must be >= 20")
    ollama_soft_timeout_seconds = float(os.getenv("OLLAMA_SOFT_TIMEOUT_SECONDS") or "25")
    if ollama_soft_timeout_seconds < 5:
        raise RuntimeError("OLLAMA_SOFT_TIMEOUT_SECONDS must be >= 5")

    return Settings(
        bot_token=token,
        coingecko_vs=(os.getenv("COINGECKO_VS") or "usd").lower(),
        price_currencies=tuple(
            c.strip().lower()
            for c in (os.getenv("PRICE_CURRENCIES") or "usd,eur,rub").split(",")
            if c.strip()
        ),
        ollama_api_url=os.getenv("OLLAMA_API_URL") or "http://localhost:11434/api/generate",
        ollama_model=os.getenv("OLLAMA_MODEL") or "gemma3:27b",
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS") or "60"),
        max_history_messages=max_history,
        system_prompt=os.getenv("SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT,
        default_lang=default_lang,
        enable_crypto_watcher=_env_bool("ENABLE_CRYPTO_WATCHER", False),
        log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
        timezone_name=os.getenv("TIMEZONE"),
        weather_city=os.getenv("WEATHER_CITY") or "Moscow",
        home_address=(os.getenv("HOME_ADDRESS") or "").strip() or None,
        work_address=(os.getenv("WORK_ADDRESS") or "").strip() or None,
        enable_auto_digest=_env_bool("ENABLE_AUTO_DIGEST", True),
        digest_times=digest_times,
        digest_chat_id=digest_chat_id,
        birth_date=birth_date,
        moto_season_start_mmdd=moto_mmdd,
        fuel95_source_url=os.getenv("FUEL95_SOURCE_URL") or "https://www.petrolplus.ru/fuelindex/gorod-moskva/ai95/",
        fuel95_moscow_rub=fuel95_value,
        feedback_min_chars=feedback_min_chars,
        style_mode=style_mode,
        fitness_vault_chat_id=fitness_vault_chat_id,
        fitness_admin_user_id=fitness_admin_user_id,
        fitness_log_chat_id=fitness_log_chat_id,
        enable_prewarm=_env_bool("ENABLE_PREWARM", True),
        prewarm_interval_seconds=prewarm_interval_seconds,
        enable_task_reminders=_env_bool("ENABLE_TASK_REMINDERS", True),
        task_reminder_interval_seconds=task_reminder_interval_seconds,
        enable_llm_enhancer=_env_bool("ENABLE_LLM_ENHANCER", False),
        llm_enhancer_timeout_seconds=float(os.getenv("LLM_ENHANCER_TIMEOUT_SECONDS") or "3.5"),
        ollama_soft_timeout_seconds=ollama_soft_timeout_seconds,
    )
