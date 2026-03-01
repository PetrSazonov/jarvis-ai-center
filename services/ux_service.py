from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def daypart_by_hour(hour: int) -> str:
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 18:
        return "day"
    if 19 <= hour <= 23:
        return "evening"
    return "night"


def adaptive_menu_rows(hour: int) -> list[list[str]]:
    part = daypart_by_hour(hour)
    if part == "morning":
        return [
            ["/today", "/startnow", "/price"],
            ["/digest", "/weather", "/route"],
            ["/fit", "/arena", "/week"],
            ["/session", "/menu", "/help"],
        ]
    if part == "day":
        return [
            ["/today", "/focus", "/todo"],
            ["/route", "/price", "/weather"],
            ["/fit", "/arena", "/week"],
            ["/session", "/menu", "/help"],
        ]
    return [
        ["/today", "/checkin", "/digest"],
        ["/weekly", "/recap", "/todo"],
        ["/fit", "/arena", "/price"],
        ["/session", "/menu", "/help"],
    ]


def adaptive_menu_markup(*, hour: int | None = None) -> ReplyKeyboardMarkup:
    use_hour = datetime.now().hour if hour is None else max(0, min(23, int(hour)))
    rows = adaptive_menu_rows(use_hour)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=item) for item in row] for row in rows],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def memory_chips_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧠 Запомнить", callback_data="ux:mem:remember:1"),
                InlineKeyboardButton(text="🧩 Сделать правилом", callback_data="ux:mem:rule:1"),
            ],
            [
                InlineKeyboardButton(text="📌 Использовать завтра", callback_data="ux:mem:tomorrow:1"),
            ],
        ]
    )


def today_panel_markup(*, has_todo: bool, workout_id: int | None) -> InlineKeyboardMarkup:
    done_target = "top" if has_todo else "none"
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ Done", callback_data=f"ux:today:done:{done_target}"),
            InlineKeyboardButton(text="⏱ Start 25m", callback_data="ux:sprint:start:25"),
            InlineKeyboardButton(text="🔄 Replan", callback_data="ux:today:replan:both"),
        ],
        [
            InlineKeyboardButton(text="😵 2/10", callback_data="ux:mood:set:2"),
            InlineKeyboardButton(text="😐 5/10", callback_data="ux:mood:set:5"),
            InlineKeyboardButton(text="🔥 8/10", callback_data="ux:mood:set:8"),
        ],
        [
            InlineKeyboardButton(text="🧠 Focus Mode", callback_data="ux:sprint:start:45"),
            InlineKeyboardButton(text="🧵 Session", callback_data="ux:session:show:0"),
        ],
    ]
    if workout_id:
        buttons.append([InlineKeyboardButton(text="🏋️ Тренировка дня", callback_data=f"fit:show:{int(workout_id)}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def sprint_done_markup(focus_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Готово", callback_data=f"ux:sprint:done:{int(focus_id)}"),
                InlineKeyboardButton(text="🔄 Еще 15m", callback_data="ux:sprint:start:15"),
            ]
        ]
    )


def digest_story_nav(index: int, total: int) -> InlineKeyboardMarkup:
    safe_total = max(1, total)
    safe_idx = max(0, min(safe_total - 1, index))
    left = (safe_idx - 1) % safe_total
    right = (safe_idx + 1) % safe_total
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data=f"ux:digest:go:{left}"),
                InlineKeyboardButton(text=f"{safe_idx + 1}/{safe_total}", callback_data="ux:digest:noop:0"),
                InlineKeyboardButton(text="➡️", callback_data=f"ux:digest:go:{right}"),
            ],
            [InlineKeyboardButton(text="📄 Полный текст", callback_data="ux:digest:full:0")],
        ]
    )


def week_story_nav(index: int, total: int) -> InlineKeyboardMarkup:
    safe_total = max(1, total)
    safe_idx = max(0, min(safe_total - 1, index))
    left = (safe_idx - 1) % safe_total
    right = (safe_idx + 1) % safe_total
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data=f"ux:week:go:{left}"),
                InlineKeyboardButton(text=f"{safe_idx + 1}/{safe_total}", callback_data="ux:week:noop:0"),
                InlineKeyboardButton(text="➡️", callback_data=f"ux:week:go:{right}"),
            ]
        ]
    )


