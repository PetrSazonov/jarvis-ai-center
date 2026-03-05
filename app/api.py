from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from core.coordinator import handle_command
from core.settings import Settings, load_settings
from db import (
    daily_checkin_recent,
    fitness_add_session,
    fitness_current_streak_days,
    fitness_done_count_between,
    fitness_get_latest_session_for_user,
    fitness_get_progress,
    fitness_get_recent_rpe,
    fitness_get_workout,
    fitness_list_workouts,
    fitness_stats_recent,
    fitness_upsert_progress,
    focus_stats_recent,
    garage_list_assets,
    garage_seed_defaults,
    garage_update_asset,
    get_cache_value,
    init_db,
    set_cache_value,
    todo_stats_recent,
    user_settings_get_full,
)
from services.crypto_service import fetch_prices
from services.fitness_plan_service import (
    build_ai_workout_plan,
    pick_workout_of_day,
    program_summary,
    render_plain_workout_plan,
)
from services.fitness_progress_service import next_hint_by_context
from services.forex_service import fetch_usd_eur_to_rub
from services.fuel_service import fetch_fuel95_moscow_data
from services.ingest_service import fetch_ingest_signals
from services.llm_service import build_prompt, call_ollama
from services.rag_service import resolve_rag_for_query
from services.news_service import TOPIC_KEYWORDS, fetch_topic_links
from services.weather_service import fetch_weather_summary


app = FastAPI(title="Jarvis AI Center API", version="0.2.0")
_APP_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _APP_DIR.parent
_DASHBOARD_HTML = _APP_DIR / "dashboard.html"
_API_RELOAD_TRIGGER = _APP_DIR / "_reload_trigger.py"
_CODEX_INBOX = _PROJECT_DIR / "ops" / "codex_inbox.jsonl"
_CODEX_RUNS_DIR = _PROJECT_DIR / "ops" / "codex_runs"
_SETTINGS_CACHE: Settings | None = None
_AI_CACHE_TTL_SECONDS = 300
_CODEX_RUN_LOCK = threading.Lock()
_CODEX_RUN_STATE: dict[str, dict[str, object]] = {}
_DASH_AUTH_COOKIE_NAME = "jarvis_dash_auth"
_API_STARTED_AT = datetime.now().isoformat(timespec="seconds")
_FITNESS_VIDEO_DIR = _PROJECT_DIR / "Video"
_FITNESS_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
_FITNESS_VIDEO_TITLE_CACHE_PREFIX = "dashboard:fitness_video_title:v1:"

# API can run independently from bot.py, so load project .env here as well.
load_dotenv(dotenv_path=_PROJECT_DIR / ".env", override=False)
# API can also run without bot.py, so ensure DB schema/migrations are applied here.
init_db()


class TaskCreateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=1200)
    due_date: str | None = None
    remind_at: str | None = None
    remind_telegram: bool = True


class TaskDoneRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    done_at: str | None = None


class TaskUpdateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    text: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=1200)
    due_date: str | None = None
    remind_at: str | None = None
    remind_telegram: bool = True


class SubscriptionCreateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=160)
    next_date: str = Field(..., min_length=10, max_length=10)
    period: str = Field(default="monthly", min_length=6, max_length=16)
    amount: float | None = None
    currency: str = Field(default="RUB", min_length=3, max_length=6)
    note: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=80)
    autopay: bool = True
    remind_days: int = Field(default=3, ge=0, le=60)


class CopilotMessageRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    message: str = Field(..., min_length=1, max_length=1500)
    mode: str = Field(default="normal")
    chat_mode: str = Field(default="full")


class CopilotActionRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    action: str = Field(..., min_length=1, max_length=64)
    text: str | None = None
    mode: str = Field(default="normal")


class CodexRunRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    prompt: str = Field(..., min_length=1, max_length=6000)


class DashboardNewsProfileRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    interests: list[str] = Field(default_factory=list)
    hidden_topics: list[str] = Field(default_factory=list)
    hidden_sources: list[str] = Field(default_factory=list)
    explain: bool = True


class FitnessSessionCreateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    workout_id: int = Field(..., ge=1)
    rpe: int | None = Field(default=None, ge=1, le=10)
    comment: str | None = Field(default=None, max_length=500)
    done_at: str | None = None


class GarageAssetUpdateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    mileage_km: int | None = Field(default=None, ge=0)
    last_service_km: int | None = Field(default=None, ge=0)
    maintenance_interval_km: int | None = Field(default=None, ge=1000, le=60000)
    maintenance_due_date: str | None = None
    insurance_until: str | None = None
    tech_inspection_until: str | None = None
    note: str | None = Field(default=None, max_length=1000)


_AI_QUICK_ACTIONS_DEFAULT = [
    {"type": "replan_day", "label": "Переплан дня"},
    {"type": "focus_start", "label": "Фокус 25м"},
]
_AI_MESSAGE_TIMEOUT_TEXT = "Gemma отвечает дольше обычного. Дала быстрый безопасный ответ. Попробуй ещё раз через 10–20 секунд."
_AI_MESSAGE_UNAVAILABLE_TEXT = "Gemma временно недоступна. Дала быстрый безопасный ответ. Попробуй позже."
_AI_ACTION_TIMEOUT_TEXT = "Действие заняло слишком много времени. Попробуй ещё раз через 10–20 секунд."
_AI_ACTION_UNAVAILABLE_TEXT = "Сервис действий Gemma временно недоступен. Попробуй позже."
_AI_MESSAGE_EMPTY_TEXT = "Не получила текст от модели. Дала быстрый ответ из базового режима."
_NEWS_PROFILE_CACHE_PREFIX = "dashboard:news_profile:"
_NEWS_TOPIC_CATALOG = tuple(sorted({str(topic).strip().lower() for topic in TOPIC_KEYWORDS.keys() if str(topic).strip()}))
_GEMMA_NUDGE_STATE_PREFIX = "dashboard:gemma:nudge_state:"
_GEMMA_NUDGE_MIN_INTERVAL_SEC = 35 * 60
_GEMMA_NUDGE_DEFAULT_POLL_SEC = 8 * 60
_GEMMA_NUDGE_IDLE_POLL_MIN_SEC = 5 * 60
_GEMMA_NUDGE_IDLE_POLL_MAX_SEC = 12 * 60
_GEMMA_NUDGE_SEND_PROBABILITY = 0.30
_GEMMA_HISTORY_MAX_ITEMS = 80
_GEMMA_MICRO_FACTS = (
    "Короткий 25-минутный фокус-блок почти всегда эффективнее долгого старта «когда-нибудь потом».",
    "Если вечером зафиксировать 1 вывод дня, утром легче войти в рабочий режим.",
    "Один закрытый приоритет в день даёт больше системного прогресса, чем пять начатых задач.",
    "Для устойчивого роста лучше держать умеренный ритм 5 дней подряд, чем делать рывки и откаты.",
    "Минимальный шаг на 10 минут часто снимает внутреннее сопротивление лучше, чем долгие размышления.",
    "Когда список задач перегружен, топ-3 на день почти всегда поднимает качество решений.",
)
_GEMMA_PERSONA_BRIEF = (
    "Ты Gemma — персональный второй пилот пользователя.\n"
    "Стиль: умная, уверенная, компанейская, с лёгкой игрой, дерзостью и юмором.\n"
    "Допустим лёгкий флирт и пикап-энергия как интеллектуальная игра, но без пошлости, вульгарности и давления.\n"
    "Иногда добавляй короткую дерзкую искру в формулировку, если это поднимает мотивацию и остаётся уместным.\n"
    "Иногда можно мягко спорить и показывать характер, если это помогает решению.\n"
    "Тон: живой, тёплый, остроумный, уместно дерзкий.\n"
    "Главное — практическая польза: следующий шаг, фокус, результат.\n"
    "Если информации о пользователе не хватает, задай один короткий уточняющий вопрос.\n"
    "Рабочий язык: русский."
)


