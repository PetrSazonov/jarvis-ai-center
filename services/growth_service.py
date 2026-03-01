from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from db import (
    daily_checkin_count_between,
    daily_checkin_get,
    daily_checkin_recent,
    fitness_done_count_between,
    fitness_stats_recent,
    focus_stats_recent,
    reflection_count_between,
    subs_due_within,
    todo_done_count_between,
    todo_list_open,
    todo_stats_recent,
)
from services.fitness_plan_service import pick_workout_of_day


TARGET_FOCUS_MIN_PER_WEEK = 250
TARGET_WORKOUTS_PER_WEEK = 4
TARGET_REFLECTIONS_PER_WEEK = 4
MAX_OPEN_TASKS_IN_EXECUTION_DENOM = 10


@dataclass(frozen=True)
class GrowthScores:
    execution: int
    focus: int
    recovery: int
    consistency: int
    growth: int
    index: int
    done_tasks_7d: int
    open_tasks: int
    focus_minutes_7d: int
    focus_sessions_7d: int
    workouts_7d: int
    avg_energy: float | None
    checkin_days_7d: int
    reflections_7d: int


def _lang(lang: str, ru: str, en: str) -> str:
    return ru if lang == "ru" else en


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _pct(value: float, target: float) -> int:
    if target <= 0:
        return 0
    return _clamp_score((value / target) * 100.0)


def _shorten(text: str, limit: int = 84) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(8, limit - 1)].rstrip() + "…"


def _date_window(base_day: date, days: int) -> tuple[date, date]:
    start_day = base_day - timedelta(days=max(0, days - 1))
    end_day_exclusive = base_day + timedelta(days=1)
    return start_day, end_day_exclusive


def _since_iso(start_day: date) -> str:
    return datetime.combine(start_day, time.min).isoformat(timespec="seconds")


def calculate_growth_scores(*, user_id: int, today: date | None = None) -> GrowthScores:
    current = today or date.today()
    week_start, week_end = _date_window(current, 7)
    since_week_iso = _since_iso(week_start)

    done_tasks_7d, open_tasks = todo_stats_recent(user_id=user_id, since_iso=since_week_iso)
    execution_denom = done_tasks_7d + min(MAX_OPEN_TASKS_IN_EXECUTION_DENOM, max(0, open_tasks))
    execution = _pct(done_tasks_7d, max(1, execution_denom))

    focus_minutes_7d, focus_sessions_7d = focus_stats_recent(user_id=user_id, since_iso=since_week_iso)
    focus = _pct(focus_minutes_7d, TARGET_FOCUS_MIN_PER_WEEK)

    workouts_7d, _fit_rows = fitness_stats_recent(user_id=user_id, since_iso=since_week_iso)
    workout_score = _pct(workouts_7d, TARGET_WORKOUTS_PER_WEEK)

    checkins = daily_checkin_recent(user_id=user_id, since_iso=week_start.isoformat(), limit=7)
    energies = [int(row[3]) for row in checkins if row[3] is not None]
    avg_energy = (sum(energies) / len(energies)) if energies else None
    energy_score = _clamp_score((avg_energy if avg_energy is not None else 5.5) * 10.0)
    recovery = _clamp_score(energy_score * 0.7 + workout_score * 0.3)

    checkin_days_7d = daily_checkin_count_between(
        user_id=user_id,
        start_date_iso=week_start.isoformat(),
        end_date_iso=week_end.isoformat(),
    )
    consistency = _pct(checkin_days_7d, 7)

    reflections_7d = reflection_count_between(
        user_id=user_id,
        start_date_iso=week_start.isoformat(),
        end_date_iso=week_end.isoformat(),
    )
    growth = _pct(reflections_7d, TARGET_REFLECTIONS_PER_WEEK)

    index = _clamp_score(
        execution * 0.30
        + focus * 0.25
        + recovery * 0.20
        + consistency * 0.15
        + growth * 0.10
    )

    return GrowthScores(
        execution=execution,
        focus=focus,
        recovery=recovery,
        consistency=consistency,
        growth=growth,
        index=index,
        done_tasks_7d=done_tasks_7d,
        open_tasks=open_tasks,
        focus_minutes_7d=focus_minutes_7d,
        focus_sessions_7d=focus_sessions_7d,
        workouts_7d=workouts_7d,
        avg_energy=avg_energy,
        checkin_days_7d=checkin_days_7d,
        reflections_7d=reflections_7d,
    )


