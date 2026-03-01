import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

from aiogram import F, Router, types
from aiogram.filters import Command

from db import (
    daily_checkin_recent,
    fitness_stats_recent,
    focus_stats_recent,
    get_cache_value,
    set_cache_value,
    subs_due_within,
    todo_done_count_between,
    todo_stats_recent,
    user_settings_get,
    user_settings_get_full,
)
from handlers.context import AppContext
from services.http_service import ExternalAPIError
from services.llm_service import call_ollama


def _resolve_user_runtime_settings(ctx: AppContext, user_id: int) -> tuple[object, str]:
    if user_id <= 0:
        return ctx.settings, ctx.settings.default_lang

    profile = user_settings_get_full(user_id)
    lang = str(profile.get("lang") or ctx.settings.default_lang)
    timezone_name = profile.get("timezone_name") or ctx.settings.timezone_name
    weather_city = profile.get("weather_city") or ctx.settings.weather_city
    runtime_settings = replace(
        ctx.settings,
        default_lang=lang,
        timezone_name=timezone_name,
        weather_city=weather_city,
    )
    return runtime_settings, lang


def _fmt_delta(cur: float, prev: float) -> str:
    delta = cur - prev
    if delta > 0:
        return f"+{delta:.1f}"
    if delta < 0:
        return f"{delta:.1f}"
    return "0.0"


def _scenario_params(avg_energy: float, open_count: int) -> tuple[int, int, int, str]:
    plan_a = max(2, min(5, open_count if open_count > 0 else 3))
    plan_b = max(1, min(3, plan_a - 1))
    plan_c = 1
    risk = (
        "\u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437"
        if avg_energy < 6
        else "\u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u043d\u044b\u0435 \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f"
    )
    return plan_a, plan_b, plan_c, risk


def _cache_key_legend_enabled(user_id: int) -> str:
    return f"user:legend:enabled:{user_id}"


def _legend_is_enabled(user_id: int) -> bool:
    row = get_cache_value(_cache_key_legend_enabled(user_id))
    return bool(row and str(row[0]).strip() == "1")


def _legend_set_enabled(user_id: int, enabled: bool) -> None:
    set_cache_value(
        _cache_key_legend_enabled(user_id),
        "1" if enabled else "0",
        datetime.now().isoformat(timespec="seconds"),
    )


def _legend_day_status(user_id: int) -> tuple[str, int, dict[str, int]]:
    now = datetime.now()
    day_start = datetime.combine(now.date(), datetime.min.time())
    start_iso = day_start.isoformat(timespec="seconds")
    end_iso = now.isoformat(timespec="seconds")

    done_today = todo_done_count_between(user_id=user_id, start_iso=start_iso, end_iso=end_iso)
    focus_minutes, focus_sessions = focus_stats_recent(user_id=user_id, since_iso=start_iso)
    workouts_today, _ = fitness_stats_recent(user_id=user_id, since_iso=start_iso)

    points = 0
    if done_today >= 1:
        points += 1
    if focus_minutes >= 25:
        points += 1
    if focus_minutes >= 60:
        points += 1
    if workouts_today >= 1:
        points += 1

    # "Legendary" requires at least one clearly strategic action.
    strategic = focus_minutes >= 60 or focus_sessions >= 2
    if points >= 4 and strategic:
        status = "Legendary"
    elif points >= 2:
        status = "Elite"
    else:
        status = "Ordinary"

    meta = {
        "done_today": done_today,
        "focus_minutes": focus_minutes,
        "focus_sessions": focus_sessions,
        "workouts_today": workouts_today,
    }
    return status, points, meta


