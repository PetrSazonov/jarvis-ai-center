import logging
import time
from pathlib import Path

from core.settings import Settings
from services.http_service import request_json
from services.time_service import now_dt

OLLAMA_SOFT_TIMEOUT_SECONDS = 25.0
_PROMPT_TEMPLATES_DIR = Path(__file__).with_name("prompts")
_PROMPT_TEMPLATE_CACHE: dict[str, str] = {}
_DEFAULT_PROFILE = "advisor"
_ALLOWED_PROFILES = {"classifier", "advisor", "rewriter"}
_HISTORY_TOKEN_BUDGET = 1800

logger = logging.getLogger("purecompanybot")


def _style_instructions(settings: Settings) -> str | None:
    if settings.style_mode == "rogan_like":
        return (
            "Communication style: energetic, conversational podcast-host vibe. "
            "Be curious, practical, and direct. Use short paragraphs and occasional light humor. "
            "Structure: (1) short thesis, (2) 2-4 practical points, (3) one clarifying question when helpful. "
            "Do not claim to be Joe Rogan or any real person."
        )
    return None


def _mode_instruction(mode: str) -> str:
    value = (mode or "normal").strip().lower()
    if value == "fast":
        return "Answer policy: fast mode. Keep replies short and practical."
    if value == "precise":
        return (
            "Answer policy: precise mode. Be careful with assumptions and uncertainty. "
            "If request is ambiguous, ask one clarifying question first."
        )
    return "Answer policy: normal mode. Keep balance between clarity and brevity."


def _normalize_profile(profile: str | None) -> str:
    value = (profile or _DEFAULT_PROFILE).strip().lower()
    if value in _ALLOWED_PROFILES:
        return value
    return _DEFAULT_PROFILE


def _profile_options(profile: str, mode: str) -> dict[str, float | int]:
    profile_value = _normalize_profile(profile)
    if profile_value == "classifier":
        return {
            "temperature": 0.15,
            "top_p": 0.8,
            "top_k": 30,
            "repeat_penalty": 1.1,
            "num_predict": 220,
        }
    if profile_value == "rewriter":
        return {
            "temperature": 0.25,
            "top_p": 0.85,
            "top_k": 35,
            "repeat_penalty": 1.1,
            "num_predict": 260,
        }
    return {
        "temperature": 0.4,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "num_predict": 700,
    }


def _load_prompt_template(profile: str) -> str:
    profile_value = _normalize_profile(profile)
    cached = _PROMPT_TEMPLATE_CACHE.get(profile_value)
    if cached is not None:
        return cached

    path = _PROMPT_TEMPLATES_DIR / f"{profile_value}.txt"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    _PROMPT_TEMPLATE_CACHE[profile_value] = value
    return value


def _rough_token_size(value: str) -> int:
    return max(1, len(value) // 4)


def _trim_history_by_token_budget(history: list[dict[str, str]], budget: int) -> list[dict[str, str]]:
    if not history:
        return []

    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(history):
        role = str(item.get("role", "user"))
        content = str(item.get("content", ""))
        size = _rough_token_size(role) + _rough_token_size(content) + 4
        if selected and (used + size) > budget:
            break
        selected.append({"role": role, "content": content})
        used += size
    selected.reverse()
    return selected


def build_prompt(
    history: list[dict[str, str]],
    user_message: str,
    settings: Settings,
    extra_context: str = "",
    mode: str = "normal",
    profile: str = "advisor",
) -> str:
    profile_value = _normalize_profile(profile)
    trimmed = history[-settings.max_history_messages :]
    trimmed = _trim_history_by_token_budget(trimmed, _HISTORY_TOKEN_BUDGET)

    now = now_dt(settings.timezone_name)
    lines: list[str] = []
    template = _load_prompt_template(profile_value)
    if template:
        lines.append(template)
    else:
        lines.append("System: You are a pragmatic assistant.")
    lines.append(f"Base policy: {settings.system_prompt}")

    style_line = _style_instructions(settings)
    if style_line and profile_value == "advisor":
        lines.append(style_line)
    lines.append(_mode_instruction(mode))
    lines.append(
        "Factual policy: never invent facts, prices, statuses, or weather. "
        "If data is missing, explicitly say 'no data' and propose one next step."
    )
    lines.append(f"Current server datetime: {now.isoformat(timespec='seconds')}")
    if settings.default_lang == "ru":
        lines.append("Response language: Russian.")
    else:
        lines.append("Response language: English.")

    if extra_context:
        lines.append("External context:\n" + extra_context)

    for entry in trimmed:
        role = str(entry.get("role", "user"))
        content = str(entry.get("content", ""))
        if role == "assistant":
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"User: {content}")

    lines.append(f"User: {user_message}")
    lines.append("Assistant:")
    return "\n".join(lines)


async def call_ollama(
    prompt: str,
    settings: Settings,
    mode: str = "normal",
    profile: str = "advisor",
) -> str:
    soft_timeout = float(getattr(settings, "ollama_soft_timeout_seconds", OLLAMA_SOFT_TIMEOUT_SECONDS))
    timeout = min(float(settings.ollama_timeout_seconds), soft_timeout)
    options = _profile_options(profile, mode)
    started_at = time.perf_counter()
    result = await request_json(
        service="ollama",
        method="POST",
        url=settings.ollama_api_url,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
        json_data={
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        },
    )

    text = str(result.get("response", "")).strip()
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "event=llm_call mode=%s profile=%s latency_ms=%s response_chars=%s",
        mode,
        _normalize_profile(profile),
        latency_ms,
        len(text),
    )

    if not text:
        return "I do not have a response yet."
    return text
