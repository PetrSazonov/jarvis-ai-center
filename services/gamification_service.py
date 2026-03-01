from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from db import (
    daily_checkin_get,
    fitness_done_count_between,
    fitness_current_streak_days,
    get_cache_value,
    set_cache_value,
    todo_done_count_between,
)


@dataclass(frozen=True)
class BossBattleStatus:
    boss_name: str
    damage_pct: int
    hp_left_pct: int
    completed: bool
    rank_title: str
    done_tasks: int
    workouts_done: int
    streak_days: int


@dataclass(frozen=True)
class DailyArenaStatus:
    today_score: int
    yesterday_score: int
    today_done_tasks: int
    yesterday_done_tasks: int
    today_workouts: int
    yesterday_workouts: int
    today_energy: int | None
    yesterday_energy: int | None
    won_today: bool


_BOSSES = (
    "Дисциплина",
    "Фокус",
    "Энергия",
    "Приоритеты",
    "Анти-шум",
)

_RESCUE_QUESTS = (
    "3 минуты: 20 отжиманий + 20 приседаний + 30 секунд планки.",
    "5 минут: закрыть один микро-шаг по самой важной задаче.",
    "7 минут: уборка рабочего стола + 1 заметка с планом на завтра.",
    "4 минуты: дыхание 4-4-4 + 1 короткий фокус-блок 3 минуты.",
)


def _day_start_iso(day: date) -> str:
    return datetime.combine(day, datetime.min.time()).isoformat(timespec="seconds")


def _cache_key_rescue(user_id: int, day: date) -> str:
    return f"ux:rescue:{user_id}:{day.isoformat()}"


def _count_todo_done_for_day(*, user_id: int, day: date) -> int:
    start = _day_start_iso(day)
    next_start = _day_start_iso(day + timedelta(days=1))
    return todo_done_count_between(user_id=user_id, start_iso=start, end_iso=next_start)


def _count_fitness_done_for_day(*, user_id: int, day: date) -> int:
    start = _day_start_iso(day)
    next_start = _day_start_iso(day + timedelta(days=1))
    return fitness_done_count_between(user_id=user_id, start_iso=start, end_iso=next_start)


def _energy_for_day(*, user_id: int, day: date) -> int | None:
    row = daily_checkin_get(user_id=user_id, check_date=day.isoformat())
    if not row:
        return None
    value = row[2]
    return int(value) if value is not None else None


def _weekly_boss_name(today: date) -> str:
    # Stable weekly boss selection.
    index = (today.isocalendar().week + today.year) % len(_BOSSES)
    return _BOSSES[index]


def prestige_title(*, progress_points: int) -> str:
    if progress_points < 90:
        return "Operator I"
    if progress_points < 180:
        return "Strategist II"
    return "Commander III"


def build_boss_battle_status(*, user_id: int, today: date | None = None) -> BossBattleStatus:
    cur = today or date.today()
    week_start = cur - timedelta(days=cur.weekday())
    start_iso = _day_start_iso(week_start)
    end_iso = _day_start_iso(cur + timedelta(days=1))
    done_tasks = todo_done_count_between(user_id=user_id, start_iso=start_iso, end_iso=end_iso)
    workouts_done = fitness_done_count_between(user_id=user_id, start_iso=start_iso, end_iso=end_iso)
    streak_days = fitness_current_streak_days(user_id=user_id)

    damage_raw = int(done_tasks) * 7 + int(workouts_done) * 14 + min(7, int(streak_days)) * 4
    damage_pct = max(0, min(100, damage_raw))
    hp_left = max(0, 100 - damage_pct)
    points = int(done_tasks) * 5 + int(workouts_done) * 18 + int(streak_days) * 3

    return BossBattleStatus(
        boss_name=_weekly_boss_name(cur),
        damage_pct=damage_pct,
        hp_left_pct=hp_left,
        completed=damage_pct >= 100,
        rank_title=prestige_title(progress_points=points),
        done_tasks=int(done_tasks),
        workouts_done=int(workouts_done),
        streak_days=int(streak_days),
    )


def build_daily_arena_status(*, user_id: int, today: date | None = None) -> DailyArenaStatus:
    cur = today or date.today()
    prev = cur - timedelta(days=1)

    t_done = _count_todo_done_for_day(user_id=user_id, day=cur)
    y_done = _count_todo_done_for_day(user_id=user_id, day=prev)
    t_fit = _count_fitness_done_for_day(user_id=user_id, day=cur)
    y_fit = _count_fitness_done_for_day(user_id=user_id, day=prev)
    t_energy = _energy_for_day(user_id=user_id, day=cur)
    y_energy = _energy_for_day(user_id=user_id, day=prev)

    t_energy_safe = t_energy if t_energy is not None else 0
    y_energy_safe = y_energy if y_energy is not None else 0
    t_score = t_done * 10 + t_fit * 20 + t_energy_safe * 3
    y_score = y_done * 10 + y_fit * 20 + y_energy_safe * 3

    return DailyArenaStatus(
        today_score=t_score,
        yesterday_score=y_score,
        today_done_tasks=t_done,
        yesterday_done_tasks=y_done,
        today_workouts=t_fit,
        yesterday_workouts=y_fit,
        today_energy=t_energy,
        yesterday_energy=y_energy,
        won_today=t_score >= y_score,
    )