def weakest_metric_key(scores: GrowthScores) -> str:
    pairs = {
        "execution": scores.execution,
        "focus": scores.focus,
        "recovery": scores.recovery,
        "consistency": scores.consistency,
        "growth": scores.growth,
    }
    return min(pairs.items(), key=lambda item: item[1])[0]


def _metric_label(key: str, lang: str) -> str:
    labels_ru = {
        "execution": "Execution",
        "focus": "Focus",
        "recovery": "Recovery",
        "consistency": "Consistency",
        "growth": "Growth",
    }
    labels_en = {
        "execution": "Execution",
        "focus": "Focus",
        "recovery": "Recovery",
        "consistency": "Consistency",
        "growth": "Growth",
    }
    mapping = labels_ru if lang == "ru" else labels_en
    return mapping.get(key, key)


def _next_action_for_metric(key: str, lang: str) -> str:
    actions_ru = {
        "execution": "Сузьте день до 1 MIT и закройте его первым до 12:00.",
        "focus": "Сделайте 1 deep-блок 25-45 минут без мессенджеров.",
        "recovery": "Добавьте recovery-минимум: 20 минут ходьбы или легкая тренировка.",
        "consistency": "Закройте базовый ритуал: короткий /checkin каждый вечер 7 дней.",
        "growth": "Сделайте вечернюю /review day и зафиксируйте правило на завтра.",
    }
    actions_en = {
        "execution": "Reduce the day to 1 MIT and finish it before noon.",
        "focus": "Run one deep-work block for 25-45 minutes without messengers.",
        "recovery": "Add a recovery minimum: 20 minutes walk or easy workout.",
        "consistency": "Lock the base ritual: short /checkin every evening for 7 days.",
        "growth": "Run /review day tonight and set one rule for tomorrow.",
    }
    mapping = actions_ru if lang == "ru" else actions_en
    return mapping.get(key, "")


def build_score_text(*, user_id: int, lang: str = "ru", today: date | None = None) -> str:
    scores = calculate_growth_scores(user_id=user_id, today=today)
    weakest = weakest_metric_key(scores)
    avg_energy_text = (
        "н/д"
        if scores.avg_energy is None and lang == "ru"
        else "-"
        if scores.avg_energy is None
        else f"{scores.avg_energy:.1f}/10"
    )
    lines = [
        _lang(lang, "📈 Score Engine (объективные метрики)", "📈 Score Engine (objective metrics)"),
        "",
        f"Execution: {scores.execution}/100",
        f"Focus: {scores.focus}/100",
        f"Recovery: {scores.recovery}/100",
        f"Consistency: {scores.consistency}/100",
        f"Growth: {scores.growth}/100",
        "",
        f"🎯 Growth Index: {scores.index}/100",
        _lang(
            lang,
            f"Слабое место: {_metric_label(weakest, lang)}. {_next_action_for_metric(weakest, lang)}",
            f"Weakest area: {_metric_label(weakest, lang)}. {_next_action_for_metric(weakest, lang)}",
        ),
        "",
        _lang(
            lang,
            (
                f"7д факт: done={scores.done_tasks_7d}, open={scores.open_tasks}, "
                f"focus={scores.focus_minutes_7d}м/{scores.focus_sessions_7d} сесс., "
                f"workouts={scores.workouts_7d}, checkins={scores.checkin_days_7d}, "
                f"energy={avg_energy_text}, reflections={scores.reflections_7d}"
            ),
            (
                f"7d facts: done={scores.done_tasks_7d}, open={scores.open_tasks}, "
                f"focus={scores.focus_minutes_7d}m/{scores.focus_sessions_7d} sessions, "
                f"workouts={scores.workouts_7d}, checkins={scores.checkin_days_7d}, "
                f"energy={avg_energy_text}, reflections={scores.reflections_7d}"
            ),
        ),
    ]
    return "\n".join(lines)


