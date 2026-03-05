from __future__ import annotations

from datetime import datetime


def make_event(*, name: str, user_id: int, payload: dict | None = None, ts: str | None = None) -> dict:
    return {
        "name": name,
        "ts": ts or datetime.now().isoformat(timespec="seconds"),
        "user_id": int(user_id),
        "payload": payload or {},
    }


class EventCollector:
    def __init__(self) -> None:
        self._events: list[dict] = []

    def dispatch(self, event: dict) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[dict]:
        return list(self._events)


def emit_event(collector: EventCollector, *, name: str, user_id: int, payload: dict | None = None) -> None:
    collector.dispatch(make_event(name=name, user_id=user_id, payload=payload))

