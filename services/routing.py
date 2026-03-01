from dataclasses import dataclass
from enum import Enum


class RouteType(str, Enum):
    KNOWN_COMMAND = "known_command"
    UNKNOWN_COMMAND = "unknown_command"
    DATE_TIME = "date_time"
    PLAIN_TEXT = "plain_text"
    EMPTY = "empty"


@dataclass(frozen=True)
class RouteDecision:
    route_type: RouteType
    command: str | None = None


def extract_command(text: str | None) -> str | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    token = raw.split()[0]
    cmd = token[1:]
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    return cmd.lower() if cmd else None


def determine_route(text: str | None, known_commands: set[str], is_date_time_question: bool) -> RouteDecision:
    cleaned = (text or "").strip()
    if not cleaned:
        return RouteDecision(RouteType.EMPTY)

    command = extract_command(cleaned)
    if command:
        if command in known_commands:
            return RouteDecision(RouteType.KNOWN_COMMAND, command=command)
        return RouteDecision(RouteType.UNKNOWN_COMMAND, command=command)

    if is_date_time_question:
        return RouteDecision(RouteType.DATE_TIME)

    return RouteDecision(RouteType.PLAIN_TEXT)


def should_persist_history(decision: RouteDecision) -> bool:
    return decision.route_type == RouteType.PLAIN_TEXT
