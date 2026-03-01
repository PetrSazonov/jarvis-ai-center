from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    automation_rule_add,
    daily_checkin_get,
    daily_checkin_recent,
    daily_checkin_upsert,
    fitness_current_streak_days,
    fitness_stats_recent,
    focus_session_finish,
    focus_session_start,
    get_cache_value,
    memory_get,
    memory_set,
    set_cache_value,
    todo_add,
    todo_list_open,
    todo_mark_done,
    todo_stats_recent,
    user_settings_get_full,
)
from handlers.context import AppContext
from services.digest_service import safe_build_digest_render
from services.fitness_plan_service import pick_workout_of_day
from services.gamification_service import (
    build_arena_text,
    build_boss_battle_status,
    build_boss_text,
    build_cinematic_weekly_recap,
    build_rescue_quest_text,
    mark_rescue_completed,
    rescue_completed_today,
    rescue_needed_today,
)
from services.ux_service import (
    WeekPlaybackMetrics,
    build_digest_story_screens,
    build_week_playback_screens,
    digest_story_nav,
    sprint_done_markup,
    today_panel_markup,
    week_story_nav,
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cache_json_get(key: str) -> dict | None:
    row = get_cache_value(key)
    if not row or not row[0]:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _cache_json_set(key: str, payload: dict) -> None:
    set_cache_value(key, json.dumps(payload, ensure_ascii=False), _now_iso())


def _cache_text_get(key: str) -> str:
    row = get_cache_value(key)
    return str(row[0]) if row and row[0] else ""


def _trim(value: str, limit: int = 64) -> str:
    clean = " ".join((value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _today_replan_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ Жесткий", callback_data="ux:today:apply:hard"),
                InlineKeyboardButton(text="🫶 Мягкий", callback_data="ux:today:apply:soft"),
            ]
        ]
    )


def _rescue_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Засчитано", callback_data="ux:rescue:done:1")]]
    )


def _digest_key(user_id: int) -> str:
    return f"ux:digest:{user_id}"


def _week_key(user_id: int) -> str:
    return f"ux:week:{user_id}"


def _last_user_key(user_id: int) -> str:
    return f"ux:last_user:{user_id}"


def _last_assistant_key(user_id: int) -> str:
    return f"ux:last_assistant:{user_id}"


def _sprint_ack_key(focus_id: int) -> str:
    return f"ux:sprint:ack:{focus_id}"


def _nudge_counter_key(user_id: int) -> str:
    return f"ux:nudge:{user_id}:{date.today().isoformat()}"


def _session_label(session_name: str) -> str:
    value = (session_name or "work").strip().lower()
    if value == "fitness":
        return "Фитнес"
    if value == "finance":
        return "Финансы"
    return "Работа"


def _day_mode_label(mode: str) -> str:
    value = (mode or "").strip().lower()
    if value in {"workday", "operator", "normal"}:
        return "Рабочий"
    if value in {"recovery", "recovery_day"}:
        return "Восстановление"
    if value in {"travel", "travel_day"}:
        return "В дороге"
    return mode or "Рабочий"


def _session_selector_markup(current: str) -> InlineKeyboardMarkup:
    cur = (current or "work").strip().lower()

    def label(code: str, text: str) -> str:
        return f"✅ {text}" if code == cur else text

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label("work", "💼 Работа"), callback_data="ux:session:set:work"),
                InlineKeyboardButton(text=label("fitness", "🏋️ Фитнес"), callback_data="ux:session:set:fitness"),
                InlineKeyboardButton(text=label("finance", "💹 Финансы"), callback_data="ux:session:set:finance"),
            ]
        ]
    )