def _chronotwin_simulation_text(user_id: int, lang: str) -> str:
    now = datetime.now()
    since_14 = (now - timedelta(days=14)).isoformat(timespec="seconds")
    since_7 = (now - timedelta(days=7)).isoformat(timespec="seconds")

    done_14, open_now = todo_stats_recent(user_id=user_id, since_iso=since_14)
    focus_14, sessions_14 = focus_stats_recent(user_id=user_id, since_iso=since_14)
    workouts_14, _ = fitness_stats_recent(user_id=user_id, since_iso=since_14)
    checkins = daily_checkin_recent(user_id=user_id, since_iso=since_7, limit=7)
    energies = [int(row[3]) for row in checkins if row[3] is not None]
    avg_energy = (sum(energies) / len(energies)) if energies else 6.0

    avg_done_day = done_14 / 14.0
    avg_focus_day = focus_14 / 14.0
    avg_workouts_week = workouts_14 / 2.0

    peak_tasks = max(1, round(avg_done_day * 1.25))
    real_tasks = max(1, round(avg_done_day))
    chaos_tasks = max(1, round(avg_done_day * 0.55))

    peak_focus = int(max(25, round(avg_focus_day * 1.3)))
    real_focus = int(max(20, round(avg_focus_day)))
    chaos_focus = int(max(15, round(avg_focus_day * 0.5)))

    levers: list[str] = []
    if avg_energy < 6.0:
        levers.append(
            "Сдвинь сложный блок на первые 2 часа дня и оставь только 1 MIT."
            if lang == "ru"
            else "Move hard work to first 2 hours and keep only 1 MIT."
        )
    if open_now > 8:
        levers.append(
            "Убери 2 лишние задачи из open-листа до начала работы."
            if lang == "ru"
            else "Remove 2 non-critical open tasks before starting."
        )
    if not levers:
        levers.append(
            "Первый deep-блок 45 минут без мессенджеров."
            if lang == "ru"
            else "Run first 45-minute deep block with messengers off."
        )
    if len(levers) == 1:
        levers.append(
            "Фиксированный вечерний review 7 минут."
            if lang == "ru"
            else "Fixed 7-minute evening review."
        )

    if lang == "ru":
        return "\n".join(
            [
                "🕒 Chrono Twin — симуляция",
                "",
                f"База 14д: done={done_14}, focus={focus_14} мин/{sessions_14} сесс., workouts≈{avg_workouts_week:.1f}/нед, energy={avg_energy:.1f}/10, open={open_now}",
                "",
                f"Peak: {peak_tasks} ключ. задачи/день, {peak_focus} мин deep-work.",
                f"Real: {real_tasks} ключ. задачи/день, {real_focus} мин deep-work.",
                f"Chaos: {chaos_tasks} ключ. задача/день, {chaos_focus} мин deep-work.",
                "",
                "Рычаги Real → Peak:",
                f"1) {levers[0]}",
                f"2) {levers[1]}",
            ]
        )

    return "\n".join(
        [
            "🕒 Chrono Twin — simulation",
            "",
            f"14d baseline: done={done_14}, focus={focus_14}m/{sessions_14} sessions, workouts≈{avg_workouts_week:.1f}/week, energy={avg_energy:.1f}/10, open={open_now}",
            "",
            f"Peak: {peak_tasks} key tasks/day, {peak_focus}m deep-work.",
            f"Real: {real_tasks} key tasks/day, {real_focus}m deep-work.",
            f"Chaos: {chaos_tasks} key task/day, {chaos_focus}m deep-work.",
            "",
            "Levers Real → Peak:",
            f"1) {levers[0]}",
            f"2) {levers[1]}",
        ]
    )


