import logging


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="ts=%(asctime)s level=%(levelname)s name=%(name)s %(message)s",
    )
    # Reduce noisy per-request transport logs; keep our structured app logs visible.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def kv(event: str, **fields: object) -> str:
    parts = [f"event={event}"]
    for key, value in fields.items():
        safe = str(value).replace("\n", "\\n")
        parts.append(f"{key}={safe}")
    return " ".join(parts)