def rescue_completed_today(*, user_id: int, today: date | None = None) -> bool:
    cur = today or date.today()
    row = get_cache_value(_cache_key_rescue(user_id, cur))
    return bool(row and str(row[0]) == "1")


def mark_rescue_completed(*, user_id: int, now: datetime | None = None) -> None:
    current = now or datetime.now()
    set_cache_value(
        _cache_key_rescue(user_id, current.date()),
        "1",
        current.isoformat(timespec="seconds"),
    )


def rescue_needed_today(*, user_id: int, today: date | None = None) -> bool:
    cur = today or date.today()
    if rescue_completed_today(user_id=user_id, today=cur):
        return False
    done_today = _count_todo_done_for_day(user_id=user_id, day=cur)
    fit_today = _count_fitness_done_for_day(user_id=user_id, day=cur)
    energy_today = _energy_for_day(user_id=user_id, day=cur)
    low_energy = energy_today is not None and energy_today <= 4
    return (done_today + fit_today) == 0 or low_energy


def build_rescue_quest_text(*, user_id: int, today: date | None = None) -> str:
    cur = today or date.today()
    idx = (user_id + cur.toordinal()) % len(_RESCUE_QUESTS)
    return _RESCUE_QUESTS[idx]


def build_boss_text(*, user_id: int, today: date | None = None) -> str:
    status = build_boss_battle_status(user_id=user_id, today=today)
    health_bar_units = 10
    filled = max(0, min(health_bar_units, (100 - status.hp_left_pct) // 10))
    bar = "🟥" * filled + "⬜️" * (health_bar_units - filled)
    if status.completed:
        finale = f"🏆 Босс недели побежден. Титул: {status.rank_title}"
    else:
        finale = f"🎯 Добей босса: осталось {status.hp_left_pct}% HP."
    return "\n".join(
        [
            f"🧨 Boss Battle Week: {status.boss_name}",
            f"Урон боссу: {status.damage_pct}% | HP: {status.hp_left_pct}%",
            bar,
            f"Метрики: deep-tasks {status.done_tasks}, тренировки {status.workouts_done}, streak {status.streak_days}д",
            finale,
        ]
    )


def build_arena_text(*, user_id: int, today: date | None = None) -> str:
    arena = build_daily_arena_status(user_id=user_id, today=today)
    result = "Победа над вчерашним собой ✅" if arena.won_today else "Пока отстаешь от вчерашнего ⚠️"
    t_energy = "-" if arena.today_energy is None else str(arena.today_energy)
    y_energy = "-" if arena.yesterday_energy is None else str(arena.yesterday_energy)
    return "\n".join(
        [
            "⚔️ Daily Arena: Ты vs Вчерашний Ты",
            f"Сегодня: score {arena.today_score} (задачи {arena.today_done_tasks}, фит {arena.today_workouts}, энергия {t_energy}/10)",
            f"Вчера: score {arena.yesterday_score} (задачи {arena.yesterday_done_tasks}, фит {arena.yesterday_workouts}, энергия {y_energy}/10)",
            result,
        ]
    )


def build_cinematic_weekly_recap(*, user_id: int, today: date | None = None) -> str:
    status = build_boss_battle_status(user_id=user_id, today=today)
    arena = build_daily_arena_status(user_id=user_id, today=today)
    victory = (
        f"Главная победа: {status.workouts_done} тренировок и {status.done_tasks} deep-task за неделю."
        if status.done_tasks + status.workouts_done > 0
        else "Главная победа: ты не выпал из трека и продолжаешь движение."
    )
    fail = (
        "Главный провал: слабая интенсивность в начале недели."
        if status.damage_pct < 40
        else "Главный провал: перегрев в середине недели, не хватало восстановления."
    )
    turn = (
        "Поворотный момент: ты перегнал вчерашний темп."
        if arena.won_today
        else "Поворотный момент: есть шанс развернуть неделю через Rescue и 1 deep-task."
    )
    mission = (
        "Следующая миссия: 2 deep-task до обеда + 1 тренировка + вечерний check-in."
    )
    slogan = (
        "Слоган недели: стабильность бьет мотивацию."
        if status.completed
        else "Слоган недели: маленький шаг каждый день — это большой отрыв на дистанции."
    )
    return "\n".join(
        [
            "🎬 Cinematic Weekly Recap",
            f"🏅 {victory}",
            f"🕳 {fail}",
            f"🧭 {turn}",
            f"🚀 {mission}",
            f"🪧 {slogan}",
        ]
    )