def _plan_day(*, user_id: int, lang: str, today: date) -> str:
    scores = calculate_growth_scores(user_id=user_id, today=today)
    todos = todo_list_open(user_id=user_id, limit=5)
    mit = _shorten(str(todos[0][1])) if todos else _lang(lang, "Определить 1 MIT на 25 минут.", "Pick 1 MIT for 25 minutes.")
    secondary = [_shorten(str(row[1])) for row in todos[1:3]]
    while len(secondary) < 2:
        secondary.append(
            _lang(
                lang,
                "Поддерживающая задача из бэклога",
                "One supporting backlog task",
            )
        )

    checkin = daily_checkin_get(user_id=user_id, check_date=today.isoformat())
    energy = int(checkin[2]) if checkin and checkin[2] is not None else None
    minimal_day = energy is not None and energy <= 4

    workout = pick_workout_of_day(today)
    workout_line = (
        _lang(lang, "Легкая прогулка 20-30 минут", "Easy 20-30 minute walk")
        if workout is None
        else _shorten(str(workout[1]), limit=72)
    )

    due_subs = subs_due_within(user_id=user_id, days=3)
    subs_line = ""
    if due_subs:
        top = due_subs[0]
        subs_line = _lang(
            lang,
            f"Финансы: проверьте подписку «{_shorten(str(top[1]), 28)}», дата {top[2]}.",
            f"Finance: check subscription “{_shorten(str(top[1]), 28)}”, due {top[2]}.",
        )

    if_then = _lang(
        lang,
        "Если энергия <5/10, то только MIT + recovery-минимум (без штрафов).",
        "If energy <5/10, do MIT + recovery minimum only (no penalties).",
    )
    woop = _lang(
        lang,
        "WOOP: цель = закрыть MIT; препятствие = отвлечения; план = 25 минут в авиарежиме.",
        "WOOP: wish = close MIT; obstacle = distractions; plan = 25 minutes in airplane mode.",
    )
    impl = _lang(
        lang,
        "Implementation Intentions: если потянуло в ленту, сразу 10 минут по MIT.",
        "Implementation Intention: if you drift to feeds, do 10 minutes on MIT immediately.",
    )

    lines = [
        _lang(lang, "🧭 План на день", "🧭 Day plan"),
        _lang(lang, f"Индекс роста: {scores.index}/100", f"Growth index: {scores.index}/100"),
        "",
        f"MIT: {mit}",
        f"2nd: {secondary[0]}",
        f"3rd: {secondary[1]}",
        _lang(
            lang,
            f"Recovery-минимум: {'12 минут легкой нагрузки' if minimal_day else '20-30 минут движения'}",
            f"Recovery minimum: {'12 minutes easy load' if minimal_day else '20-30 minutes of movement'}",
        ),
        _lang(lang, f"Тренировка: {workout_line}", f"Workout: {workout_line}"),
        if_then,
        impl,
        woop,
    ]
    if subs_line:
        lines.extend(["", subs_line])
    return "\n".join(lines)


def _plan_week(*, user_id: int, lang: str, today: date) -> str:
    scores = calculate_growth_scores(user_id=user_id, today=today)
    todos = todo_list_open(user_id=user_id, limit=8)
    priorities = [_shorten(str(row[1]), 64) for row in todos[:3]]
    while len(priorities) < 3:
        priorities.append(_lang(lang, "Сформулировать и закрыть один стратегический шаг", "Define and close one strategic step"))

    weakest = weakest_metric_key(scores)
    constraint = _next_action_for_metric(weakest, lang)
    lines = [
        _lang(lang, "📅 План на неделю", "📅 Week plan"),
        _lang(lang, f"Текущий индекс: {scores.index}/100", f"Current index: {scores.index}/100"),
        "",
        _lang(lang, "3 приоритета:", "3 priorities:"),
        f"1) {priorities[0]}",
        f"2) {priorities[1]}",
        f"3) {priorities[2]}",
        "",
        _lang(
            lang,
            "Ограничения недели:",
            "Week constraints:",
        ),
        _lang(lang, "- Не больше 3 ключевых задач в день.", "- Max 3 key tasks per day."),
        _lang(lang, f"- Фокус метрика: {_metric_label(weakest, lang)}.", f"- Focus metric: {_metric_label(weakest, lang)}."),
        f"- {constraint}",
        "",
        _lang(
            lang,
            "Чекпоинты: вт/чт короткий /review week, вс — /weekly.",
            "Checkpoints: Tue/Thu short /review week, Sun — /weekly.",
        ),
    ]
    return "\n".join(lines)


