from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.fitness_plan_service import fmt_minutes


def fmt_difficulty(level: int) -> str:
    clamped = max(1, min(5, int(level or 1)))
    return "⚡" * clamped


def workout_card(workout: dict, next_hint: str | None = None) -> str:
    lines = [f"🏋️ {workout['title']} | {fmt_minutes(int(workout.get('duration_sec') or 0))} мин"]
    lines.append(f"Инвентарь: {workout.get('equipment') or 'нет'}")
    lines.append(f"Сложность: {fmt_difficulty(int(workout.get('difficulty') or 1))}")
    notes = str(workout.get("notes") or "").strip()
    if notes:
        lines.append(f"Заметки: {notes}")
    lines.append(f"ID: {workout['id']}")
    if next_hint:
        lines.append(f"🎯 Следующий шаг: {next_hint}")
    return "\n".join(lines)


def workout_actions(workout_id: int, is_favorite: bool) -> InlineKeyboardMarkup:
    fav_text = "✖ Убрать из избранного" if is_favorite else "⭐ В избранное"
    fav_action = "unfav" if is_favorite else "fav"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧠 План", callback_data=f"fit:send:{workout_id}")],
            [InlineKeyboardButton(text="✅ Сделал", callback_data=f"fit:done:{workout_id}")],
            [InlineKeyboardButton(text=fav_text, callback_data=f"fit:{fav_action}:{workout_id}")],
            [InlineKeyboardButton(text="➡️ Следующая", callback_data="fit:next:0")],
        ]
    )


def menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔥 Тренировка дня", callback_data="fit:today:0"),
                InlineKeyboardButton(text="🎲 Случайная", callback_data="fit:next:0"),
            ],
            [
                InlineKeyboardButton(text="📚 Список", callback_data="fit:list:1"),
                InlineKeyboardButton(text="🗺 План", callback_data="fit:plan:0"),
            ],
            [
                InlineKeyboardButton(text="🔁 Повторить", callback_data="fit:repeat:0"),
                InlineKeyboardButton(text="🗓 Неделя", callback_data="fit:week:0"),
            ],
            [InlineKeyboardButton(text="📈 Статистика", callback_data="fit:stats:0")],
        ]
    )


def list_markup(page: int, total: int, workouts: list[dict], page_size: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + page_size - 1) // page_size)
    keyboard: list[list[InlineKeyboardButton]] = []
    for workout in workouts:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"🏋️ {workout['id']} - {workout['title'][:42]}",
                    callback_data=f"fit:show:{workout['id']}",
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"fit:list:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"fit:list:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="⬆️ Меню", callback_data="fit:menu:0")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
