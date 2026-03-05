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
        notes = str(data.get("notes") or "").strip()
        created_at = str(data.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        due_date = str(data.get("due_date") or "").strip() or None
        remind_at = str(data.get("remind_at") or "").strip() or None
        remind_telegram = bool(data.get("remind_telegram", True))
        task_id = tasks.add_task(
            user_id=user_id,
            text=text,
            created_at=created_at,
            notes=notes,
            due_date=due_date,
            remind_at=remind_at,
            remind_telegram=remind_telegram,
        )
        result = {"id": task_id}
        emit_event(
            collector,
            name="tasks.added",
            user_id=user_id,
            payload={
                "task_id": task_id,
                "text": text,
                "notes": notes,
                "due_date": due_date,
                "remind_at": remind_at,
                "remind_telegram": remind_telegram,
            },
        )
        return _response(result, collector, return_events=return_events)

    if cmd == "tasks:calendar":
        limit_raw = data.get("limit", 800)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 800
        limit = max(1, min(1200, limit))
        result = {"items": tasks.list_calendar_tasks(user_id=user_id, limit=limit)}
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

    if cmd == "tasks:update":
        task_id_raw = data.get("task_id")
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            raise ValueError("task_id is required") from None

        has_text = "text" in data
        has_notes = "notes" in data
        has_due_date = "due_date" in data
        has_remind_at = "remind_at" in data
        has_remind_telegram = "remind_telegram" in data
        if not (has_text or has_notes or has_due_date or has_remind_at or has_remind_telegram):
            raise ValueError("no task fields provided")

        text = str(data.get("text") or "").strip() if has_text else None
        if has_text and not text:
            raise ValueError("text cannot be empty")
        notes = str(data.get("notes") or "").strip() if has_notes else None
        due_date = (str(data.get("due_date") or "").strip() or None) if has_due_date else None
        remind_at = (str(data.get("remind_at") or "").strip() or None) if has_remind_at else None
        remind_telegram = bool(data.get("remind_telegram")) if has_remind_telegram else None

        ok = tasks.update_task(
            user_id=user_id,
            todo_id=task_id,
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
        result = {"ok": ok}
        if ok:
            emit_event(
                collector,
                name="tasks.updated",
                user_id=user_id,
                payload={
                    "task_id": task_id,
                    "text": text if has_text else None,
                    "notes": notes if has_notes else None,
                    "due_date": due_date,
                    "remind_at": remind_at,
                    "remind_telegram": remind_telegram,
                },
            )
        return _response(result, collector, return_events=return_events)

    if cmd == "subs:add":
        name = str(data.get("name") or "").strip()
        next_date = str(data.get("next_date") or "").strip()
        period = str(data.get("period") or "").strip().lower()
        if not name or not next_date or not period:
            raise ValueError("name, next_date and period are required")
        created_at = str(data.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        amount_raw = data.get("amount")
        amount: float | None
        if amount_raw is None or str(amount_raw).strip() == "":
            amount = None
        else:
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                raise ValueError("amount must be a number") from None
        currency = str(data.get("currency") or "RUB").strip().upper() or "RUB"
        note = str(data.get("note") or "").strip()
        category = str(data.get("category") or "").strip()
        autopay = bool(data.get("autopay", True))
        remind_days_raw = data.get("remind_days", 3)
        try:
            remind_days = int(remind_days_raw)
        except (TypeError, ValueError):
            remind_days = 3
        sub_id = subs.add_subscription(
            user_id=user_id,
            name=name,
            next_date=next_date,
            period=period,
            created_at=created_at,
            amount=amount,
            currency=currency,
            note=note,
            category=category,
            autopay=autopay,
            remind_days=max(0, remind_days),
        )
        result = {"id": sub_id}
        emit_event(
            collector,
            name="subs.added",
            user_id=user_id,
            payload={
                "sub_id": sub_id,
                "name": name,
                "next_date": next_date,
                "period": period,
                "amount": amount,
                "currency": currency,
                "autopay": autopay,
            },
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