def _is_quiet_hours(profile: dict[str, object]) -> bool:
    start_raw = str(profile.get("quiet_start") or "").strip()
    end_raw = str(profile.get("quiet_end") or "").strip()
    if not start_raw or not end_raw or ":" not in start_raw or ":" not in end_raw:
        return False
    try:
        sh, sm = [int(x) for x in start_raw.split(":", 1)]
        eh, em = [int(x) for x in end_raw.split(":", 1)]
    except ValueError:
        return False
    cur = datetime.now().hour * 60 + datetime.now().minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _reserve_nudge_slot(user_id: int, profile: dict[str, object], max_per_day: int = 3) -> bool:
    if _is_quiet_hours(profile):
        return False
    key = _nudge_counter_key(user_id)
    try:
        count = int(_cache_text_get(key) or 0)
    except ValueError:
        count = 0
    if count >= max_per_day:
        return False
    set_cache_value(key, str(count + 1), _now_iso())
    return True


def _build_today_text(user_id: int) -> tuple[str, bool, int | None]:
    profile = user_settings_get_full(user_id)
    session_name = memory_get(user_id=user_id, key="active_session") or "work"
    open_todos = todo_list_open(user_id=user_id, limit=5)
    workout = pick_workout_of_day()
    today_iso = date.today().isoformat()
    checkin = daily_checkin_get(user_id=user_id, check_date=today_iso)
    energy = checkin[2] if checkin and checkin[2] is not None else None

    boss = build_boss_battle_status(user_id=user_id)
    arena_lines = [line.strip() for line in build_arena_text(user_id=user_id).splitlines() if line.strip()]
    arena_short = arena_lines[-1] if arena_lines else "⚔️ Арена: без данных"

    lines = [
        "🎯 Фокус дня",
        f"Режим: {_day_mode_label(str(profile.get('day_mode') or 'workday'))} | Сессия: {_session_label(session_name)}",
        f"Энергия: {energy}/10" if energy is not None else "Энергия: не отмечена",
        f"👾 Boss Week: {boss.boss_name} • урон {boss.damage_pct}% • HP {boss.hp_left_pct}%",
        arena_short,
        "",
        "MIT сегодня:",
    ]
    if open_todos:
        for idx, (_todo_id, todo_text, _created_at) in enumerate(open_todos[:3], start=1):
            lines.append(f"{idx}. {_trim(str(todo_text), 70)}")
    else:
        lines.append("1. Добавьте задачу: /todo add <текст>")

    workout_id: int | None = None
    if workout:
        workout_id = int(workout[0])
        lines.extend(["", f"🏋️ Тренировка дня: {_trim(str(workout[1] or ''), 70)}", f"Открыть: /fit show {workout_id}"])

    if rescue_needed_today(user_id=user_id):
        lines.extend(["", "🛟 Спасение стрика: /rescue (3-7 минут)."])

    lines.extend(["", "Действия: Done • Start 25m • Replan • Mood • Focus"])
    return "\n".join(lines), bool(open_todos), workout_id


def _build_replan_text(user_id: int, mood: int | None = None) -> str:
    now = datetime.now()
    todos = todo_list_open(user_id=user_id, limit=6)
    core = [f"- {_trim(str(row[1]), 72)}" for row in todos[:3]] or ["- Добавить 1 ключевую задачу через /todo add ..."]
    lite = [f"- {_trim(str(row[1]), 72)}" for row in todos[:2]] or ["- 15 минут на один быстрый шаг", "- 10 минут на закрытие хвоста"]
    next_hour = max(now.hour + 1, 9)

    hard = [
        "⚡ Replan: жесткий",
        f"{next_hour:02d}:00-12:00 — 1 главный блок без переключений",
        "12:00-13:00 — короткий перерыв и проверка входящих",
        "После 13:00 — закрыть 1-2 вторичных задачи",
        "",
        "Приоритеты:",
        *core,
    ]
    soft = [
        "🫶 Replan: мягкий",
        "1 блок 25/5 для важного шага",
        "Легкая тренировка/прогулка 30-40 минут",
        "Вечером — закрыть 1 небольшой хвост",
        "",
        "Минимум на день:",
        *lite,
    ]
    if mood is not None and mood <= 3:
        soft.append("Совет: низкая энергия — держите только 1 обязательный результат.")
    elif mood is not None and mood >= 8:
        hard.append("Совет: высокая энергия — лучшее окно для deep-work прямо сейчас.")
    return "\n".join([*hard, "", *soft])


