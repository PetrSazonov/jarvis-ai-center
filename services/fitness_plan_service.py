from datetime import date, datetime

from core.settings import Settings
from db import fitness_list_workouts_by_tag, get_cache_value, set_cache_value
from services.http_service import ExternalAPIError
from services.llm_service import build_prompt, call_ollama


PROGRAM_ANCHOR = date(2026, 1, 5)
FIT_PLAN_CACHE_TTL_SECONDS = 1800


def program_week(today: date | None = None) -> int:
    current = today or datetime.now().date()
    delta_weeks = max(0, (current - PROGRAM_ANCHOR).days // 7)
    return (delta_weeks % 4) + 1


def weekday_plan_slot(today: date | None = None) -> tuple[str, str]:
    current = today or datetime.now().date()
    slots = {
        0: ("Сила верх", "pull"),
        2: ("Ноги и корпус", "legs"),
        4: ("Кондиция и берпи", "burpee"),
    }
    return slots.get(current.weekday(), ("Восстановление", "recovery"))


def pick_workout_of_day(today: date | None = None):
    current = today or datetime.now().date()
    _day_name, focus_tag = weekday_plan_slot(current)
    tagged_rows = fitness_list_workouts_by_tag(focus_tag)
    rows = tagged_rows if tagged_rows else fitness_list_workouts_by_tag(None)
    if not rows:
        return None
    idx = current.toordinal() % len(rows)
    return rows[idx]


def program_summary(today: date | None = None) -> str:
    week = program_week(today)
    day_name, focus_tag = weekday_plan_slot(today)
    week_load = {
        1: "Неделя 1: вход в цикл (RPE 6-7, оставляй 2-3 повтора в запасе).",
        2: "Неделя 2: рабочая (RPE 7-8, старайся добавить 1-2 повтора).",
        3: "Неделя 3: пиковая (RPE 8-9, держи технику, отдых 90-120 сек).",
        4: "Неделя 4: разгрузка (объем -30-40%, легкий темп).",
    }[week]
    return (
        f"План 4 недели • неделя {week}/4\n"
        "Пн: сила верх | Ср: ноги+кор | Пт: кондиция\n"
        f"Сегодня: {day_name} (фокус #{focus_tag})\n"
        f"{week_load}"
    )


def fmt_minutes(duration_sec: int) -> str:
    if duration_sec <= 0:
        return "?"
    return str(max(1, round(duration_sec / 60)))


def render_plain_workout_plan(workout: dict) -> str:
    duration = fmt_minutes(workout["duration_sec"]) if workout.get("duration_sec") else "25-35"
    difficulty = int(workout.get("difficulty") or 2)
    rounds = 4 if difficulty <= 2 else 5 if difficulty >= 4 else 4
    rest = "60-75" if difficulty <= 2 else "75-90" if difficulty <= 3 else "90-120"
    notes = (workout.get("notes") or "").strip()
    lines = [f"🧠 План: {workout['title']}"]
    lines.append(f"Длительность: ~{duration} мин | Рабочих кругов: {rounds}")
    lines.append("1. Разминка 6 мин: суставная + динамика корпуса/плеч/таза.")
    if notes:
        lines.append(f"2. Основной блок ({rounds} круга): {notes}")
    else:
        lines.append(
            "2. Основной блок: приседания 20-28, отжимания 14-22, тяга/кор 12-16, планка 45-60 сек."
        )
    lines.append(f"3. Паузы между кругами: {rest} сек.")
    lines.append("4. Заминка 5 мин: дыхание + мобилизация.")
    lines.append("Фокус: плотная работа в технике, без провала в качестве.")
    return "\n".join(lines)


def fit_plan_cache_key(workout: dict) -> str:
    workout_id = int(workout.get("id") or 0)
    stamp = str(workout.get("created_at") or "")
    return f"fit_plan:{workout_id}:{stamp}"


async def build_ai_workout_plan(settings: Settings, workout: dict) -> str:
    fallback = render_plain_workout_plan(workout)
    cache_key = fit_plan_cache_key(workout)
    cached = get_cache_value(cache_key)
    if cached and cached[0] and cached[1]:
        try:
            age = (datetime.now() - datetime.fromisoformat(str(cached[1]))).total_seconds()
        except ValueError:
            age = FIT_PLAN_CACHE_TTL_SECONDS + 1
        if age <= FIT_PLAN_CACHE_TTL_SECONDS:
            return str(cached[0])

    prompt = build_prompt(
        history=[],
        user_message=(
            "Составь удобный и короткий план домашней тренировки на русском языке.\n"
            "Формат строго:\n"
            "## <название>\n"
            "**Длительность:** <минуты>\n"
            "1. **Разминка (N мин):** ...\n"
            "2. **Основной блок (4-6 кругов):** список упражнений с рабочими диапазонами\n"
            "3. **Паузы:** ...\n"
            "4. **Заминка (N мин):** ...\n"
            "**Фокус дня:** ...\n"
            "Правила:\n"
            "- Плотность выше среднего, не занижай объем без причины.\n"
            "- Для базовых движений не предлагай слишком слабые диапазоны.\n"
            "- Без воды, максимум 900 символов.\n\n"
            f"Название: {workout['title']}\n"
            f"Инвентарь: {workout.get('equipment') or 'нет'}\n"
            f"Сложность: {workout.get('difficulty')} из 5\n"
            f"Длительность: {workout.get('duration_sec')} сек\n"
            f"Заметки: {workout.get('notes') or 'нет'}"
        ),
        settings=settings,
    )
    try:
        text = (await call_ollama(prompt, settings)).strip()
    except ExternalAPIError:
        return fallback
    if not text:
        return fallback
    if len(text) > 1200:
        text = text[:1200].rstrip() + "..."
    set_cache_value(cache_key, text, datetime.now().isoformat(timespec="seconds"))
    return text