def _plan_month(*, user_id: int, lang: str, today: date) -> str:
    scores = calculate_growth_scores(user_id=user_id, today=today)
    lines = [
        _lang(lang, "🗓 План на месяц", "🗓 Month plan"),
        _lang(lang, "Формат: 3 outcome-цели с измеримым результатом.", "Format: 3 measurable outcomes."),
        "",
        _lang(lang, "Outcome #1 (Execution): закрыть 20+ задач MIT за месяц.", "Outcome #1 (Execution): close 20+ MIT tasks this month."),
        _lang(lang, "Outcome #2 (Focus): 900+ минут deep work за месяц.", "Outcome #2 (Focus): 900+ minutes of deep work this month."),
        _lang(lang, "Outcome #3 (Recovery): 14+ дней с энергией 7/10 и выше.", "Outcome #3 (Recovery): 14+ days with energy 7/10 or higher."),
        "",
        _lang(
            lang,
            f"Текущая база: индекс {scores.index}/100. Слабая зона: {_metric_label(weakest_metric_key(scores), lang)}.",
            f"Current baseline: index {scores.index}/100. Weak area: {_metric_label(weakest_metric_key(scores), lang)}.",
        ),
        _lang(lang, "Паттерны: WOOP + If-Then + Weekly Review каждое воскресенье.", "Patterns: WOOP + If-Then + Weekly Review every Sunday."),
    ]
    return "\n".join(lines)


def _plan_year(*, user_id: int, lang: str, today: date) -> str:
    scores = calculate_growth_scores(user_id=user_id, today=today)
    lines = [
        _lang(lang, "🧱 План на год (практичный каркас)", "🧱 Year plan (practical framework)"),
        _lang(lang, "Держите не более 3 фокусов:", "Keep no more than 3 annual focuses:"),
        "",
        _lang(lang, "1) Карьера/бизнес: один главный KPI и квартальные вехи.", "1) Career/business: one primary KPI + quarterly milestones."),
        _lang(lang, "2) Здоровье/форма: 150+ тренировок в год, контроль энергии.", "2) Health/fitness: 150+ workouts per year, energy tracking."),
        _lang(lang, "3) Качество решений: Decision Journal + ежемесячный разбор.", "3) Decision quality: Decision Journal + monthly review."),
        "",
        _lang(
            lang,
            f"Стартовая точка сегодня: Growth Index {scores.index}/100.",
            f"Starting point today: Growth Index {scores.index}/100.",
        ),
        _lang(
            lang,
            "Правило прогресса: повышайте сложность только после 2 стабильных недель.",
            "Progress rule: raise complexity only after 2 stable weeks.",
        ),
    ]
    return "\n".join(lines)


def build_plan_text(*, user_id: int, horizon: str, lang: str = "ru", today: date | None = None) -> str:
    current = today or date.today()
    key = (horizon or "").strip().lower()
    if key in {"day", "d", "today", "день", "дня"}:
        return _plan_day(user_id=user_id, lang=lang, today=current)
    if key in {"week", "w", "неделя", "недели"}:
        return _plan_week(user_id=user_id, lang=lang, today=current)
    if key in {"month", "m", "месяц", "месяца"}:
        return _plan_month(user_id=user_id, lang=lang, today=current)
    if key in {"year", "y", "год", "года"}:
        return _plan_year(user_id=user_id, lang=lang, today=current)
    return _lang(
        lang,
        "Формат: /plan day | week | month | year",
        "Format: /plan day | week | month | year",
    )


def _review_day(*, user_id: int, lang: str, today: date) -> str:
    day_start = datetime.combine(today, time.min).isoformat(timespec="seconds")
    day_end = datetime.combine(today + timedelta(days=1), time.min).isoformat(timespec="seconds")
    done_today = todo_done_count_between(user_id=user_id, start_iso=day_start, end_iso=day_end)
    fit_today = fitness_done_count_between(user_id=user_id, start_iso=day_start, end_iso=day_end)
    checkin = daily_checkin_get(user_id=user_id, check_date=today.isoformat())
    energy = int(checkin[2]) if checkin and checkin[2] is not None else None
    done_text = str(checkin[0]).strip() if checkin and checkin[0] else _lang(lang, "не заполнено", "not set")
    carry_text = str(checkin[1]).strip() if checkin and checkin[1] else _lang(lang, "не заполнено", "not set")
    rule = (
        _lang(
            lang,
            "Если усталость вечером высокая, завтра начинаю с 25 минут MIT и без лишних встреч.",
            "If evening fatigue is high, tomorrow starts with 25-minute MIT and no extra meetings.",
        )
        if energy is not None and energy <= 5
        else _lang(
            lang,
            "Если старт затянулся, запускаю /startnow и закрываю первый шаг до 10 минут.",
            "If startup drifts, run /startnow and finish first step within 10 minutes.",
        )
    )
    lines = [
        _lang(lang, "🧾 Review: день", "🧾 Review: day"),
        f"Tasks done: {done_today}",
        f"Workout sessions: {fit_today}",
        _lang(lang, f"Energy: {energy if energy is not None else 'н/д'}/10", f"Energy: {energy if energy is not None else '-'}/10"),
        _lang(lang, f"Done (checkin): {done_text}", f"Done (checkin): {done_text}"),
        _lang(lang, f"Carry (checkin): {carry_text}", f"Carry (checkin): {carry_text}"),
        "",
        _lang(lang, f"Правило на завтра: {rule}", f"Rule for tomorrow: {rule}"),
    ]
    return "\n".join(lines)


