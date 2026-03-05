from __future__ import annotations

from datetime import date

from db import daily_checkin_get, memory_get, todo_list_open, user_settings_get_full
from services.fitness_plan_service import pick_workout_of_day


def get_today_overview(*, user_id: int) -> dict[str, object]:
    profile = user_settings_get_full(user_id)
    session_name = memory_get(user_id=user_id, key="active_session") or "work"
    today_iso = date.today().isoformat()
    checkin = daily_checkin_get(user_id=user_id, check_date=today_iso)
    energy = int(checkin[2]) if checkin and checkin[2] is not None else None

    todos = []
    for todo_id, text, created_at, due_date, remind_at, notes in todo_list_open(user_id=user_id, limit=3, include_meta=True):
        todos.append(
            {
                "id": int(todo_id),
                "text": str(text or ""),
                "created_at": str(created_at or ""),
                "due_date": str(due_date or ""),
                "remind_at": str(remind_at or ""),
                "notes": str(notes or ""),
            }
        )

    workout = pick_workout_of_day()
    workout_data: dict[str, object] | None = None
    if workout:
        workout_data = {
            "id": int(workout[0]),
            "title": str(workout[1] or ""),
        }

    return {
        "date": today_iso,
        "day_mode": str(profile.get("day_mode") or "workday"),
        "session": session_name,
        "energy": energy,
        "todos_top": todos,
        "workout": workout_data,
        "next_actions": ["/todo", "/focus", "/checkin"],
    }


def get_today(*, user_id: int) -> dict[str, object]:
    return get_today_overview(user_id=user_id)
