import asyncio
import json
import logging

from core.settings import Settings
from services.http_service import ExternalAPIError
from services.llm_service import build_prompt, call_ollama

logger = logging.getLogger("purecompanybot")


async def enhance_screen_text(
    *,
    settings: Settings,
    screen: str,
    base_text: str,
    mode: str = "normal",
) -> str:
    if not settings.enable_llm_enhancer:
        return base_text

    prompt = build_prompt(
        history=[],
        user_message=(
            "Rewrite the bot screen to sound more natural and concise without changing facts.\n"
            "Rules:\n"
            "1) Keep all numbers, dates, IDs and slash-commands unchanged.\n"
            "2) Keep the same structure and meaning.\n"
            "3) Keep it short and practical.\n"
            "4) Do not invent any data.\n\n"
            f"Screen: {screen}\n\n"
            f"Text:\n{base_text}"
        ),
        settings=settings,
        mode=mode,
        profile="rewriter",
    )

    try:
        enhanced = await asyncio.wait_for(
            call_ollama(prompt, settings, mode=mode, profile="rewriter"),
            timeout=settings.llm_enhancer_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.info("event=llm_enhancer_screen_fallback reason=timeout")
        return base_text
    except ExternalAPIError as exc:
        logger.info("event=llm_enhancer_screen_fallback reason=api_error kind=%s", exc.kind)
        return base_text
    except Exception as exc:
        logger.info("event=llm_enhancer_screen_fallback reason=exception type=%s", exc.__class__.__name__)
        return base_text

    clean = (enhanced or "").strip()
    if not clean:
        return base_text
    if len(clean) < max(60, int(len(base_text) * 0.35)):
        return base_text
    if len(clean) > int(len(base_text) * 1.8):
        clean = clean[: int(len(base_text) * 1.8)].rstrip() + "..."
    return clean


async def enhance_news_titles(
    *,
    settings: Settings,
    titles: list[str],
    mode: str = "fast",
) -> list[str]:
    if not settings.enable_llm_enhancer:
        return titles
    if not titles:
        return titles

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = build_prompt(
        history=[],
        user_message=(
            "Rewrite each news title to be compact and lively.\n"
            "Rules:\n"
            "1) Return strict JSON array of strings only.\n"
            "2) Keep item count exactly the same.\n"
            "3) Do not change facts, names, numbers or dates.\n"
            "4) No markdown, no numbering.\n\n"
            f"Titles:\n{numbered}"
        ),
        settings=settings,
        mode=mode,
        profile="rewriter",
    )

    try:
        raw = await asyncio.wait_for(
            call_ollama(prompt, settings, mode=mode, profile="rewriter"),
            timeout=settings.llm_enhancer_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.info("event=llm_enhancer_news_fallback reason=timeout")
        return titles
    except ExternalAPIError as exc:
        logger.info("event=llm_enhancer_news_fallback reason=api_error kind=%s", exc.kind)
        return titles
    except Exception as exc:
        logger.info("event=llm_enhancer_news_fallback reason=exception type=%s", exc.__class__.__name__)
        return titles

    text = (raw or "").strip()
    if not text:
        logger.info("event=llm_enhancer_news_fallback reason=empty")
        return titles

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.info("event=llm_enhancer_news_fallback reason=invalid_json")
            return titles
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.info("event=llm_enhancer_news_fallback reason=invalid_json_extracted")
            return titles

    if not isinstance(payload, list):
        logger.info("event=llm_enhancer_news_fallback reason=not_list")
        return titles
    if len(payload) != len(titles):
        logger.info("event=llm_enhancer_news_fallback reason=size_mismatch expected=%s actual=%s", len(titles), len(payload))
        return titles

    cleaned: list[str] = []
    for original, item in zip(titles, payload):
        value = str(item or "").strip()
        if not value:
            cleaned.append(original)
            continue
        if len(value) > max(220, int(len(original) * 1.8)):
            value = value[: max(80, int(len(original) * 1.8))].rstrip() + "..."
        cleaned.append(value)

    return cleaned