def _strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _pick_lines(lines: list[str], *, marker: str, stop_markers: tuple[str, ...]) -> list[str]:
    start = -1
    for idx, line in enumerate(lines):
        if line.startswith(marker):
            start = idx
            break
    if start < 0:
        return []
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith(stop_markers) and out:
            break
        out.append(line)
    return out


def _unique_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        clean = (line or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def build_digest_story_screens(text: str) -> list[str]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ["Дайджест временно недоступен."]

    market = _pick_lines(lines, marker="💹", stop_markers=("🏋️", "☀️", "🌤️", "☁️", "🌧️", "❄️", "🗞️", "Рекомендация:", "Факт дня:", "Задание дня:"))
    workout = _pick_lines(lines, marker="🏋️", stop_markers=("☀️", "🌤️", "☁️", "🌧️", "❄️", "🗞️", "Рекомендация:", "Факт дня:", "Задание дня:"))
    weather = [ln for ln in lines if ln.startswith(("☀️", "🌤️", "☁️", "🌧️", "❄️", "⛈️", "Осадки:", "Тренд 5д:"))]
    news = _pick_lines(lines, marker="🗞️", stop_markers=("Рекомендация:", "Факт дня:", "Задание дня:"))
    focus = [ln for ln in lines if ln.startswith(("Рекомендация:", "Факт дня:", "Задание дня:", "🏁", "🏍️", "🤝", "🪐"))]

    header = [ln for ln in lines[:2] if ln]
    screens: list[list[str]] = []
    screens.append(_unique_order([*header, *(focus[:2] if focus else [])]))
    if market:
        screens.append(market)
    if workout or weather:
        screens.append([*(workout[:3] if workout else []), *(weather[:3] if weather else [])])
    if news:
        screens.append(news[:5])
    if focus:
        screens.append(focus[-3:])

    normalized: list[str] = []
    for idx, block in enumerate(screens, start=1):
        block_lines = [x for x in block if x]
        if not block_lines:
            continue
        title = f"📖 Дайджест {idx}/{len(screens)}"
        normalized.append("\n".join([title, "", *block_lines]))
    return normalized or ["Дайджест временно недоступен."]


@dataclass(frozen=True)
class WeekPlaybackMetrics:
    done_tasks: int
    open_tasks: int
    fitness_done: int
    streak_days: int
    avg_energy: float | None
    best_day: str | None
    leaks: list[str]
    next_focus: list[str]


def build_week_playback_screens(metrics: WeekPlaybackMetrics) -> list[str]:
    avg_energy = "-" if metrics.avg_energy is None else f"{metrics.avg_energy:.1f}/10"
    best_day = metrics.best_day or "н/д"
    leaks = ", ".join(metrics.leaks[:3]) if metrics.leaks else "нет явных"
    focuses = "\n".join(f"- {item}" for item in metrics.next_focus[:3]) if metrics.next_focus else "- Закрыть 1 ключевую задачу до обеда"

    return [
        "\n".join(
            [
                "📼 Week Replay 1/5",
                "",
                f"Сделано задач: {metrics.done_tasks}",
                f"Открытых задач: {metrics.open_tasks}",
                f"Тренировок: {metrics.fitness_done}",
            ]
        ),
        "\n".join(
            [
                "📼 Week Replay 2/5",
                "",
                f"Энергия (средняя): {avg_energy}",
                f"Стрик тренировок: {metrics.streak_days} дн.",
            ]
        ),
        "\n".join(
            [
                "📼 Week Replay 3/5",
                "",
                f"Лучший день недели: {best_day}",
                f"Утечки энергии: {leaks}",
            ]
        ),
        "\n".join(
            [
                "📼 Week Replay 4/5",
                "",
                "Риск недели: много второстепенных задач.",
                "План B: до 12:00 закрывать 1 стратегическую задачу.",
            ]
        ),
        "\n".join(
            [
                "📼 Week Replay 5/5",
                "",
                "3 фокуса на новую неделю:",
                focuses,
            ]
        ),
    ]


def render_no_html(text: str) -> str:
    return _strip_html_tags(text)
