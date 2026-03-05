import asyncio
import json
import math
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from html import escape as html_escape
from typing import Awaitable
from urllib.parse import quote_plus
from uuid import uuid4

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from core.coordinator import handle_command
from db import (
    daily_checkin_get,
    daily_checkin_upsert,
    fitness_get_latest_session_for_user,
    fitness_get_latest_workout,
    fitness_workouts_count,
    get_cache_value,
    memory_delete,
    memory_list,
    memory_set,
    memory_timeline_list,
    ping_db,
    save_conversation_history,
    set_cache_value,
    subs_add,
    subs_delete,
    subs_due_within,
    subs_get,
    subs_update_next_date,
    todo_delete,
    todo_list_open,
    todo_mark_done,
    user_settings_get,
    user_settings_get_full,
    user_settings_set_confidence,
    user_settings_set_energy_autopilot,
    user_settings_set_mode,
)
from handlers.context import AppContext
from services.crypto_service import fetch_prices
from services.forex_service import fetch_usd_eur_to_rub
from services.fuel_service import fetch_fuel95_moscow_data
from services.http_service import ExternalAPIError, healthcheck_json
from services.llm_service import call_ollama
from services.messages import t
from services.routing import extract_command
from services.text_clean_service import normalize_display_text
from services.weather_service import clean_weather_summary, fetch_weather_summary, weather_emoji


HOME_COORDS = (55.688177, 37.865975)
WORK_COORDS = (55.468433, 37.576555)
MODE_VALUES = ("fast", "normal", "precise")
PERIOD_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}

LLM_GUIDED_COMMANDS = {
    "mission",
    "startnow",
    "simulate",
    "premortem",
    "negotiate",
    "life360",
    "goal",
    "drift",
    "futureme",
    "crisis",
    "manual",
    "decide",
    "rule",
    "radar",
    "state",
    "reflect",
    "export",
    "pro",
}


# Core-first command center overrides.
_COMMAND_CENTER_ROOT_TEXT = {
    "ru": "<b>Day OS Menu</b>\nCore-first navigation.",
    "en": "<b>Command Center</b>\nPick a section.",
}

_COMMAND_CENTER_ROOT_ROWS = {
    "ru": [
        [("Core / День", "cmd:center:core"), ("Advanced", "cmd:center:advanced")],
        [("Tools / Info", "cmd:center:tools")],
    ],
    "en": [
        [("Core / Day", "cmd:center:core"), ("Advanced", "cmd:center:advanced")],
        [("Tools / Info", "cmd:center:tools")],
    ],
}

_COMMAND_CENTER_SECTIONS = {
    "ru": {
        "core": (
            "<b>Core / День</b>\n"
            "<code>/today</code> старт дня\n"
            "<code>/todo</code> задачи\n"
            "<code>/focus</code> фокус-сессия\n"
            "<code>/checkin</code> фиксация дня\n"
            "<code>/week</code> обзор недели\n"
            "<code>/review week</code> weekly review\n"
            "<code>/decide</code> помощь с решением"
        ),
        "advanced": (
            "<b>Advanced</b>\n"
            "<code>/fit</code>, <code>/subs</code>, <code>/score</code>, <code>/plan</code>, <code>/session</code>\n"
            "<code>/settings</code>, <code>/mode</code>, <code>/confidence</code>\n"
            "<code>/weekly</code> - alias -> <code>/review week</code>"
        ),
        "tools": (
            "<b>Tools / Info</b>\n"
            "<code>/price</code>, <code>/weather</code>, <code>/digest</code>, <code>/route</code>, <code>/status</code>"
        ),
    },
    "en": {
        "core": (
            "<b>Core / Day</b>\n"
            "<code>/today</code> start day\n"
            "<code>/todo</code> tasks\n"
            "<code>/focus</code> focus session\n"
            "<code>/checkin</code> daily log\n"
            "<code>/week</code> week dashboard\n"
            "<code>/review week</code> weekly review\n"
            "<code>/decide</code> decision support"
        ),
        "advanced": (
            "<b>Advanced</b>\n"
            "<code>/fit</code>, <code>/subs</code>, <code>/score</code>, <code>/plan</code>, <code>/session</code>\n"
            "<code>/settings</code>, <code>/mode</code>, <code>/confidence</code>\n"
            "<code>/weekly</code> - alias -> <code>/review week</code>"
        ),
        "tools": (
            "<b>Tools / Info</b>\n"
            "<code>/price</code>, <code>/weather</code>, <code>/digest</code>, <code>/route</code>, <code>/status</code>"
        ),
    },
}

_TODO_PANEL_ROWS = {
    "ru": [
        [("Список", "cmd:todo:list"), ("Готово top", "cmd:todo:done_top")],
        [("Удалить top", "cmd:todo:del_top"), ("Как добавить", "cmd:todo:add_hint")],
    ],
    "en": [
        [("List", "cmd:todo:list"), ("Done top", "cmd:todo:done_top")],
        [("Delete top", "cmd:todo:del_top"), ("How to add", "cmd:todo:add_hint")],
    ],
}

_SUBS_PANEL_ROWS = {
    "ru": [
        [("Список", "cmd:subs:list"), ("Проверка", "cmd:subs:check")],
        [("Как добавить", "cmd:subs:add_hint")],
    ],
    "en": [
        [("List", "cmd:subs:list"), ("Check", "cmd:subs:check")],
        [("How to add", "cmd:subs:add_hint")],
    ],
}


def _lang_key(lang: str) -> str:
    return "ru" if lang == "ru" else "en"


def _callback_markup(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback_data) for text, callback_data in row]
            for row in rows
        ]
    )