def _build_week_screens(user_id: int) -> list[str]:
    since_iso = f"{(date.today() - timedelta(days=7)).isoformat()}T00:00:00"
    done_tasks, open_tasks = todo_stats_recent(user_id=user_id, since_iso=since_iso)
    fitness_done, _rows = fitness_stats_recent(user_id=user_id, since_iso=since_iso)
    checkins = daily_checkin_recent(user_id=user_id, since_iso=since_iso, limit=7)
    streak_days = fitness_current_streak_days(user_id=user_id)

    energies = [int(row[3]) for row in checkins if row[3] is not None]
    avg_energy = (sum(energies) / len(energies)) if energies else None
    best_day = sorted(checkins, key=lambda x: (int(x[3]) if x[3] is not None else -1), reverse=True)[0][0] if checkins else None
    leaks = [_trim(carry, 48) for _d, _done, carry, _e in checkins if carry.strip()] or ["нет явных"]
    next_focus = [_trim(str(row[1]), 64) for row in todo_list_open(user_id=user_id, limit=3)]

    metrics = WeekPlaybackMetrics(
        done_tasks=done_tasks,
        open_tasks=open_tasks,
        fitness_done=fitness_done,
        streak_days=streak_days,
        avg_energy=avg_energy,
        best_day=best_day,
        leaks=leaks,
        next_focus=next_focus,
    )
    screens = build_week_playback_screens(metrics)
    screens.append(build_cinematic_weekly_recap(user_id=user_id))
    return screens


