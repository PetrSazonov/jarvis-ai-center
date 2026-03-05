from __future__ import annotations

import asyncio
import email
import imaplib
import os
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_GLOBS = ("*.md", "*.txt", "*.json", "*.csv")


def _env_bool(key: str, default: bool = False) -> bool:
    raw = str(os.getenv(key, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int, *, min_value: int = 1, max_value: int = 500) -> int:
    raw = str(os.getenv(key, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _short_text(text: str, limit: int = 220) -> str:
    clean = " ".join((text or "").replace("\n", " ").replace("\r", " ").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _decode_mime(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value).strip()


def _parse_email_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().isoformat(timespec="seconds")
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def _extract_text_from_email(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = str(part.get_content_type() or "").lower()
            content_disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in content_disp:
                continue
            if content_type != "text/plain":
                continue
            payload = part.get_payload(decode=True) or b""
            charset = str(part.get_content_charset() or "utf-8")
            try:
                return payload.decode(charset, errors="ignore")
            except Exception:
                return payload.decode("utf-8", errors="ignore")
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = str(msg.get_content_charset() or "utf-8")
    try:
        return payload.decode(charset, errors="ignore")
    except Exception:
        return payload.decode("utf-8", errors="ignore")


def _imap_config() -> dict[str, Any]:
    return {
        "enabled": _env_bool("INGEST_IMAP_ENABLED", False),
        "host": str(os.getenv("INGEST_IMAP_HOST", "")).strip(),
        "port": _env_int("INGEST_IMAP_PORT", 993, min_value=1, max_value=65535),
        "user": str(os.getenv("INGEST_IMAP_USER", "")).strip(),
        "password": str(os.getenv("INGEST_IMAP_PASSWORD", "")).strip(),
        "folder": str(os.getenv("INGEST_IMAP_FOLDER", "INBOX")).strip() or "INBOX",
        "ssl": _env_bool("INGEST_IMAP_SSL", True),
        "max_messages": _env_int("INGEST_IMAP_MAX_MESSAGES", 10, min_value=1, max_value=200),
    }


def _local_config() -> dict[str, Any]:
    raw_paths = str(os.getenv("INGEST_LOCAL_PATHS", "")).strip()
    paths = [token.strip() for token in raw_paths.split(",") if token.strip()]
    raw_globs = str(os.getenv("INGEST_LOCAL_GLOBS", "")).strip()
    globs = [token.strip() for token in raw_globs.split(",") if token.strip()]
    if not globs:
        globs = list(DEFAULT_LOCAL_GLOBS)
    return {
        "enabled": _env_bool("INGEST_LOCAL_ENABLED", False),
        "paths": paths,
        "globs": globs,
        "max_files": _env_int("INGEST_LOCAL_MAX_FILES", 40, min_value=1, max_value=500),
        "max_file_bytes": _env_int("INGEST_LOCAL_MAX_FILE_BYTES", 500_000, min_value=512, max_value=20_000_000),
    }


def _record(
    *,
    source: str,
    kind: str,
    record_id: str,
    title: str,
    snippet: str,
    ts: str,
    tags: list[str],
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": record_id,
        "source": source,
        "kind": kind,
        "title": _short_text(title, 160),
        "snippet": _short_text(snippet, 260),
        "ts": ts,
        "tags": tags,
        "meta": meta,
    }


def _collect_imap_records(limit: int) -> dict[str, Any]:
    cfg = _imap_config()
    if not cfg["enabled"]:
        return {"enabled": False, "status": "off", "items": [], "error": ""}
    if not cfg["host"] or not cfg["user"] or not cfg["password"]:
        return {"enabled": True, "status": "misconfigured", "items": [], "error": "missing IMAP credentials"}

    mailbox: imaplib.IMAP4 | None = None
    items: list[dict[str, Any]] = []
    try:
        if cfg["ssl"]:
            mailbox = imaplib.IMAP4_SSL(cfg["host"], int(cfg["port"]))
        else:
            mailbox = imaplib.IMAP4(cfg["host"], int(cfg["port"]))
        mailbox.login(cfg["user"], cfg["password"])
        typ, _ = mailbox.select(cfg["folder"], readonly=True)
        if typ != "OK":
            raise RuntimeError(f"select_failed:{cfg['folder']}")

        typ, data = mailbox.search(None, "ALL")
        if typ != "OK":
            raise RuntimeError("search_failed")
        raw_ids = data[0].split() if data and data[0] else []
        ids = raw_ids[-int(cfg["max_messages"]):]
        ids.reverse()
        per_source_limit = max(1, min(limit, int(cfg["max_messages"])))
        for message_id in ids[:per_source_limit]:
            typ, payload = mailbox.fetch(message_id, "(RFC822)")
            if typ != "OK" or not payload:
                continue
            message_bytes = b""
            for chunk in payload:
                if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[1], (bytes, bytearray)):
                    message_bytes = bytes(chunk[1])
                    break
            if not message_bytes:
                continue
            msg = email.message_from_bytes(message_bytes)
            subject = _decode_mime(str(msg.get("Subject") or "No subject")) or "No subject"
            sender = _decode_mime(str(msg.get("From") or ""))
            ts = _parse_email_date(str(msg.get("Date") or ""))
            body = _extract_text_from_email(msg)
            items.append(
                _record(
                    source="imap",
                    kind="email",
                    record_id=f"imap:{message_id.decode(errors='ignore')}",
                    title=subject,
                    snippet=body or sender,
                    ts=ts,
                    tags=["email", "imap"],
                    meta={"from": sender, "folder": cfg["folder"]},
                )
            )
        return {"enabled": True, "status": "ok", "items": items, "error": ""}
    except Exception as exc:
        return {"enabled": True, "status": "error", "items": [], "error": exc.__class__.__name__}
    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except Exception:
                pass


def _resolve_local_roots(raw_paths: list[str]) -> list[Path]:
    roots: list[Path] = []
    for token in raw_paths:
        value = Path(token)
        if not value.is_absolute():
            value = PROJECT_ROOT / value
        try:
            roots.append(value.expanduser().resolve())
        except Exception:
            continue
    return roots


def _safe_read_text(path: Path, max_bytes: int) -> str:
    try:
        size = int(path.stat().st_size)
    except OSError:
        return ""
    if size <= 0 or size > max_bytes:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _collect_local_records(limit: int) -> dict[str, Any]:
    cfg = _local_config()
    if not cfg["enabled"]:
        return {"enabled": False, "status": "off", "items": [], "error": ""}
    roots = _resolve_local_roots(cfg["paths"])
    if not roots:
        return {"enabled": True, "status": "misconfigured", "items": [], "error": "no local paths configured"}

    candidates: dict[str, Path] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for pattern in cfg["globs"]:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                candidates[str(path)] = path

    if not candidates:
        return {"enabled": True, "status": "ok", "items": [], "error": ""}

    sorted_paths = sorted(
        candidates.values(),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    cap = max(1, min(limit, int(cfg["max_files"])))
    items: list[dict[str, Any]] = []
    for path in sorted_paths[:cap]:
        text = _safe_read_text(path, int(cfg["max_file_bytes"]))
        if not text:
            continue
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = first_line or path.stem
        snippet = text
        ts = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        try:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        items.append(
            _record(
                source="local_file",
                kind="document",
                record_id=f"file:{rel}",
                title=title,
                snippet=snippet,
                ts=ts,
                tags=["file", path.suffix.lower().lstrip(".")],
                meta={"path": rel, "size_bytes": int(path.stat().st_size)},
            )
        )
    return {"enabled": True, "status": "ok", "items": items, "error": ""}


def collect_ingest_signals(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    imap_part = _collect_imap_records(safe_limit)
    file_part = _collect_local_records(safe_limit)

    items = []
    items.extend(imap_part.get("items", []) if isinstance(imap_part.get("items"), list) else [])
    items.extend(file_part.get("items", []) if isinstance(file_part.get("items"), list) else [])

    def _ts_key(item: dict[str, Any]) -> str:
        return str(item.get("ts") or "")

    items = sorted([x for x in items if isinstance(x, dict)], key=_ts_key, reverse=True)[:safe_limit]

    enabled_sources = int(bool(imap_part.get("enabled"))) + int(bool(file_part.get("enabled")))
    status = "off"
    if enabled_sources > 0:
        statuses = {str(imap_part.get("status")), str(file_part.get("status"))}
        if "error" in statuses:
            status = "partial"
        elif statuses <= {"off", "misconfigured"}:
            status = "misconfigured"
        else:
            status = "ok"

    return {
        "enabled": enabled_sources > 0,
        "status": status,
        "count": len(items),
        "items": items,
        "sources": {
            "imap": {
                "enabled": bool(imap_part.get("enabled")),
                "status": str(imap_part.get("status") or "off"),
                "count": len(imap_part.get("items", [])) if isinstance(imap_part.get("items"), list) else 0,
                "error": str(imap_part.get("error") or ""),
            },
            "local_files": {
                "enabled": bool(file_part.get("enabled")),
                "status": str(file_part.get("status") or "off"),
                "count": len(file_part.get("items", [])) if isinstance(file_part.get("items"), list) else 0,
                "error": str(file_part.get("error") or ""),
            },
        },
    }


async def fetch_ingest_signals(limit: int = 20) -> dict[str, Any]:
    return await asyncio.to_thread(collect_ingest_signals, limit)
