from __future__ import annotations

from db import (
    todo_add,
    todo_delete,
    todo_list_calendar,
    todo_list_open,
    todo_mark_done,
    todo_update_item,
    todo_update_schedule,
)


def _trim_text(value: str, max_len: int = 84) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "..."


def list_tasks(*, user_id: int, limit: int = 20) -> list[dict[str, str | int]]:
    rows = todo_list_open(user_id=user_id, limit=limit, include_meta=True)
    items: list[dict[str, str | int]] = []
    for todo_id, text, created_at, due_date, remind_at, notes in rows:
        items.append(
            {
                "id": int(todo_id),
                "text": str(text or ""),
                "created_at": str(created_at or ""),
                "due_date": str(due_date or ""),
                "remind_at": str(remind_at or ""),
                "notes": str(notes or ""),
            }
        )
    return items


def render_tasks_text(
    *,
    user_id: int,
    empty_text: str,
    title_text: str,
    max_len: int = 84,
) -> str:
    items = list_tasks(user_id=user_id, limit=20)
    if not items:
        return empty_text
    lines = [title_text]
    for item in items:
        lines.append(f"{int(item['id'])}. {_trim_text(str(item['text']), max_len)}")
    return "\n".join(lines)


def add_task(
    *,
    user_id: int,
    text: str,
    created_at: str,
    notes: str | None = None,
    due_date: str | None = None,
    remind_at: str | None = None,
    remind_telegram: bool = True,
) -> int:
    return int(
        todo_add(
            user_id=user_id,
            text=text,
            created_at=created_at,
            notes=notes,
            due_date=due_date,
            remind_at=remind_at,
            remind_telegram=remind_telegram,
        )
    )


def mark_task_done(*, user_id: int, todo_id: int, done_at: str) -> bool:
    return bool(todo_mark_done(user_id=user_id, todo_id=todo_id, done_at=done_at))


def delete_task(*, user_id: int, todo_id: int) -> bool:
    return bool(todo_delete(user_id=user_id, todo_id=todo_id))


def update_task_schedule(
    *,
    user_id: int,
    todo_id: int,
    due_date: str | None = None,
    remind_at: str | None = None,
    remind_telegram: bool = True,
) -> bool:
    return bool(
        todo_update_schedule(
            user_id=user_id,
            todo_id=todo_id,
            due_date=due_date,
            remind_at=remind_at,
            remind_telegram=remind_telegram,
        )
    )


def update_task(
    *,
    user_id: int,
    todo_id: int,
    text: str | None = None,
    has_text: bool = False,
    notes: str | None = None,
    has_notes: bool = False,
    due_date: str | None = None,
    has_due_date: bool = False,
    remind_at: str | None = None,
    has_remind_at: bool = False,
    remind_telegram: bool | None = None,
    has_remind_telegram: bool = False,
) -> bool:
    return bool(
        todo_update_item(
            user_id=user_id,
            todo_id=todo_id,
            text=text,
            has_text=has_text,
            notes=notes,
            has_notes=has_notes,
            due_date=due_date,
            has_due_date=has_due_date,
            remind_at=remind_at,
            has_remind_at=has_remind_at,
            remind_telegram=remind_telegram,
            has_remind_telegram=has_remind_telegram,
        )
    )


def list_calendar_tasks(*, user_id: int, limit: int = 800) -> list[dict[str, str | int]]:
    rows = todo_list_calendar(user_id=user_id, limit=limit)
    items: list[dict[str, str | int]] = []
    for todo_id, text, status, created_at, done_at, due_date, remind_at, notes in rows:
        items.append(
            {
                "id": int(todo_id),
                "text": str(text or ""),
                "status": str(status or ""),
                "created_at": str(created_at or ""),
                "done_at": str(done_at or ""),
                "due_date": str(due_date or ""),
                "remind_at": str(remind_at or ""),
                "notes": str(notes or ""),
            }
        )
    return items