def _command_center_root_text(lang: str) -> str:
    return _COMMAND_CENTER_ROOT_TEXT[_lang_key(lang)]


def _request_id() -> str:
    return uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cache_age_minutes(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return max(0, int((datetime.now() - dt).total_seconds() // 60))


def _is_cache_fresh(ts: str | None, *, ttl_minutes: int = 180) -> bool:
    age = _cache_age_minutes(ts)
    return age is not None and age <= ttl_minutes


def _fmt_change(change: float | None) -> str:
    if change is None:
        return "⚪️ н/д"
    value = float(change)
    icon = "🟢" if value > 0 else "🔴" if value < 0 else "⚪️"
    return f"{icon} {value:+.1f}%"


def _fitness_latest_note() -> str:
    row = fitness_get_latest_workout()
    if not row:
        return "нет данных"
    return f"#{int(row[0])} {str(row[1] or '').strip()} ({str(row[10] or '').replace('T', ' ')[:16]})"


def _fitness_latest_session_note(user_id: int) -> str:
    row = fitness_get_latest_session_for_user(user_id)
    if not row:
        return "нет сессий"
    workout_id = int(row[0])
    title = str(row[1] or "").strip()
    done_at = str(row[2] or "").replace("T", " ")[:16]
    rpe = row[3]
    if rpe is None:
        return f"#{workout_id} {title} ({done_at})"
    return f"#{workout_id} {title} ({done_at}, rpe={int(rpe)})"


async def _fitness_status(ctx: AppContext) -> tuple[bool, str]:
    count = fitness_workouts_count()
    if not ctx.settings.fitness_vault_chat_id or not ctx.settings.fitness_admin_user_id:
        return (True, "ready") if count == 0 else (True, "text-only")
    try:
        await ctx.bot.get_chat(ctx.settings.fitness_vault_chat_id)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, exc.__class__.__name__


def _profile_runtime_settings(ctx: AppContext, user_id: int) -> tuple[object, dict[str, object], str]:
    profile = user_settings_get_full(user_id) if user_id > 0 else {}
    lang = str(profile.get("lang") or ctx.settings.default_lang)
    timezone_name = str(profile.get("timezone_name") or ctx.settings.timezone_name) if (profile.get("timezone_name") or ctx.settings.timezone_name) else None
    weather_city = str(profile.get("weather_city") or ctx.settings.weather_city)
    runtime = replace(ctx.settings, default_lang=lang, timezone_name=timezone_name, weather_city=weather_city)
    return runtime, profile, lang


def _menu_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/today"), KeyboardButton(text="/todo"), KeyboardButton(text="/focus")],
            [KeyboardButton(text="/checkin"), KeyboardButton(text="/week"), KeyboardButton(text="/review week")],
            [KeyboardButton(text="/decide"), KeyboardButton(text="/menu"), KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
    )

def _command_center_root_markup(lang: str) -> InlineKeyboardMarkup:
    return _callback_markup(_COMMAND_CENTER_ROOT_ROWS[_lang_key(lang)])


def _command_center_section_text(section: str, lang: str) -> str:
    sections = _COMMAND_CENTER_SECTIONS[_lang_key(lang)]
    return sections.get(section, sections["core"])


def _command_center_section_markup(section: str, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if section == "core":
        rows.append([("TODO", "cmd:todo:list")])
    elif section == "advanced":
        rows.append(
            [
                ("/fit", "fit:menu:0"),
                ("/subs", "cmd:subs:list"),
            ]
        )
    rows.append([("Sections", "cmd:center:root")])
    return _callback_markup(rows)

def _route_markup(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=("🏠 Дом" if lang == "ru" else "🏠 Home"), url=f"https://yandex.ru/maps/?rtext=~{quote_plus(f'{HOME_COORDS[0]:.6f},{HOME_COORDS[1]:.6f}')}&rtt=auto"),
                InlineKeyboardButton(text=("🏢 Работа" if lang == "ru" else "🏢 Work"), url=f"https://yandex.ru/maps/?rtext=~{quote_plus(f'{WORK_COORDS[0]:.6f},{WORK_COORDS[1]:.6f}')}&rtt=auto"),
            ],
            [InlineKeyboardButton(text=("📍 Ввести адрес" if lang == "ru" else "📍 Enter address"), url="https://yandex.ru/maps/?rtext=~&rtt=auto")],
            [
                InlineKeyboardButton(text=("⏱ ETA Дом" if lang == "ru" else "⏱ ETA Home"), callback_data="route:eta:home"),
                InlineKeyboardButton(text=("⏱ ETA Работа" if lang == "ru" else "⏱ ETA Work"), callback_data="route:eta:work"),
            ],
        ]
    )


def _distance_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _estimate_eta_minutes(src_lat: float, src_lon: float, dst_lat: float, dst_lon: float) -> int:
    return max(5, int(round((_distance_km(src_lat, src_lon, dst_lat, dst_lon) / 32.0) * 60)))


def _cache_get_json(key: str) -> tuple[dict[str, object] | None, str | None]:
    row = get_cache_value(key)
    if not row or not row[0]:
        return None, None
    try:
        value = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None, row[1]
    if not isinstance(value, dict):
        return None, row[1]
    return value, row[1]


def _cache_set_json(key: str, value: dict[str, object]) -> None:
    set_cache_value(key, json.dumps(value, ensure_ascii=False), _now_iso())


def _trim_text(value: str, max_len: int = 90) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _advance_sub_date(current_iso: str, period: str, steps: int) -> str | None:
    try:
        current = date.fromisoformat(current_iso)
    except ValueError:
        return None
    days = PERIOD_DAYS.get((period or "").strip().lower())
    if not days:
        return None
    return (current + timedelta(days=days * max(1, steps))).isoformat()


def _domain_command(user_id: int, command: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = payload or {}
    try:
        return handle_command(user_id, command, data)
    except ValueError:
        if command == "tasks:done":
            todo_id = int(data.get("task_id") or 0)
            done_at = str(data.get("done_at") or _now_iso())
            return {"ok": bool(todo_mark_done(user_id=user_id, todo_id=todo_id, done_at=done_at))}
        if command == "tasks:delete":
            todo_id = int(data.get("task_id") or 0)
            return {"ok": bool(todo_delete(user_id=user_id, todo_id=todo_id))}
        if command == "subs:add":
            name = str(data.get("name") or "").strip()
            next_date = str(data.get("next_date") or "").strip()
            period = str(data.get("period") or "").strip().lower()
            created_at = str(data.get("created_at") or _now_iso())
            if not name or not next_date or period not in PERIOD_DAYS:
                raise
            return {
                "id": int(
                    subs_add(
                        user_id=user_id,
                        name=name,
                        next_date=next_date,
                        period=period,
                        created_at=created_at,
                    )
                )
            }
        if command == "subs:delete":
            sub_id = int(data.get("sub_id") or 0)
            return {"ok": bool(subs_delete(user_id=user_id, sub_id=sub_id))}
        if command == "subs:roll":
            sub_id = int(data.get("sub_id") or 0)
            steps = int(data.get("steps") or 1)
            updated_at = str(data.get("updated_at") or _now_iso())
            row = subs_get(user_id=user_id, sub_id=sub_id)
            if not row:
                return {"ok": False, "reason": "not_found"}
            new_date = _advance_sub_date(str(row[2] or ""), str(row[3] or ""), steps)
            if not new_date:
                return {"ok": False, "reason": "bad_date"}
            ok = subs_update_next_date(user_id=user_id, sub_id=sub_id, next_date=new_date, updated_at=updated_at)
            return {"ok": bool(ok), "new_date": (new_date if ok else None), "reason": ("update_failed" if not ok else None)}
        raise


def _todo_render(user_id: int, lang: str) -> str:
    try:
        data = _domain_command(user_id, "tasks:list", {"limit": 20})
    except ValueError:
        return t(lang, "error_generic")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return t(lang, "todo_empty")
    lines = [t(lang, "todo_list_title")]
    for item in items:
        if not isinstance(item, dict):
            continue
        todo_id = int(item.get("id", 0))
        text = str(item.get("text", ""))
        lines.append(f"{todo_id}. {_trim_text(text, 84)}")
    return "\n".join(lines) if len(lines) > 1 else t(lang, "todo_empty")


def render_tasks_text(user_id: int, lang: str) -> str:
    """Compatibility alias used by smoke tests and legacy call sites."""
    return _todo_render(user_id, lang)


def _todo_markup(lang: str) -> InlineKeyboardMarkup:
    return _callback_markup(_TODO_PANEL_ROWS[_lang_key(lang)])


def _subs_markup(lang: str) -> InlineKeyboardMarkup:
    return _callback_markup(_SUBS_PANEL_ROWS[_lang_key(lang)])


def _render_subs_list(user_id: int, lang: str) -> str:
    try:
        data = _domain_command(user_id, "subs:list")
    except ValueError:
        return t(lang, "error_generic")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return t(lang, "subs_empty")
    today = date.today()
    lines = [t(lang, "subs_list_title")]
    for item in items:
        if not isinstance(item, dict):
            continue
        sub_id = int(item.get("id", 0))
        name = _trim_text(str(item.get("name", "")), 42)
        next_date = str(item.get("next_date", ""))
        period = str(item.get("period", ""))
        try:
            due = date.fromisoformat(next_date)
            delta = (due - today).days
            if delta >= 0:
                left = f"{delta} дн." if lang == "ru" else f"{delta}d"
            else:
                late = abs(delta)
                left = f"просрочено {late} дн." if lang == "ru" else f"overdue {late}d"
        except ValueError:
            left = next_date
        lines.append(f"#{sub_id} {name} — {next_date} ({period}, {left})")
    return "\n".join(lines) if len(lines) > 1 else t(lang, "subs_empty")


def render_subs_list_text(user_id: int, lang: str) -> str:
    """Compatibility alias used by smoke tests and legacy call sites."""
    return _render_subs_list(user_id, lang)


def _render_subs_check(user_id: int, lang: str) -> str:
    rows = subs_due_within(user_id=user_id, days=7)
    title = t(lang, "subs_check_title")
    if not rows:
        no_due = "Критичных списаний в ближайшие 7 дней нет." if lang == "ru" else "No due subscriptions in next 7 days."
        return f"{title}\n\n{no_due}"
    today = date.today()
    lines = [title]
    for sub_id, name, next_date, period in rows:
        next_date_str = str(next_date or "")
        try:
            due = date.fromisoformat(next_date_str)
            delta = (due - today).days
            days_text = f"{delta} дн." if lang == "ru" else f"{delta}d"
        except ValueError:
            days_text = next_date_str
        lines.append(f"#{int(sub_id)} {_trim_text(str(name or ''), 42)} — {next_date_str} ({str(period or '')}, {days_text})")
    return "\n".join(lines)


def _route_target(user_id: int) -> str | None:
    row = get_cache_value(f"route:eta:target:{user_id}")
    if not row or not row[0]:
        return None
    target = str(row[0]).strip().lower()
    return target if target in {"home", "work"} else None


def _set_route_target(user_id: int, target: str) -> None:
    set_cache_value(f"route:eta:target:{user_id}", target, _now_iso())


def _clear_route_target(user_id: int) -> None:
    set_cache_value(f"route:eta:target:{user_id}", "", _now_iso())


def _route_location_markup(lang: str) -> ReplyKeyboardMarkup:
    cancel_label = "Отмена ETA" if lang == "ru" else "Cancel ETA"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 " + ("Отправить геолокацию" if lang == "ru" else "Send location"), request_location=True)],
            [KeyboardButton(text=cancel_label)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _parse_checkin_payload(payload: str) -> tuple[str, str, int | None] | None:
    done_text = ""
    carry_text = ""
    energy: int | None = None
    recognized = False
    normalized = (payload or "").replace("\n", ";")
    for raw_part in normalized.split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"done", "сделал"}:
            recognized = True
            done_text = value
        elif key in {"carry", "перенос"}:
            recognized = True
            carry_text = value
        elif key in {"energy", "энергия"}:
            recognized = True
            try:
                parsed = int(value)
            except ValueError:
                return None
            if not (1 <= parsed <= 10):
                return None
            energy = parsed
    if not recognized:
        return None
    if not done_text and not carry_text and energy is None:
        return None
    return done_text, carry_text, energy


async def _send_command_center(message: types.Message, lang: str) -> None:
    await message.reply(
        _command_center_root_text(lang),
        parse_mode="HTML",
        reply_markup=_command_center_root_markup(lang),
    )


async def _edit_or_reply(
    callback: types.CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    if not callback.message:
        return
    try:
        if parse_mode:
            await callback.message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:  # noqa: BLE001
        if parse_mode:
            await callback.message.reply(text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            await callback.message.reply(text, reply_markup=reply_markup)


async def _reply_todo(message: types.Message, user_id: int, lang: str, *, prefix: str | None = None) -> None:
    text = render_tasks_text(user_id, lang)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await message.reply(text, reply_markup=_todo_markup(lang))


async def _reply_subs_list(message: types.Message, user_id: int, lang: str, *, prefix: str | None = None) -> None:
    text = render_subs_list_text(user_id, lang)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await message.reply(text, reply_markup=_subs_markup(lang))


def build_commands_router(ctx: AppContext) -> Router:
    router = Router(name="commands")
    router.message.filter(F.chat.type == "private")

    @router.message(Command("start"))
    async def start_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        row = get_cache_value(f"user:start_seen:{uid}")
        seen = bool(row and row[0] == "1")
        await message.reply(t(lang, "start_back") if seen else t(lang, "start_welcome"), parse_mode="HTML", reply_markup=_menu_markup())
        if uid > 0 and not seen:
            set_cache_value(f"user:start_seen:{uid}", "1", _now_iso())

    @router.message(Command("menu"))
    async def menu_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        await message.reply(t(lang, "menu_enabled"), parse_mode="HTML", reply_markup=_menu_markup())
        await _send_command_center(message, lang)

    @router.message(Command("help"))
    async def help_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        await message.reply(t(lang, "help"), parse_mode="HTML", disable_web_page_preview=True)

    @router.message(Command("reset"))
    async def reset_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        if uid > 0:
            save_conversation_history(uid, [])
        await message.reply(t(lang, "history_reset"))

    @router.message(Command("clean"))
    async def clean_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        deleted = 0
        if message.chat and message.message_id:
            for msg_id in range(message.message_id, max(1, message.message_id - 250), -1):
                try:
                    await ctx.bot.delete_message(message.chat.id, msg_id)
                    deleted += 1
                except Exception:  # noqa: BLE001
                    continue
        if uid > 0:
            save_conversation_history(uid, [])
        await message.answer(t(lang, "clean_result", count=deleted) if deleted else t(lang, "clean_result_none"), reply_markup=_menu_markup())

    @router.message(Command("price"))
    async def price_cmd(message: types.Message) -> None:
        rid = _request_id()
        uid = message.from_user.id if message.from_user else 0
        runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        ctx.logger.info("event=command name=price request_id=%s user_id=%s", rid, uid)

        async def _timed(coro: Awaitable[object]) -> object:
            try:
                return await asyncio.wait_for(coro, timeout=6.5)
            except Exception as exc:  # noqa: BLE001
                return exc

        cg, fx, fuel = await asyncio.gather(
            _timed(fetch_prices(runtime.coingecko_vs)),
            _timed(fetch_usd_eur_to_rub()),
            _timed(fetch_fuel95_moscow_data(runtime)),
        )

        cg_cached, _ = _cache_get_json("price_cache:coingecko")
        fx_cached, _ = _cache_get_json("price_cache:fx")
        fuel_cached, _ = _cache_get_json("price_cache:fuel95")

        if isinstance(cg, Exception):
            cg = cg_cached or cg
        if isinstance(fx, Exception):
            fx = fx_cached or fx
        if isinstance(fuel, Exception):
            fuel = fuel_cached or fuel

        lines: list[str] = []
        errs: list[str] = []
        if not isinstance(cg, Exception):
            btc = cg.get("bitcoin", {})
            eth = cg.get("ethereum", {})
            code = runtime.coingecko_vs.upper()
            lines.append(f"{t(lang, 'market_btc')}: {code} {float(btc.get(runtime.coingecko_vs, 0)):.2f} | 24ч {_fmt_change(btc.get(f'{runtime.coingecko_vs}_24h_change'))}")
            lines.append(f"{t(lang, 'market_eth')}: {code} {float(eth.get(runtime.coingecko_vs, 0)):.2f} | 24ч {_fmt_change(eth.get(f'{runtime.coingecko_vs}_24h_change'))}")
            _cache_set_json("price_cache:coingecko", cg)
        else:
            errs.append("CoinGecko")
        if not isinstance(fx, Exception):
            lines.append(f"{t(lang, 'market_usd_rub')}: RUB {float(fx.get('usd_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('usd_rub_24h_change'))}")
            lines.append(f"{t(lang, 'market_eur_rub')}: RUB {float(fx.get('eur_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('eur_rub_24h_change'))}")
            _cache_set_json("price_cache:fx", fx)
        else:
            errs.append("FX")
        if not isinstance(fuel, Exception):
            lines.append(f"{t(lang, 'market_fuel95')}: RUB {float(fuel.get('price_rub') or 0):.2f} | 24ч {_fmt_change(fuel.get('change_24h_pct'))}")
            _cache_set_json("price_cache:fuel95", fuel)
        else:
            errs.append("Fuel95")
        if not lines:
            await message.reply(t(lang, "prices_error"))
            return
        text = "\n".join(lines)
        if errs:
            text += f"\n\n{t(lang, 'prices_partial_unavailable', services='/'.join(errs))}"
        await message.reply(normalize_display_text(text))

    @router.message(Command("weather"))
    async def weather_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        cached_summary = None
        cached, _cached_ts = _cache_get_json("weather_cache:summary")
        if cached:
            raw_cached = str(cached.get("summary") or "").strip()
            cached_summary = clean_weather_summary(raw_cached) or None
            if cached_summary and cached_summary != raw_cached:
                _cache_set_json("weather_cache:summary", {"summary": cached_summary})
        try:
            summary = clean_weather_summary(
                await asyncio.wait_for(fetch_weather_summary(runtime.weather_city, lang), timeout=6.5)
            )
            await message.reply(f"{weather_emoji(summary)} {summary}")
            _cache_set_json("weather_cache:summary", {"summary": summary})
        except ExternalAPIError:
            if cached_summary:
                await message.reply(f"{weather_emoji(cached_summary)} {cached_summary}")
            else:
                await message.reply(t(lang, "weather_error"))
        except asyncio.TimeoutError:
            if cached_summary:
                await message.reply(f"{weather_emoji(cached_summary)} {cached_summary}")
            else:
                await message.reply(t(lang, "weather_error"))

    @router.message(Command("status"))
    async def status_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        db_ok, _ = ping_db()
        fit_ok, fit_note = await _fitness_status(ctx)
        ollama_ok, _ = await healthcheck_json(service="ollama", method="GET", url=runtime.ollama_api_url.replace("/api/generate", "/api/tags"), timeout=4.5, retries=0)
        cg_ok, _ = await healthcheck_json(service="coingecko", method="GET", url="https://api.coingecko.com/api/v3/ping", timeout=4.5, retries=0)
        cbr_ok, _ = await healthcheck_json(service="cbr", method="GET", url="https://www.cbr-xml-daily.ru/daily_json.js", timeout=4.5, retries=0)
        price_row = get_cache_value("price_cache:coingecko")
        weather_row = get_cache_value("weather_cache:summary")
        def dot(ok: bool) -> str:
            return "🟢" if ok else "🔴"

        lines = [
            t(lang, "status_title"),
            "",
            f"{dot(ollama_ok)} LLM",
            f"{dot(cg_ok)} CoinGecko",
            f"{dot(cbr_ok)} CBR FX",
            f"{dot(db_ok)} DB",
            f"{dot(fit_ok)} Fitness ({fit_note})",
            "",
            (
                f"Кэш: рынок {'свежий' if _is_cache_fresh(price_row[1] if price_row else None) else 'нет'}, погода {'свежая' if _is_cache_fresh(weather_row[1] if weather_row else None) else 'нет'}"
                if lang == "ru"
                else f"Cache: market {'fresh' if _is_cache_fresh(price_row[1] if price_row else None) else 'none'}, weather {'fresh' if _is_cache_fresh(weather_row[1] if weather_row else None) else 'none'}"
            ),
        ]
        await message.reply("\n".join(lines), parse_mode="HTML")

    @router.message(Command("route"))
    async def route_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        await message.reply(t(lang, "route_intro"), parse_mode="HTML", reply_markup=_route_markup(lang))

    @router.callback_query(F.data.startswith("route:eta:"))
    async def route_eta_callback(callback: types.CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        target = (callback.data or "").split(":")[-1].strip().lower()
        if target not in {"home", "work"}:
            await callback.answer(t(lang, "digest_bad_format"), show_alert=False)
            return
        _set_route_target(uid, target)
        await callback.message.reply(
            t(lang, "route_eta_ask_location"),
            reply_markup=_route_location_markup(lang),
        )
        await callback.answer(t(lang, "done_short"), show_alert=False)

    @router.callback_query(F.data.startswith("cmd:center:"))
    async def command_center_callback(callback: types.CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        section = (callback.data or "").split(":")[-1].strip().lower()
        if section == "root":
            text = _command_center_root_text(lang)
            markup = _command_center_root_markup(lang)
        else:
            text = _command_center_section_text(section, lang)
            markup = _command_center_section_markup(section, lang)
        await _edit_or_reply(callback, text, parse_mode="HTML", reply_markup=markup)
        await callback.answer("", show_alert=False)

    @router.message(F.location)
    async def route_eta_location(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        target = _route_target(uid)
        if target not in {"home", "work"}:
            return
        if not message.location:
            await message.reply(t(lang, "route_eta_failed"), reply_markup=ReplyKeyboardRemove())
            return

        dst_lat, dst_lon = HOME_COORDS if target == "home" else WORK_COORDS
        eta_min = _estimate_eta_minutes(
            src_lat=float(message.location.latitude),
            src_lon=float(message.location.longitude),
            dst_lat=dst_lat,
            dst_lon=dst_lon,
        )
        title = "Дом" if (target == "home" and lang == "ru") else "Работа" if lang == "ru" else "Home" if target == "home" else "Work"
        await message.reply(
            t(lang, "route_eta_done", title=title, minutes=eta_min),
            reply_markup=ReplyKeyboardRemove(),
        )
        _clear_route_target(uid)

    @router.message(F.text.in_({"Отмена ETA", "Cancel ETA"}))
    async def route_eta_cancel(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        _clear_route_target(uid)
        await message.reply(t(lang, "route_eta_cleared"), reply_markup=ReplyKeyboardRemove())

    @router.callback_query(F.data.startswith("cmd:todo:"))
    async def todo_panel_callback(callback: types.CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        action = (callback.data or "").split(":")[-1].strip().lower()
        panel = _todo_markup(lang)

        if action == "list":
            text = render_tasks_text(uid, lang)
            await _edit_or_reply(callback, text, reply_markup=panel)
            await callback.answer("", show_alert=False)
            return

        if action == "done_top":
            rows = todo_list_open(user_id=uid, limit=1)
            if not rows:
                await callback.answer(t(lang, "todo_empty"), show_alert=False)
                return
            todo_id = int(rows[0][0])
            try:
                _domain_command(uid, "tasks:done", {"task_id": todo_id, "done_at": _now_iso()})
            except ValueError:
                await callback.answer(t(lang, "error_generic"), show_alert=False)
                return
            text = f"{t(lang, 'todo_done', todo_id=todo_id)}\n\n{render_tasks_text(uid, lang)}"
            await _edit_or_reply(callback, text, reply_markup=panel)
            await callback.answer(t(lang, "done_short"), show_alert=False)
            return

        if action == "del_top":
            rows = todo_list_open(user_id=uid, limit=1)
            if not rows:
                await callback.answer(t(lang, "todo_empty"), show_alert=False)
                return
            todo_id = int(rows[0][0])
            try:
                _domain_command(uid, "tasks:delete", {"task_id": todo_id})
            except ValueError:
                await callback.answer(t(lang, "error_generic"), show_alert=False)
                return
            text = f"{t(lang, 'todo_deleted', todo_id=todo_id)}\n\n{render_tasks_text(uid, lang)}"
            await _edit_or_reply(callback, text, reply_markup=panel)
            await callback.answer(t(lang, "done_short"), show_alert=False)
            return

        if action == "add_hint":
            hint = "/todo add <текст>" if lang == "ru" else "/todo add <text>"
            if callback.message:
                await callback.message.reply(hint, reply_markup=panel)
            await callback.answer("", show_alert=False)
            return

        await callback.answer("", show_alert=False)

    @router.callback_query(F.data.startswith("cmd:subs:"))
    async def subs_panel_callback(callback: types.CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        action = (callback.data or "").split(":")[-1].strip().lower()
        panel = _subs_markup(lang)

        if action == "list":
            text = render_subs_list_text(uid, lang)
            await _edit_or_reply(callback, text, reply_markup=panel)
            await callback.answer("", show_alert=False)
            return

        if action == "check":
            text = _render_subs_check(uid, lang)
            await _edit_or_reply(callback, text, reply_markup=panel)
            await callback.answer("", show_alert=False)
            return

        if action == "add_hint":
            hint = (
                "/subs add <name> <YYYY-MM-DD> <monthly|weekly|yearly|quarterly>"
                if lang == "ru"
                else "/subs add <name> <YYYY-MM-DD> <monthly|weekly|yearly|quarterly>"
            )
            if callback.message:
                await callback.message.reply(hint, reply_markup=panel)
            await callback.answer("", show_alert=False)
            return

        await callback.answer("", show_alert=False)

    @router.message(F.text.regexp(r"^/(mode|confidence|settings|autopilot|todo|subs|checkin|remember|forget|profile|timeline)(?:@\w+)?(?:\s|$)"))
    async def basic_text_cmds(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        runtime, profile, lang = _profile_runtime_settings(ctx, uid)
        raw = (message.text or "").strip()
        parts = raw.split(maxsplit=2)
        cmd = extract_command(raw) or ""
        if cmd == "autopilot":
            arg = parts[1].lower() if len(parts) > 1 else ("on" if bool(profile.get("energy_autopilot", True)) else "off")
            if arg in {"on", "off"}:
                user_settings_set_energy_autopilot(user_id=uid, enabled=(arg == "on"), updated_at=_now_iso())
                if lang == "ru":
                    await message.reply(f"Энерго-автопилот: {'вкл' if arg == 'on' else 'выкл'}")
                else:
                    await message.reply(f"Energy autopilot: {arg}")
            else:
                await message.reply("Формат: /autopilot on|off" if lang == "ru" else "Format: /autopilot on|off")
            return
        if cmd == "mode":
            if len(parts) == 1:
                mode, _show = user_settings_get(uid)
                await message.reply(t(lang, "mode_show", mode=mode))
                return
            mode = parts[1].lower()
            if mode not in MODE_VALUES:
                await message.reply(t(lang, "mode_help"))
                return
            user_settings_set_mode(user_id=uid, mode=mode, updated_at=_now_iso())
            await message.reply(t(lang, "mode_set", mode=mode))
            return
        if cmd == "confidence":
            if len(parts) == 1:
                await message.reply(t(lang, "confidence_show", state=("on" if bool(profile.get("show_confidence")) else "off")))
                return
            value = parts[1].lower()
            if value not in {"on", "off"}:
                await message.reply(t(lang, "confidence_help"))
                return
            user_settings_set_confidence(user_id=uid, show_confidence=(value == "on"), updated_at=_now_iso())
            await message.reply(t(lang, "confidence_set", state=value))
            return
        # Keep these commands concise and deterministic.
        if cmd == "settings":
            await message.reply("\n".join([("<b>Настройки</b>" if lang == "ru" else "<b>Settings</b>"), "", f"Mode: <code>{html_escape(str(profile.get('llm_mode') or 'normal'))}</code>", f"Confidence: <code>{'on' if bool(profile.get('show_confidence')) else 'off'}</code>", f"Weather city: <code>{html_escape(str(profile.get('weather_city') or runtime.weather_city))}</code>"]), parse_mode="HTML")
            return
        if cmd == "todo":
            if len(parts) == 1:
                await _reply_todo(message, uid, lang)
                return
            sub = parts[1].lower()
            if sub == "list":
                await _reply_todo(message, uid, lang)
                return
            if sub == "add":
                payload = raw.split(maxsplit=2)
                text_payload = payload[2].strip() if len(payload) > 2 else ""
                if not text_payload:
                    await message.reply(t(lang, "todo_bad_format"))
                    return
                try:
                    result = _domain_command(uid, "tasks:add", {"text": text_payload, "created_at": _now_iso()})
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                todo_id = int(result.get("id", 0))
                await _reply_todo(message, uid, lang, prefix=t(lang, "todo_added", todo_id=todo_id))
                return
            if sub == "done":
                payload = raw.split(maxsplit=2)
                value = payload[2].strip() if len(payload) > 2 else ""
                if not value.isdigit():
                    await message.reply(t(lang, "todo_bad_format"))
                    return
                todo_id = int(value)
                try:
                    result = _domain_command(uid, "tasks:done", {"task_id": todo_id, "done_at": _now_iso()})
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                ok = bool(result.get("ok"))
                await _reply_todo(
                    message,
                    uid,
                    lang,
                    prefix=(t(lang, "todo_done", todo_id=todo_id) if ok else t(lang, "todo_not_found", todo_id=todo_id)),
                )
                return
            if sub in {"del", "delete"}:
                payload = raw.split(maxsplit=2)
                value = payload[2].strip() if len(payload) > 2 else ""
                if not value.isdigit():
                    await message.reply(t(lang, "todo_bad_format"))
                    return
                todo_id = int(value)
                try:
                    result = _domain_command(uid, "tasks:delete", {"task_id": todo_id})
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                ok = bool(result.get("ok"))
                await _reply_todo(
                    message,
                    uid,
                    lang,
                    prefix=(t(lang, "todo_deleted", todo_id=todo_id) if ok else t(lang, "todo_not_found", todo_id=todo_id)),
                )
                return
            await message.reply(t(lang, "todo_bad_format"))
            return
        if cmd == "subs":
            if len(parts) == 1:
                await _reply_subs_list(message, uid, lang)
                return
            sub = parts[1].lower()
            if sub == "list":
                await _reply_subs_list(message, uid, lang)
                return
            if sub == "check":
                await message.reply(_render_subs_check(uid, lang), reply_markup=_subs_markup(lang))
                return
            if sub == "add":
                payload = raw.split(maxsplit=2)
                args_text = payload[2].strip() if len(payload) > 2 else ""
                m = re.match(r"^(.+)\s+(\d{4}-\d{2}-\d{2})\s+(weekly|monthly|quarterly|yearly)$", args_text, flags=re.IGNORECASE)
                if not m:
                    await message.reply(t(lang, "subs_help"))
                    return
                name = m.group(1).strip()
                date_raw = m.group(2).strip()
                period = m.group(3).strip().lower()
                try:
                    date.fromisoformat(date_raw)
                except ValueError:
                    await message.reply(t(lang, "subs_bad_date"))
                    return
                if period not in PERIOD_DAYS:
                    await message.reply(t(lang, "subs_bad_period"))
                    return
                try:
                    result = _domain_command(
                        uid,
                        "subs:add",
                        {"name": name, "next_date": date_raw, "period": period, "created_at": _now_iso()},
                    )
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                sub_id = int(result.get("id", 0))
                await _reply_subs_list(message, uid, lang, prefix=t(lang, "subs_added", sub_id=sub_id))
                return
            if sub == "del":
                payload = raw.split(maxsplit=2)
                value = payload[2].strip() if len(payload) > 2 else ""
                if not value.isdigit():
                    await message.reply(t(lang, "subs_help"))
                    return
                sub_id = int(value)
                try:
                    result = _domain_command(uid, "subs:delete", {"sub_id": sub_id})
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                ok = bool(result.get("ok"))
                await _reply_subs_list(
                    message,
                    uid,
                    lang,
                    prefix=(t(lang, "subs_deleted", sub_id=sub_id) if ok else t(lang, "subs_not_found")),
                )
                return
            if sub == "roll":
                payload = raw.split(maxsplit=3)
                if len(payload) < 3 or not payload[2].strip().isdigit():
                    await message.reply(t(lang, "subs_help"))
                    return
                sub_id = int(payload[2].strip())
                steps = int(payload[3].strip()) if len(payload) > 3 and payload[3].strip().isdigit() else 1
                try:
                    result = _domain_command(uid, "subs:roll", {"sub_id": sub_id, "steps": steps, "updated_at": _now_iso()})
                except ValueError:
                    await message.reply(t(lang, "error_generic"))
                    return
                if str(result.get("reason") or "") == "not_found":
                    await message.reply(t(lang, "subs_not_found"))
                    return
                new_date = str(result.get("new_date") or "")
                if not new_date:
                    await message.reply(t(lang, "subs_bad_date"))
                    return
                await _reply_subs_list(
                    message,
                    uid,
                    lang,
                    prefix=t(lang, "subs_rolled", sub_id=sub_id, date=new_date),
                )
                return
            await message.reply(t(lang, "subs_help"))
            return
        if cmd == "checkin":
            if len(parts) == 1:
                await message.reply(t(lang, "checkin_help"))
                return
            if parts[1].lower() == "show":
                row = daily_checkin_get(user_id=uid, check_date=date.today().isoformat())
                if not row:
                    await message.reply(t(lang, "checkin_empty"))
                else:
                    await message.reply(t(lang, "checkin_show", date=date.today().isoformat(), done=str(row[0] or "-"), carry=str(row[1] or "-"), energy=row[2] if row[2] is not None else "-"))
                return
            payload = raw.split(maxsplit=1)[1].strip()
            parsed = _parse_checkin_payload(payload)
            if not parsed:
                await message.reply(t(lang, "checkin_bad_format"))
                return
            done_text, carry_text, energy = parsed
            today_iso = date.today().isoformat()
            now_iso = _now_iso()
            daily_checkin_upsert(
                user_id=uid,
                check_date=today_iso,
                done_text=done_text,
                carry_text=carry_text,
                energy=energy,
                created_at=now_iso,
                updated_at=now_iso,
            )
            await message.reply(t(lang, "checkin_saved"))
            return
        if cmd == "remember":
            payload = raw.split(maxsplit=1)[1].strip() if len(raw.split(maxsplit=1)) > 1 else ""
            if "=" not in payload:
                await message.reply(t(lang, "remember_help"))
                return
            key, value = payload.split("=", 1)
            key, value = key.strip(), value.strip()
            if not key or not value:
                await message.reply(t(lang, "remember_help"))
                return
            memory_set(user_id=uid, key=key, value=value, updated_at=_now_iso())
            await message.reply(t(lang, "remember_saved", key=html_escape(key)), parse_mode="HTML")
            return
        if cmd == "forget":
            key = parts[1].strip() if len(parts) > 1 else ""
            if not key:
                await message.reply(t(lang, "forget_help"))
                return
            ok = memory_delete(user_id=uid, key=key)
            await message.reply(t(lang, "forget_done", key=html_escape(key)) if ok else t(lang, "forget_not_found", key=html_escape(key)), parse_mode="HTML")
            return
        if cmd == "profile":
            rows = memory_list(user_id=uid, limit=20)
            if not rows:
                await message.reply(f"{t(lang, 'profile_title')}\n\n{t(lang, 'profile_empty')}", parse_mode="HTML")
            else:
                await message.reply("\n".join([t(lang, "profile_title"), ""] + [f"• <b>{html_escape(k)}</b>: {html_escape(v)}" for k, v, _ in rows]), parse_mode="HTML")
            return
        if cmd == "timeline": 
            rows = memory_timeline_list(user_id=uid, limit=25)
            if not rows:
                await message.reply("Пока пусто." if lang == "ru" else "No timeline entries yet.")
            else:
                lines = ["<b>Memory Timeline</b>", ""] + [f"{'✅' if bool(vf) else '▫️'} <b>{html_escape(str(k))}</b>: {html_escape(str(v))} (<code>{html_escape(str(ts))}</code>, conf={float(cf):.2f})" for k, v, vf, cf, ts in rows]
                await message.reply("\n".join(lines), parse_mode="HTML")

    @router.message(Command("weekly"))
    async def weekly_alias_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        if lang == "ru":
            text = "Weekly путь обновлен: используйте /week для обзора и /review week для weekly review."
        else:
            text = "Weekly flow updated: use /week for dashboard and /review week for weekly review."
        await message.reply(text)

    @router.message(F.text.regexp(r"^/(mission|startnow|simulate|premortem|negotiate|life360|goal|drift|futureme|crisis|manual|decide|rule|radar|state|reflect|export|pro)(?:@\w+)?(?:\s|$)"))
    async def llm_guided_cmd(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        runtime, profile, lang = _profile_runtime_settings(ctx, uid)
        mode = str(profile.get("llm_mode") or "normal")
        text = (message.text or "").strip()
        cmd = extract_command(text) or ""
        args = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        prompt = (
            "You are an execution-focused personal AI assistant. Respond concise and practical.\n\n"
            f"Language: {'Russian' if lang == 'ru' else 'English'}\n"
            f"Command: /{cmd}\n"
            f"User input: {args or '(none)'}\n\n"
            "Output:\n1) Goal\n2) 3-step plan\n3) Next action in <=10 minutes"
        )
        try:
            answer = await call_ollama(prompt, runtime, mode=mode, profile="advisor")
            await message.reply(answer)
        except ExternalAPIError:
            await message.reply(t(lang, "llm_unavailable"))

    @router.message(F.text.regexp(r"^/[^\s]+"))
    async def known_fallback(message: types.Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        _runtime, _profile, lang = _profile_runtime_settings(ctx, uid)
        cmd = extract_command((message.text or "").strip())
        if not cmd or cmd not in ctx.known_commands:
            return
        await message.reply("Команда доступна в меню /help." if lang == "ru" else "Command is available in /help.")

    return router