def _copy_actions(actions: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    source = actions if isinstance(actions, list) else _AI_QUICK_ACTIONS_DEFAULT
    out: list[dict[str, str]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip()
        label = str(item.get("label") or "").strip()
        if not action_type or not label:
            continue
        out.append({"type": action_type, "label": label})
    return out or list(_AI_QUICK_ACTIONS_DEFAULT)


def _day_mode_label_ru(value: object) -> str:
    mode = str(value or "").strip().lower()
    mapping = {
        "workday": "рабочий день",
        "deep_work": "глубокий фокус",
        "maintenance": "поддерживающий режим",
        "recovery": "восстановление",
    }
    return mapping.get(mode, "рабочий день")


def _normalize_ai_message_result(
    result: dict[str, object] | None,
    *,
    fallback_text: str,
    status: str = "ok",
    source: str = "gemma",
    error_kind: str | None = None,
) -> dict[str, object]:
    raw = result if isinstance(result, dict) else {}
    answer = str(raw.get("answer") or "").strip()
    actions = raw.get("quick_actions")
    normalized_actions = _copy_actions(actions if isinstance(actions, list) else None)
    payload: dict[str, object] = {
        "answer": answer or fallback_text,
        "quick_actions": normalized_actions,
        "status": status,
        "source": source,
    }
    if error_kind:
        payload["error_kind"] = error_kind
    return payload


def _normalize_ai_action_result(
    *,
    ok: bool,
    message: str,
    quick_actions: list[dict[str, str]] | None = None,
    status: str = "ok",
    error_kind: str | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": bool(ok),
        "message": str(message or "").strip() or _AI_ACTION_UNAVAILABLE_TEXT,
        "quick_actions": _copy_actions(quick_actions),
        "status": status,
    }
    if error_kind:
        payload["error_kind"] = error_kind
    for key, value in extra.items():
        payload[key] = value
    return payload


def _chat_llm_timeout(chat_mode: str) -> float:
    mode = str(chat_mode or "").strip().lower()
    if mode == "coach":
        return 14.0
    return 36.0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_iso_date(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.isoformat()


def _clean_iso_datetime(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.isoformat(timespec="seconds")


def _news_profile_key(user_id: int) -> str:
    return f"{_NEWS_PROFILE_CACHE_PREFIX}{int(user_id)}"


def _normalize_source_host(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        host = (urlparse(raw).hostname or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _clean_text_list(values: list[str], *, item_type: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        value = str(item or "").strip().lower()
        if not value:
            continue
        if item_type == "topic":
            if value not in _NEWS_TOPIC_CATALOG:
                continue
        elif item_type == "source":
            value = _normalize_source_host(value)
            if not value:
                continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out[:24]


def _default_news_profile() -> dict[str, Any]:
    return {
        "interests": list(_NEWS_TOPIC_CATALOG),
        "hidden_topics": [],
        "hidden_sources": [],
        "explain": True,
    }


def _normalize_news_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_news_profile()
    raw = payload if isinstance(payload, dict) else {}
    interests = raw.get("interests")
    hidden_topics = raw.get("hidden_topics")
    hidden_sources = raw.get("hidden_sources")
    base["interests"] = _clean_text_list(interests if isinstance(interests, list) else base["interests"], item_type="topic")
    base["hidden_topics"] = _clean_text_list(hidden_topics if isinstance(hidden_topics, list) else [], item_type="topic")
    base["hidden_sources"] = _clean_text_list(hidden_sources if isinstance(hidden_sources, list) else [], item_type="source")
    base["explain"] = bool(raw.get("explain", True))
    # Hidden topics must not remain in interests.
    hidden_topic_set = set(base["hidden_topics"])
    base["interests"] = [topic for topic in base["interests"] if topic not in hidden_topic_set]
    return base


def _load_news_profile(user_id: int) -> dict[str, Any]:
    cached = get_cache_value(_news_profile_key(user_id))
    if not cached:
        return _default_news_profile()
    raw_value = str(cached[0] or "").strip()
    if not raw_value:
        return _default_news_profile()
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return _default_news_profile()
    return _normalize_news_profile(parsed if isinstance(parsed, dict) else {})


def _save_news_profile(user_id: int, profile: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_news_profile(profile)
    set_cache_value(
        _news_profile_key(user_id),
        json.dumps(normalized, ensure_ascii=False),
        _now_iso(),
    )
    return normalized


def _settings() -> Settings | None:
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE
    try:
        _SETTINGS_CACHE = load_settings()
    except Exception as exc:
        # Dashboard/API does not require Telegram polling, so allow local API mode
        # even when BOT_TOKEN is absent.
        if "BOT_TOKEN not found in .env" in str(exc):
            os.environ["BOT_TOKEN"] = os.getenv("BOT_TOKEN") or "api-local-token"
            try:
                _SETTINGS_CACHE = load_settings()
            except Exception:
                _SETTINGS_CACHE = None
        else:
            _SETTINGS_CACHE = None
    return _SETTINGS_CACHE


def _debug_events_enabled() -> bool:
    raw = os.getenv("API_DEBUG_EVENTS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _debug_events_remote_enabled() -> bool:
    raw = os.getenv("API_DEBUG_EVENTS_REMOTE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _allow_public_access() -> bool:
    raw = os.getenv("DASHBOARD_ALLOW_PUBLIC", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _trusted_networks() -> list[ipaddress._BaseNetwork]:
    raw = str(
        os.getenv(
            "DASHBOARD_TRUSTED_NETS",
            "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7",
        )
        or ""
    ).strip()
    networks: list[ipaddress._BaseNetwork] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_client(request: Request) -> bool:
    if _allow_public_access():
        return True
    client = request.client
    host = str(client.host or "").strip().lower() if client else ""
    # TestClient host is synthetic and only used in-process.
    if host in {"localhost", "testclient"}:
        return True
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    for network in _trusted_networks():
        if ip in network:
            return True
    return False


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    host = str(client.host or "").strip().lower() if client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _safe_debug_enabled(request: Request, debug: int) -> bool:
    if int(debug or 0) != 1:
        return False
    if not _debug_events_enabled():
        return False
    if not _is_trusted_client(request):
        return False
    # In local/dev mode without API auth barrier, keep debug simple.
    if not _dashboard_auth_required():
        return True
    if _debug_events_remote_enabled():
        return True
    return _is_loopback_request(request)


def _dashboard_auth_enabled() -> bool:
    raw = os.getenv("DASHBOARD_AUTH_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _dashboard_access_token() -> str:
    return os.getenv("DASHBOARD_ACCESS_TOKEN", "").strip()


def _dashboard_auth_required() -> bool:
    return _dashboard_auth_enabled() and bool(_dashboard_access_token())


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = str(request.headers.get("authorization") or "").strip()
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    return token or None


def _extract_auth_token(request: Request, query_token: str | None = None) -> str | None:
    if query_token:
        token = str(query_token).strip()
        if token:
            return token
    header_token = str(request.headers.get("x-jarvis-token") or "").strip()
    if header_token:
        return header_token
    bearer = _extract_bearer_token(request)
    if bearer:
        return bearer
    cookie_token = str(request.cookies.get(_DASH_AUTH_COOKIE_NAME) or "").strip()
    if cookie_token:
        return cookie_token
    return None


def _is_authorized_request(request: Request, query_token: str | None = None) -> bool:
    if not _dashboard_auth_required():
        return True
    expected = _dashboard_access_token()
    provided = _extract_auth_token(request, query_token=query_token)
    if not expected or not provided:
        return False
    return bool(hmac.compare_digest(provided, expected))


def _auth_cookie_secure() -> bool:
    raw = os.getenv("DASHBOARD_AUTH_COOKIE_SECURE", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _ensure_api_authorized(request: Request) -> None:
    if not _is_trusted_client(request):
        raise HTTPException(status_code=403, detail="Remote access is restricted. Use VPN/mesh/trusted network.")
    if _is_authorized_request(request):
        return
    raise HTTPException(status_code=401, detail="Unauthorized. Provide dashboard token.")


def _dashboard_login_html() -> str:
    return (
        "<!doctype html>"
        "<html lang='ru'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>Jarvis Dashboard Login</title>"
        "<style>"
        "body{margin:0;background:#07110d;color:#d6e7df;font-family:Segoe UI,Arial,sans-serif;}"
        ".wrap{min-height:100vh;display:grid;place-items:center;padding:20px;}"
        ".card{width:min(460px,92vw);background:#0d1c17;border:1px solid #2e6d58;border-radius:12px;padding:18px;}"
        "h1{margin:0 0 8px;font-size:20px;}p{margin:0 0 12px;color:#9ec0b2;line-height:1.4;}"
        "input{width:100%;padding:10px;border-radius:8px;border:1px solid #3e8a70;background:#08120f;color:#d6e7df;}"
        "button{margin-top:10px;padding:10px 12px;border-radius:8px;border:1px solid #49ba90;background:#133427;color:#d6f9ea;cursor:pointer;}"
        "</style></head><body><div class='wrap'><div class='card'>"
        "<h1>Доступ к Day OS</h1>"
        "<p>Введи dashboard-токен. После входа токен будет сохранён в secure-cookie для текущего браузера.</p>"
        "<form method='get' action='/dashboard'>"
        "<input type='password' name='token' placeholder='DASHBOARD_ACCESS_TOKEN' autocomplete='off' required />"
        "<button type='submit'>Войти</button>"
        "</form></div></div></body></html>"
    )


def _fitness_studio_html() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Jarvis Fitness Studio</title>
  <style>
    :root{
      --bg:#0f1311; --panel:#141a16; --panel2:#101612; --line:#2b3a31;
      --text:#e4ece7; --muted:#8da094; --green:#2ed85e; --amber:#db9733; --red:#db3146;
      --mono:"JetBrains Mono","IBM Plex Mono","Consolas",monospace; --ui:"IBM Plex Sans","Segoe UI",sans-serif;
    }
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--text);font-family:var(--ui)}
    .shell{max-width:1380px;margin:0 auto;padding:14px;display:grid;gap:12px}
    .top{display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid var(--line);background:var(--panel);padding:10px 12px;border-radius:10px}
    .title{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
    .main{display:grid;grid-template-columns:1.35fr .95fr;gap:12px}
    .card{border:1px solid var(--line);background:var(--panel);border-radius:10px;padding:10px;display:grid;gap:8px}
    .sub{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
    .headline{font-size:18px;font-weight:600}
    .row{border:1px solid #324338;background:var(--panel2);border-radius:8px;padding:8px}
    .row-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
    .row-name{font-size:14px;font-weight:600}
    .row-meta{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
    .toolbar{display:flex;flex-wrap:wrap;gap:6px}
    button,select,input{border:1px solid #3c5245;background:#0e1712;color:var(--text);border-radius:999px;min-height:32px;padding:0 12px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
    button{cursor:pointer}
    button:hover{border-color:#5f8c75}
    .btn-primary{border-color:var(--green);background:rgba(46,216,94,.16)}
    .btn-danger{border-color:#7b2733;background:rgba(90,16,27,.38)}
    .timer{font-family:var(--mono);font-size:18px;letter-spacing:.08em}
    .exercise{display:grid;gap:6px;border:1px solid #33443a;background:#0c1511;border-radius:8px;padding:8px}
    .exercise-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
    .chips{display:flex;flex-wrap:wrap;gap:6px}
    .chip{display:inline-flex;align-items:center;justify-content:center;min-width:30px;height:26px;padding:0 10px;border-radius:999px;border:1px solid #3e5448;background:#111b16;font-family:var(--mono);font-size:10px;color:#c8ddd2;cursor:pointer}
    .chip.done{border-color:var(--green);background:rgba(46,216,94,.18);color:#eaffef}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    .video{width:100%;max-height:320px;background:#050807;border:1px solid #27352d;border-radius:8px}
    .list{display:grid;gap:6px;max-height:320px;overflow:auto}
    .hint{font-size:12px;color:#9eb2a7}
    .muted{font-family:var(--mono);font-size:11px;color:var(--muted)}
    .status-ok{color:#bdeccb}.status-warn{color:#ffdba4}.status-bad{color:#ffbcc5}
    @media (max-width: 1080px){.main{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="shell">
    <div class="top">
      <div>
        <div class="title">Fitness Studio</div>
        <div class="headline" id="studioTitle">Загрузка...</div>
      </div>
      <div class="toolbar">
        <button id="backBtn">К дашборду</button>
        <button id="refreshBtn">Обновить</button>
      </div>
    </div>

    <div class="main">
      <div class="card">
        <div class="toolbar">
          <select id="workoutSelect"></select>
          <button id="logDoneBtn" class="btn-primary">Сделал тренировку</button>
        </div>
        <div class="grid2">
          <input id="rpeInput" type="number" min="1" max="10" step="1" placeholder="RPE 1-10" />
          <input id="commentInput" type="text" placeholder="Комментарий" />
        </div>
        <div class="row">
          <div class="row-head">
            <div class="row-name">Таймер</div>
            <div class="timer" id="timerDisplay">00:00</div>
          </div>
          <div class="toolbar">
            <button id="timerStopBtn">Стоп</button>
            <button id="timerRestBtn">Отдых 90с</button>
            <button id="timerTabataBtn">Табата 45/15 × 10</button>
          </div>
          <div class="muted" id="timerHint">Таймер не запущен</div>
        </div>

        <div class="row">
          <div class="row-head">
            <div class="row-name">Сценарий тренировки</div>
            <div class="row-meta" id="scriptMeta"></div>
          </div>
          <div id="scriptBlock" class="list"></div>
        </div>
      </div>

      <div class="card">
        <div class="row">
          <div class="row-head">
            <div class="row-name">Видео ритуалов</div>
            <div class="row-meta" id="videoCount">0</div>
          </div>
          <video id="videoPlayer" class="video" controls preload="metadata"></video>
          <div class="hint" id="videoTitle">Выбери видео из списка</div>
          <div class="list" id="videoList"></div>
        </div>
        <div class="row">
          <div class="row-name">Статус</div>
          <div class="hint" id="statusText">Готов к работе.</div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const qs = new URLSearchParams(window.location.search);
    const userId = Number(qs.get("user_id") || "118100880");
    const state = { training:null, selectedId:0, timer:null, timerSec:0, timerMode:"", checks:{}, tabata:null };
    const checkKey = (wid) => `jarvis.fit.studio.check.v1:${new Date().toISOString().slice(0,10)}:${wid}`;

    const el = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
    const arr = (v) => Array.isArray(v) ? v : [];

    function fmt(sec){
      const s = Math.max(0, Number(sec||0)|0);
      const mm = String(Math.floor(s/60)).padStart(2,"0");
      const ss = String(s%60).padStart(2,"0");
      return `${mm}:${ss}`;
    }

    function setStatus(text, cls="status-ok"){
      const node = el("statusText");
      if(!node) return;
      node.className = `hint ${cls}`;
      node.textContent = text;
    }

    function timerStop(){
      if(state.timer){ clearInterval(state.timer); state.timer = null; }
      state.timerSec = 0; state.timerMode = ""; state.tabata = null;
      el("timerDisplay").textContent = "00:00";
      el("timerHint").textContent = "Таймер не запущен";
    }

    function timerStartCountdown(sec,label){
      timerStop();
      state.timerMode = "countdown";
      state.timerSec = Math.max(1, Number(sec)||0);
      el("timerDisplay").textContent = fmt(state.timerSec);
      el("timerHint").textContent = label || "Таймер";
      state.timer = setInterval(()=>{
        state.timerSec -= 1;
        el("timerDisplay").textContent = fmt(state.timerSec);
        if(state.timerSec <= 0){
          timerStop();
          setStatus("Таймер завершён.", "status-warn");
        }
      },1000);
    }

    function timerStartTabata(workSec, restSec, rounds){
      timerStop();
      const work = Math.max(5, Number(workSec)||0);
      const rest = Math.max(0, Number(restSec)||0);
      const totalRounds = Math.max(1, Number(rounds)||0);
      state.timerMode = "tabata";
      state.tabata = { work, rest, rounds: totalRounds, round: 1, phase: "work" };
      state.timerSec = work;
      el("timerDisplay").textContent = fmt(state.timerSec);
      el("timerHint").textContent = `Табата: работа · раунд 1/${totalRounds}`;

      state.timer = setInterval(()=>{
        state.timerSec -= 1;
        el("timerDisplay").textContent = fmt(state.timerSec);
        if(state.timerSec > 0) return;

        const tabata = state.tabata;
        if(!tabata){
          timerStop();
          return;
        }
        if(tabata.phase === "work"){
          tabata.phase = "rest";
          state.timerSec = tabata.rest;
          if(state.timerSec <= 0){
            // Если отдых = 0, сразу перескочим в следующий раунд на этом же тике.
            tabata.phase = "rest-end";
          }else{
            el("timerHint").textContent = `Табата: отдых · раунд ${tabata.round}/${tabata.rounds}`;
            return;
          }
        }
        if(tabata.round >= tabata.rounds){
          timerStop();
          setStatus("Табата завершена.", "status-ok");
          return;
        }
        tabata.round += 1;
        tabata.phase = "work";
        state.timerSec = tabata.work;
        el("timerDisplay").textContent = fmt(state.timerSec);
        el("timerHint").textContent = `Табата: работа · раунд ${tabata.round}/${tabata.rounds}`;
      },1000);
    }

    function loadChecks(workoutId){
      try{
        const raw = localStorage.getItem(checkKey(workoutId));
        state.checks = raw ? JSON.parse(raw) : {};
      }catch(_e){ state.checks = {}; }
    }

    function saveChecks(workoutId){
      try{ localStorage.setItem(checkKey(workoutId), JSON.stringify(state.checks||{})); }catch(_e){}
    }

    function renderScript(script){
      const root = el("scriptBlock");
      if(!root) return;
      if(!script || typeof script !== "object"){
        root.innerHTML = `<div class="hint">Сценарий пока не готов.</div>`;
        return;
      }
      const rounds = Math.max(1, Number(script.rounds || 4));
      el("scriptMeta").textContent = `${rounds} круга · ${Number(script.duration_min||25)} мин`;
      const warm = script.warmup || {};
      const cool = script.cooldown || {};
      const main = script.main || {};
      const exercises = arr(main.exercises);

      const warmMin = Number(warm.minutes || 6);
      const coolMin = Number(cool.minutes || 5);
      const restSec = Number(main.rest_sec || 75);

      const exerciseRows = exercises.map((ex, idx)=>{
        const name = String(ex && ex.name || `Упражнение ${idx+1}`);
        const target = String(ex && ex.target || "по самочувствию");
        const keyBase = `ex:${idx}`;
        const chips = Array.from({length: rounds}, (_,r)=>{
          const key = `${keyBase}:r${r+1}`;
          const done = !!state.checks[key];
          return `<button class="chip ${done ? "done" : ""}" data-check="${esc(key)}">Круг ${r+1}</button>`;
        }).join("");
        return `
          <div class="exercise">
            <div class="exercise-top">
              <div>
                <div class="row-name">${esc(name)}</div>
                <div class="row-meta">${esc(target)}</div>
              </div>
              <button data-rest="${restSec}">Отдых ${restSec}с</button>
            </div>
            <div class="chips">${chips}</div>
          </div>
        `;
      }).join("");

      root.innerHTML = `
        <div class="exercise">
          <div class="exercise-top">
            <div>
              <div class="row-name">${esc(String(warm.label || "Разминка"))}</div>
              <div class="hint">${esc(String(warm.description || ""))}</div>
            </div>
            <button data-count="${warmMin*60}">Таймер ${warmMin}:00</button>
          </div>
        </div>
        <div class="exercise">
          <div class="row-name">Основной блок</div>
          <div class="hint">${esc(String(main.description || ""))}</div>
          <div class="chips"><button data-rest="${restSec}">Пауза ${restSec}с</button></div>
        </div>
        ${exerciseRows}
        <div class="exercise">
          <div class="exercise-top">
            <div>
              <div class="row-name">${esc(String(cool.label || "Заминка"))}</div>
              <div class="hint">${esc(String(cool.description || ""))}</div>
            </div>
            <button data-count="${coolMin*60}">Таймер ${coolMin}:00</button>
          </div>
        </div>
        <div class="muted">Фокус: ${esc(String(script.focus || ""))}</div>
      `;

      root.querySelectorAll("[data-count]").forEach((node)=>{
        node.addEventListener("click", ()=> timerStartCountdown(Number(node.getAttribute("data-count")||0), "Таймер шага"));
      });
      root.querySelectorAll("[data-rest]").forEach((node)=>{
        node.addEventListener("click", ()=> timerStartCountdown(Number(node.getAttribute("data-rest")||0), "Отдых"));
      });
      root.querySelectorAll("[data-check]").forEach((node)=>{
        node.addEventListener("click", ()=>{
          const key = String(node.getAttribute("data-check")||"");
          if(!key) return;
          state.checks[key] = !state.checks[key];
          saveChecks(state.selectedId);
          renderScript(script);
        });
      });
    }

    function renderVideos(videos){
      const player = el("videoPlayer");
      const title = el("videoTitle");
      const list = el("videoList");
      const items = arr(videos);
      el("videoCount").textContent = `${items.length}`;
      if(!items.length){
        list.innerHTML = `<div class="hint">Видео пока не добавлены.</div>`;
        return;
      }
      const setVideo = (url,name)=>{
        if(player){ player.src = url; player.load(); }
        if(title){ title.textContent = name || "Видео"; }
      };
      list.innerHTML = items.map((it,idx)=>{
        const name = String(it.title || it.name || `Видео ${idx+1}`);
        const url = String(it.stream_url || "");
        const meta = [Number(it.size_mb||0) > 0 ? `${Number(it.size_mb).toFixed(2)} MB` : "", String(it.modified_at||"").slice(0,16).replace("T"," ")].filter(Boolean).join(" · ");
        return `<button data-url="${esc(url)}" data-title="${esc(name)}">${esc(name)}${meta ? `<div class="row-meta">${esc(meta)}</div>`:""}</button>`;
      }).join("");
      const first = list.querySelector("button[data-url]");
      if(first){ setVideo(first.getAttribute("data-url")||"", first.getAttribute("data-title")||""); }
      list.querySelectorAll("button[data-url]").forEach((node)=>{
        node.addEventListener("click", ()=> setVideo(node.getAttribute("data-url")||"", node.getAttribute("data-title")||""));
      });
    }

    async function logDone(){
      const workoutId = Number(state.selectedId || 0);
      if(!workoutId){ setStatus("Сначала выбери тренировку.", "status-bad"); return; }
      const payload = {
        user_id: userId,
        workout_id: workoutId,
        rpe: Number(el("rpeInput").value || 0) || null,
        comment: String(el("commentInput").value || "").trim(),
      };
      const res = await fetch("/dashboard/fitness/session", {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify(payload),
      });
      if(!res.ok){ setStatus(`Не удалось сохранить: HTTP ${res.status}`, "status-bad"); return; }
      const data = await res.json();
      setStatus(String(data.next_hint || "Сессия сохранена."), "status-ok");
    }

    function currentWorkout(training){
      const workouts = arr(training && training.workouts);
      let selected = workouts.find((w)=> Number(w && w.id) === Number(state.selectedId));
      if(!selected){
        selected = workouts[0] || null;
        state.selectedId = selected ? Number(selected.id||0) : 0;
      }
      return selected;
    }

    function renderTraining(training){
      state.training = training || {};
      const workouts = arr(training && training.workouts);
      const select = el("workoutSelect");
      select.innerHTML = workouts.map((w)=>`<option value="${Number(w.id||0)}">#${Number(w.id||0)} · ${esc(String(w.title||"Тренировка"))}</option>`).join("");
      if(state.selectedId){ select.value = String(state.selectedId); }
      if(!select.value && workouts.length){ select.value = String(Number(workouts[0].id||0)); }
      state.selectedId = Number(select.value||0);
      const selected = currentWorkout(training);
      const script = selected && selected.script && typeof selected.script === "object"
        ? selected.script
        : (training && training.today_script && typeof training.today_script === "object" ? training.today_script : null);
      loadChecks(state.selectedId);
      renderScript(script);
      renderVideos(training && training.ritual_videos);
      const title = el("studioTitle");
      if(title){
        const plan = training && training.today_plan && typeof training.today_plan === "object" ? training.today_plan : null;
        title.textContent = plan ? `Сегодня: #${Number(plan.id||0)} ${String(plan.title||"Тренировка")}` : "Fitness Studio";
      }
      setStatus("Готово. Сценарий загружен.", "status-ok");
    }

    async function refresh(){
      try{
        const res = await fetch(`/dashboard/data?user_id=${userId}&ai=1`);
        if(!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = await res.json();
        const section = payload && payload.sections && payload.sections.training ? payload.sections.training.data : payload.training;
        renderTraining(section || {});
      }catch(err){
        setStatus(`Ошибка загрузки: ${err.message}`, "status-bad");
      }
    }

    el("workoutSelect").addEventListener("change", ()=>{ state.selectedId = Number(el("workoutSelect").value||0); renderTraining(state.training); });
    el("refreshBtn").addEventListener("click", ()=>{ void refresh(); });
    el("backBtn").addEventListener("click", ()=>{ window.location.href = "/dashboard"; });
    el("logDoneBtn").addEventListener("click", ()=>{ void logDone(); });
    el("timerStopBtn").addEventListener("click", ()=> timerStop());
    el("timerRestBtn").addEventListener("click", ()=> timerStartCountdown(90, "Отдых"));
    el("timerTabataBtn").addEventListener("click", ()=> timerStartTabata(45, 15, 10));

    void refresh();
  </script>
</body>
</html>
"""


def _dashboard_ai_enabled() -> bool:
    raw = os.getenv("DASHBOARD_AI_BRIEF", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _dashboard_ai_everywhere_enabled() -> bool:
    raw = os.getenv("DASHBOARD_AI_EVERYWHERE", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _codex_bridge_enabled() -> bool:
    raw = os.getenv("DASHBOARD_CODEX_BRIDGE", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _handle(
    user_id: int,
    command: str,
    payload: dict | None = None,
    *,
    debug: int = 0,
) -> dict[str, object]:
    want_events = bool(debug == 1 and _debug_events_enabled())
    return handle_command(user_id, command, payload, return_events=want_events)


async def _handle_async(
    user_id: int,
    command: str,
    payload: dict | None = None,
    *,
    debug: int = 0,
) -> dict[str, object]:
    return await asyncio.to_thread(_handle, user_id, command, payload, debug=debug)


def _unwrap_result(value: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    maybe_result = value.get("result")
    maybe_events = value.get("events")
    if isinstance(maybe_result, dict):
        events = maybe_events if isinstance(maybe_events, list) else []
        return maybe_result, [event for event in events if isinstance(event, dict)]
    return value, []


def _freshness_label(age_sec: int) -> str:
    if age_sec <= 5:
        return "только что"
    if age_sec < 60:
        return f"{age_sec}с назад"
    if age_sec < 3600:
        return f"{age_sec // 60}м назад"
    return f"{age_sec // 3600}ч назад"


def _build_freshness(as_of: str, *, stale_after_sec: int = 300) -> dict[str, object]:
    age_sec = 0
    try:
        as_of_dt = datetime.fromisoformat(str(as_of))
        age_sec = max(0, int((datetime.now() - as_of_dt).total_seconds()))
    except ValueError:
        age_sec = 0
    state = "fresh" if age_sec <= max(1, int(stale_after_sec)) else "stale"
    return {
        "as_of": as_of,
        "age_sec": age_sec,
        "stale_after_sec": max(1, int(stale_after_sec)),
        "state": state,
        "label": _freshness_label(age_sec),
    }


def _section_payload(
    data: object,
    *,
    as_of: str,
    stale_after_sec: int,
) -> dict[str, object]:
    return {
        "data": data,
        "freshness": _build_freshness(as_of, stale_after_sec=stale_after_sec),
    }


def _safe_temp(summary: str) -> float | None:
    m = re.search(r"(-?\d+(?:[\.,]\d+)?)\s*C", summary or "")
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _clothing_advice(weather_summary: str) -> str:
    lower = (weather_summary or "").lower()
    temp = _safe_temp(weather_summary)
    if temp is not None and temp <= -10:
        return "Термослой + утепленная куртка + шапка/перчатки."
    if temp is not None and temp <= 0:
        return "Куртка, тёплый средний слой и непромокаемая обувь."
    if temp is not None and temp <= 12:
        return "Лёгкая куртка или худи + длинные брюки."
    if temp is not None and temp <= 22:
        return "Футболка/лонгслив + лёгкий верх на вечер."
    if "дожд" in lower or "лив" in lower:
        return "Возьми дождевик или зонт, обувь лучше водостойкую."
    if temp is not None and temp >= 28:
        return "Дышащая одежда, головной убор и вода с собой."
    return "Ориентируйся на комфорт: лёгкий слой и запасной верх на вечер."


def _cache_get_json(key: str, ttl_seconds: int) -> dict[str, object] | None:
    row = get_cache_value(key)
    if not row or not row[0] or not row[1]:
        return None
    try:
        updated = datetime.fromisoformat(str(row[1]))
    except ValueError:
        return None
    age = (datetime.now() - updated).total_seconds()
    if age > ttl_seconds:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _cache_set_json(key: str, payload: dict[str, object]) -> None:
    set_cache_value(key, json.dumps(payload, ensure_ascii=False), _now_iso())


def _parse_llm_json_object(raw: str) -> dict[str, object] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _chat_history_key(user_id: int) -> str:
    return f"dashboard:gemma:history:{user_id}"


def _chat_history_load(user_id: int) -> list[dict[str, str]]:
    row = get_cache_value(_chat_history_key(user_id))
    if not row or not row[0]:
        return []
    try:
        raw = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content})
    return out[-_GEMMA_HISTORY_MAX_ITEMS:]


def _chat_history_save(user_id: int, history: list[dict[str, str]]) -> None:
    clean = []
    for item in history[-_GEMMA_HISTORY_MAX_ITEMS:]:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            clean.append({"role": role, "content": content})
    set_cache_value(_chat_history_key(user_id), json.dumps(clean, ensure_ascii=False), _now_iso())


def _chat_history_append(user_id: int, *, role: str, content: str) -> None:
    clean_role = str(role or "").strip()
    clean_content = str(content or "").strip()
    if clean_role not in {"user", "assistant"} or not clean_content:
        return
    history = _chat_history_load(user_id)
    history.append({"role": clean_role, "content": clean_content})
    _chat_history_save(user_id, history)


def _chat_history_append_exchange(user_id: int, *, user_text: str, assistant_text: str) -> None:
    clean_user = str(user_text or "").strip()
    clean_assistant = str(assistant_text or "").strip()
    if not clean_user or not clean_assistant:
        return
    history = _chat_history_load(user_id)
    if len(history) >= 2:
        last_user = history[-2]
        last_assistant = history[-1]
        if (
            isinstance(last_user, dict)
            and isinstance(last_assistant, dict)
            and str(last_user.get("role") or "") == "user"
            and str(last_assistant.get("role") or "") == "assistant"
            and str(last_user.get("content") or "").strip() == clean_user
            and str(last_assistant.get("content") or "").strip() == clean_assistant
        ):
            return
    history.append({"role": "user", "content": clean_user})
    history.append({"role": "assistant", "content": clean_assistant})
    _chat_history_save(user_id, history)


def _gemma_nudge_state_key(user_id: int) -> str:
    return f"{_GEMMA_NUDGE_STATE_PREFIX}{int(user_id)}"


def _gemma_nudge_state_load(user_id: int) -> dict[str, object]:
    row = get_cache_value(_gemma_nudge_state_key(user_id))
    default: dict[str, object] = {"cursor": 0, "last_sent_at": ""}
    if not row or not row[0]:
        return default
    try:
        payload = json.loads(str(row[0]))
    except Exception:
        return default
    if not isinstance(payload, dict):
        return default
    cursor_raw = payload.get("cursor")
    try:
        cursor = int(cursor_raw) if cursor_raw is not None else 0
    except Exception:
        cursor = 0
    last_sent_at = str(payload.get("last_sent_at") or "").strip()
    return {"cursor": max(0, cursor), "last_sent_at": last_sent_at}


def _gemma_nudge_state_save(user_id: int, *, cursor: int, last_sent_at: str) -> None:
    payload = {
        "cursor": max(0, int(cursor)),
        "last_sent_at": str(last_sent_at or "").strip(),
    }
    set_cache_value(_gemma_nudge_state_key(user_id), json.dumps(payload, ensure_ascii=False), _now_iso())


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _parse_hhmm_minutes(raw: object) -> int | None:
    text = str(raw or "").strip()
    if not text or len(text) != 5 or text[2] != ":":
        return None
    try:
        hh = int(text[:2])
        mm = int(text[3:])
    except Exception:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def _in_quiet_hours(user_id: int, now_dt: datetime) -> bool:
    profile = user_settings_get_full(user_id)
    start_min = _parse_hhmm_minutes(profile.get("quiet_start"))
    end_min = _parse_hhmm_minutes(profile.get("quiet_end"))
    if start_min is None or end_min is None:
        return False
    cur = now_dt.hour * 60 + now_dt.minute
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= cur < end_min
    return cur >= start_min or cur < end_min


def _build_gemma_nudge_candidates(user_id: int) -> list[dict[str, object]]:
    today_raw = _handle(user_id, "today", debug=0)
    tasks_raw = _handle(user_id, "tasks:list", {"limit": 8}, debug=0)
    today, _ = _unwrap_result(today_raw)
    tasks_obj, _ = _unwrap_result(tasks_raw)
    tasks = tasks_obj.get("items") if isinstance(tasks_obj.get("items"), list) else []
    trend = _trend_panel(user_id)
    stats = _stats_panel(user_id)
    training = _training_panel(user_id)

    open_tasks = len(tasks)
    energy = _safe_int(today.get("energy"))
    trend_summary = str(trend.get("summary") or "").strip()

    candidates: list[dict[str, object]] = []

    if isinstance(energy, int) and energy <= 4:
        candidates.append(
            {
                "kind": "signal",
                "message": (
                    f"Сигнал: энергия {energy}/10. Держи щадящий режим: 1 ключевая задача, "
                    "потом короткий фокус-блок 25 минут."
                ),
                "quick_actions": [
                    {"type": "focus_start", "label": "Фокус 25м"},
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
            }
        )

    if open_tasks >= 8:
        candidates.append(
            {
                "kind": "signal",
                "message": (
                    f"Сигнал: в списке {open_tasks} открытых задач. "
                    "Срежь день до top-3, чтобы не распыляться."
                ),
                "quick_actions": [
                    {"type": "replan_day", "label": "Переплан дня"},
                    {"type": "focus_start", "label": "Фокус 25м"},
                ],
            }
        )
    elif open_tasks == 0:
        candidates.append(
            {
                "kind": "signal",
                "message": "Сигнал: список чистый. Хороший момент добавить 1 осознанную задачу на рост.",
                "quick_actions": [
                    {"type": "task_add", "label": "Добавить задачу"},
                ],
            }
        )

    if isinstance(energy, int) and energy >= 8 and open_tasks >= 1:
        candidates.append(
            {
                "kind": "casual",
                "message": "Как ты? По энергии у тебя сейчас хороший ход. Хочешь, зафиксируем один мощный фокус-блок?",
                "quick_actions": [
                    {"type": "focus_start", "label": "Фокус 25м"},
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
            }
        )

    first_task_text = ""
    if tasks:
        first_task = tasks[0]
        if isinstance(first_task, dict):
            first_task_text = str(first_task.get("text") or "").strip()
    if first_task_text:
        candidates.append(
            {
                "kind": "signal",
                "message": f"Сигнал по дню: начни с «{first_task_text}». Достаточно первого подшага на 10 минут.",
                "quick_actions": [
                    {"type": "focus_start", "label": "Фокус 25м"},
                ],
            }
        )

    if trend_summary:
        candidates.append(
            {
                "kind": "signal",
                "message": f"Сигнал недели: {trend_summary}",
                "quick_actions": [
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
            }
        )

    today_plan = training.get("today_plan") if isinstance(training, dict) else None
    plan_title = ""
    if isinstance(today_plan, dict):
        plan_title = str(today_plan.get("title") or "").strip().lower()
    interval_tokens = ("tabata", "табата", "emom", "интервал", "45/15", "20/10")
    if plan_title and any(token in plan_title for token in interval_tokens):
        candidates.append(
            {
                "kind": "signal",
                "message": (
                    "Смотри, что я придумала: у тебя интервальная тренировка, "
                    "логично подключить таймер (например 45/15 или 20/10) и вести подходы без ручного контроля."
                ),
                "quick_actions": [
                    {"type": "focus_start", "label": "Фокус 25м"},
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
            }
        )

    candidates.extend(
        [
            {
                "kind": "casual",
                "message": "Я тут придумала новую фишку для дашборда: авто-пакет «утро/день/вечер» по одному клику. Проверим позже?",
                "quick_actions": [
                    {"type": "replan_day", "label": "Переплан дня"},
                    {"type": "task_add", "label": "+ Задача"},
                ],
            },
            {
                "kind": "casual",
                "message": "Короткий пинг: как дела с главным приоритетом сегодня? Могу помочь дожать до результата.",
                "quick_actions": [
                    {"type": "focus_start", "label": "Фокус 25м"},
                ],
            },
            {
                "kind": "casual",
                "message": "Слышал свежий трек для тренировки? Если хочешь, добавим виджет плейлиста прямо в фитнес-модуль.",
                "quick_actions": [
                    {"type": "task_add", "label": "+ Задача"},
                ],
            },
        ]
    )

    day_idx = datetime.now().timetuple().tm_yday
    fact_idx = (day_idx + int(user_id)) % len(_GEMMA_MICRO_FACTS)
    fact_text = _GEMMA_MICRO_FACTS[fact_idx]
    days_on_planet = _safe_int(stats.get("days_on_planet"))
    if isinstance(days_on_planet, int) and days_on_planet > 0:
        fact_message = f"Факт дня: сегодня твой {days_on_planet}-й день на планете. {fact_text}"
    else:
        fact_message = f"Факт дня: {fact_text}"
    candidates.append(
        {
            "kind": "fact",
            "message": fact_message,
            "quick_actions": [
                {"type": "focus_start", "label": "Фокус 25м"},
                {"type": "task_add", "label": "+ Задача"},
            ],
        }
    )

    return candidates


def _pick_gemma_nudge(user_id: int, *, force: bool = False) -> tuple[dict[str, object] | None, int]:
    state = _gemma_nudge_state_load(user_id)
    now_dt = datetime.now()
    now_iso = now_dt.isoformat(timespec="seconds")
    last_sent_raw = str(state.get("last_sent_at") or "").strip()
    cursor = max(0, int(state.get("cursor") or 0))
    rng = random.Random()

    last_sent_dt: datetime | None = None
    if last_sent_raw:
        try:
            last_sent_dt = datetime.fromisoformat(last_sent_raw)
        except Exception:
            last_sent_dt = None

    if not force and _in_quiet_hours(user_id, now_dt):
        return None, 900

    if not force and last_sent_dt is None:
        # Anti-spam bootstrap: never push immediately after restart/new session.
        _gemma_nudge_state_save(user_id, cursor=cursor, last_sent_at=now_iso)
        return None, rng.randint(_GEMMA_NUDGE_IDLE_POLL_MIN_SEC, _GEMMA_NUDGE_IDLE_POLL_MAX_SEC)

    if not force and isinstance(last_sent_dt, datetime):
        elapsed_sec = int((now_dt - last_sent_dt).total_seconds())
        if elapsed_sec < _GEMMA_NUDGE_MIN_INTERVAL_SEC:
            wait_sec = max(15, _GEMMA_NUDGE_MIN_INTERVAL_SEC - elapsed_sec)
            return None, wait_sec

    if not force and rng.random() > _GEMMA_NUDGE_SEND_PROBABILITY:
        return None, rng.randint(_GEMMA_NUDGE_IDLE_POLL_MIN_SEC, _GEMMA_NUDGE_IDLE_POLL_MAX_SEC)

    candidates = _build_gemma_nudge_candidates(user_id)
    if not candidates:
        return None, _GEMMA_NUDGE_DEFAULT_POLL_SEC

    idx = (cursor + rng.randrange(len(candidates))) % len(candidates)
    chosen = candidates[idx]
    kind = str(chosen.get("kind") or "signal").strip().lower()
    base_ms = 1100 if kind == "signal" else 1450
    typing_ms = base_ms + ((cursor * 173) % 420)
    payload = {
        "kind": kind,
        "message": str(chosen.get("message") or "").strip(),
        "quick_actions": chosen.get("quick_actions") if isinstance(chosen.get("quick_actions"), list) else [],
        "typing_ms": int(max(700, min(2600, typing_ms))),
        "sent_at": now_iso,
    }
    _gemma_nudge_state_save(user_id, cursor=cursor + 1, last_sent_at=now_iso)
    return payload, rng.randint(_GEMMA_NUDGE_IDLE_POLL_MIN_SEC, _GEMMA_NUDGE_IDLE_POLL_MAX_SEC)


async def _safe_async(default: Any, coro: Any, timeout_sec: float = 6.5) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except Exception:
        return default


async def _load_weather_panel(city: str, lang: str) -> dict[str, object]:
    cache_key = f"dashboard:weather:{city.strip().lower()}:{lang.strip().lower()}"
    cached = _cache_get_json(cache_key, 120)
    if cached and "summary" in cached:
        return {
            "city": str(cached.get("city") or city),
            "summary": str(cached.get("summary") or "Погода временно недоступна"),
            "clothing": str(cached.get("clothing") or _clothing_advice(str(cached.get("summary") or ""))),
        }

    summary = await _safe_async("Погода временно недоступна", fetch_weather_summary(city, lang), timeout_sec=7.0)
    panel = {
        "city": city,
        "summary": str(summary),
        "clothing": _clothing_advice(str(summary)),
    }
    _cache_set_json(cache_key, panel)
    return panel


async def _load_news_panel(profile: dict[str, Any] | None = None, *, ai_enabled: bool = True) -> dict[str, object]:
    active_profile = _normalize_news_profile(profile if isinstance(profile, dict) else None)
    profile_seed = json.dumps(active_profile, ensure_ascii=False, sort_keys=True)
    panel_cache_hash = hashlib.sha1(f"{int(bool(ai_enabled))}:{profile_seed}".encode("utf-8")).hexdigest()[:16]
    panel_cache_key = f"dashboard:news_panel:{panel_cache_hash}"
    cached_panel = _cache_get_json(panel_cache_key, 120)
    if cached_panel and isinstance(cached_panel.get("items"), list):
        return cached_panel

    links = await _safe_async([], fetch_topic_links(limit_total=18), timeout_sec=8.5)
    valid_links: list[dict[str, object]] = [x for x in links if isinstance(x, dict)]
    interests = set(str(x) for x in active_profile.get("interests", []))
    hidden_topics = set(str(x) for x in active_profile.get("hidden_topics", []))
    hidden_sources = set(str(x) for x in active_profile.get("hidden_sources", []))

    normalized_items: list[dict[str, object]] = []
    for item in valid_links:
        topic = str(item.get("topic") or "").strip().lower() or "технологии"
        if topic not in _NEWS_TOPIC_CATALOG:
            topic = "технологии"
        url = str(item.get("url") or "").strip()
        source = _normalize_source_host(url)
        title = str(item.get("title") or "").strip()
        try:
            ts = float(str(item.get("published_ts") or "0"))
        except ValueError:
            ts = 0.0
        normalized_items.append(
            {
                "topic": topic,
                "title": title,
                "url": url,
                "source": source,
                "published_ts": f"{ts:.0f}",
            }
        )

    available_topics = sorted({str(item.get("topic") or "") for item in normalized_items if str(item.get("topic") or "")})
    available_sources = sorted({str(item.get("source") or "") for item in normalized_items if str(item.get("source") or "")})

    filtered: list[dict[str, object]] = []
    filtered_out = {"topic": 0, "source": 0, "interest": 0}
    for item in normalized_items:
        topic = str(item.get("topic") or "")
        source = str(item.get("source") or "")
        if topic in hidden_topics:
            filtered_out["topic"] += 1
            continue
        if source and source in hidden_sources:
            filtered_out["source"] += 1
            continue
        if interests and topic not in interests:
            filtered_out["interest"] += 1
            continue
        filtered.append(item)

    # Guarantee baseline amount for dashboard readability even with strict interests.
    if len(filtered) < 5 and not interests:
        seen_urls = {str(item.get("url") or "") for item in filtered}
        for item in normalized_items:
            url = str(item.get("url") or "")
            topic = str(item.get("topic") or "")
            source = str(item.get("source") or "")
            if not url or url in seen_urls:
                continue
            if topic in hidden_topics:
                continue
            if source and source in hidden_sources:
                continue
            filtered.append(item)
            seen_urls.add(url)
            if len(filtered) >= 8:
                break

    now_ts = datetime.now().timestamp()

    def _published_ts(item: dict[str, object]) -> float:
        try:
            return float(str(item.get("published_ts") or "0"))
        except ValueError:
            return 0.0

    def _hype_score(item: dict[str, object]) -> int:
        title = str(item.get("title") or "").lower()
        topic = str(item.get("topic") or "")
        score = 0
        if any(token in title for token in ("тренд", "хайп", "viral", "launch", "новый", "breaking", "громк")):
            score += 3
        if topic in interests:
            score += 3
        if any(token in title for token in ("ai", "ии", "llm", "chatgpt", "dota", "motogp", "крипт")):
            score += 2
        ts = _published_ts(item)
        if ts > 0:
            age_hours = max(0.0, (now_ts - ts) / 3600.0)
            if age_hours <= 8:
                score += 2
            elif age_hours <= 24:
                score += 1
        return score

    def _priority_for(item: dict[str, object], score: int) -> str:
        title = str(item.get("title") or "").lower()
        ts = _published_ts(item)
        age_hours = max(0.0, (now_ts - ts) / 3600.0) if ts > 0 else 9999.0
        urgent_tokens = (
            "breaking",
            "срочно",
            "urgent",
            "alert",
            "экстр",
            "критич",
            "взлом",
            "утечк",
            "обвал",
            "санкц",
            "exploit",
        )
        if score >= 6:
            return "urgent"
        if age_hours <= 8 and any(token in title for token in urgent_tokens):
            return "urgent"
        if score >= 3 or age_hours <= 24:
            return "medium"
        return "low"

    for item in filtered:
        score = _hype_score(item)
        item["_priority_score"] = score
        item["_priority"] = _priority_for(item, score)

    sorted_links = sorted(filtered, key=lambda item: int(item.get("_priority_score") or 0), reverse=True)
    hype_urls = {str(item.get("url") or "") for item in sorted_links[:5]}

    def _why_line(item: dict[str, object]) -> str:
        parts: list[str] = []
        topic = str(item.get("topic") or "")
        source = str(item.get("source") or "")
        if topic and topic in interests:
            parts.append(f"в профиле интересов: {topic}")
        if str(item.get("url") or "") in hype_urls:
            parts.append("в топе по резонансу")
        if source:
            parts.append(f"источник: {source}")
        try:
            ts = float(str(item.get("published_ts") or "0"))
        except ValueError:
            ts = 0.0
        if ts > 0:
            age_hours = max(0.0, (now_ts - ts) / 3600.0)
            if age_hours <= 1:
                parts.append("опубликовано менее часа назад")
            elif age_hours <= 24:
                parts.append(f"свежесть: {int(round(age_hours))} ч назад")
        return "; ".join(parts[:3]) if parts else "базовый сигнал по теме"

    def _decorate(source_items: list[dict[str, object]]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for item in source_items:
            payload = dict(item)
            payload.pop("_priority", None)
            payload.pop("_priority_score", None)
            payload["priority"] = str(item.get("_priority") or "medium")
            payload["priority_score"] = int(item.get("_priority_score") or 0)
            payload["why"] = _why_line(item)
            out.append(payload)
        return out

    # LLM headline rewrite for dashboard readability (short, factual), with safe fallback.
    async def _rewrite_news_titles(items: list[dict[str, object]]) -> list[str]:
        titles = [str(item.get("title") or "").strip() for item in items if str(item.get("title") or "").strip()]
        if not titles:
            return []
        settings = _settings()
        if not ai_enabled or not settings or not _dashboard_ai_enabled():
            return titles

        cache_hash = hashlib.sha1("\n".join(titles).encode("utf-8")).hexdigest()[:16]
        cache_key = f"dashboard:news_rewrite:{cache_hash}"
        cached = _cache_get_json(cache_key, 900)
        if cached and isinstance(cached.get("titles"), list):
            payload = [str(x).strip() for x in cached.get("titles") if str(x).strip()]
            if len(payload) == len(titles):
                return payload

        prompt = (
            "Перепиши заголовки новостей на русском, кратко и по делу.\n"
            "Правила:\n"
            "1) Не искажать факты, цифры, имена и смысл.\n"
            "2) Убрать кликбейт и лишние обороты.\n"
            "3) Каждый заголовок до 110 символов.\n"
            "4) Верни строго JSON-массив строк, того же размера.\n\n"
            f"Заголовки:\n{json.dumps(titles, ensure_ascii=False)}"
        )
        try:
            llm_prompt = build_prompt(
                history=[],
                user_message=prompt,
                settings=settings,
                mode="fast",
                profile="rewriter",
            )
            raw = await asyncio.wait_for(
                call_ollama(llm_prompt, settings, mode="fast", profile="rewriter"),
                timeout=min(6.0, max(2.8, float(getattr(settings, "llm_enhancer_timeout_seconds", 3.5)) + 1.5)),
            )
            text = (raw or "").strip()
            payload: list[str] | None = None
            try:
                maybe = json.loads(text)
                if isinstance(maybe, list):
                    payload = [str(x).strip() for x in maybe]
            except Exception:
                start = text.find("[")
                end = text.rfind("]")
                if start != -1 and end != -1 and end > start:
                    try:
                        maybe = json.loads(text[start : end + 1])
                        if isinstance(maybe, list):
                            payload = [str(x).strip() for x in maybe]
                    except Exception:
                        payload = None
            if not payload or len(payload) != len(titles):
                return titles
            cleaned: list[str] = []
            for old, new in zip(titles, payload):
                value = new or old
                if len(value) > 110:
                    value = value[:107].rstrip() + "..."
                cleaned.append(value)
            _cache_set_json(cache_key, {"titles": cleaned})
            return cleaned
        except Exception:
            return titles

    rewrite_targets = sorted_links[:12]
    rewritten = await _rewrite_news_titles(rewrite_targets)
    if len(rewritten) == len(rewrite_targets):
        by_url: dict[str, str] = {}
        for item, title in zip(rewrite_targets, rewritten):
            url = str(item.get("url") or "")
            if url and title:
                by_url[url] = title
        if by_url:
            for item in filtered:
                url = str(item.get("url") or "")
                if url in by_url:
                    item["title"] = by_url[url]
            for item in sorted_links:
                url = str(item.get("url") or "")
                if url in by_url:
                    item["title"] = by_url[url]

    priority_rank = {"urgent": 0, "medium": 1, "low": 2}
    ranked_for_feed = sorted(
        filtered,
        key=lambda item: (
            priority_rank.get(str(item.get("_priority") or "medium"), 1),
            -int(item.get("_priority_score") or 0),
            -_published_ts(item),
        ),
    )
    priority_counts = {"urgent": 0, "medium": 0, "low": 0}
    for item in ranked_for_feed:
        key = str(item.get("_priority") or "medium")
        if key not in priority_counts:
            key = "medium"
        priority_counts[key] += 1

    panel = {
        "items": _decorate(ranked_for_feed[:12]),
        "hype": _decorate(sorted_links[:5]),
        "priority_counts": priority_counts,
        "profile": active_profile,
        "catalog": {
            "topics": available_topics,
            "sources": available_sources,
        },
        "noise": {
            "raw_count": len(normalized_items),
            "shown_count": len(filtered),
            "filtered_topic": int(filtered_out["topic"]),
            "filtered_source": int(filtered_out["source"]),
            "filtered_interest": int(filtered_out["interest"]),
        },
    }
    _cache_set_json(panel_cache_key, panel)
    return panel


async def _load_signals_panel(limit: int = 20) -> dict[str, object]:
    default = {
        "enabled": False,
        "status": "off",
        "count": 0,
        "items": [],
        "sources": {
            "imap": {"enabled": False, "status": "off", "count": 0, "error": ""},
            "local_files": {"enabled": False, "status": "off", "count": 0, "error": ""},
        },
    }
    safe_limit = max(1, min(int(limit), 200))
    cache_key = f"dashboard:signals:{safe_limit}"
    cached = _cache_get_json(cache_key, 60)
    if cached and isinstance(cached.get("sources"), dict):
        return cached
    panel = await _safe_async(default, fetch_ingest_signals(limit=safe_limit), timeout_sec=8.0)
    if not isinstance(panel, dict):
        return default
    _cache_set_json(cache_key, panel)
    return panel


def _fmt_change(value: float | None) -> str:
    if value is None:
        return "н/д"
    return f"{float(value):+.1f}%"


async def _load_market_panel() -> dict[str, object]:
    settings = _settings()
    vs = (settings.coingecko_vs if settings else (os.getenv("COINGECKO_VS") or "usd")).lower()
    cache_key = f"dashboard:market:{vs}"
    cached = _cache_get_json(cache_key, 90)
    if cached and isinstance(cached.get("highlights"), list):
        return cached

    prices_task = _safe_async({}, fetch_prices(vs), timeout_sec=6.5)
    fx_task = _safe_async({}, fetch_usd_eur_to_rub(), timeout_sec=6.5)
    fuel_task = _safe_async({}, fetch_fuel95_moscow_data(settings), timeout_sec=7.0) if settings else None

    prices, fx = await asyncio.gather(prices_task, fx_task)
    fuel: dict[str, object] = {}
    if fuel_task is not None:
        fuel = await fuel_task

    btc = prices.get("bitcoin", {}) if isinstance(prices, dict) else {}
    eth = prices.get("ethereum", {}) if isinstance(prices, dict) else {}
    out: dict[str, object] = {
        "vs": vs.upper(),
        "btc": {
            "price": float(btc.get(vs, 0)) if btc else None,
            "change_24h": btc.get(f"{vs}_24h_change") if btc else None,
        },
        "eth": {
            "price": float(eth.get(vs, 0)) if eth else None,
            "change_24h": eth.get(f"{vs}_24h_change") if eth else None,
        },
        "usd_rub": {
            "price": float(fx.get("usd_rub", 0)) if isinstance(fx, dict) and fx else None,
            "change_24h": fx.get("usd_rub_24h_change") if isinstance(fx, dict) else None,
        },
        "eur_rub": {
            "price": float(fx.get("eur_rub", 0)) if isinstance(fx, dict) and fx else None,
            "change_24h": fx.get("eur_rub_24h_change") if isinstance(fx, dict) else None,
        },
    }
    if fuel:
        out["fuel95"] = {
            "price": float(fuel.get("price_rub", 0)) if fuel.get("price_rub") is not None else None,
            "change_24h": fuel.get("change_24h_pct"),
        }

    highlights: list[str] = []
    if out["btc"]["price"]:
        highlights.append(f"BTC {out['btc']['price']:.0f} ({_fmt_change(out['btc']['change_24h'])})")
    if out["eth"]["price"]:
        highlights.append(f"ETH {out['eth']['price']:.0f} ({_fmt_change(out['eth']['change_24h'])})")
    if out["usd_rub"]["price"]:
        highlights.append(f"USD/RUB {out['usd_rub']['price']:.2f} ({_fmt_change(out['usd_rub']['change_24h'])})")
    if out.get("fuel95") and out["fuel95"]["price"]:
        highlights.append(f"AI-95 {out['fuel95']['price']:.2f} RUB ({_fmt_change(out['fuel95']['change_24h'])})")
    out["highlights"] = highlights
    _cache_set_json(cache_key, out)
    return out


def _workout_title_from_row(row: Any) -> str:
    try:
        return str(row[1] or "").strip()
    except Exception:
        return ""


def _csv_tokens(value: Any) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in str(value).split(","):
        item = token.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _serialize_workout_row(row: Any) -> dict[str, object] | None:
    if not row:
        return None
    try:
        workout_id = int(row[0])
    except Exception:
        return None
    title = _workout_title_from_row(row)
    difficulty = int(row[4] or 2) if len(row) > 4 else 2
    duration_sec = int(row[5] or 0) if len(row) > 5 else 0
    notes = str(row[6] or "").strip() if len(row) > 6 else ""
    return {
        "id": workout_id,
        "title": title,
        "tags": _csv_tokens(row[2] if len(row) > 2 else ""),
        "equipment": _csv_tokens(row[3] if len(row) > 3 else ""),
        "difficulty": max(1, min(5, difficulty)),
        "duration_sec": max(0, duration_sec),
        "duration_min": max(1, round(max(0, duration_sec) / 60)) if duration_sec else 25,
        "notes": notes,
        "created_at": str(row[10] or "").strip() if len(row) > 10 else "",
    }


def _fitness_timer_presets() -> dict[str, object]:
    return {
        "tabata": [
            {"label": "Табата 20/10 × 8", "work_sec": 20, "rest_sec": 10, "rounds": 8},
            {"label": "Интервалы 45/15 × 10", "work_sec": 45, "rest_sec": 15, "rounds": 10},
            {"label": "Интервалы 30/30 × 12", "work_sec": 30, "rest_sec": 30, "rounds": 12},
        ],
        "rest_seconds": [60, 90, 120, 180],
    }


def _suggested_timers_for_workout(
    *,
    workout: dict[str, object] | None,
    activity: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if not isinstance(workout, dict):
        return []

    activity = activity if isinstance(activity, dict) else {}
    title = str(workout.get("title") or "")
    notes = str(workout.get("notes") or "")
    tags = workout.get("tags") if isinstance(workout.get("tags"), list) else []
    equipment = workout.get("equipment") if isinstance(workout.get("equipment"), list) else []
    text_blob = " ".join(
        [
            title,
            notes,
            *[str(x) for x in tags],
            *[str(x) for x in equipment],
        ]
    ).lower()

    difficulty = int(workout.get("difficulty") or 2)
    duration_min = int(workout.get("duration_min") or 25)
    load_state = str(activity.get("load_state") or "").strip().lower()

    timers: list[dict[str, object]] = []
    seen: set[tuple[str, int, int, int]] = set()

    def _add_rest(seconds: int, *, label: str | None = None) -> None:
        sec = max(15, int(seconds))
        key = ("rest", sec, 0, 0)
        if key in seen:
            return
        seen.add(key)
        timers.append(
            {
                "kind": "rest",
                "seconds": sec,
                "label": label or f"Отдых {sec}с",
                "source": "ai",
            }
        )

    def _add_tabata(work_sec: int, rest_sec: int, rounds: int, *, label: str | None = None) -> None:
        work = max(5, int(work_sec))
        rest = max(5, int(rest_sec))
        r = max(1, int(rounds))
        key = ("tabata", work, rest, r)
        if key in seen:
            return
        seen.add(key)
        timers.append(
            {
                "kind": "tabata",
                "work_sec": work,
                "rest_sec": rest,
                "rounds": r,
                "label": label or f"{work}/{rest} × {r}",
                "source": "ai",
            }
        )

    def _add_countdown(seconds: int, *, label: str) -> None:
        sec = max(30, int(seconds))
        key = ("countdown", sec, 0, 0)
        if key in seen:
            return
        seen.add(key)
        timers.append(
            {
                "kind": "countdown",
                "seconds": sec,
                "label": label,
                "source": "ai",
            }
        )

    def _add_stopwatch(*, label: str = "Секундомер подходов") -> None:
        key = ("stopwatch", 0, 0, 0)
        if key in seen:
            return
        seen.add(key)
        timers.append(
            {
                "kind": "stopwatch",
                "label": label,
                "source": "ai",
            }
        )

    is_breathing = any(token in text_blob for token in ("дыхан", "wim hof", "breath"))
    is_mobility = any(token in text_blob for token in ("растяж", "мобил", "mobility", "stretch", "йога", "yoga"))
    is_interval = any(token in text_blob for token in ("табата", "tabata", "hiit", "берпи", "burpee", "интервал", "кардио", "cardio"))
    is_strength = any(
        token in text_blob
        for token in ("подтяг", "отжим", "жим", "гантел", "dumbbell", "pull", "push", "ноги", "legs", "сил")
    )

    if is_breathing:
        _add_countdown(max(180, min(900, duration_min * 60)), label="Дыхательная сессия")
        _add_countdown(300, label="Восстановление 5м")
        _add_stopwatch(label="Секундомер дыхания")

    if is_mobility:
        _add_countdown(max(300, min(1200, duration_min * 60)), label="Растяжка / мобилити")
        _add_rest(45, label="Пауза 45с")

    if is_interval:
        rounds = max(6, min(16, duration_min // 3 or 8))
        _add_tabata(20, 10, 8, label="Табата 20/10 × 8")
        _add_tabata(45, 15, rounds, label=f"Интервалы 45/15 × {rounds}")

    if is_strength:
        base_rest = 90
        if difficulty >= 4 or load_state == "deload":
            base_rest = 120
        elif difficulty <= 2 and load_state == "build":
            base_rest = 75
        _add_rest(base_rest)
        _add_rest(base_rest + 30)
        _add_stopwatch()

    if not timers:
        _add_tabata(30, 30, max(8, duration_min // 3 or 8), label="Интервалы 30/30")
        _add_rest(90)
        _add_stopwatch()

    return timers[:6]


def _workout_tier(*, workout: dict[str, object], activity: dict[str, object]) -> int:
    difficulty = int(workout.get("difficulty") or 2)
    base = max(1, min(5, difficulty))
    load_state = str(activity.get("load_state") or "").strip().lower()
    if load_state == "build":
        base += 1
    elif load_state == "deload":
        base -= 1
    return max(1, min(5, base))


def _workout_token_hit(workout: dict[str, object], *tokens: str) -> bool:
    tags = workout.get("tags") if isinstance(workout.get("tags"), list) else []
    notes = str(workout.get("notes") or "")
    title = str(workout.get("title") or "")
    bag = " ".join([title, notes, *[str(x) for x in tags]]).lower()
    return any(token in bag for token in tokens)


def _build_workout_script(
    *,
    workout: dict[str, object] | None,
    activity: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if not isinstance(workout, dict):
        return None
    activity = activity if isinstance(activity, dict) else {}
    tier = _workout_tier(workout=workout, activity=activity)
    title = str(workout.get("title") or "Тренировка")
    difficulty = int(workout.get("difficulty") or 2)
    duration_min = int(workout.get("duration_min") or 25)
    load_state = str(activity.get("load_state") or "").strip().lower()

    script: dict[str, object] = {
        "title": title,
        "tier": tier,
        "difficulty": difficulty,
        "duration_min": max(20, duration_min),
        "rounds": 4,
        "warmup": {
            "label": "Разминка",
            "minutes": 6,
            "description": "Суставная мобилизация + динамика корпуса/плеч/таза.",
        },
        "main": {
            "rest_sec": 75,
            "description": "Рабочие круги в ровной технике.",
            "exercises": [],
        },
        "cooldown": {
            "label": "Заминка",
            "minutes": 5,
            "description": "Спина/бедра/грудной отдел + дыхание 2 минуты.",
        },
        "focus": "Держи технику и ритм без провала в качестве.",
    }

    is_recovery = _workout_token_hit(workout, "recovery", "восстанов", "mobility", "мобил")
    is_legs = _workout_token_hit(workout, "legs", "ног", "корпус")
    is_pull = _workout_token_hit(workout, "pull", "подтяг", "хват", "тяга")
    is_interval = _workout_token_hit(workout, "burpee", "табата", "hiit", "интервал", "кардио")
    is_dumbbell = _workout_token_hit(workout, "dumbbell", "гантел")

    rounds = 4 + (1 if tier >= 4 else 0)
    if is_recovery:
        rounds = 3 + (1 if tier >= 4 else 0)
        script["main"] = {
            "rest_sec": 45 if tier <= 2 else 60,
            "description": "Восстановительный, но плотный круг.",
            "exercises": [
                {"name": "Приседания", "target": "18-24"},
                {"name": "Отжимания", "target": "14-20"},
                {"name": "Планка", "target": "45 сек"},
                {"name": "Ягодичный мост", "target": "20-26"},
            ],
        }
        script["focus"] = "Лёгкое восстановление без потери тонуса."
    elif is_interval:
        script["warmup"] = {
            "label": "Разминка",
            "minutes": 7,
            "description": "Пульс в рабочую зону: 3 раунда по 40с актив / 20с лёгко.",
        }
        script["main"] = {
            "rest_sec": 15,
            "description": "Интервальный блок, работа по таймеру.",
            "exercises": [
                {"name": "Берпи", "target": "45 сек"},
                {"name": "Mountain climbers", "target": "45 сек"},
                {"name": "Присед + выпрыгивание", "target": "45 сек"},
                {"name": "Пауза", "target": "15 сек"},
            ],
        }
        script["rounds"] = max(8, min(14, duration_min // 3))
        script["main"]["rest_sec"] = 15
        script["focus"] = "Держи стабильный темп, не умирай в первых раундах."
    elif is_legs:
        script["main"] = {
            "rest_sec": 75 if tier <= 3 else 90,
            "description": "Силовой круг ноги + кор.",
            "exercises": [
                {"name": "Приседания", "target": "22-30"},
                {"name": "Выпады", "target": "14-18/нога"},
                {"name": "Ягодичный мост", "target": "22-30"},
                {"name": "Планка", "target": "45-60 сек"},
            ],
        }
        script["focus"] = "Глубина и контроль корпуса важнее скорости."
    elif is_pull:
        script["main"] = {
            "rest_sec": 90 if tier >= 4 else 75,
            "description": "Верх + тяга + стабилизация корпуса.",
            "exercises": [
                {"name": "Подтягивания", "target": "6-10"},
                {"name": "Отжимания", "target": "18-26"},
                {"name": "Подъём коленей в висе", "target": "12-18"},
                {"name": "Планка", "target": "50-70 сек"},
            ],
        }
        script["focus"] = "Сохраняй полный контроль в каждом повторе."
    else:
        script["main"] = {
            "rest_sec": 75,
            "description": "Универсальный full-body круг.",
            "exercises": [
                {"name": "Приседания", "target": "20-28"},
                {"name": "Отжимания", "target": "16-24"},
                {"name": "Тяга в наклоне", "target": "12-16"},
                {"name": "Планка", "target": "45-60 сек"},
            ],
        }
        script["focus"] = "Ровный темп и контроль дыхания."

    if is_dumbbell and isinstance(script.get("main"), dict):
        main = dict(script.get("main") or {})
        exercises = main.get("exercises") if isinstance(main.get("exercises"), list) else []
        has_row = any("тяга" in str(item.get("name") or "").lower() for item in exercises if isinstance(item, dict))
        if not has_row:
            exercises.append({"name": "Тяга гантелей в наклоне", "target": "12-16"})
        main["exercises"] = exercises[:5]
        script["main"] = main

    if load_state == "deload":
        script["focus"] = "Разгрузочная неделя: качество повторов, без отказа."
        rounds = max(3, rounds - 1)
        if isinstance(script.get("main"), dict):
            script["main"]["rest_sec"] = int(max(60, int(script["main"].get("rest_sec") or 75)))
    elif load_state == "build":
        rounds += 1
        if isinstance(script.get("main"), dict):
            script["main"]["rest_sec"] = int(max(45, int(script["main"].get("rest_sec") or 75) - 10))

    script["rounds"] = int(max(3, min(6, rounds)))
    return script


def _progression_advice(*, rpe: int | None, recent_rpe: list[int | None]) -> dict[str, object]:
    if rpe is None:
        return {
            "delta_reps": 1,
            "delta_sets": 0,
            "rule": "Базовая прогрессия",
            "note": "Зафиксируй RPE, чтобы точнее повышать нагрузку.",
        }
    if rpe <= 6:
        return {
            "delta_reps": 2,
            "delta_sets": 0,
            "rule": "Легко",
            "note": "Следующий раз добавь +2 повтора в ключевых подходах.",
        }
    if rpe <= 8:
        return {
            "delta_reps": 1,
            "delta_sets": 0,
            "rule": "Рабочая зона",
            "note": "Следующий раз добавь +1 повтор в 1-2 подходах.",
        }
    valid_rpe = [int(x) for x in recent_rpe if isinstance(x, int)]
    return {
        "delta_reps": 0,
        "delta_sets": -1 if len(valid_rpe) >= 2 and all(x >= 8 for x in valid_rpe[:2]) else 0,
        "rule": "Высокая нагрузка",
        "note": "Оставь объем, добавь восстановление и контроль техники.",
    }


def _video_title_from_filename(name: str) -> str:
    stem = Path(name).stem.strip()
    if not stem:
        return "Ритуал"
    cleaned = re.sub(r"[_\-]+", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or stem


def _normalize_video_display_title(value: str, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    cleaned = re.sub(r"[_\-]+", " ", raw)
    cleaned = re.sub(r"[^\w\s\-\+]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    if not cleaned:
        return fallback
    if len(cleaned) > 72:
        cleaned = cleaned[:69].rstrip() + "..."
    return cleaned


def _fitness_video_title_cache_key(path: Path) -> str:
    stat = path.stat()
    signature = f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}"
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:24]
    return f"{_FITNESS_VIDEO_TITLE_CACHE_PREFIX}{digest}"


def _fitness_video_title_cached(path: Path) -> str | None:
    row = get_cache_value(_fitness_video_title_cache_key(path))
    if not row or not row[0]:
        return None
    value = str(row[0]).strip()
    return value or None


def _fitness_video_title_save(path: Path, title: str) -> None:
    set_cache_value(_fitness_video_title_cache_key(path), str(title).strip(), _now_iso())


def _parse_llm_json_list(raw: str) -> list[object] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            maybe = parsed.get("titles")
            if isinstance(maybe, list):
                return maybe
    except Exception:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, list) else None


def _rewrite_fitness_video_titles_with_ai(items: list[tuple[Path, str]]) -> dict[str, str]:
    if not items:
        return {}
    settings = _settings()
    if not settings or not _dashboard_ai_enabled():
        return {}

    payload = [{"name": path.name, "fallback": fallback} for path, fallback in items]
    user_message = (
        "Переименуй названия фитнес-видео максимально просто и понятно.\n"
        "Правила:\n"
        "1) Верни ровно столько же элементов, сколько на входе.\n"
        "2) Каждый элемент короткий: 2-6 слов.\n"
        "3) Без эмодзи, без кавычек, без лишней пунктуации.\n"
        "4) Сохраняй смысл (дыхание, растяжка, табата и т.п.).\n"
        "5) Если не уверен — используй fallback.\n"
        "Верни строго JSON-массив строк.\n\n"
        f"Видео: {json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        llm_prompt = build_prompt(
            history=[],
            user_message=user_message,
            settings=settings,
            mode="fast",
            profile="rewriter",
        )
        raw = asyncio.run(
            asyncio.wait_for(
                call_ollama(llm_prompt, settings, mode="fast", profile="rewriter"),
                timeout=min(9.0, max(3.0, float(getattr(settings, "llm_enhancer_timeout_seconds", 3.5)) + 2.5)),
            )
        )
        parsed = _parse_llm_json_list(str(raw or ""))
        if not parsed or len(parsed) != len(items):
            return {}
    except Exception:
        return {}

    result: dict[str, str] = {}
    for (path, fallback), llm_title in zip(items, parsed):
        normalized = _normalize_video_display_title(str(llm_title or ""), fallback)
        if not normalized:
            normalized = fallback
        result[path.name] = normalized
    return result


def _safe_video_filename(name: str) -> str | None:
    raw = Path(str(name or "")).name.strip()
    if not raw or raw in {".", ".."}:
        return None
    if Path(raw).suffix.lower() not in _FITNESS_VIDEO_EXTENSIONS:
        return None
    return raw


def _resolve_video_file(name: str) -> Path | None:
    safe_name = _safe_video_filename(name)
    if not safe_name:
        return None
    try:
        root = _FITNESS_VIDEO_DIR.resolve()
        target = (root / safe_name).resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root):
            return None
        return target
    except Exception:
        return None


def _video_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".mp4", ".m4v"}:
        return "video/mp4"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".webm":
        return "video/webm"
    return "application/octet-stream"


def _fitness_video_item(path: Path, *, display_title: str | None = None) -> dict[str, object]:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return {
        "name": path.name,
        "title": str(display_title or _video_title_from_filename(path.name)),
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified_at": modified_at,
        "stream_url": f"/dashboard/fitness/video?name={quote(path.name)}",
    }


def _list_fitness_videos(*, limit: int = 40) -> list[dict[str, object]]:
    if not _FITNESS_VIDEO_DIR.exists() or not _FITNESS_VIDEO_DIR.is_dir():
        return []
    files = [
        p
        for p in _FITNESS_VIDEO_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _FITNESS_VIDEO_EXTENSIONS
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    selected = files[: max(1, limit)]

    prepared: list[tuple[Path, str]] = []
    cached_titles: dict[str, str] = {}
    for path in selected:
        fallback = _video_title_from_filename(path.name)
        prepared.append((path, fallback))
        cached = _fitness_video_title_cached(path)
        if cached:
            cached_titles[path.name] = _normalize_video_display_title(cached, fallback)

    pending = [(path, fallback) for path, fallback in prepared if path.name not in cached_titles]
    ai_titles = _rewrite_fitness_video_titles_with_ai(pending)
    for path, fallback in pending:
        title = _normalize_video_display_title(ai_titles.get(path.name, ""), fallback)
        if title:
            _fitness_video_title_save(path, title)
            cached_titles[path.name] = title

    return [
        _fitness_video_item(path, display_title=cached_titles.get(path.name, fallback))
        for path, fallback in prepared
    ]


def _fitness_activity_snapshot(*, user_id: int, latest_session: dict[str, object] | None = None) -> dict[str, object]:
    now = datetime.now()
    today = now.date()
    since_7 = (now - timedelta(days=7)).isoformat(timespec="seconds")
    since_30 = (now - timedelta(days=30)).isoformat(timespec="seconds")
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)

    done_7d, _rows_7d = fitness_stats_recent(user_id=user_id, since_iso=since_7)
    done_30d, _rows_30d = fitness_stats_recent(user_id=user_id, since_iso=since_30)
    done_this_week = fitness_done_count_between(
        user_id=user_id,
        start_iso=f"{week_start.isoformat()}T00:00:00",
        end_iso=f"{week_end.isoformat()}T00:00:00",
    )
    done_today = fitness_done_count_between(
        user_id=user_id,
        start_iso=f"{today.isoformat()}T00:00:00",
        end_iso=f"{(today + timedelta(days=1)).isoformat()}T00:00:00",
    )
    streak_days = fitness_current_streak_days(user_id=user_id)
    weekly_target = 3
    weekly_progress_pct = min(100, int(round((done_this_week / max(1, weekly_target)) * 100)))

    recent_rpe = []
    latest_rpe = None
    if latest_session and isinstance(latest_session, dict):
        latest_rpe = latest_session.get("rpe")
        recent_rpe = latest_session.get("recent_rpe") if isinstance(latest_session.get("recent_rpe"), list) else []
    heavy_recent = [int(x) for x in recent_rpe if isinstance(x, int) and x >= 8]
    easy_recent = [int(x) for x in recent_rpe if isinstance(x, int) and x <= 6]
    if len(heavy_recent) >= 2:
        load_state = "deload"
        load_label = "Разгрузка"
    elif len(easy_recent) >= 2:
        load_state = "build"
        load_label = "Рост нагрузки"
    else:
        load_state = "steady"
        load_label = "Ровный режим"

    return {
        "done_today": int(done_today),
        "done_7d": int(done_7d),
        "done_30d": int(done_30d),
        "done_this_week": int(done_this_week),
        "weekly_target": int(weekly_target),
        "weekly_progress_pct": int(weekly_progress_pct),
        "streak_days": int(streak_days),
        "latest_rpe": int(latest_rpe) if isinstance(latest_rpe, int) else None,
        "load_state": load_state,
        "load_label": load_label,
    }


def _fitness_rule_coach_text(*, plan: dict[str, object] | None, activity: dict[str, object]) -> str:
    load_state = str(activity.get("load_state") or "steady")
    streak = int(activity.get("streak_days") or 0)
    done_7d = int(activity.get("done_7d") or 0)
    weekly = int(activity.get("done_this_week") or 0)
    weekly_target = int(activity.get("weekly_target") or 3)
    title = str(plan.get("title") or "") if isinstance(plan, dict) else ""

    lines: list[str] = []
    if title:
        lines.append(f"Сегодня держи фокус на тренировке: {title}.")
    if load_state == "deload":
        lines.append("Нагрузка была высокой. Убери ~20% объема и оставь чистую технику.")
    elif load_state == "build":
        lines.append("Сессии идут легко. Добавь +1 повтор в ключевых подходах.")
    else:
        lines.append("Режим ровный. Держи стабильный темп и качество выполнения.")
    lines.append(f"Неделя: {weekly}/{weekly_target} тренировок. Стрик: {streak} дн. (7д: {done_7d}).")
    return " ".join(lines)


async def _build_training_ai_layer(
    *,
    user_id: int,
    training_panel: dict[str, object],
    ai_enabled: bool,
) -> dict[str, str]:
    plan = training_panel.get("today_plan") if isinstance(training_panel.get("today_plan"), dict) else None
    activity = training_panel.get("activity") if isinstance(training_panel.get("activity"), dict) else {}
    rule_coach = _fitness_rule_coach_text(plan=plan, activity=activity)

    plan_text = render_plain_workout_plan(plan) if plan else ""
    coach_text = rule_coach
    if not plan:
        return {"ai_plan": plan_text, "ai_coach": coach_text}

    settings = _settings()
    if settings:
        if ai_enabled:
            plan_text = await _safe_async(
                plan_text,
                build_ai_workout_plan(settings, plan),
                timeout_sec=18.0,
            )

    if ai_enabled and settings:
        today_iso = date.today().isoformat()
        signal = f"{today_iso}:{int(activity.get('done_7d') or 0)}:{int(activity.get('streak_days') or 0)}:{int(plan.get('id') or 0)}"
        cache_key = f"dash:fitness:coach:{user_id}:{signal}"
        cached = get_cache_value(cache_key)
        if cached and cached[0] and cached[1]:
            try:
                age = (datetime.now() - datetime.fromisoformat(str(cached[1]))).total_seconds()
            except ValueError:
                age = 9999
            if age <= 600:
                coach_text = str(cached[0])
                return {"ai_plan": str(plan_text or ""), "ai_coach": coach_text}

        user_message = (
            "Ты фитнес-коуч ассистента Day OS. Дай короткую адаптацию плана на сегодня на русском.\n"
            "Формат: 3 строки.\n"
            "1) Нагрузка\n"
            "2) Фокус техники\n"
            "3) Восстановление\n"
            "Без воды, до 320 символов.\n\n"
            f"Тренировка: {plan.get('title')}\n"
            f"Сложность: {plan.get('difficulty')}/5\n"
            f"Длительность: {plan.get('duration_min')} мин\n"
            f"Неделя: {activity.get('done_this_week')}/{activity.get('weekly_target')} "
            f"Стрик: {activity.get('streak_days')} дн "
            f"7д: {activity.get('done_7d')}\n"
            f"Текущий сигнал: {activity.get('load_label')}"
        )
        prompt = build_prompt(
            history=[],
            user_message=user_message,
            settings=settings,
            profile="advisor",
        )
        ai_coach = await _safe_async(
            "",
            call_ollama(prompt, settings, profile="advisor"),
            timeout_sec=14.0,
        )
        coach_text = str(ai_coach or "").strip() or rule_coach
        set_cache_value(cache_key, coach_text, _now_iso())

    return {"ai_plan": str(plan_text or ""), "ai_coach": str(coach_text or rule_coach)}


def _training_panel(user_id: int) -> dict[str, object]:
    plan_row = pick_workout_of_day()
    workout_rows, _ = fitness_list_workouts(page=1, limit=40)
    latest = fitness_get_latest_session_for_user(user_id)

    plan: dict[str, object] | None = None
    if plan_row:
        serialized = _serialize_workout_row(plan_row)
        if serialized:
            plan = serialized

    latest_payload: dict[str, object] | None = None
    next_hint = "Сделай базовый подход: техника > скорость."
    if latest:
        workout_id = int(latest[0])
        title = str(latest[1] or "")
        done_at = str(latest[2] or "")
        rpe = int(latest[3]) if latest[3] is not None else None
        recent_rpe = fitness_get_recent_rpe(user_id=user_id, workout_id=workout_id, limit=3)
        next_hint = next_hint_by_context(rpe, recent_rpe)
        latest_payload = {
            "workout_id": workout_id,
            "title": title,
            "done_at": done_at,
            "rpe": rpe,
            "recent_rpe": recent_rpe,
        }

    workouts: list[dict[str, object]] = []
    activity = _fitness_activity_snapshot(user_id=user_id, latest_session=latest_payload)
    for row in workout_rows:
        item = _serialize_workout_row(row)
        if not item:
            continue
        progress = fitness_get_progress(user_id=user_id, workout_id=int(item["id"]))
        if progress:
            item["next_hint"] = str(progress[2] or "").strip()
            item["last_rpe"] = int(progress[0]) if progress[0] is not None else None
        item["suggested_timers"] = _suggested_timers_for_workout(workout=item, activity=activity)
        item["script"] = _build_workout_script(workout=item, activity=activity)
        workouts.append(item)

    coach_fallback = _fitness_rule_coach_text(plan=plan, activity=activity)
    plan_script = _build_workout_script(workout=plan, activity=activity)

    return {
        "today_plan": plan,
        "today_script": plan_script,
        "latest_session": latest_payload,
        "progressive_hint": next_hint,
        "program_summary": program_summary(),
        "activity": activity,
        "ai_coach": coach_fallback,
        "ai_plan": "",
        "workouts": workouts,
        "timer_presets": _fitness_timer_presets(),
        "suggested_timers": _suggested_timers_for_workout(workout=plan, activity=activity),
        "ritual_videos": _list_fitness_videos(limit=30),
    }


def _trend_panel(user_id: int) -> dict[str, object]:
    since_iso = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    done_7d, open_now = todo_stats_recent(user_id=user_id, since_iso=since_iso)
    focus_minutes_7d, focus_sessions_7d = focus_stats_recent(user_id=user_id, since_iso=since_iso)
    workouts_7d, _ = fitness_stats_recent(user_id=user_id, since_iso=since_iso)
    checkins = daily_checkin_recent(user_id=user_id, since_iso=since_iso, limit=7)
    energies = [int(row[3]) for row in checkins if len(row) > 3 and row[3] is not None]
    avg_energy_7d = round(sum(energies) / len(energies), 1) if energies else None

    if avg_energy_7d is None:
        summary = "Недостаточно данных за 7 дней. Делай вечерний /checkin для точного анализа."
    elif avg_energy_7d >= 7 and done_7d >= 5:
        summary = "Хорошая динамика: энергия и выполнение в зелёной зоне."
    elif avg_energy_7d <= 4:
        summary = "Энергия проседает. Снизь нагрузку и держи только 1 ключевую задачу в день."
    elif open_now >= 10:
        summary = "Много открытых задач. Нужен переплан и жёсткий top-3 на день."
    else:
        summary = "Стабильная неделя. Держи ритм: 1 deep-блок и 1 закрытая задача в день."

    return {
        "done_7d": done_7d,
        "open_now": open_now,
        "focus_minutes_7d": focus_minutes_7d,
        "focus_sessions_7d": focus_sessions_7d,
        "workouts_7d": workouts_7d,
        "avg_energy_7d": avg_energy_7d,
        "summary": summary,
    }


def _days_on_planet(*, birth_date: date, today: date) -> int:
    delta = (today - birth_date).days
    return max(0, delta + 1)


def _stats_panel(user_id: int) -> dict[str, object]:
    now = datetime.now()
    settings = _settings()
    birth_date = settings.birth_date if settings else date(1984, 12, 15)

    since_7 = (now - timedelta(days=7)).isoformat(timespec="seconds")
    since_30 = (now - timedelta(days=30)).isoformat(timespec="seconds")

    done_7d, open_now = todo_stats_recent(user_id=user_id, since_iso=since_7)
    done_30d, _ = todo_stats_recent(user_id=user_id, since_iso=since_30)
    focus_minutes_7d, focus_sessions_7d = focus_stats_recent(user_id=user_id, since_iso=since_7)
    workouts_30d, _ = fitness_stats_recent(user_id=user_id, since_iso=since_30)
    checkins_7d = daily_checkin_recent(user_id=user_id, since_iso=since_7, limit=7)

    energies = [int(row[3]) for row in checkins_7d if len(row) > 3 and row[3] is not None]
    avg_energy_7d = round(sum(energies) / len(energies), 1) if energies else None

    today_date = now.date()
    days_alive = _days_on_planet(birth_date=birth_date, today=today_date)
    age_years = int((today_date - birth_date).days // 365.2425) if today_date >= birth_date else 0

    return {
        "birth_date": birth_date.isoformat(),
        "days_on_planet": days_alive,
        "age_years": age_years,
        "done_7d": done_7d,
        "done_30d": done_30d,
        "open_now": open_now,
        "focus_minutes_7d": focus_minutes_7d,
        "focus_sessions_7d": focus_sessions_7d,
        "workouts_30d": workouts_30d,
        "avg_energy_7d": avg_energy_7d,
        "checkins_7d": len(checkins_7d),
    }


def _calendar_panel(tasks_items: list[dict[str, object]]) -> dict[str, object]:
    items = tasks_items if isinstance(tasks_items, list) else []
    by_day: dict[str, dict[str, int]] = {}
    upcoming: list[dict[str, object]] = []
    done_recent: list[dict[str, object]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        due_date = str(item.get("due_date") or "").strip()
        created_at = str(item.get("created_at") or "").strip()
        status = str(item.get("status") or "open").strip().lower()
        day_key = due_date or created_at[:10]
        if not day_key:
            continue
        bucket = by_day.setdefault(day_key, {"open": 0, "done": 0, "total": 0})
        bucket["total"] += 1
        if status == "done":
            bucket["done"] += 1
            done_recent.append(
                {
                    "id": int(item.get("id") or 0),
                    "text": str(item.get("text") or ""),
                    "notes": str(item.get("notes") or "").strip(),
                    "done_at": str(item.get("done_at") or ""),
                    "due_date": due_date,
                }
            )
        else:
            bucket["open"] += 1

        if status == "open":
            upcoming.append(
                {
                    "id": int(item.get("id") or 0),
                    "text": str(item.get("text") or ""),
                    "notes": str(item.get("notes") or "").strip(),
                    "day": day_key,
                    "due_date": due_date,
                    "created_at": created_at,
                    "remind_at": str(item.get("remind_at") or ""),
                }
            )

    upcoming.sort(key=lambda x: (str(x.get("due_date") or "") == "", str(x.get("day") or ""), int(x.get("id") or 0)))
    done_recent.sort(
        key=lambda x: (
            str(x.get("done_at") or "") == "",
            str(x.get("done_at") or ""),
            int(x.get("id") or 0),
        ),
        reverse=True,
    )

    return {
        "days": by_day,
        "upcoming": upcoming[:120],
        "done_recent": done_recent[:20],
        "year_goals": [],
    }


def _days_left(value: str | None) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        target = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return (target - date.today()).days


def _garage_date_status(days_left: int | None, *, warn_days: int = 30) -> tuple[str, str]:
    if days_left is None:
        return ("unknown", "дата не задана")
    if days_left < 0:
        return ("critical", f"просрочено на {abs(days_left)} дн.")
    if days_left <= warn_days:
        return ("warn", f"истекает через {days_left} дн.")
    return ("ok", f"еще {days_left} дн.")


def _garage_safe_docs(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        source = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        source = parsed if isinstance(parsed, list) else []
    out: list[dict[str, object]] = []
    for item in source:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not label or not url:
            continue
        out.append({"label": label, "url": url, "official": bool(item.get("official"))})
    return out


def _garage_panel(user_id: int) -> dict[str, object]:
    garage_seed_defaults(user_id=int(user_id), created_at=_now_iso())
    rows = garage_list_assets(user_id=int(user_id))

    assets: list[dict[str, object]] = []
    alerts: list[dict[str, object]] = []
    now_iso = _now_iso()

    for row in rows:
        asset_id = int(row[0])
        kind = str(row[1] or "car")
        title = str(row[2] or "")
        year = int(row[3]) if row[3] is not None else None
        nickname = str(row[4] or "")
        mileage_km = int(row[7] or 0)
        last_service_km = int(row[8]) if row[8] is not None else None
        interval_km = max(1000, int(row[9] or 10000))
        maintenance_due_date = str(row[10] or "") or None
        insurance_until = str(row[11] or "") or None
        inspection_until = str(row[12] or "") or None
        note = str(row[13] or "").strip()
        docs = _garage_safe_docs(row[14])
        updated_at = str(row[15] or "")

        km_since_service = mileage_km - (last_service_km or 0)
        km_to_service = interval_km - km_since_service
        if km_to_service < 0:
            service_state = "critical"
            service_hint = f"ТО просрочено на {abs(km_to_service)} км"
        elif km_to_service <= 1000:
            service_state = "warn"
            service_hint = f"ТО скоро: {km_to_service} км"
        else:
            service_state = "ok"
            service_hint = f"до ТО ~{km_to_service} км"

        insurance_days = _days_left(insurance_until)
        insurance_state, insurance_hint = _garage_date_status(insurance_days, warn_days=30)
        maintenance_days = _days_left(maintenance_due_date)
        maintenance_state, maintenance_hint = _garage_date_status(maintenance_days, warn_days=14)
        inspection_days = _days_left(inspection_until)
        inspection_state, inspection_hint = _garage_date_status(inspection_days, warn_days=30)

        if insurance_state in {"critical", "warn"}:
            alerts.append(
                {
                    "asset_id": asset_id,
                    "title": title,
                    "type": "insurance",
                    "severity": insurance_state,
                    "message": f"Страховка: {insurance_hint}",
                }
            )
        if maintenance_state in {"critical", "warn"}:
            alerts.append(
                {
                    "asset_id": asset_id,
                    "title": title,
                    "type": "maintenance_date",
                    "severity": maintenance_state,
                    "message": f"ТО по дате: {maintenance_hint}",
                }
            )
        if service_state in {"critical", "warn"}:
            alerts.append(
                {
                    "asset_id": asset_id,
                    "title": title,
                    "type": "maintenance_km",
                    "severity": service_state,
                    "message": f"ТО по пробегу: {service_hint}",
                }
            )
        if inspection_state in {"critical", "warn"}:
            alerts.append(
                {
                    "asset_id": asset_id,
                    "title": title,
                    "type": "inspection",
                    "severity": inspection_state,
                    "message": f"Техосмотр: {inspection_hint}",
                }
            )

        assets.append(
            {
                "id": asset_id,
                "kind": kind,
                "title": title,
                "year": year,
                "nickname": nickname,
                "mileage_km": mileage_km,
                "last_service_km": last_service_km,
                "maintenance_interval_km": interval_km,
                "km_to_service": km_to_service,
                "service_state": service_state,
                "service_hint": service_hint,
                "maintenance_due_date": maintenance_due_date,
                "insurance_until": insurance_until,
                "tech_inspection_until": inspection_until,
                "insurance_state": insurance_state,
                "insurance_hint": insurance_hint,
                "maintenance_state": maintenance_state,
                "maintenance_hint": maintenance_hint,
                "inspection_state": inspection_state,
                "inspection_hint": inspection_hint,
                "note": note,
                "docs": docs,
                "updated_at": updated_at,
            }
        )

    priority = {"critical": 0, "warn": 1, "ok": 2, "unknown": 3}
    alerts.sort(key=lambda item: priority.get(str(item.get("severity") or "unknown"), 3))

    return {
        "assets": assets,
        "alerts": alerts[:30],
        "updated_at": now_iso,
        "summary": f"{len(assets)} ТС · предупреждений: {len(alerts)}",
    }


def _rule_based_ai(
    *,
    today: dict[str, object],
    tasks: list[dict[str, object]],
    weather: dict[str, object],
    training: dict[str, object],
    news: dict[str, object],
    trend: dict[str, object] | None = None,
) -> dict[str, str]:
    energy = today.get("energy")
    energy_num = int(energy) if isinstance(energy, int) else 6
    top_news = (news.get("hype") or news.get("items") or [])
    top_news_title = ""
    if isinstance(top_news, list) and top_news:
        top_news_title = str(top_news[0].get("title") or "")
    task_count = len(tasks)
    trend_summary = str((trend or {}).get("summary") or "").strip()

    priority_items = _daily_priority_items(tasks, limit=3)

    if energy_num <= 4:
        signal = "Энергия низкая: нужен режим сохранения ресурса."
        action = _daily_priority_action_text(priority_items, fallback="Сделай 1 главную задачу + короткая тренировка/прогулка 20 мин.")
        risk = "Риск перегруза и отката, если взять больше 3 задач."
    elif task_count >= 7:
        signal = "В задачах перегруз: фокус может распасться."
        action = _daily_priority_action_text(priority_items, fallback="Срежь список до top-3 и закрой первую задачу без переключений 25 минут.")
        risk = "Много незавершенного = снижение качества решений."
    else:
        signal = "Состояние рабочее: можно идти в умеренный рост."
        action = _daily_priority_action_text(priority_items, fallback="1 deep-блок на 45 мин + 1 тактическая задача + checkin вечером.")
        risk = "Риск расфокуса на новостной шум."

    weather_hint = str(weather.get("clothing") or "").strip()
    coach = str(training.get("progressive_hint") or "").strip()
    if top_news_title:
        coach = f"{coach} | Сигнал дня: {top_news_title}"
    if weather_hint:
        coach = f"{coach} | Одежда: {weather_hint}"

    if trend_summary:
        coach = f"{coach} | Динамика: {trend_summary}"

    return {
        "signal": signal,
        "action": action,
        "risk": risk,
        "coach": coach,
    }


def _parse_due_date(value: object) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:10]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _task_title_short(value: object, max_len: int = 54) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _task_priority_score(item: dict[str, object], *, today_date: date) -> int:
    due = _parse_due_date(item.get("due_date"))
    if due is None:
        base = 220
    else:
        delta = (due - today_date).days
        if delta < 0:
            base = 10 + abs(delta)
        elif delta == 0:
            base = 30
        elif delta == 1:
            base = 60
        else:
            base = 90 + min(delta, 180)
    created = str(item.get("created_at") or "").strip()
    created_bias = 0
    if created:
        try:
            created_dt = datetime.fromisoformat(created[:19])
            age_days = max(0, (datetime.now() - created_dt).days)
            created_bias = min(age_days, 60)
        except ValueError:
            created_bias = 0
    return base - created_bias


def _task_priority_reason(item: dict[str, object], *, today_date: date) -> str:
    due = _parse_due_date(item.get("due_date"))
    if due is not None:
        delta = (due - today_date).days
        if delta < 0:
            return f"просрочено на {abs(delta)} дн."
        if delta == 0:
            return "срок сегодня"
        if delta == 1:
            return "срок завтра"
        if delta <= 3:
            return f"срок через {delta} дн."
    created = str(item.get("created_at") or "").strip()
    if created:
        try:
            created_dt = datetime.fromisoformat(created[:19])
            age_days = max(0, (datetime.now() - created_dt).days)
            if age_days >= 4:
                return f"в очереди {age_days} дн."
        except ValueError:
            pass
    return "рабочий приоритет"


def _micro_step_for_task(text: object) -> str:
    raw = " ".join(str(text or "").split())
    lower = raw.lower()
    if not raw:
        return "Открой задачу и зафиксируй первый подшаг."
    if "письм" in lower or "почт" in lower:
        return "Открой почту и обработай первые 3 письма по правилу 2 минут."
    if "план" in lower:
        return "Сделай черновик из 3 пунктов и выбери первый к выполнению."
    if "интерф" in lower or "дизайн" in lower:
        return "Определи один экран и за 10 минут набросай 2 правки без перфекционизма."
    if "рынок" in lower or "новост" in lower:
        return "Собери 3 сигнала и выпиши один конкретный вывод."
    return f"Поставь таймер 10 минут и выполни первый шаг: «{_task_title_short(raw, max_len=44)}»."


def _daily_priority_items(tasks: list[dict[str, object]], *, limit: int = 3) -> list[dict[str, object]]:
    today_date = date.today()
    normalized: list[dict[str, object]] = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        normalized.append(item)

    ranked = sorted(
        normalized,
        key=lambda item: (
            _task_priority_score(item, today_date=today_date),
            int(item.get("id") or 0),
        ),
    )
    return ranked[: max(1, limit)]


def _daily_priority_action_text(priority_items: list[dict[str, object]], *, fallback: str) -> str:
    if not priority_items:
        return fallback
    today_date = date.today()
    parts: list[str] = []
    for idx, item in enumerate(priority_items, start=1):
        title = _task_title_short(item.get("text"))
        reason = _task_priority_reason(item, today_date=today_date)
        parts.append(f"{idx}) {title} [{reason}]")
    first = _task_title_short(priority_items[0].get("text"), max_len=46)
    micro_step = _micro_step_for_task(priority_items[0].get("text"))
    return (
        f"Top-3 на сегодня: {'; '.join(parts)}. "
        f"Старт: «{first}» на 25 минут без переключений. "
        f"Микро-шаг (10м): {micro_step}"
    )


def _focus_protocol() -> str:
    return (
        "Фокус 25 минут:\n"
        "1) Оставь одну задачу на экране.\n"
        "2) Выключи уведомления на 25 минут.\n"
        "3) Начни с самого сложного подшага.\n"
        "4) После блока: 5 минут пауза и фиксация результата."
    )


def _copilot_fallback(message: str, context: dict[str, object]) -> dict[str, object]:
    text = (message or "").strip().lower()
    tasks = context.get("tasks") if isinstance(context.get("tasks"), list) else []
    energy = context.get("today_energy")
    energy_text = f"{energy}/10" if isinstance(energy, int) else "н/д"

    if "добав" in text and "задач" in text:
        return {
            "answer": "Бросай формулировку одним сообщением — упакую её в задачу без лишнего шума.",
            "quick_actions": [
                {"type": "task_add", "label": "Добавить задачу"},
            ],
        }
    if "фокус" in text or "собер" in text:
        return {
            "answer": (
                "Давай дерзко и чисто: один блок, один результат.\n"
                f"{_focus_protocol()}"
            ),
            "quick_actions": [
                {"type": "focus_start", "label": "Старт фокуса"},
                {"type": "replan_day", "label": "Переплан дня"},
            ],
        }
    if "переплан" in text or "replan" in text:
        return {
            "answer": (
                f"Быстрый переплан: энергия {energy_text}, открытых задач {len(tasks)}.\n"
                "Делаем красивую тройку: 1 главная, 1 поддерживающая, 1 короткая."
            ),
            "quick_actions": [
                {"type": "replan_day", "label": "Сделать переплан"},
                {"type": "focus_start", "label": "Фокус 25м"},
            ],
        }
    return {
        "answer": (
            "Я на связи, напарник. Ты задаёшь цель — я делаю её неотразимо выполнимой. "
            "Выбирай ход: задача, переплан или фокус-блок."
        ),
        "quick_actions": [
            {"type": "task_add", "label": "Добавить задачу"},
            {"type": "replan_day", "label": "Переплан дня"},
            {"type": "focus_start", "label": "Фокус 25м"},
        ],
    }


async def _ai_brief(
    *,
    user_id: int,
    today: dict[str, object],
    tasks: list[dict[str, object]],
    weather: dict[str, object],
    training: dict[str, object],
    news: dict[str, object],
    trend: dict[str, object] | None = None,
) -> dict[str, str]:
    cache_key = f"dashboard:ai_brief:{user_id}"
    cached = _cache_get_json(cache_key, _AI_CACHE_TTL_SECONDS)
    if cached and all(k in cached for k in ("signal", "action", "risk", "coach")):
        return {
            "signal": str(cached.get("signal")),
            "action": str(cached.get("action")),
            "risk": str(cached.get("risk")),
            "coach": str(cached.get("coach")),
        }

    fallback = _rule_based_ai(
        today=today,
        tasks=tasks,
        weather=weather,
        training=training,
        news=news,
        trend=trend,
    )
    settings = _settings()
    if not settings or not _dashboard_ai_enabled():
        _cache_set_json(cache_key, fallback)
        return fallback

    news_titles = []
    for item in (news.get("hype") or news.get("items") or []):
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            if title:
                news_titles.append(title)
        if len(news_titles) >= 3:
            break

    prompt = (
        "Сформируй краткий персональный AI-бриф на русском.\n"
        "Строго 4 строки в формате:\n"
        "signal: ...\n"
        "action: ...\n"
        "risk: ...\n"
        "coach: ...\n\n"
        "Контекст:\n"
        f"- date: {today.get('date')}\n"
        f"- day_mode: {today.get('day_mode')}\n"
        f"- energy: {today.get('energy')}\n"
        f"- tasks_open: {len(tasks)}\n"
        f"- weather: {weather.get('summary')}\n"
        f"- clothing: {weather.get('clothing')}\n"
        f"- training_hint: {training.get('progressive_hint')}\n"
        f"- trend_7d: {(trend or {}).get('summary')}\n"
        f"- top_news: {' | '.join(news_titles) if news_titles else 'none'}\n"
        "Без воды. Только практично."
    )

    try:
        llm_prompt = build_prompt(
            history=[],
            user_message=prompt,
            settings=settings,
            mode="fast",
            profile="advisor",
        )
        raw = (await asyncio.wait_for(call_ollama(llm_prompt, settings, mode="fast", profile="advisor"), timeout=8.0)).strip()
        parsed = dict(fallback)
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            val = value.strip()
            if key in parsed and val:
                parsed[key] = val
        _cache_set_json(cache_key, parsed)
        return parsed
    except Exception:
        _cache_set_json(cache_key, fallback)
        return fallback


def _fallback_ai_pack(
    *,
    today: dict[str, object],
    tasks: list[dict[str, object]],
    weather: dict[str, object],
    training: dict[str, object],
    market: dict[str, object],
    ai_panel: dict[str, str],
    trend: dict[str, object] | None = None,
) -> dict[str, str]:
    open_tasks = len(tasks)
    energy = today.get("energy")
    energy_num = int(energy) if isinstance(energy, int) else None
    day_mode_raw = str(today.get("day_mode") or "workday")
    day_mode = _day_mode_label_ru(day_mode_raw)
    trend_summary = str((trend or {}).get("summary") or "").strip() or "стабильный ритм недели"
    workout = training.get("today_plan") if isinstance(training.get("today_plan"), dict) else None
    workout_label = "без фиксированного плана"
    if isinstance(workout, dict):
        wid = workout.get("id")
        wtitle = str(workout.get("title") or "").strip()
        if wid and wtitle:
            workout_label = f"#{wid} {wtitle}"

    mission_text = (
        f"Режим: {day_mode}. Открытых задач: {open_tasks}. "
        "Берём один главный приоритет, закрываем его и фиксируем итог в чекине."
    )
    if energy_num is not None and energy_num <= 4:
        mission_text = (
            f"Энергия {energy_num}/10. Бережный режим: 1 ключевая задача и короткий фокус-блок без перегруза."
        )

    month_goal = "Стабилизировать ритм: не накапливать хвост, держать 1-2 закрытия в день."
    if open_tasks >= 8:
        month_goal = "Срезать хвост задач до управляемого ядра: 3-5 активных пунктов."

    return {
        "mission_text": mission_text,
        "growth_year": "Годовой вектор: дисциплина, энергия, стратегический фокус.",
        "growth_month": month_goal,
        "growth_week": f"Фокус недели: {trend_summary}",
        "growth_day": f"Шаг дня: {workout_label}; затем /focus и фиксация в /checkin.",
        "weather_brief": str(weather.get("summary") or "").strip() or "Погода недоступна.",
        "weather_clothing": str(weather.get("clothing") or "").strip() or "Одежда по погоде.",
        "training_hint": str(training.get("progressive_hint") or "").strip() or "Фокус на технику и базовый объём.",
        "market_brief": " | ".join([str(x) for x in (market.get("highlights") or [])[:3]]).strip() or "Рынок без свежих метрик.",
        "coach_line": str(ai_panel.get("coach") or "").strip() or "Держи один приоритет и не распыляйся.",
    }


async def _build_ai_pack(
    *,
    user_id: int,
    today: dict[str, object],
    tasks: list[dict[str, object]],
    weather: dict[str, object],
    training: dict[str, object],
    market: dict[str, object],
    ai_panel: dict[str, str],
    trend: dict[str, object] | None = None,
    ai_enabled: bool = True,
) -> dict[str, str]:
    fallback = _fallback_ai_pack(
        today=today,
        tasks=tasks,
        weather=weather,
        training=training,
        market=market,
        ai_panel=ai_panel,
        trend=trend,
    )

    # Keep cache scoped to context snapshot to avoid stale "old day" copies.
    context_seed = json.dumps(
        {
            "pack_rev": "v2",
            "today": {
                "date": today.get("date"),
                "mode": today.get("day_mode"),
                "energy": today.get("energy"),
            },
            "tasks_open": len(tasks),
            "weather": weather.get("summary"),
            "training_hint": training.get("progressive_hint"),
            "trend": (trend or {}).get("summary"),
            "market": (market.get("highlights") or [])[:3],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_hash = hashlib.sha1(context_seed.encode("utf-8")).hexdigest()[:12]
    cache_key = f"dashboard:ai_pack:{user_id}:{cache_hash}"
    cached = _cache_get_json(cache_key, _AI_CACHE_TTL_SECONDS)
    if cached:
        packed = {}
        for key, base in fallback.items():
            val = str(cached.get(key) or "").strip()
            packed[key] = val or base
        return packed

    settings = _settings()
    if (
        not ai_enabled
        or not settings
        or not _dashboard_ai_enabled()
        or not _dashboard_ai_everywhere_enabled()
    ):
        _cache_set_json(cache_key, fallback)
        return fallback

    prompt = (
        "Ты усиливаешь текст Day OS. Верни СТРОГО JSON-объект с ключами:\n"
        "mission_text, growth_year, growth_month, growth_week, growth_day, "
        "weather_brief, weather_clothing, training_hint, market_brief, coach_line.\n\n"
        "Правила:\n"
        "1) Только русский язык.\n"
        "2) Кратко и практично (каждое поле 1-2 предложения).\n"
        "3) Не выдумывай факты, числа, цены и даты.\n"
        "4) Если данных мало — формулируй осторожно.\n\n"
        f"Контекст JSON:\n{context_seed}\n\n"
        "Текущие безопасные формулировки (можно улучшить стиль, но не смысл):\n"
        f"{json.dumps(fallback, ensure_ascii=False)}"
    )

    try:
        llm_prompt = build_prompt(
            history=[],
            user_message=prompt,
            settings=settings,
            mode="fast",
            profile="advisor",
        )
        raw = await asyncio.wait_for(
            call_ollama(llm_prompt, settings, mode="fast", profile="advisor"),
            timeout=8.5,
        )
        payload = _parse_llm_json_object(raw or "")
        if not payload:
            _cache_set_json(cache_key, fallback)
            return fallback

        packed = {}
        for key, base in fallback.items():
            value = str(payload.get(key) or "").strip()
            if not value:
                packed[key] = base
                continue
            if len(value) > 280:
                value = value[:280].rstrip() + "..."
            packed[key] = value
        _cache_set_json(cache_key, packed)
        return packed
    except Exception:
        _cache_set_json(cache_key, fallback)
        return fallback


async def _copilot_reply(
    *,
    user_id: int,
    message: str,
    mode: str = "normal",
) -> dict[str, object]:
    today_raw = _handle(user_id, "today", debug=0)
    tasks_raw = _handle(user_id, "tasks:list", {"limit": 20}, debug=0)
    today, _ = _unwrap_result(today_raw)
    tasks_obj, _ = _unwrap_result(tasks_raw)
    tasks = tasks_obj.get("items") if isinstance(tasks_obj.get("items"), list) else []
    trend = _trend_panel(user_id)
    context = {
        "today_energy": today.get("energy"),
        "today_mode": today.get("day_mode"),
        "tasks": tasks,
        "tasks_count": len(tasks),
        "trend_summary": trend.get("summary"),
    }

    fallback = _copilot_fallback(message, context)
    settings = _settings()
    if not settings:
        return fallback

    rag_payload = await resolve_rag_for_query(user_id=user_id, query=message, lang="ru")
    block_message = str(rag_payload.get("block_message") or "").strip()
    if block_message:
        return {
            "answer": block_message,
            "quick_actions": list(fallback.get("quick_actions") or []),
        }
    rag_context = str(rag_payload.get("context") or "").strip()

    prompt = (
        f"{_GEMMA_PERSONA_BRIEF}\n"
        "Формат ответа:\n"
        "1) Сначала 2-5 строк по делу.\n"
        "2) Затем строка с префиксом 'next:' и один следующий шаг.\n"
        "Без длинных объяснений и без воды.\n\n"
        "Контекст:\n"
        f"- day_mode: {today.get('day_mode')}\n"
        f"- energy: {today.get('energy')}\n"
        f"- tasks_open: {len(tasks)}\n"
        f"- trend_7d: {trend.get('summary')}\n"
        f"- message: {message}\n"
    )
    if rag_context:
        prompt = (
            f"{prompt}\n"
            "Личный контекст с цитатами:\n"
            f"{rag_context}\n"
            "Если используешь личные данные, обязательно ссылайся на [n]."
        )
    try:
        llm_prompt = build_prompt(
            history=[],
            user_message=prompt,
            settings=settings,
            mode=mode if mode in {"fast", "normal", "precise"} else "normal",
            profile="advisor",
        )
        raw = (await asyncio.wait_for(call_ollama(llm_prompt, settings, mode=mode, profile="advisor"), timeout=9.0)).strip()
        if not raw:
            return fallback
        next_step = ""
        answer_lines: list[str] = []
        for line in raw.splitlines():
            if line.lower().startswith("next:"):
                next_step = line.split(":", 1)[1].strip()
                continue
            if line.strip():
                answer_lines.append(line.strip())
        answer = "\n".join(answer_lines[:6]).strip() or fallback["answer"]
        quick_actions = list(fallback.get("quick_actions") or [])
        if next_step:
            answer = f"{answer}\n\nСледующий шаг: {next_step}"
        citations_block = str(rag_payload.get("citations_block") or "").strip()
        if bool(rag_payload.get("personal")) and citations_block:
            answer = f"{answer}\n\n{citations_block}"
        return {
            "answer": answer,
            "quick_actions": quick_actions,
        }
    except Exception:
        return fallback


async def _gemma_full_reply(
    *,
    user_id: int,
    message: str,
    mode: str = "normal",
) -> dict[str, object]:
    settings = _settings()
    today_raw = _handle(user_id, "today", debug=0)
    tasks_raw = _handle(user_id, "tasks:list", {"limit": 20}, debug=0)
    today, _ = _unwrap_result(today_raw)
    tasks_obj, _ = _unwrap_result(tasks_raw)
    tasks = tasks_obj.get("items") if isinstance(tasks_obj.get("items"), list) else []
    trend = _trend_panel(user_id)

    fallback = _copilot_fallback(message, {
        "today_energy": today.get("energy"),
        "today_mode": today.get("day_mode"),
        "tasks": tasks,
        "tasks_count": len(tasks),
        "trend_summary": trend.get("summary"),
    })
    if not settings:
        return fallback

    rag_payload = await resolve_rag_for_query(user_id=user_id, query=message, lang="ru")
    block_message = str(rag_payload.get("block_message") or "").strip()
    if block_message:
        return {
            "answer": block_message,
            "quick_actions": list(fallback.get("quick_actions") or []),
        }

    history = _chat_history_load(user_id)
    extra_context = (
        f"day_mode={today.get('day_mode')}; energy={today.get('energy')}; "
        f"open_tasks={len(tasks)}; trend_7d={trend.get('summary')}"
    )
    rag_context = str(rag_payload.get("context") or "").strip()
    if rag_context:
        extra_context = (
            f"{extra_context}\n{rag_context}\n"
            "If personal data is used, cite sources as [1], [2], ..."
        ).strip()
    user_message = (
        f"{_GEMMA_PERSONA_BRIEF}\n"
        "Отвечай по делу и естественно, тёплым и уважительным тоном.\n"
        "Если пользователь просит план/структуру — дай структурированный ответ.\n"
        "Если вопрос разговорный — отвечай разговорно.\n"
        "Если данных не хватает — честно скажи и задай один короткий уточняющий вопрос.\n\n"
        f"Запрос пользователя:\n{message}"
    )
    try:
        request_timeout = max(10.0, float(getattr(settings, "ollama_soft_timeout_seconds", 25.0)) + 2.0)
        llm_prompt = build_prompt(
            history=history,
            user_message=user_message,
            settings=settings,
            extra_context=extra_context,
            mode=mode if mode in {"fast", "normal", "precise"} else "normal",
            profile="advisor",
        )
        raw = (
            await asyncio.wait_for(
                call_ollama(llm_prompt, settings, mode=mode, profile="advisor"),
                timeout=request_timeout,
            )
        ).strip()
        answer = raw or str(fallback.get("answer") or "")
        citations_block = str(rag_payload.get("citations_block") or "").strip()
        if bool(rag_payload.get("personal")) and citations_block:
            answer = f"{answer}\n\n{citations_block}"
        quick_actions = list(fallback.get("quick_actions") or [])
        _chat_history_save(
            user_id,
            history + [
                {"role": "user", "content": message.strip()},
                {"role": "assistant", "content": answer},
            ],
        )
        return {"answer": answer, "quick_actions": quick_actions}
    except Exception:
        return fallback


def _extract_task_from_message(message: str) -> str | None:
    text = (message or "").strip()
    if not text:
        return None
    patterns = [
        r"^\s*(?:добавь|добавить)\s+задач[ауи]?\s*[:\-]\s*(.+)$",
        r"^\s*задач[ауи]?\s*[:\-]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return None


def _extract_codex_request(message: str) -> str | None:
    text = (message or "").strip()
    if not text:
        return None
    match = re.match(r"^/codex(?:@\w+)?(?:\s+(.+))?$", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    payload = (match.group(1) or "").strip()
    return payload or ""


def _codex_status_path(run_id: str) -> Path:
    return _CODEX_RUNS_DIR / run_id / "status.json"


def _codex_log_path(run_id: str) -> Path:
    return _CODEX_RUNS_DIR / run_id / "stdout.log"


def _codex_last_message_path(run_id: str) -> Path:
    return _CODEX_RUNS_DIR / run_id / "last_message.txt"


def _short_text(value: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _windows_detached_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "DETACHED_PROCESS", 0))


def _codex_write_status(run_id: str, payload: dict[str, object]) -> None:
    path = _codex_status_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with _CODEX_RUN_LOCK:
        _CODEX_RUN_STATE[run_id] = dict(payload)


def _codex_read_status(run_id: str) -> dict[str, object]:
    with _CODEX_RUN_LOCK:
        cached = _CODEX_RUN_STATE.get(run_id)
    if isinstance(cached, dict):
        return dict(cached)
    path = _codex_status_path(run_id)
    if not path.exists():
        return {"run_id": run_id, "status": "not_found"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"run_id": run_id, "status": "unknown"}


def _codex_read_log_delta(run_id: str, cursor: int = 0, limit: int = 40) -> tuple[list[str], int]:
    path = _codex_log_path(run_id)
    if not path.exists():
        return [], max(0, int(cursor))
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [], max(0, int(cursor))
    start = max(0, int(cursor))
    if start >= len(lines):
        return [], len(lines)
    chunk = lines[start : start + max(1, int(limit))]
    ui_lines: list[str] = []
    for raw in chunk:
        line = str(raw or "").strip()
        if not line:
            continue
        if line.startswith("[") and "] " in line:
            ui_lines.append(line)
            continue
        try:
            obj = json.loads(line)
        except Exception:
            ui_lines.append(_short_text(line, 240))
            continue
        if not isinstance(obj, dict):
            continue
        event_type = str(obj.get("type") or "")
        if event_type == "turn.started":
            ui_lines.append("▶️ Запуск Codex")
            continue
        if event_type == "turn.completed":
            ui_lines.append("✅ Codex завершил ход")
            continue
        item = obj.get("item")
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if event_type == "item.completed" and item_type == "agent_message":
            text = _short_text(str(item.get("text") or ""), 260)
            if text:
                ui_lines.append(f"🤖 {text}")
            continue
        if event_type == "item.completed" and item_type == "command_execution":
            code = item.get("exit_code")
            command = _short_text(str(item.get("command") or ""), 110)
            if isinstance(code, int) and code != 0:
                ui_lines.append(f"⚠️ Команда завершилась с кодом {code}: {command}")
            continue
    return ui_lines, start + len(chunk)


def _codex_read_last_message(run_id: str) -> str:
    path = _codex_last_message_path(run_id)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    return text


def _run_codex_exec(run_id: str, prompt: str, user_id: int) -> None:
    status = _codex_read_status(run_id)
    status.update({"status": "running", "started_at": _now_iso(), "pid": None})
    _codex_write_status(run_id, status)

    pre_status = _git_status_map()
    pre_hash = _hash_map(list(pre_status.keys()))

    log_path = _codex_log_path(run_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "cmd",
        "/c",
        "codex",
        "exec",
        "--cd",
        str(_PROJECT_DIR),
        "--sandbox",
        "workspace-write",
        "--json",
        "--output-last-message",
        str(_codex_last_message_path(run_id)),
        prompt,
    ]
    try:
        with log_path.open("a", encoding="utf-8") as log_fh:
            log_fh.write(f"[{_now_iso()}] run_id={run_id} user_id={user_id}\n")
            log_fh.write(f"[{_now_iso()}] cmd={' '.join(cmd)}\n")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_DIR),
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            status["pid"] = int(proc.pid)
            _codex_write_status(run_id, status)
            if proc.stdout:
                for line in proc.stdout:
                    log_fh.write(line)
            code = int(proc.wait())
            status.update(
                {
                    "status": "done" if code == 0 else "failed",
                    "exit_code": code,
                    "finished_at": _now_iso(),
                }
            )
            post_status = _git_status_map()
            candidates = sorted(set(pre_status.keys()) | set(post_status.keys()))
            post_hash = _hash_map(candidates)
            changed_files: list[dict[str, object]] = []
            for path in candidates:
                before_state = pre_status.get(path)
                after_state = post_status.get(path)
                before_hash = pre_hash.get(path)
                after_hash = post_hash.get(path)
                if before_state != after_state or before_hash != after_hash:
                    changed_files.append(
                        {
                            "path": path,
                            "pre_status": before_state or "",
                            "post_status": after_state or "",
                            "dirty_before": path in pre_status,
                        }
                    )

            changed_paths = [str(item["path"]) for item in changed_files]
            safe_rollback_paths = [str(item["path"]) for item in changed_files if not bool(item.get("dirty_before"))]
            tracked_for_diff = [str(item["path"]) for item in changed_files if str(item.get("post_status") or "") != "??"]
            diff_text = _git_diff_for_paths(tracked_for_diff)
            diff_path = log_path.parent / "diff.patch"
            if diff_text:
                diff_path.write_text(diff_text, encoding="utf-8", errors="replace")

            tests = _run_codex_smoke_tests(changed_paths)
            tests_text = (
                "не запускались"
                if not tests.get("ran")
                else ("ok" if tests.get("ok") else "fail")
            )
            status["report"] = {
                "changed_files": changed_files,
                "changed_count": len(changed_files),
                "safe_rollback_paths": safe_rollback_paths,
                "tests": tests,
                "diff_available": bool(diff_text),
                "diff_path": str(diff_path) if diff_text else "",
                "summary": f"Изменено файлов: {len(changed_files)}; smoke-tests: {tests_text}.",
            }
            last_message = _codex_read_last_message(run_id)
            if last_message:
                status["last_message_preview"] = _short_text(last_message, 320)
            _codex_write_status(run_id, status)
    except Exception as exc:
        status.update(
            {
                "status": "failed",
                "exit_code": -1,
                "finished_at": _now_iso(),
                "error": str(exc),
            }
        )
        _codex_write_status(run_id, status)
        try:
            with log_path.open("a", encoding="utf-8") as log_fh:
                log_fh.write(f"[{_now_iso()}] bridge_error={exc}\n")
        except Exception:
            pass


def _start_codex_run(*, user_id: int, prompt: str) -> dict[str, object]:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    base = {
        "run_id": run_id,
        "status": "queued",
        "created_at": _now_iso(),
        "user_id": int(user_id),
        "prompt": prompt,
        "exit_code": None,
    }
    _codex_write_status(run_id, base)
    thread = threading.Thread(
        target=_run_codex_exec,
        kwargs={"run_id": run_id, "prompt": prompt, "user_id": user_id},
        daemon=True,
    )
    thread.start()
    return base


def _save_codex_ticket(*, user_id: int, request_text: str) -> str:
    _CODEX_INBOX.parent.mkdir(parents=True, exist_ok=True)
    ticket_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
    record = {
        "ticket_id": ticket_id,
        "ts": _now_iso(),
        "user_id": int(user_id),
        "request": request_text,
        "source": "dashboard",
        "status": "new",
    }
    with _CODEX_INBOX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return ticket_id


def _build_codex_dashboard_prompt(*, request_text: str, ticket_id: str) -> str:
    clean_request = request_text.strip()
    return (
        "Контекст: ты Dev Agent проекта jarvis-ai-center. "
        "Работаешь в текущем репозитории локально.\n\n"
        f"Задача: {clean_request}\n"
        f"ticket_id={ticket_id}\n\n"
        "Обязательный порядок:\n"
        "1) Внести минимально необходимые правки в код.\n"
        "2) Сохранить совместимость, не ломать UX без запроса.\n"
        "3) Прогнать smoke-проверку (или объяснить, почему нельзя).\n"
        "4) Дать итог в формате:\n"
        "   - Goal\n"
        "   - Changed files\n"
        "   - What changed\n"
        "   - Manual test steps\n"
        "   - Risks / Notes\n"
        "   - Suggested next step\n\n"
        "Важно: если формулировка неполная, сначала сделай разумную "
        "минимальную реализацию без лишних уточнений."
    )


def _git_status_map() -> dict[str, str]:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_PROJECT_DIR),
        )
    except Exception:
        return {}
    if res.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for raw in (res.stdout or "").splitlines():
        if not raw.strip():
            continue
        code = raw[:2]
        path = raw[3:].strip()
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        if path:
            out[path.replace("\\", "/")] = code
    return out


def _safe_rel_target(rel_path: str) -> Path | None:
    try:
        target = (_PROJECT_DIR / rel_path).resolve()
        root = _PROJECT_DIR.resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root):
            return None
        return target
    except Exception:
        return None


def _file_sha256(rel_path: str) -> str | None:
    target = _safe_rel_target(rel_path)
    if not target or not target.exists() or not target.is_file():
        return None
    h = hashlib.sha256()
    try:
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                if not chunk:
                    break
                h.update(chunk)
    except Exception:
        return None
    return h.hexdigest()


def _hash_map(paths: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in paths:
        key = rel.replace("\\", "/")
        out[key] = _file_sha256(key)
    return out


def _git_diff_for_paths(paths: list[str]) -> str:
    safe = [p for p in paths if p and not p.startswith("../")]
    if not safe:
        return ""
    cmd = ["git", "diff", "--"] + safe
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=40,
            cwd=str(_PROJECT_DIR),
        )
    except Exception:
        return ""
    if res.returncode != 0:
        return ""
    return str(res.stdout or "")


def _run_codex_smoke_tests(changed_paths: list[str]) -> dict[str, object]:
    has_python = any(str(path).lower().endswith(".py") for path in changed_paths)
    if not has_python:
        return {"ran": False, "ok": None, "cmd": "", "duration_ms": 0, "output_preview": "python files not changed"}

    cmd = [
        "python",
        "-m",
        "unittest",
        "tests.test_day_os_smoke",
        "tests.test_commands_todo_panel",
    ]
    started = time.perf_counter()
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_PROJECT_DIR),
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        output = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        lines = output.splitlines()[-40:]
        preview = "\n".join(lines)
        return {
            "ran": True,
            "ok": res.returncode == 0,
            "cmd": " ".join(cmd),
            "duration_ms": elapsed,
            "output_preview": _short_text(preview, 2000),
            "exit_code": int(res.returncode),
        }
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return {
            "ran": True,
            "ok": False,
            "cmd": " ".join(cmd),
            "duration_ms": elapsed,
            "output_preview": _short_text(str(exc), 500),
            "exit_code": -1,
        }


def _command_available_windows(cmd: str) -> bool:
    try:
        res = subprocess.run(
            ["cmd", "/c", "where", cmd],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(_PROJECT_DIR),
        )
        return res.returncode == 0 and bool((res.stdout or "").strip())
    except Exception:
        return False


def _ollama_service_status() -> dict[str, object]:
    available = _command_available_windows("ollama")
    if not available:
        return {"installed": False, "running": False, "message": "ollama command not found"}
    try:
        res = subprocess.run(
            ["cmd", "/c", "ollama", "list"],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=str(_PROJECT_DIR),
        )
        running = res.returncode == 0
        return {
            "installed": True,
            "running": running,
            "message": "ok" if running else _short_text(res.stderr or res.stdout or "unknown error", 200),
        }
    except Exception as exc:
        return {"installed": True, "running": False, "message": _short_text(str(exc), 200)}


def _restart_ollama_service() -> dict[str, object]:
    status = _ollama_service_status()
    if not bool(status.get("installed")):
        return {"ok": False, "message": "Ollama не установлен или не найден в PATH."}
    stop_code = 0
    stop_out = ""
    try:
        stop = subprocess.run(
            ["cmd", "/c", "taskkill", "/IM", "ollama.exe", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_PROJECT_DIR),
        )
        stop_code = int(stop.returncode)
        stop_out = _short_text((stop.stdout or "") + " " + (stop.stderr or ""), 180)
    except Exception as exc:
        stop_out = _short_text(str(exc), 180)

    try:
        subprocess.Popen(
            ["cmd", "/c", "ollama", "serve"],
            cwd=str(_PROJECT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_windows_detached_flags(),
        )
    except Exception as exc:
        return {"ok": False, "message": f"Не удалось запустить Ollama: {exc}"}

    return {
        "ok": True,
        "message": "Перезапуск Ollama отправлен.",
        "stop_code": stop_code,
        "stop_info": stop_out,
    }


def _trigger_api_reload() -> dict[str, object]:
    payload = (
        "# Auto-generated by dashboard ops\n"
        f"RELOAD_TS = '{_now_iso()}'\n"
    )
    _API_RELOAD_TRIGGER.write_text(payload, encoding="utf-8")
    return {"ok": True, "message": "Reload trigger записан.", "path": str(_API_RELOAD_TRIGGER)}


def _codex_history(limit: int = 20) -> list[dict[str, object]]:
    if not _CODEX_RUNS_DIR.exists():
        return []
    dirs = [p for p in _CODEX_RUNS_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, object]] = []
    for run_dir in dirs[: max(1, limit)]:
        run_id = run_dir.name
        status = _codex_read_status(run_id)
        report = status.get("report") if isinstance(status.get("report"), dict) else {}
        tests = report.get("tests") if isinstance(report.get("tests"), dict) else {}
        out.append(
            {
                "run_id": run_id,
                "status": str(status.get("status") or "unknown"),
                "created_at": status.get("created_at"),
                "finished_at": status.get("finished_at"),
                "exit_code": status.get("exit_code"),
                "changed_count": int(report.get("changed_count") or 0),
                "tests_ran": bool(tests.get("ran")),
                "tests_ok": tests.get("ok"),
                "summary": str(report.get("summary") or ""),
                "prompt_preview": _short_text(str(status.get("prompt") or ""), 180),
                "last_message_preview": _short_text(str(status.get("last_message_preview") or ""), 220),
            }
        )
    return out


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    # Quiet browser default favicon requests to avoid noisy 404 logs.
    return Response(status_code=204)


@app.get("/today")
def get_today(request: Request, user_id: int, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    return _handle(user_id, "today", debug=safe_debug)


@app.get("/tasks")
def get_tasks(request: Request, user_id: int, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    return _handle(user_id, "tasks:list", {"limit": 20}, debug=safe_debug)


@app.post("/tasks")
def create_task(request: Request, payload: TaskCreateRequest, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    now_iso = _now_iso()
    due_date = _clean_iso_date(payload.due_date)
    remind_at = _clean_iso_datetime(payload.remind_at)
    notes = str(payload.notes or "").strip()
    return _handle(
        payload.user_id,
        "tasks:add",
        {
            "text": payload.text.strip(),
            "created_at": now_iso,
            "notes": notes,
            "due_date": due_date,
            "remind_at": remind_at,
            "remind_telegram": bool(payload.remind_telegram),
        },
        debug=safe_debug,
    )


@app.post("/tasks/{task_id}/done")
def complete_task(
    request: Request,
    task_id: int,
    payload: TaskDoneRequest,
    debug: int = 0,
) -> dict[str, object]:
    _ensure_api_authorized(request)
    if int(task_id) <= 0:
        raise HTTPException(status_code=400, detail="task_id must be positive")
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    done_at = _clean_iso_datetime(payload.done_at) or _now_iso()
    return _handle(
        payload.user_id,
        "tasks:done",
        {
            "task_id": int(task_id),
            "done_at": done_at,
        },
        debug=safe_debug,
    )


@app.patch("/tasks/{task_id}")
def update_task(
    request: Request,
    task_id: int,
    payload: TaskUpdateRequest,
    debug: int = 0,
) -> dict[str, object]:
    _ensure_api_authorized(request)
    if int(task_id) <= 0:
        raise HTTPException(status_code=400, detail="task_id must be positive")
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    fields_set = set(getattr(payload, "model_fields_set", set()))
    command_payload: dict[str, object] = {"task_id": int(task_id)}

    if "text" in fields_set:
        text = str(payload.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text cannot be empty")
        command_payload["text"] = text

    if "notes" in fields_set:
        command_payload["notes"] = str(payload.notes or "").strip()

    if "due_date" in fields_set:
        command_payload["due_date"] = _clean_iso_date(payload.due_date)

    if "remind_at" in fields_set:
        command_payload["remind_at"] = _clean_iso_datetime(payload.remind_at)

    if "remind_telegram" in fields_set:
        command_payload["remind_telegram"] = bool(payload.remind_telegram)

    if len(command_payload) == 1:
        raise HTTPException(status_code=400, detail="no task fields provided")

    return _handle(
        payload.user_id,
        "tasks:update",
        command_payload,
        debug=safe_debug,
    )


@app.delete("/tasks/{task_id}")
def delete_task(request: Request, task_id: int, user_id: int, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    if int(task_id) <= 0:
        raise HTTPException(status_code=400, detail="task_id must be positive")
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    return _handle(
        int(user_id),
        "tasks:delete",
        {
            "task_id": int(task_id),
        },
        debug=safe_debug,
    )


@app.get("/subs")
def get_subscriptions(request: Request, user_id: int, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    return _handle(user_id, "subs:list", debug=safe_debug)


@app.post("/subs")
def create_subscription(request: Request, payload: SubscriptionCreateRequest, debug: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    next_date = _clean_iso_date(payload.next_date)
    if not next_date:
        raise HTTPException(status_code=400, detail="next_date must be YYYY-MM-DD")
    period = str(payload.period or "").strip().lower()
    if period not in {"weekly", "monthly", "quarterly", "yearly"}:
        raise HTTPException(status_code=400, detail="period must be weekly|monthly|quarterly|yearly")
    return _handle(
        payload.user_id,
        "subs:add",
        {
            "name": payload.name.strip(),
            "next_date": next_date,
            "period": period,
            "created_at": _now_iso(),
            "amount": payload.amount,
            "currency": str(payload.currency or "RUB").strip().upper() or "RUB",
            "note": str(payload.note or "").strip(),
            "category": str(payload.category or "").strip(),
            "autopay": bool(payload.autopay),
            "remind_days": int(payload.remind_days),
        },
        debug=safe_debug,
    )


@app.get("/dashboard/garage")
def dashboard_garage(request: Request, user_id: int) -> dict[str, object]:
    _ensure_api_authorized(request)
    panel = _garage_panel(int(user_id))
    return {"ok": True, **panel}


@app.patch("/dashboard/garage/assets/{asset_id}")
def dashboard_garage_update_asset(
    request: Request,
    asset_id: int,
    payload: GarageAssetUpdateRequest,
) -> dict[str, object]:
    _ensure_api_authorized(request)
    if int(asset_id) <= 0:
        raise HTTPException(status_code=400, detail="asset_id must be positive")

    fields_set = set(getattr(payload, "model_fields_set", set()))
    if not fields_set:
        raise HTTPException(status_code=400, detail="no fields provided")

    maintenance_due_date: str | None = None
    insurance_until: str | None = None
    tech_inspection_until: str | None = None
    if "maintenance_due_date" in fields_set:
        raw = str(payload.maintenance_due_date or "").strip()
        if raw:
            clean = _clean_iso_date(raw)
            if not clean:
                raise HTTPException(status_code=400, detail="maintenance_due_date must be YYYY-MM-DD")
            maintenance_due_date = clean
        else:
            maintenance_due_date = ""
    if "insurance_until" in fields_set:
        raw = str(payload.insurance_until or "").strip()
        if raw:
            clean = _clean_iso_date(raw)
            if not clean:
                raise HTTPException(status_code=400, detail="insurance_until must be YYYY-MM-DD")
            insurance_until = clean
        else:
            insurance_until = ""
    if "tech_inspection_until" in fields_set:
        raw = str(payload.tech_inspection_until or "").strip()
        if raw:
            clean = _clean_iso_date(raw)
            if not clean:
                raise HTTPException(status_code=400, detail="tech_inspection_until must be YYYY-MM-DD")
            tech_inspection_until = clean
        else:
            tech_inspection_until = ""

    ok = garage_update_asset(
        user_id=int(payload.user_id),
        asset_id=int(asset_id),
        updated_at=_now_iso(),
        mileage_km=(payload.mileage_km if "mileage_km" in fields_set else None),
        last_service_km=(payload.last_service_km if "last_service_km" in fields_set else None),
        maintenance_interval_km=(
            payload.maintenance_interval_km if "maintenance_interval_km" in fields_set else None
        ),
        maintenance_due_date=(maintenance_due_date if "maintenance_due_date" in fields_set else None),
        insurance_until=(insurance_until if "insurance_until" in fields_set else None),
        tech_inspection_until=(tech_inspection_until if "tech_inspection_until" in fields_set else None),
        note=(payload.note if "note" in fields_set else None),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="asset not found")

    panel = _garage_panel(int(payload.user_id))
    return {"ok": True, "asset_id": int(asset_id), "garage": panel, "updated_at": _now_iso()}


@app.get("/signals")
async def get_signals(request: Request, user_id: int, limit: int = 20) -> dict[str, object]:
    _ensure_api_authorized(request)
    generated_at = _now_iso()
    panel = await _load_signals_panel(limit=limit)
    return {
        "meta": {
            "schema": "signals.v1",
            "generated_at": generated_at,
            "user_id": user_id,
        },
        "signals": panel,
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, token: str | None = None) -> HTMLResponse:
    if not _is_trusted_client(request):
        return HTMLResponse(content="Remote access is restricted. Use VPN/mesh/trusted network.", status_code=403)
    if not _is_authorized_request(request, query_token=token):
        return HTMLResponse(content=_dashboard_login_html(), status_code=401)
    html = _DASHBOARD_HTML.read_text(encoding="utf-8")
    response = HTMLResponse(content=html)
    if _dashboard_auth_required() and token and _is_authorized_request(request, query_token=token):
        response.set_cookie(
            key=_DASH_AUTH_COOKIE_NAME,
            value=str(token).strip(),
            httponly=True,
            samesite="lax",
            secure=_auth_cookie_secure(),
            max_age=60 * 60 * 12,
        )
    return response


async def _assistant_message(payload: CopilotMessageRequest) -> dict[str, object]:
    text_message = str(payload.message or "").strip()

    def _remember(response: dict[str, object]) -> dict[str, object]:
        answer = str(response.get("answer") or "").strip()
        if text_message and answer:
            _chat_history_append_exchange(
                payload.user_id,
                user_text=text_message,
                assistant_text=answer,
            )
        return response

    try:
        codex_request = _extract_codex_request(text_message)
        if codex_request is not None:
            if not codex_request:
                return _remember(
                    {
                    "answer": "Формат: /codex <задача>. Пример: /codex добавь минималистичный стиль в блок задач.",
                    "quick_actions": [],
                    }
                )
            ticket_id = _save_codex_ticket(user_id=payload.user_id, request_text=codex_request)
            codex_prompt = _build_codex_dashboard_prompt(request_text=codex_request, ticket_id=ticket_id)
            if _codex_bridge_enabled():
                run = _start_codex_run(user_id=payload.user_id, prompt=codex_prompt)
                run_id = str(run.get("run_id") or "")
                return _remember(
                    {
                    "answer": (
                        "Принял. Запустил Codex в фоне.\n"
                        f"Ticket: {ticket_id}\n"
                        f"Run: {run_id}\n"
                        "Показываю прогресс прямо в чате дашборда."
                    ),
                    "quick_actions": [],
                    "codex_ticket_id": ticket_id,
                    "codex_prompt": codex_prompt,
                    "codex_run_id": run_id,
                    }
                )
            return _remember(
                {
                "answer": (
                    "Запрос для Codex зафиксирован.\n"
                    f"Ticket: {ticket_id}\n"
                    "Автопередача прямо в этот чат пока недоступна, "
                    "но задача сохранена в ops/codex_inbox.jsonl.\n"
                    "Готовый текст для отправки Codex:\n"
                    f"{codex_prompt}"
                ),
                "quick_actions": [],
                "codex_ticket_id": ticket_id,
                "codex_prompt": codex_prompt,
                }
            )

        task_from_text = _extract_task_from_message(text_message)
        if task_from_text:
            result = _handle(
                payload.user_id,
                "tasks:add",
                {"text": task_from_text, "created_at": _now_iso()},
                debug=0,
            )
            data, _ = _unwrap_result(result)
            task_id = int(data.get("id") or 0)
            return _remember(
                _normalize_ai_message_result(
                    {
                        "answer": f"Готово. Добавила задачу #{task_id}: {task_from_text}",
                        "quick_actions": [
                            {"type": "focus_start", "label": "Фокус 25м"},
                            {"type": "replan_day", "label": "Переплан дня"},
                        ],
                    },
                    fallback_text="Задача добавлена.",
                    status="ok",
                    source="task_add",
                )
            )

        chat_mode = (payload.chat_mode or "full").strip().lower()
        llm_timeout = _chat_llm_timeout(chat_mode)
        try:
            if chat_mode == "coach":
                result = await asyncio.wait_for(
                    _copilot_reply(
                        user_id=payload.user_id,
                        message=text_message,
                        mode=payload.mode,
                    ),
                    timeout=llm_timeout,
                )
                source = "coach"
            else:
                result = await asyncio.wait_for(
                    _gemma_full_reply(
                        user_id=payload.user_id,
                        message=text_message,
                        mode=payload.mode,
                    ),
                    timeout=llm_timeout,
                )
                source = "gemma"
            return _remember(
                _normalize_ai_message_result(
                    result,
                    fallback_text=_AI_MESSAGE_EMPTY_TEXT,
                    status="ok",
                    source=source,
                )
            )
        except asyncio.TimeoutError:
            return _remember(
                _normalize_ai_message_result(
                    None,
                    fallback_text=_AI_MESSAGE_TIMEOUT_TEXT,
                    status="fallback",
                    source="fallback",
                    error_kind="timeout",
                )
            )
        except Exception:
            return _remember(
                _normalize_ai_message_result(
                    None,
                    fallback_text=_AI_MESSAGE_UNAVAILABLE_TEXT,
                    status="fallback",
                    source="fallback",
                    error_kind="unavailable",
                )
            )
    except Exception:
        return _remember(
            _normalize_ai_message_result(
                None,
                fallback_text=_AI_MESSAGE_UNAVAILABLE_TEXT,
                status="fallback",
                source="fallback",
                error_kind="runtime_error",
            )
        )


async def _assistant_action(payload: CopilotActionRequest) -> dict[str, object]:
    try:
        action = payload.action.strip().lower()
        if action == "task_add":
            text = (payload.text or "").strip()
            if not text:
                return _normalize_ai_action_result(
                    ok=False,
                    message="Нужен текст задачи.",
                    quick_actions=[{"type": "task_add", "label": "Добавить задачу"}],
                    status="validation_error",
                    error_kind="missing_task_text",
                )
            result = _handle(
                payload.user_id,
                "tasks:add",
                {"text": text, "created_at": _now_iso()},
                debug=0,
            )
            data, _ = _unwrap_result(result)
            task_id = int(data.get("id") or 0)
            return _normalize_ai_action_result(
                ok=True,
                message=f"Задача добавлена: #{task_id}.",
                task_id=task_id,
                quick_actions=[
                    {"type": "focus_start", "label": "Фокус 25м"},
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
                status="ok",
            )
        if action == "focus_start":
            return _normalize_ai_action_result(
                ok=True,
                message=_focus_protocol(),
                quick_actions=[
                    {"type": "replan_day", "label": "Переплан дня"},
                ],
                status="ok",
            )
        if action == "replan_day":
            try:
                reply = await asyncio.wait_for(
                    _copilot_reply(
                        user_id=payload.user_id,
                        message="Сделай краткий переплан дня по текущему контексту.",
                        mode=payload.mode,
                    ),
                    timeout=_chat_llm_timeout("coach"),
                )
                return _normalize_ai_action_result(
                    ok=True,
                    message=str(reply.get("answer") or "").strip() or _AI_MESSAGE_EMPTY_TEXT,
                    quick_actions=reply.get("quick_actions") if isinstance(reply.get("quick_actions"), list) else None,
                    status="ok",
                )
            except asyncio.TimeoutError:
                return _normalize_ai_action_result(
                    ok=False,
                    message=_AI_ACTION_TIMEOUT_TEXT,
                    status="fallback",
                    error_kind="timeout",
                )
            except Exception:
                return _normalize_ai_action_result(
                    ok=False,
                    message=_AI_ACTION_UNAVAILABLE_TEXT,
                    status="fallback",
                    error_kind="unavailable",
                )
        return _normalize_ai_action_result(
            ok=False,
            message="Неизвестное действие. Доступно: task_add, replan_day, focus_start.",
            status="validation_error",
            error_kind="unknown_action",
        )
    except asyncio.TimeoutError:
        return _normalize_ai_action_result(
            ok=False,
            message=_AI_ACTION_TIMEOUT_TEXT,
            status="fallback",
            error_kind="timeout",
        )
    except Exception:
        return _normalize_ai_action_result(
            ok=False,
            message=_AI_ACTION_UNAVAILABLE_TEXT,
            status="fallback",
            error_kind="runtime_error",
        )


@app.post("/gemma/message")
async def gemma_message(request: Request, payload: CopilotMessageRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    return await _assistant_message(payload)


@app.post("/gemma/action")
async def gemma_action(request: Request, payload: CopilotActionRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    return await _assistant_action(payload)


@app.get("/gemma/nudge")
async def gemma_nudge(request: Request, user_id: int, force: int = 0) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_user_id = int(user_id)
    safe_force = bool(force == 1)
    try:
        payload, next_poll_sec = await asyncio.to_thread(_pick_gemma_nudge, safe_user_id, force=safe_force)
    except Exception:
        return {
            "ok": False,
            "has_message": False,
            "next_poll_sec": _GEMMA_NUDGE_DEFAULT_POLL_SEC,
        }
    if not payload or not str(payload.get("message") or "").strip():
        return {
            "ok": True,
            "has_message": False,
            "next_poll_sec": int(max(15, next_poll_sec)),
        }
    return {
        "ok": True,
        "has_message": True,
        "kind": str(payload.get("kind") or "signal"),
        "message": str(payload.get("message") or ""),
        "quick_actions": payload.get("quick_actions") if isinstance(payload.get("quick_actions"), list) else [],
        "typing_ms": int(payload.get("typing_ms") or 1200),
        "sent_at": str(payload.get("sent_at") or _now_iso()),
        "next_poll_sec": int(max(15, next_poll_sec)),
    }


@app.get("/gemma/history")
def gemma_history(request: Request, user_id: int, limit: int = 50) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_user_id = int(user_id)
    safe_limit = max(1, min(int(limit), _GEMMA_HISTORY_MAX_ITEMS))
    items = _chat_history_load(safe_user_id)[-safe_limit:]
    return {
        "ok": True,
        "user_id": safe_user_id,
        "items": items,
    }


@app.post("/copilot/message")
async def copilot_message(request: Request, payload: CopilotMessageRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    return await _assistant_message(payload)


@app.post("/copilot/action")
async def copilot_action(request: Request, payload: CopilotActionRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    return await _assistant_action(payload)


@app.post("/codex/run")
def codex_run(request: Request, payload: CodexRunRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    if not _codex_bridge_enabled():
        return {"ok": False, "status": "disabled", "message": "Codex bridge disabled (DASHBOARD_CODEX_BRIDGE=0)."}
    run = _start_codex_run(user_id=payload.user_id, prompt=payload.prompt.strip())
    return {"ok": True, **run}


@app.get("/codex/run/{run_id}")
def codex_run_status(request: Request, run_id: str, cursor: int = 0, limit: int = 30) -> dict[str, object]:
    _ensure_api_authorized(request)
    status = _codex_read_status(run_id)
    lines, next_cursor = _codex_read_log_delta(run_id, cursor=cursor, limit=limit)
    last_message = _codex_read_last_message(run_id)
    return {
        "ok": status.get("status") != "not_found",
        "status": status,
        "lines": lines,
        "cursor": next_cursor,
        "last_message": last_message,
    }


@app.get("/codex/run/{run_id}/diff", response_class=PlainTextResponse)
def codex_run_diff(request: Request, run_id: str) -> PlainTextResponse:
    _ensure_api_authorized(request)
    run_dir = _CODEX_RUNS_DIR / run_id
    diff_path = run_dir / "diff.patch"
    if not diff_path.exists():
        status = _codex_read_status(run_id)
        report = status.get("report") if isinstance(status.get("report"), dict) else {}
        changed = report.get("changed_files") if isinstance(report.get("changed_files"), list) else []
        changed_paths = [str(item.get("path") or "") for item in changed if isinstance(item, dict) and item.get("path")]
        tracked = [p for p in changed_paths if p]
        diff_text = _git_diff_for_paths(tracked)
        if diff_text:
            run_dir.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(diff_text, encoding="utf-8", errors="replace")
    if not diff_path.exists():
        return PlainTextResponse("diff not available", status_code=404)
    text = diff_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        text = "diff is empty"
    return PlainTextResponse(text)


@app.post("/codex/run/{run_id}/rollback")
def codex_run_rollback(request: Request, run_id: str) -> dict[str, object]:
    _ensure_api_authorized(request)
    status = _codex_read_status(run_id)
    report = status.get("report") if isinstance(status.get("report"), dict) else {}
    changed = report.get("changed_files") if isinstance(report.get("changed_files"), list) else []
    safe_paths = report.get("safe_rollback_paths") if isinstance(report.get("safe_rollback_paths"), list) else []
    changed_map: dict[str, dict[str, object]] = {}
    for item in changed:
        if isinstance(item, dict) and item.get("path"):
            changed_map[str(item["path"])] = item

    applied: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in safe_paths:
        rel = str(raw_path or "").replace("\\", "/")
        if not rel:
            continue
        meta = changed_map.get(rel, {})
        post_status = str(meta.get("post_status") or "")
        target = _safe_rel_target(rel)
        if target is None:
            skipped.append({"path": rel, "reason": "unsafe_path"})
            continue
        try:
            if post_status == "??":
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                applied.append(rel)
                continue
            res = subprocess.run(
                ["git", "restore", "--", rel],
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(_PROJECT_DIR),
            )
            if res.returncode == 0:
                applied.append(rel)
            else:
                skipped.append({"path": rel, "reason": _short_text(res.stderr or res.stdout or "restore_failed", 140)})
        except Exception as exc:
            skipped.append({"path": rel, "reason": _short_text(str(exc), 140)})

    return {
        "ok": bool(applied),
        "applied": applied,
        "skipped": skipped,
        "message": f"rollback applied={len(applied)} skipped={len(skipped)}",
    }


@app.get("/codex/history")
def codex_history(request: Request, limit: int = 20) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_limit = max(1, min(int(limit), 100))
    return {"runs": _codex_history(limit=safe_limit)}


@app.get("/ops/services")
def ops_services(request: Request) -> dict[str, object]:
    _ensure_api_authorized(request)
    checked_at = _now_iso()
    ollama_state = _ollama_service_status()
    auth_required = _dashboard_auth_required()
    debug_enabled = _debug_events_enabled()
    debug_remote = _debug_events_remote_enabled()
    public_access_allowed = _allow_public_access()
    trusted_client = _is_trusted_client(request)
    trusted_networks = [str(net) for net in _trusted_networks()]

    api_state = {
        "pid": int(os.getpid()),
        "cwd": str(_PROJECT_DIR),
        "reload_mode": True,
        "started_at": _API_STARTED_AT,
        "status": "ok",
    }

    ollama_status = "n/a"
    if bool(ollama_state.get("installed")):
        ollama_status = "ok" if bool(ollama_state.get("running")) else "down"

    codex_enabled = _codex_bridge_enabled()

    overall_status = "ok"
    if ollama_status == "down":
        overall_status = "down"
    elif not auth_required or debug_remote or public_access_allowed:
        overall_status = "warn"

    security_status = "ok"
    if public_access_allowed or not auth_required or debug_remote:
        security_status = "warn"

    return {
        "checked_at": checked_at,
        "status": overall_status,
        "api": api_state,
        "ollama": {
            **ollama_state,
            "status": ollama_status,
        },
        "codex_bridge": {
            "enabled": codex_enabled,
            "status": "ok" if codex_enabled else "off",
        },
        "security": {
            "auth_required": auth_required,
            "public_access_allowed": public_access_allowed,
            "trusted_client": trusted_client,
            "trusted_networks": trusted_networks,
            "debug_events_enabled": debug_enabled,
            "debug_events_remote": debug_remote,
            "status": security_status,
        },
    }


@app.post("/ops/ollama/restart")
def ops_ollama_restart(request: Request) -> dict[str, object]:
    _ensure_api_authorized(request)
    result = _restart_ollama_service()
    return result


@app.post("/ops/api/reload")
def ops_api_reload(request: Request) -> dict[str, object]:
    _ensure_api_authorized(request)
    return _trigger_api_reload()


@app.get("/dashboard/news/profile")
def dashboard_news_profile_get(request: Request, user_id: int) -> dict[str, object]:
    _ensure_api_authorized(request)
    profile = _load_news_profile(user_id)
    return {
        "user_id": int(user_id),
        "profile": profile,
        "topic_catalog": list(_NEWS_TOPIC_CATALOG),
    }


@app.post("/dashboard/news/profile")
def dashboard_news_profile_set(request: Request, payload: DashboardNewsProfileRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    profile = _save_news_profile(
        payload.user_id,
        {
            "interests": payload.interests,
            "hidden_topics": payload.hidden_topics,
            "hidden_sources": payload.hidden_sources,
            "explain": bool(payload.explain),
        },
    )
    return {
        "ok": True,
        "user_id": int(payload.user_id),
        "profile": profile,
        "topic_catalog": list(_NEWS_TOPIC_CATALOG),
    }


@app.get("/dashboard/fitness/workouts")
def dashboard_fitness_workouts(request: Request, user_id: int) -> dict[str, object]:
    _ensure_api_authorized(request)
    rows, _total = fitness_list_workouts(page=1, limit=120)
    items = [item for item in (_serialize_workout_row(row) for row in rows) if item]
    return {
        "ok": True,
        "user_id": int(user_id),
        "items": items,
        "count": len(items),
    }


@app.get("/dashboard/fitness/studio")
def dashboard_fitness_studio(request: Request, user_id: int = 118100880) -> HTMLResponse:
    _ensure_api_authorized(request)
    html = _fitness_studio_html().replace(
        'const userId = Number(qs.get("user_id") || "118100880");',
        f'const userId = Number(qs.get("user_id") || "{int(user_id)}");',
    )
    return HTMLResponse(content=html, status_code=200)


@app.post("/dashboard/fitness/session")
def dashboard_fitness_add_session(request: Request, payload: FitnessSessionCreateRequest) -> dict[str, object]:
    _ensure_api_authorized(request)
    workout = fitness_get_workout(int(payload.workout_id))
    if not workout:
        raise HTTPException(status_code=404, detail="workout not found")

    done_at = _clean_iso_datetime(payload.done_at) or _now_iso()
    comment = str(payload.comment or "").strip()
    rpe = int(payload.rpe) if payload.rpe is not None else None

    fitness_add_session(
        user_id=int(payload.user_id),
        workout_id=int(payload.workout_id),
        done_at=done_at,
        rpe=rpe,
        comment=comment or None,
    )
    recent_rpe = fitness_get_recent_rpe(user_id=int(payload.user_id), workout_id=int(payload.workout_id), limit=3)
    next_hint = next_hint_by_context(rpe, recent_rpe)
    fitness_upsert_progress(
        user_id=int(payload.user_id),
        workout_id=int(payload.workout_id),
        last_rpe=rpe,
        last_comment=comment or None,
        next_hint=next_hint,
        updated_at=_now_iso(),
    )
    progression = _progression_advice(rpe=rpe, recent_rpe=recent_rpe)
    latest_payload = {
        "workout_id": int(payload.workout_id),
        "title": _workout_title_from_row(workout),
        "done_at": done_at,
        "rpe": rpe,
        "recent_rpe": recent_rpe,
    }
    activity = _fitness_activity_snapshot(user_id=int(payload.user_id), latest_session=latest_payload)
    return {
        "ok": True,
        "user_id": int(payload.user_id),
        "workout_id": int(payload.workout_id),
        "workout_title": _workout_title_from_row(workout),
        "done_at": done_at,
        "rpe": rpe,
        "next_hint": next_hint,
        "progression": progression,
        "activity": activity,
    }


@app.get("/dashboard/fitness/videos")
def dashboard_fitness_videos(request: Request, user_id: int) -> dict[str, object]:
    _ensure_api_authorized(request)
    items = _list_fitness_videos(limit=120)
    return {
        "ok": True,
        "user_id": int(user_id),
        "count": len(items),
        "items": items,
    }


@app.get("/dashboard/fitness/video")
def dashboard_fitness_video(request: Request, name: str) -> FileResponse:
    _ensure_api_authorized(request)
    target = _resolve_video_file(name)
    if not target:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="video not found")
    return FileResponse(
        path=str(target),
        media_type=_video_media_type(target),
        filename=target.name,
    )


@app.get("/dashboard/data")
async def dashboard_data(request: Request, user_id: int, debug: int = 0, ai: int = 1) -> dict[str, object]:
    _ensure_api_authorized(request)
    safe_debug = 1 if _safe_debug_enabled(request, debug) else 0
    generated_at = _now_iso()
    today_raw, tasks_raw, subs_raw = await asyncio.gather(
        _handle_async(user_id, "today", debug=safe_debug),
        _handle_async(user_id, "tasks:list", {"limit": 20}, debug=safe_debug),
        _handle_async(user_id, "subs:list", debug=safe_debug),
    )

    today, today_events = _unwrap_result(today_raw)
    tasks_obj, tasks_events = _unwrap_result(tasks_raw)
    subs_obj, subs_events = _unwrap_result(subs_raw)
    tasks = tasks_obj.get("items") if isinstance(tasks_obj.get("items"), list) else []
    subs = subs_obj.get("items") if isinstance(subs_obj.get("items"), list) else []

    settings = _settings()
    city = settings.weather_city if settings else (os.getenv("WEATHER_CITY") or "Москва")
    lang = settings.default_lang if settings else "ru"
    news_profile = _load_news_profile(user_id)

    weather_panel, news_panel, market_panel, training_panel, trend_panel, signals_panel, stats_panel, calendar_panel, garage_panel = await asyncio.gather(
        _load_weather_panel(city, lang),
        _load_news_panel(news_profile, ai_enabled=(ai == 1)),
        _load_market_panel(),
        asyncio.to_thread(_training_panel, user_id),
        asyncio.to_thread(_trend_panel, user_id),
        _load_signals_panel(limit=20),
        _safe_async({}, asyncio.to_thread(_stats_panel, user_id), timeout_sec=4.5),
        _safe_async({}, asyncio.to_thread(_calendar_panel, tasks), timeout_sec=4.5),
        _safe_async({}, asyncio.to_thread(_garage_panel, user_id), timeout_sec=4.5),
    )

    ai_panel = (
        await _ai_brief(
            user_id=user_id,
            today=today,
            tasks=tasks,
            weather=weather_panel,
            training=training_panel,
            news=news_panel,
            trend=trend_panel,
        )
        if ai == 1
        else _rule_based_ai(
            today=today,
            tasks=tasks,
            weather=weather_panel,
            training=training_panel,
            news=news_panel,
            trend=trend_panel,
        )
    )

    ai_pack = await _build_ai_pack(
        user_id=user_id,
        today=today,
        tasks=tasks,
        weather=weather_panel,
        training=training_panel,
        market=market_panel,
        ai_panel=ai_panel,
        trend=trend_panel,
        ai_enabled=(ai == 1),
    )

    training_ai_layer = await _safe_async(
        {"ai_plan": "", "ai_coach": str(training_panel.get("ai_coach") or "")},
        _build_training_ai_layer(
            user_id=user_id,
            training_panel=training_panel if isinstance(training_panel, dict) else {},
            ai_enabled=(ai == 1),
        ),
        timeout_sec=18.0,
    )
    if isinstance(training_panel, dict) and isinstance(training_ai_layer, dict):
        training_panel["ai_plan"] = str(training_ai_layer.get("ai_plan") or "")
        if training_ai_layer.get("ai_coach"):
            training_panel["ai_coach"] = str(training_ai_layer.get("ai_coach") or "")

    # LLM-first text overlays with deterministic fallback values already resolved in ai_pack.
    if isinstance(weather_panel, dict):
        weather_panel["summary"] = str(ai_pack.get("weather_brief") or weather_panel.get("summary") or "")
        weather_panel["clothing"] = str(ai_pack.get("weather_clothing") or weather_panel.get("clothing") or "")
    if isinstance(training_panel, dict):
        training_panel["progressive_hint"] = str(ai_pack.get("training_hint") or training_panel.get("progressive_hint") or "")
    if isinstance(market_panel, dict):
        highlights = market_panel.get("highlights")
        existing = [str(x) for x in highlights] if isinstance(highlights, list) else []
        top_line = str(ai_pack.get("market_brief") or "").strip()
        market_panel["highlights"] = [top_line, *existing[:3]] if top_line else existing
    if isinstance(calendar_panel, dict):
        calendar_panel["year_goals"] = [
            str(ai_pack.get("growth_year") or "").strip(),
            str(ai_pack.get("growth_month") or "").strip(),
            str(ai_pack.get("growth_week") or "").strip(),
        ]

    events: list[dict[str, object]] = []
    if safe_debug == 1 and _debug_events_enabled():
        events.extend(today_events)
        events.extend(tasks_events)
        events.extend(subs_events)

    sections: dict[str, dict[str, object]] = {
        "today": _section_payload(today, as_of=generated_at, stale_after_sec=60),
        "tasks": _section_payload(tasks, as_of=generated_at, stale_after_sec=60),
        "subs": _section_payload(subs, as_of=generated_at, stale_after_sec=300),
        "market": _section_payload(market_panel, as_of=generated_at, stale_after_sec=300),
        "weather": _section_payload(weather_panel, as_of=generated_at, stale_after_sec=300),
        "news": _section_payload(news_panel, as_of=generated_at, stale_after_sec=600),
        "training": _section_payload(training_panel, as_of=generated_at, stale_after_sec=180),
        "trend": _section_payload(trend_panel, as_of=generated_at, stale_after_sec=300),
        "signals": _section_payload(signals_panel, as_of=generated_at, stale_after_sec=180),
        "stats": _section_payload(stats_panel, as_of=generated_at, stale_after_sec=180),
        "calendar": _section_payload(calendar_panel, as_of=generated_at, stale_after_sec=180),
        "garage": _section_payload(garage_panel, as_of=generated_at, stale_after_sec=180),
        "ai": _section_payload(ai_panel, as_of=generated_at, stale_after_sec=300),
        "ai_pack": _section_payload(ai_pack, as_of=generated_at, stale_after_sec=180),
        "assistant": _section_payload(
            {
                "name": "Gemma",
                "model": settings.ollama_model if settings else "",
            },
            as_of=generated_at,
            stale_after_sec=300,
        ),
        "events": _section_payload(events, as_of=generated_at, stale_after_sec=60),
    }

    response: dict[str, object] = {
        "meta": {
            "schema": "dashboard.v2",
            "generated_at": generated_at,
            "user_id": user_id,
            "timezone": os.getenv("TIMEZONE") or "local",
        },
        "sections": sections,
        # Backward compatibility for existing clients.
        "generated_at": generated_at,
        "user_id": user_id,
        "today": sections["today"]["data"],
        "tasks": sections["tasks"]["data"],
        "subs": sections["subs"]["data"],
        "market": sections["market"]["data"],
        "weather": sections["weather"]["data"],
        "news": sections["news"]["data"],
        "training": sections["training"]["data"],
        "trend": sections["trend"]["data"],
        "signals": sections["signals"]["data"],
        "stats": sections["stats"]["data"],
        "calendar": sections["calendar"]["data"],
        "garage": sections["garage"]["data"],
        "ai": sections["ai"]["data"],
        "ai_pack": sections["ai_pack"]["data"],
        "assistant": sections["assistant"]["data"],
        "events": sections["events"]["data"],
        "freshness": {key: value["freshness"] for key, value in sections.items()},
    }

    return response