def build_ux_router(ctx: AppContext) -> Router:
    router = Router(name="ux")
    router.message.filter(F.chat.type == "private")
    running_sprints: dict[int, tuple[int, asyncio.Task]] = {}

    async def cancel_sprint(user_id: int, status: str) -> bool:
        running = running_sprints.pop(user_id, None)
        if not running:
            return False
        focus_id, task = running
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        focus_session_finish(user_id=user_id, focus_id=focus_id, finished_at=_now_iso(), status=status)
        return True

    async def send_sprint_escalation(user_id: int, chat_id: int, focus_id: int, minutes: int) -> None:
        await asyncio.sleep(240)
        if _cache_text_get(_sprint_ack_key(focus_id)) == "1":
            return
        profile = user_settings_get_full(user_id)
        if not _reserve_nudge_slot(user_id, profile):
            return
        await ctx.bot.send_message(chat_id=chat_id, text=f"⏱️ Спринт {minutes}m еще активен. Нажмите «Готово».", reply_markup=sprint_done_markup(focus_id))

    async def run_sprint(user_id: int, chat_id: int, focus_id: int, minutes: int) -> None:
        await asyncio.sleep(max(1, int(minutes)) * 60)
        current = running_sprints.get(user_id)
        if not current or current[0] != focus_id:
            return
        running_sprints.pop(user_id, None)
        focus_session_finish(user_id=user_id, focus_id=focus_id, finished_at=_now_iso(), status="done")
        if _reserve_nudge_slot(user_id, user_settings_get_full(user_id)):
            await ctx.bot.send_message(chat_id=chat_id, text=f"✅ Спринт {minutes}m завершен. Зафиксировать результат?", reply_markup=sprint_done_markup(focus_id))
            asyncio.create_task(send_sprint_escalation(user_id, chat_id, focus_id, minutes))

    @router.message(Command("session"))
    async def session_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            current = memory_get(user_id=user_id, key="active_session") or "work"
            await message.reply(f"🧵 Активная сессия: {_session_label(current)}", reply_markup=_session_selector_markup(current))

    @router.message(Command("boss"))
    async def boss_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            await message.reply(build_boss_text(user_id=user_id))

    @router.message(Command("arena"))
    async def arena_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            await message.reply(build_arena_text(user_id=user_id))

    @router.message(Command("rescue"))
    async def rescue_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id <= 0:
            return
        if rescue_completed_today(user_id=user_id):
            await message.reply("✅ Rescue уже выполнен сегодня.")
            return
        quest = build_rescue_quest_text(user_id=user_id)
        await message.reply("🛟 Streak Insurance\nМини-квест на 3-7 минут:\n• " + quest + "\nСделайте и нажмите кнопку ниже.", reply_markup=_rescue_markup())

    @router.message(Command("recap"))
    async def recap_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            await message.reply(build_cinematic_weekly_recap(user_id=user_id))

    @router.message(Command("today"))
    async def today_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            text, has_todo, workout_id = _build_today_text(user_id)
            await message.reply(text, reply_markup=today_panel_markup(has_todo=has_todo, workout_id=workout_id))

    @router.message(Command("digest"))
    async def digest_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id <= 0:
            return
        profile = user_settings_get_full(user_id)
        runtime_settings = replace(
            ctx.settings,
            default_lang=str(profile.get("lang") or ctx.settings.default_lang),
            timezone_name=str(profile.get("timezone_name") or ctx.settings.timezone_name) if (profile.get("timezone_name") or ctx.settings.timezone_name) else None,
            weather_city=str(profile.get("weather_city") or ctx.settings.weather_city),
        )
        render = await safe_build_digest_render(runtime_settings, morning_mode=(datetime.now().hour < 11))
        screens = build_digest_story_screens(render.expanded.text)
        _cache_json_set(_digest_key(user_id), {"screens": screens, "full": render.expanded.text, "parse_mode": render.expanded.parse_mode or "HTML"})
        await message.reply(screens[0], parse_mode="HTML", disable_web_page_preview=False, reply_markup=digest_story_nav(0, len(screens)))

    @router.message(Command("week"))
    async def week_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id > 0:
            screens = _build_week_screens(user_id)
            _cache_json_set(_week_key(user_id), {"screens": screens})
            await message.reply(screens[0], reply_markup=week_story_nav(0, len(screens)))

    @router.callback_query(F.data.startswith("ux:today:"))
    async def today_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        parts = (callback.data or "").split(":")
        if user_id <= 0:
            await callback.answer("", show_alert=False)
            return
        if len(parts) != 4:
            await callback.answer("Некорректный формат", show_alert=False)
            return
        _, _, action, value = parts
        if action == "done":
            rows = todo_list_open(user_id=user_id, limit=1) if value == "top" else []
            if not rows:
                await callback.answer("Нет активных задач", show_alert=False)
                return
            todo_mark_done(user_id=user_id, todo_id=int(rows[0][0]), done_at=_now_iso())
            text, has_todo, workout_id = _build_today_text(user_id)
            if callback.message:
                try:
                    await callback.message.edit_text(text, reply_markup=today_panel_markup(has_todo=has_todo, workout_id=workout_id))
                except Exception:
                    await callback.message.reply(text, reply_markup=today_panel_markup(has_todo=has_todo, workout_id=workout_id))
            await callback.answer("Задача закрыта", show_alert=False)
            return
        if action == "replan":
            checkin = daily_checkin_get(user_id=user_id, check_date=date.today().isoformat())
            mood = int(checkin[2]) if checkin and checkin[2] is not None else None
            if callback.message:
                await callback.message.reply(_build_replan_text(user_id, mood=mood), reply_markup=_today_replan_markup())
            await callback.answer("План пересобран", show_alert=False)
            return
        if action == "apply":
            if value not in {"hard", "soft"}:
                await callback.answer("Неизвестный тип плана", show_alert=False)
                return
            memory_set(user_id=user_id, key="today_plan", value=f"{value} plan @ {_now_iso()}", updated_at=_now_iso(), confidence=1.0)
            await callback.answer("Жесткий план применен" if value == "hard" else "Мягкий план применен", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    @router.callback_query(F.data == "ux:rescue:done:1")
    async def rescue_done_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        if user_id > 0:
            mark_rescue_completed(user_id=user_id)
            if callback.message:
                await callback.message.reply("✅ Rescue засчитан. Стрик защищен.")
        await callback.answer("Готово", show_alert=False)

    @router.callback_query(F.data.startswith("ux:mood:set:"))
    async def mood_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        parts = (callback.data or "").split(":")
        if user_id <= 0 or len(parts) != 4 or not parts[3].isdigit():
            await callback.answer("Некорректный формат", show_alert=False)
            return
        energy = max(1, min(10, int(parts[3])))
        today_iso = date.today().isoformat()
        row = daily_checkin_get(user_id=user_id, check_date=today_iso)
        daily_checkin_upsert(
            user_id=user_id,
            check_date=today_iso,
            done_text=str(row[0] or "") if row else "",
            carry_text=str(row[1] or "") if row else "",
            energy=energy,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        text, has_todo, workout_id = _build_today_text(user_id)
        if callback.message:
            try:
                await callback.message.edit_text(text, reply_markup=today_panel_markup(has_todo=has_todo, workout_id=workout_id))
            except Exception:
                await callback.message.reply(text, reply_markup=today_panel_markup(has_todo=has_todo, workout_id=workout_id))
        await callback.answer(f"Энергия: {energy}/10", show_alert=False)

    @router.callback_query(F.data.startswith("ux:session:"))
    async def session_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        parts = (callback.data or "").split(":")
        if user_id <= 0 or len(parts) != 4:
            await callback.answer("", show_alert=False)
            return
        _, _, action, value = parts
        if action == "show":
            current = memory_get(user_id=user_id, key="active_session") or "work"
            if callback.message:
                await callback.message.reply(f"🧵 Активная сессия: {_session_label(current)}", reply_markup=_session_selector_markup(current))
            await callback.answer("", show_alert=False)
            return
        if action == "set" and value in {"work", "fitness", "finance"}:
            memory_set(user_id=user_id, key="active_session", value=value, updated_at=_now_iso(), confidence=1.0, is_verified=True)
            if callback.message:
                try:
                    await callback.message.edit_reply_markup(reply_markup=_session_selector_markup(value))
                except Exception:
                    pass
            await callback.answer(f"Сессия: {_session_label(value)}", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    @router.callback_query(F.data.startswith("ux:sprint:"))
    async def sprint_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        chat_id = callback.message.chat.id if callback.message and callback.message.chat else 0
        parts = (callback.data or "").split(":")
        if user_id <= 0 or chat_id == 0 or len(parts) != 4:
            await callback.answer("", show_alert=False)
            return
        _, _, action, value = parts
        if action == "start" and value.isdigit():
            minutes = max(1, min(90, int(value)))
            await cancel_sprint(user_id, "replaced")
            focus_id = focus_session_start(user_id=user_id, duration_min=minutes, started_at=_now_iso())
            set_cache_value(_sprint_ack_key(focus_id), "0", _now_iso())
            running_sprints[user_id] = (focus_id, asyncio.create_task(run_sprint(user_id, chat_id, focus_id, minutes)))
            if callback.message:
                await callback.message.reply(
                    f"⏱️ Старт micro-sprint: {minutes}m\nФокус: одна задача без переключений.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⛔ Остановить", callback_data=f"ux:sprint:cancel:{focus_id}")]]),
                )
            await callback.answer(f"Старт {minutes}m", show_alert=False)
            return
        if action == "cancel" and value.isdigit():
            focus_id = int(value)
            running = running_sprints.get(user_id)
            if running and running[0] == focus_id:
                await cancel_sprint(user_id, "canceled")
                await callback.answer("Остановлено", show_alert=False)
                return
            await callback.answer("Спринт уже завершен", show_alert=False)
            return
        if action == "done" and value.isdigit():
            focus_id = int(value)
            set_cache_value(_sprint_ack_key(focus_id), "1", _now_iso())
            running = running_sprints.get(user_id)
            if running and running[0] == focus_id:
                await cancel_sprint(user_id, "done")
            else:
                focus_session_finish(user_id=user_id, focus_id=focus_id, finished_at=_now_iso(), status="done")
            await callback.answer("Засчитано", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    @router.callback_query(F.data.startswith("ux:mem:"))
    async def memory_chip_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        parts = (callback.data or "").split(":")
        if user_id <= 0 or len(parts) != 4:
            await callback.answer("", show_alert=False)
            return
        _, _, action, _value = parts
        last_user = _cache_text_get(_last_user_key(user_id))
        base_text = last_user or _cache_text_get(_last_assistant_key(user_id))
        if not base_text:
            await callback.answer("Нет контекста", show_alert=False)
            return
        if action == "remember":
            memory_set(user_id=user_id, key=f"fact_{datetime.now().strftime('%Y%m%d_%H%M%S')}", value=_trim(base_text, 500), updated_at=_now_iso(), confidence=0.8)
            await callback.answer("Сохранено", show_alert=False)
            return
        if action == "rule":
            match = re.search(r"(?:if|если)\s+(.+?)\s+(?:then|то)\s+(.+)", last_user, flags=re.IGNORECASE) if last_user else None
            if match:
                rule_id = automation_rule_add(user_id=user_id, condition_expr=match.group(1).strip(), action_expr=match.group(2).strip(), created_at=_now_iso())
                await callback.answer(f"Правило #{rule_id}", show_alert=False)
            else:
                memory_set(user_id=user_id, key=f"rule_draft_{datetime.now().strftime('%Y%m%d_%H%M%S')}", value=_trim(base_text, 500), updated_at=_now_iso(), confidence=0.7)
                await callback.answer("Черновик правила сохранен", show_alert=False)
            return
        if action == "tomorrow":
            todo_id = todo_add(user_id=user_id, text=_trim(base_text, 170), created_at=_now_iso())
            await callback.answer(f"В todo #{todo_id}", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    @router.callback_query(F.data.startswith("ux:digest:"))
    async def digest_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        data = _cache_json_get(_digest_key(user_id)) if user_id > 0 else None
        parts = (callback.data or "").split(":")
        if not data or not isinstance(data.get("screens"), list):
            await callback.answer("Сначала откройте /digest", show_alert=False)
            return
        if len(parts) != 4:
            await callback.answer("Некорректный формат", show_alert=False)
            return
        _, _, action, value = parts
        screens = [str(x) for x in data.get("screens", []) if str(x).strip()]
        if not screens:
            await callback.answer("Нет данных", show_alert=False)
            return
        if action == "noop":
            await callback.answer("", show_alert=False)
            return
        if action == "full":
            if callback.message:
                full_text = str(data.get("full") or "") or screens[0]
                parse_mode = str(data.get("parse_mode") or "HTML")
                try:
                    await callback.message.edit_text(full_text, parse_mode=parse_mode, disable_web_page_preview=False, reply_markup=digest_story_nav(0, len(screens)))
                except Exception:
                    await callback.message.reply(full_text, parse_mode=parse_mode, disable_web_page_preview=False)
            await callback.answer("", show_alert=False)
            return
        if action == "go" and value.isdigit():
            idx = max(0, min(len(screens) - 1, int(value)))
            if callback.message:
                try:
                    await callback.message.edit_text(screens[idx], parse_mode="HTML", disable_web_page_preview=False, reply_markup=digest_story_nav(idx, len(screens)))
                except Exception:
                    await callback.message.reply(screens[idx], parse_mode="HTML", disable_web_page_preview=False, reply_markup=digest_story_nav(idx, len(screens)))
            await callback.answer("", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    @router.callback_query(F.data.startswith("ux:week:"))
    async def week_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else 0
        data = _cache_json_get(_week_key(user_id)) if user_id > 0 else None
        parts = (callback.data or "").split(":")
        if not data or not isinstance(data.get("screens"), list):
            await callback.answer("Сначала откройте /week", show_alert=False)
            return
        if len(parts) != 4:
            await callback.answer("Некорректный формат", show_alert=False)
            return
        _, _, action, value = parts
        screens = [str(x) for x in data.get("screens", []) if str(x).strip()]
        if not screens:
            await callback.answer("Нет данных", show_alert=False)
            return
        if action == "noop":
            await callback.answer("", show_alert=False)
            return
        if action == "go" and value.isdigit():
            idx = max(0, min(len(screens) - 1, int(value)))
            if callback.message:
                try:
                    await callback.message.edit_text(screens[idx], reply_markup=week_story_nav(idx, len(screens)))
                except Exception:
                    await callback.message.reply(screens[idx], reply_markup=week_story_nav(idx, len(screens)))
            await callback.answer("", show_alert=False)
            return
        await callback.answer("", show_alert=False)

    return router
