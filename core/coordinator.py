from __future__ import annotations

from datetime import datetime

from core import day_os, subs, tasks
from core.events import EventCollector, emit_event


def _response(result: dict, collector: EventCollector, *, return_events: bool) -> dict:
    if not return_events:
        return result
    return {"result": result, "events": collector.events}


def handle_command(
    user_id: int,
    command: str,
    payload: dict | None = None,
    *,
    return_events: bool = False,
) -> dict:
    cmd = (command or "").strip().lower()
    data = payload or {}
    collector = EventCollector()

    if cmd == "today":
        result = day_os.get_today(user_id=user_id)
        return _response(result, collector, return_events=return_events)

    if cmd == "tasks:list":
        limit_raw = data.get("limit", 20)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(100, limit))
        result = {"items": tasks.list_tasks(user_id=user_id, limit=limit)}
        return _response(result, collector, return_events=return_events)

    if cmd == "tasks:add":
        text = str(data.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        created_at = str(data.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        task_id = tasks.add_task(user_id=user_id, text=text, created_at=created_at)
        result = {"id": task_id}
        emit_event(
            collector,
            name="tasks.added",
            user_id=user_id,
            payload={"task_id": task_id, "text": text},
        )
        return _response(result, collector, return_events=return_events)

    if cmd == "subs:list":
        result = {"items": subs.list_subs(user_id=user_id)}
        return _response(result, collector, return_events=return_events)

    if cmd == "tasks:done":
        task_id_raw = data.get("task_id")
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            raise ValueError("task_id is required") from None
        done_at = str(data.get("done_at") or datetime.now().isoformat(timespec="seconds"))
        ok = tasks.mark_task_done(user_id=user_id, todo_id=task_id, done_at=done_at)
        result = {"ok": ok}
        if ok:
            emit_event(
                collector,
                name="tasks.completed",
                user_id=user_id,
                payload={"task_id": task_id},
            )
        return _response(result, collector, return_events=return_events)

    if cmd == "tasks:delete":
        task_id_raw = data.get("task_id")
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            raise ValueError("task_id is required") from None
        ok = tasks.delete_task(user_id=user_id, todo_id=task_id)
        result = {"ok": ok}
        if ok:
            emit_event(
                collector,
                name="tasks.deleted",
                user_id=user_id,
                payload={"task_id": task_id},
            )
        return _response(result, collector, return_events=return_events)

    if cmd == "subs:add":
        name = str(data.get("name") or "").strip()
        next_date = str(data.get("next_date") or "").strip()
        period = str(data.get("period") or "").strip().lower()
        if not name or not next_date or not period:
            raise ValueError("name, next_date and period are required")
        created_at = str(data.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        sub_id = subs.add_subscription(
            user_id=user_id,
            name=name,
            next_date=next_date,
            period=period,
            created_at=created_at,
        )
        result = {"id": sub_id}
        emit_event(
            collector,
            name="subs.added",
            user_id=user_id,
            payload={"sub_id": sub_id, "name": name, "next_date": next_date, "period": period},
        )
        return _response(result, collector, return_events=return_events)

    if cmd == "subs:delete":
        sub_id_raw = data.get("sub_id")
        try:
            sub_id = int(sub_id_raw)
        except (TypeError, ValueError):
            raise ValueError("sub_id is required") from None
        ok = subs.delete_subscription(user_id=user_id, sub_id=sub_id)
        result = {"ok": ok}
        if ok:
            emit_event(
                collector,
                name="subs.deleted",
                user_id=user_id,
                payload={"sub_id": sub_id},
            )
        return _response(result, collector, return_events=return_events)

    if cmd == "subs:roll":
        sub_id_raw = data.get("sub_id")
        try:
            sub_id = int(sub_id_raw)
        except (TypeError, ValueError):
            raise ValueError("sub_id is required") from None
        steps_raw = data.get("steps", 1)
        try:
            steps = int(steps_raw)
        except (TypeError, ValueError):
            steps = 1
        updated_at = str(data.get("updated_at") or datetime.now().isoformat(timespec="seconds"))
        new_date = subs.roll_subscription_date(
            user_id=user_id,
            sub_id=sub_id,
            steps=max(1, steps),
            updated_at=updated_at,
        )
        result = {"ok": bool(new_date), "new_date": new_date}
        if new_date:
            emit_event(
                collector,
                name="subs.rolled",
                user_id=user_id,
                payload={"sub_id": sub_id, "steps": max(1, steps), "new_date": new_date},
            )
        return _response(result, collector, return_events=return_events)

    raise ValueError(f"unsupported command: {command}")