def _review_week(*, user_id: int, lang: str, today: date) -> str:
    current = calculate_growth_scores(user_id=user_id, today=today)
    previous = calculate_growth_scores(user_id=user_id, today=today - timedelta(days=7))
    delta = current.index - previous.index
    direction = (
        _lang(lang, "рост", "up")
        if delta > 0
        else _lang(lang, "снижение", "down")
        if delta < 0
        else _lang(lang, "без изменений", "flat")
    )
    lines = [
        _lang(lang, "🧾 Review: неделя", "🧾 Review: week"),
        _lang(lang, f"Growth Index: {current.index}/100 ({direction} {delta:+d})", f"Growth Index: {current.index}/100 ({direction} {delta:+d})"),
        "",
        _lang(
            lang,
            f"Execution {current.execution} | Focus {current.focus} | Recovery {current.recovery} | Consistency {current.consistency} | Growth {current.growth}",
            f"Execution {current.execution} | Focus {current.focus} | Recovery {current.recovery} | Consistency {current.consistency} | Growth {current.growth}",
        ),
        _lang(
            lang,
            f"Факт: задачи {current.done_tasks_7d}, фокус {current.focus_minutes_7d}м, тренировки {current.workouts_7d}, рефлексии {current.reflections_7d}",
            f"Facts: tasks {current.done_tasks_7d}, focus {current.focus_minutes_7d}m, workouts {current.workouts_7d}, reflections {current.reflections_7d}",
        ),
        "",
        _lang(
            lang,
            f"Следующая коррекция: {_next_action_for_metric(weakest_metric_key(current), lang)}",
            f"Next correction: {_next_action_for_metric(weakest_metric_key(current), lang)}",
        ),
    ]
    return "\n".join(lines)


def _review_month(*, user_id: int, lang: str, today: date) -> str:
    month_start, month_end = _date_window(today, 30)
    since_iso = _since_iso(month_start)
    done_30, open_now = todo_stats_recent(user_id=user_id, since_iso=since_iso)
    focus_30, sessions_30 = focus_stats_recent(user_id=user_id, since_iso=since_iso)
    workouts_30, _rows = fitness_stats_recent(user_id=user_id, since_iso=since_iso)
    reflections_30 = reflection_count_between(
        user_id=user_id,
        start_date_iso=month_start.isoformat(),
        end_date_iso=month_end.isoformat(),
    )
    current = calculate_growth_scores(user_id=user_id, today=today)
    lines = [
        _lang(lang, "🧾 Review: месяц", "🧾 Review: month"),
        _lang(lang, f"Текущий индекс: {current.index}/100", f"Current index: {current.index}/100"),
        "",
        _lang(
            lang,
            f"30д факт: done={done_30}, open={open_now}, focus={focus_30}м/{sessions_30} сесс., workouts={workouts_30}, reflections={reflections_30}",
            f"30d facts: done={done_30}, open={open_now}, focus={focus_30}m/{sessions_30} sessions, workouts={workouts_30}, reflections={reflections_30}",
        ),
        _lang(
            lang,
            f"Ключевая зона для следующего месяца: {_metric_label(weakest_metric_key(current), lang)}.",
            f"Key area for next month: {_metric_label(weakest_metric_key(current), lang)}.",
        ),
        _lang(
            lang,
            "Шаблон: 1 MIT в день, 4 deep-блока в неделю, weekly review каждое воскресенье.",
            "Template: 1 MIT/day, 4 deep blocks/week, weekly review every Sunday.",
        ),
    ]
    return "\n".join(lines)


def build_review_text(*, user_id: int, horizon: str, lang: str = "ru", today: date | None = None) -> str:
    current = today or date.today()
    key = (horizon or "").strip().lower()
    if key in {"day", "d", "today", "день", "дня"}:
        return _review_day(user_id=user_id, lang=lang, today=current)
    if key in {"week", "w", "неделя", "недели"}:
        return _review_week(user_id=user_id, lang=lang, today=current)
    if key in {"month", "m", "месяц", "месяца"}:
        return _review_month(user_id=user_id, lang=lang, today=current)
    return _lang(
        lang,
        "Формат: /review day | week | month",
        "Format: /review day | week | month",
    )