def build_advanced_ops_router(ctx: AppContext) -> Router:
    router = Router(name="advanced_ops")
    router.message.filter(F.chat.type == "private")

    @router.message(Command("chronotwin"))
    async def chronotwin_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        _runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        text = (message.text or "").strip()
        arg = text.split(maxsplit=1)[1].strip().lower() if " " in text else ""
        is_ru = lang == "ru"
        if arg not in {"simulate"}:
            await message.reply(
                "Формат: /chronotwin simulate" if is_ru else "Format: /chronotwin simulate"
            )
            return
        await message.reply(_chronotwin_simulation_text(user_id=user_id, lang=lang))

    @router.message(Command("boardroom"))
    async def boardroom_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        text = (message.text or "").strip()
        decision_text = text.split(maxsplit=1)[1].strip() if " " in text else ""
        is_ru = lang == "ru"

        if not decision_text:
            await message.reply(
                "Формат: /boardroom <решение>" if is_ru else "Format: /boardroom <decision>"
            )
            return

        mode, _show_conf = user_settings_get(user_id) if user_id > 0 else ("normal", False)
        prompt = (
            "You are Future Boardroom with 3 future-self roles.\n"
            "Language: Russian unless user asked English.\n"
            "Decision topic: " + decision_text + "\n\n"
            "Return plain text with exact sections:\n"
            "1) 1Y Self (tactical)\n"
            "2) 5Y Self (strategic)\n"
            "3) 10Y Self (existential)\n"
            "4) Converged Decision\n"
            "5) Price of Choice\n"
            "6) Point of No Return\n"
            "7) First 24h Action\n"
            "Rules: concise, concrete, no fluff."
        )
        try:
            response = await asyncio.wait_for(
                call_ollama(prompt, runtime_settings, mode=mode, profile="advisor"),
                timeout=16.0,
            )
            if not response.strip():
                raise ExternalAPIError(service="ollama", kind="empty", message="empty response")
            await message.reply(response.strip())
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning("event=boardroom_fallback user_id=%s reason=%s", user_id, exc.__class__.__name__)
            if is_ru:
                fallback = "\n".join(
                    [
                        "🧠 Future Boardroom",
                        "",
                        "1) 1Y Self: бери решение с самой быстрой проверкой гипотезы.",
                        "2) 5Y Self: выбирай вариант, который масштабируется и не ломает репутацию.",
                        "3) 10Y Self: оставь то, чем будешь гордиться через годы.",
                        "4) Converged Decision: делай маленький тест на 24 часа.",
                        "5) Price of Choice: придётся отказаться от 1-2 второстепенных задач.",
                        "6) Point of No Return: публично зафиксированный дедлайн.",
                        "7) First 24h Action: 45 минут на первый измеримый шаг сегодня.",
                    ]
                )
            else:
                fallback = "\n".join(
                    [
                        "🧠 Future Boardroom",
                        "",
                        "1) 1Y Self: pick the option with fastest hypothesis test.",
                        "2) 5Y Self: choose what scales and protects your reputation.",
                        "3) 10Y Self: keep what your future self will respect.",
                        "4) Converged Decision: run a small 24h test.",
                        "5) Price of Choice: drop 1-2 secondary commitments.",
                        "6) Point of No Return: commit to a public deadline.",
                        "7) First 24h Action: 45 minutes on one measurable step today.",
                    ]
                )
            await message.reply(fallback)

    @router.message(Command("legend"))
    async def legend_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        _runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        text = (message.text or "").strip()
        arg = text.split(maxsplit=1)[1].strip().lower() if " " in text else "status"
        is_ru = lang == "ru"

        if arg == "on":
            _legend_set_enabled(user_id, True)
        elif arg == "off":
            _legend_set_enabled(user_id, False)
        elif arg != "status":
            await message.reply("Формат: /legend on|off|status" if is_ru else "Format: /legend on|off|status")
            return

        enabled = _legend_is_enabled(user_id)
        status, points, meta = _legend_day_status(user_id)
        mode_text = ("вкл" if enabled else "выкл") if is_ru else ("on" if enabled else "off")

        if status == "Legendary":
            nudge = (
                "Держи темп: закрепи результат коротким вечерним review."
                if is_ru
                else "Hold momentum: lock it in with a short evening review."
            )
        elif status == "Elite":
            nudge = (
                "До Legendary не хватает одного стратегического шага (45-60 мин deep-work)."
                if is_ru
                else "One strategic step (45-60m deep work) to reach Legendary."
            )
        else:
            nudge = (
                "Стартуй с минимума: 1 MIT + 25 минут фокуса."
                if is_ru
                else "Start minimum: 1 MIT + 25 minutes focus."
            )

        if is_ru:
            lines = [
                "🏆 Legend Protocol",
                f"Режим: {mode_text}",
                f"Статус дня: {status} ({points}/4)",
                (
                    f"Факты: done={meta['done_today']}, focus={meta['focus_minutes']} мин/"
                    f"{meta['focus_sessions']} сесс., workouts={meta['workouts_today']}"
                ),
                nudge,
            ]
        else:
            lines = [
                "🏆 Legend Protocol",
                f"Mode: {mode_text}",
                f"Day status: {status} ({points}/4)",
                (
                    f"Facts: done={meta['done_today']}, focus={meta['focus_minutes']}m/"
                    f"{meta['focus_sessions']} sessions, workouts={meta['workouts_today']}"
                ),
                nudge,
            ]
        await message.reply("\n".join(lines))

    @router.message(Command("redteam"))
    async def redteam_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        text = (message.text or "").strip()
        plan_text = text.split(maxsplit=1)[1].strip() if " " in text else ""
        is_ru = lang == "ru"

        if not plan_text:
            await message.reply(
                (
                    "\u0424\u043e\u0440\u043c\u0430\u0442: /redteam <\u043f\u043b\u0430\u043d>\n"
                    "\u041f\u0440\u0438\u043c\u0435\u0440: /redteam \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043d\u043e\u0432\u044b\u0439 \u0442\u0430\u0440\u0438\u0444 \u0437\u0430 2 \u043d\u0435\u0434\u0435\u043b\u0438"
                )
                if is_ru
                else "Format: /redteam <plan>\nExample: /redteam Launch a new plan in 2 weeks"
            )
            return

        mode, _show_conf = user_settings_get(user_id) if user_id > 0 else ("normal", False)
        prompt = (
            "You are a strict red-team reviewer for personal execution plans.\n"
            "Language: Russian unless user asked English.\n"
            "Rules: no fluff, no motivation speeches, concrete risks only.\n"
            "Output exactly these sections in plain text:\n"
            "1) Where the plan breaks (top-5)\n"
            "2) Blind spots / self-deception\n"
            "3) Early warning signals\n"
            "4) Hardened version of plan (short actionable steps)\n"
            "5) Minimum safe experiment for next 24h\n"
            "Keep it concise and practical.\n\n"
            f"Plan:\n{plan_text}"
        )

        try:
            response = await asyncio.wait_for(
                call_ollama(prompt, runtime_settings, mode=mode),
                timeout=14.0,
            )
            if not response.strip():
                raise ExternalAPIError(service="ollama", kind="empty", message="empty response")
            await message.reply(response.strip())
        except Exception as exc:
            ctx.logger.warning("event=redteam_fallback user_id=%s reason=%s", user_id, exc.__class__.__name__)
            fallback_ru = "\n".join(
                [
                    "\U0001f3af Red Team",
                    "",
                    "1) \u0420\u0438\u0441\u043a\u0438: \u043e\u043f\u0442\u0438\u043c\u0438\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0441\u0440\u043e\u043a\u0438, \u043d\u0435\u0442 \u0431\u0443\u0444\u0435\u0440\u043e\u0432, \u043d\u0435 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0451\u043d Done.",
                    "2) \u0421\u043b\u0435\u043f\u044b\u0435 \u0437\u043e\u043d\u044b: \u0441\u0442\u0430\u0432\u043a\u0430 \u043d\u0430 \u043c\u043e\u0442\u0438\u0432\u0430\u0446\u0438\u044e \u0432\u043c\u0435\u0441\u0442\u043e \u0441\u0438\u0441\u0442\u0435\u043c\u044b.",
                    "3) \u0421\u0438\u0433\u043d\u0430\u043b\u044b \u0442\u0440\u0435\u0432\u043e\u0433\u0438: 2 \u0434\u043d\u044f \u0431\u0435\u0437 \u043a\u043b\u044e\u0447\u0435\u0432\u043e\u0433\u043e \u043f\u0440\u043e\u0433\u0440\u0435\u0441\u0441\u0430.",
                    "4) \u0423\u0441\u0438\u043b\u0435\u043d\u0438\u0435: 1 \u0433\u043b\u0430\u0432\u043d\u044b\u0439 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u043d\u0435\u0434\u0435\u043b\u0438 + 45 \u043c\u0438\u043d \u0432 \u0434\u0435\u043d\u044c.",
                    "5) 24\u0447 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442: \u043e\u0434\u0438\u043d \u043a\u0440\u0438\u0442\u0435\u0440\u0438\u0439 \u0443\u0441\u043f\u0435\u0445\u0430, \u0448\u0430\u0433 30-60 \u043c\u0438\u043d, \u0432\u0435\u0447\u0435\u0440\u043d\u0435\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435.",
                ]
            )
            fallback_en = "\n".join(
                [
                    "\U0001f3af Red Team",
                    "",
                    "1) Risks: optimistic timeline, no buffers, no Done criteria.",
                    "2) Blind spots: relying on motivation over process.",
                    "3) Warning signals: 2 days with no key progress.",
                    "4) Harden: one weekly core outcome + fixed 45m daily block.",
                    "5) 24h experiment: one metric, first step 30-60m, evening decision.",
                ]
            )
            await message.reply(fallback_ru if is_ru else fallback_en)

    @router.message(Command("scenario"))
    async def scenario_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        _runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        text = (message.text or "").strip()
        arg = text.split(maxsplit=1)[1].strip().lower() if " " in text else ""
        is_ru = lang == "ru"

        if arg != "week":
            await message.reply(
                "\u0424\u043e\u0440\u043c\u0430\u0442: /scenario week" if is_ru else "Format: /scenario week"
            )
            return

        since_7 = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        checkins = daily_checkin_recent(user_id=user_id, since_iso=since_7, limit=7) if user_id > 0 else []
        energies = [int(x[2]) for x in checkins if len(x) > 2 and x[2] is not None]
        avg_energy = (sum(energies) / len(energies)) if energies else 6.0
        done_count, open_count = todo_stats_recent(user_id=user_id, since_iso=since_7) if user_id > 0 else (0, 0)
        fit_total, _fit_rows = fitness_stats_recent(user_id=user_id, since_iso=since_7) if user_id > 0 else (0, [])
        subs_due = subs_due_within(user_id=user_id, days=7) if user_id > 0 else []
        plan_a, plan_b, plan_c, risk = _scenario_params(avg_energy, open_count)

        if is_ru:
            lines = [
                "\U0001f9ed Scenario Planning 3x (\u043d\u0435\u0434\u0435\u043b\u044f)",
                "",
                (
                    f"\u0411\u0430\u0437\u0430: \u044d\u043d\u0435\u0440\u0433\u0438\u044f {avg_energy:.1f}/10, "
                    f"done={done_count}, open={open_count}, \u0442\u0440\u0435\u043d\u0438\u0440\u043e\u0432\u043a\u0438={fit_total}, "
                    f"\u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438 \u043a \u043e\u043f\u043b\u0430\u0442\u0435={len(subs_due)}"
                ),
                "",
                "A) \u0418\u0434\u0435\u0430\u043b:",
                f"- {plan_a} \u043a\u043b\u044e\u0447\u0435\u0432\u044b\u0445 \u0441\u043b\u043e\u0442\u0430 deep-work;",
                "- 2 \u0442\u0440\u0435\u043d\u0438\u0440\u043e\u0432\u043a\u0438;",
                "- 1 \u0432\u0435\u0447\u0435\u0440 \u043f\u043e\u0434 weekly review.",
                "",
                "B) \u0420\u0435\u0430\u043b:",
                f"- {plan_b} \u043a\u043b\u044e\u0447\u0435\u0432\u044b\u0445 \u0441\u043b\u043e\u0442\u0430 deep-work;",
                "- 1 \u0442\u0440\u0435\u043d\u0438\u0440\u043e\u0432\u043a\u0430;",
                "- \u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u044b\u0439 \u0431\u0443\u0444\u0435\u0440 30 \u043c\u0438\u043d\u0443\u0442.",
                "",
                "C) \u0410\u0432\u0430\u0440\u0438\u044f:",
                f"- \u0442\u043e\u043b\u044c\u043a\u043e {plan_c} \u043a\u0440\u0438\u0442\u0438\u0447\u043d\u044b\u0439 \u0448\u0430\u0433 \u0432 \u0434\u0435\u043d\u044c;",
                "- \u0440\u0435\u0436\u0438\u043c \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u044d\u043d\u0435\u0440\u0433\u0438\u0438;",
                "- \u043f\u0435\u0440\u0435\u043d\u043e\u0441 \u0432\u0441\u0435\u0433\u043e \u043d\u0435\u043a\u0440\u0438\u0442\u0438\u0447\u043d\u043e\u0433\u043e.",
                "",
                f"\u0413\u043b\u0430\u0432\u043d\u044b\u0439 \u0440\u0438\u0441\u043a \u043d\u0435\u0434\u0435\u043b\u0438: {risk}.",
                "\u0422\u043e\u0447\u043a\u0438 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044f: \u0441\u0440, 14:00 \u0438 \u043f\u0442, 18:00.",
                "\u0415\u0441\u043b\u0438 \u043f\u043e\u0448\u0451\u043b \u0441\u0440\u044b\u0432: /redteam <\u043f\u043b\u0430\u043d>.",
            ]
            await message.reply("\n".join(lines))
            return

        lines_en = [
            "\U0001f9ed Scenario Planning 3x (week)",
            "",
            (
                f"Baseline: energy {avg_energy:.1f}/10, done={done_count}, open={open_count}, "
                f"workouts={fit_total}, due_subs={len(subs_due)}"
            ),
            "",
            "A) Ideal:",
            f"- {plan_a} core deep-work blocks;",
            "- 2 workouts;",
            "- 1 weekly review evening.",
            "",
            "B) Real:",
            f"- {plan_b} core deep-work blocks;",
            "- 1 workout;",
            "- daily 30-min buffer.",
            "",
            "C) Emergency:",
            f"- only {plan_c} critical step per day;",
            "- energy-preservation mode;",
            "- defer all non-critical tasks.",
            "",
            f"Main weekly risk: {risk}.",
            "Control points: Wed 14:00 and Fri 18:00.",
            "If drift starts: /redteam <plan>.",
        ]
        await message.reply("\n".join(lines_en))

    @router.message(Command("legacy"))
    async def legacy_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        _runtime_settings, lang = _resolve_user_runtime_settings(ctx, user_id)
        is_ru = lang == "ru"
        if user_id <= 0:
            await message.reply("No user context.")
            return

        since_7 = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        since_14 = (datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")
        cur_minutes, cur_sessions = focus_stats_recent(user_id=user_id, since_iso=since_7)
        prev_minutes_14d, _ = focus_stats_recent(user_id=user_id, since_iso=since_14)
        prev_minutes = max(0, prev_minutes_14d - cur_minutes)

        cur_hours = cur_minutes / 60.0
        prev_hours = prev_minutes / 60.0
        delta = _fmt_delta(cur_hours, prev_hours)

        if is_ru:
            lines = [
                "\U0001f3db Legacy Progress",
                f"\u0418\u043d\u0432\u0435\u0441\u0442\u0438\u0446\u0438\u0438 \u0432 \u0432\u0430\u0436\u043d\u043e\u0435 \u0437\u0430 7 \u0434\u043d\u0435\u0439: {cur_hours:.1f}\u0447",
                f"\u0421\u0435\u0441\u0441\u0438\u0438 \u0444\u043e\u043a\u0443\u0441\u0430: {cur_sessions}",
                f"\u0414\u0435\u043b\u044c\u0442\u0430 \u043a \u043f\u0440\u043e\u0448\u043b\u043e\u0439 \u043d\u0435\u0434\u0435\u043b\u0435: {delta}\u0447",
                "\u041e\u0440\u0438\u0435\u043d\u0442\u0438\u0440: 5-7\u0447 \u0444\u043e\u043a\u0443\u0441\u0430 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e \u043d\u0430 \u0434\u043e\u043b\u0433\u0443\u044e \u0446\u0435\u043b\u044c.",
            ]
            await message.reply("\n".join(lines))
            return

        lines_en = [
            "\U0001f3db Legacy Progress",
            f"Important work in last 7 days: {cur_hours:.1f}h",
            f"Focus sessions: {cur_sessions}",
            f"Delta vs previous week: {delta}h",
            "Target: keep 5-7h/week of focused work on long-term goals.",
        ]
        await message.reply("\n".join(lines_en))

    return router
