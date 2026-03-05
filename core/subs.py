from __future__ import annotations

from datetime import date, timedelta

from db import (
    subs_add,
    subs_delete,
    subs_due_within,
    subs_due_within_detailed,
    subs_get,
    subs_get_detailed,
    subs_list,
    subs_list_detailed,
    subs_update_next_date,
)


PERIOD_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}


def _trim_text(value: str, max_len: int = 42) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "..."


def list_subscriptions(*, user_id: int) -> list[dict[str, str | int]]:
    rows = subs_list_detailed(user_id=user_id)
    items: list[dict[str, str | int]] = []
    for sub_id, name, next_date, period, amount, currency, note, category, autopay, remind_days in rows:
        items.append(
            {
                "id": int(sub_id),
                "name": str(name or ""),
                "next_date": str(next_date or ""),
                "period": str(period or ""),
                "amount": (float(amount) if amount is not None else None),
                "currency": str(currency or "RUB"),
                "note": str(note or ""),
                "category": str(category or ""),
                "autopay": bool(int(autopay or 0)),
                "remind_days": int(remind_days or 0),
            }
        )
    return items


def list_subs(*, user_id: int) -> list[dict[str, str | int]]:
    return list_subscriptions(user_id=user_id)


def due_subscriptions(*, user_id: int, days: int = 7) -> list[dict[str, str | int]]:
    rows = subs_due_within_detailed(user_id=user_id, days=days)
    items: list[dict[str, str | int]] = []
    for sub_id, name, next_date, period, amount, currency, note, category, autopay, remind_days in rows:
        items.append(
            {
                "id": int(sub_id),
                "name": str(name or ""),
                "next_date": str(next_date or ""),
                "period": str(period or ""),
                "amount": (float(amount) if amount is not None else None),
                "currency": str(currency or "RUB"),
                "note": str(note or ""),
                "category": str(category or ""),
                "autopay": bool(int(autopay or 0)),
                "remind_days": int(remind_days or 0),
            }
        )
    return items


def render_subs_list_text(
    *,
    user_id: int,
    lang: str,
    empty_text: str,
    title_text: str,
) -> str:
    items = list_subscriptions(user_id=user_id)
    if not items:
        return empty_text
    today = date.today()
    lines = [title_text]
    for item in items:
        next_date = str(item["next_date"])
        try:
            due = date.fromisoformat(next_date)
            delta = (due - today).days
            if delta >= 0:
                left = f"{delta} дн." if lang == "ru" else f"{delta}d"
            else:
                late = abs(delta)
                left = f"просрочено {late} дн." if lang == "ru" else f"overdue {late}d"
        except ValueError:
            left = next_date
        lines.append(
            f"#{int(item['id'])} {_trim_text(str(item['name']))} — {next_date} ({item['period']}, {left})"
        )
    return "\n".join(lines)


def render_subs_check_text(
    *,
    user_id: int,
    lang: str,
    title_text: str,
    no_due_text: str,
    days: int = 7,
) -> str:
    items = due_subscriptions(user_id=user_id, days=days)
    if not items:
        return f"{title_text}\n\n{no_due_text}"
    lines = [title_text]
    today = date.today()
    for item in items:
        next_date = str(item["next_date"])
        try:
            due = date.fromisoformat(next_date)
            delta = (due - today).days
            days_text = f"{delta} дн." if lang == "ru" else f"{delta}d"
        except ValueError:
            days_text = next_date
        lines.append(
            f"#{int(item['id'])} {_trim_text(str(item['name']))} — {next_date} ({item['period']}, {days_text})"
        )
    return "\n".join(lines)


def add_subscription(
    *,
    user_id: int,
    name: str,
    next_date: str,
    period: str,
    created_at: str,
    amount: float | None = None,
    currency: str = "RUB",
    note: str = "",
    category: str = "",
    autopay: bool = True,
    remind_days: int = 3,
) -> int:
    return int(
        subs_add(
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
            remind_days=remind_days,
        )
    )


def delete_subscription(*, user_id: int, sub_id: int) -> bool:
    return bool(subs_delete(user_id=user_id, sub_id=sub_id))


def get_subscription(*, user_id: int, sub_id: int) -> tuple[int, str, str, str] | None:
    row = subs_get(user_id=user_id, sub_id=sub_id)
    if not row:
        return None
    return int(row[0]), str(row[1]), str(row[2]), str(row[3])


def get_subscription_detailed(
    *,
    user_id: int,
    sub_id: int,
) -> dict[str, str | int | float | bool | None] | None:
    row = subs_get_detailed(user_id=user_id, sub_id=sub_id)
    if not row:
        return None
    return {
        "id": int(row[0]),
        "name": str(row[1]),
        "next_date": str(row[2]),
        "period": str(row[3]),
        "amount": (float(row[4]) if row[4] is not None else None),
        "currency": str(row[5] or "RUB"),
        "note": str(row[6] or ""),
        "category": str(row[7] or ""),
        "autopay": bool(int(row[8] or 0)),
        "remind_days": int(row[9] or 0),
    }


def advance_sub_date(current_iso: str, period: str, steps: int) -> str | None:
    try:
        current = date.fromisoformat(current_iso)
    except ValueError:
        return None
    days = PERIOD_DAYS.get((period or "").strip().lower())
    if not days:
        return None
    return (current + timedelta(days=days * max(1, steps))).isoformat()


def roll_subscription_date(*, user_id: int, sub_id: int, steps: int, updated_at: str) -> str | None:
    row = get_subscription(user_id=user_id, sub_id=sub_id)
    if not row:
        return None
    _id, _name, next_date, period = row
    new_date = advance_sub_date(next_date, period, steps)
    if not new_date:
        return None
    ok = subs_update_next_date(user_id=user_id, sub_id=sub_id, next_date=new_date, updated_at=updated_at)
    return new_date if ok else None
