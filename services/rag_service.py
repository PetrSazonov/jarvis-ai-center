from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime
from typing import Any

from db import (
    get_cache_value,
    init_db,
    rag_delete_missing_records,
    rag_list_vectors,
    rag_upsert_vectors,
    set_cache_value,
)
from services.ingest_service import fetch_ingest_signals


_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9_]+")
_CACHE_KEY_TEMPLATE = "rag:index:last:{user_id}"
_SCHEMA_READY = False

_PERSONAL_OWNER_HINTS = (
    "мой",
    "моя",
    "мои",
    "моё",
    "моих",
    "моей",
    "моем",
    "моём",
    "моему",
    "моими",
    "у меня",
    "my",
)

_DATA_SOURCE_HINTS = (
    "почт",
    "письм",
    "email",
    "mail",
    "документ",
    "file",
    "файл",
    "заметк",
    "note",
    "данн",
    "data",
)

_FORCED_PERSONAL_PATTERNS = (
    "из почты",
    "из писем",
    "из моих файлов",
    "в моих заметках",
    "in my email",
    "from my email",
    "from my notes",
    "from my files",
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    init_db()
    _SCHEMA_READY = True


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _rag_enabled() -> bool:
    return _env_bool("RAG_ENABLED", True)


def _rag_require_citations() -> bool:
    return _env_bool("RAG_REQUIRE_CITATIONS", True)


def _rag_top_k() -> int:
    return _env_int("RAG_TOP_K", 4, min_value=1, max_value=12)


def _rag_min_score() -> float:
    return _env_float("RAG_MIN_SCORE", 0.2, min_value=0.01, max_value=1.0)


def _rag_dim() -> int:
    return _env_int("RAG_VECTOR_DIM", 192, min_value=32, max_value=2048)


def _rag_max_docs() -> int:
    return _env_int("RAG_MAX_DOCS", 600, min_value=20, max_value=5000)


def _rag_ingest_limit() -> int:
    return _env_int("RAG_INGEST_LIMIT", 120, min_value=10, max_value=1000)


def _rag_reindex_seconds() -> int:
    return _env_int("RAG_REINDEX_SECONDS", 300, min_value=10, max_value=86400)


def _short_text(value: str, limit: int = 260) -> str:
    clean = " ".join((value or "").replace("\n", " ").replace("\r", " ").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def is_personal_data_query(text: str) -> bool:
    low = f" {(text or '').strip().lower()} "
    if not low.strip():
        return False
    if any(pattern in low for pattern in _FORCED_PERSONAL_PATTERNS):
        return True
    has_owner = any(hint in low for hint in _PERSONAL_OWNER_HINTS)
    has_data_source = any(hint in low for hint in _DATA_SOURCE_HINTS)
    return bool(has_owner and has_data_source)


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "")]


def build_embedding(text: str, *, dim: int | None = None) -> list[float]:
    vector_dim = int(dim or _rag_dim())
    vec = [0.0] * vector_dim
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="big", signed=False)
        idx = value % vector_dim
        sign = 1.0 if ((value >> 1) & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 1e-12:
        return vec
    return [x / norm for x in vec]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _to_source_record(item: dict[str, Any]) -> dict[str, Any] | None:
    source = str(item.get("source") or "").strip()
    record_id = str(item.get("id") or "").strip()
    if not source or not record_id:
        return None
    title = _short_text(str(item.get("title") or ""), 180)
    snippet = _short_text(str(item.get("snippet") or ""), 1200)
    ts = str(item.get("ts") or "").strip()[:64]
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    base_text = f"{title}\n{snippet}".strip()
    embedding = build_embedding(base_text)
    return {
        "source": source,
        "record_id": record_id,
        "title": title,
        "snippet": snippet,
        "ts": ts,
        "meta_json": json.dumps(meta, ensure_ascii=False),
        "embedding_json": json.dumps(embedding, ensure_ascii=False),
    }


def _index_records(*, user_id: int, records: list[dict[str, Any]]) -> dict[str, Any]:
    _ensure_schema()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        normalized = _to_source_record(record)
        if not normalized:
            continue
        grouped.setdefault(str(normalized["source"]), []).append(normalized)

    updated_at = _now_iso()
    upserted = 0
    deleted = 0
    for source, source_rows in grouped.items():
        upserted += rag_upsert_vectors(user_id=user_id, source=source, rows=source_rows, updated_at=updated_at)
        keep_ids = [str(row["record_id"]) for row in source_rows if str(row.get("record_id") or "").strip()]
        deleted += rag_delete_missing_records(user_id=user_id, source=source, keep_record_ids=keep_ids)

    return {
        "sources": len(grouped),
        "indexed_rows": upserted,
        "deleted_rows": deleted,
        "updated_at": updated_at,
    }


def _cache_key(user_id: int) -> str:
    return _CACHE_KEY_TEMPLATE.format(user_id=user_id)


def _is_reindex_required(user_id: int) -> bool:
    row = get_cache_value(_cache_key(user_id))
    if not row or not row[1]:
        return True
    try:
        updated_at = datetime.fromisoformat(str(row[1]))
    except ValueError:
        return True
    age = (datetime.now() - updated_at).total_seconds()
    return age > float(_rag_reindex_seconds())


async def refresh_rag_index(user_id: int, *, force: bool = False) -> dict[str, Any]:
    if not _rag_enabled():
        return {"enabled": False, "status": "off", "indexed_rows": 0}
    if not force and not _is_reindex_required(user_id):
        return {"enabled": True, "status": "cached", "indexed_rows": 0}

    payload = await fetch_ingest_signals(limit=_rag_ingest_limit())
    records = payload.get("items") if isinstance(payload.get("items"), list) else []
    indexed = _index_records(user_id=user_id, records=[x for x in records if isinstance(x, dict)])
    set_cache_value(_cache_key(user_id), json.dumps(indexed, ensure_ascii=False), _now_iso())
    return {"enabled": True, "status": "ok", **indexed}


def retrieve_matches(*, user_id: int, query: str, top_k: int | None = None, min_score: float | None = None) -> list[dict[str, Any]]:
    _ensure_schema()
    query_embedding = build_embedding(query)
    rows = rag_list_vectors(user_id=user_id, limit=_rag_max_docs())
    score_threshold = float(min_score if min_score is not None else _rag_min_score())
    limit = int(top_k or _rag_top_k())
    matches: list[dict[str, Any]] = []
    for source, record_id, title, snippet, ts, meta_json, embedding_json in rows:
        try:
            vec = json.loads(embedding_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(vec, list):
            continue
        try:
            doc_vec = [float(x) for x in vec]
        except (TypeError, ValueError):
            continue
        score = _cosine_similarity(query_embedding, doc_vec)
        if score < score_threshold:
            continue
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except json.JSONDecodeError:
            meta = {}
        matches.append(
            {
                "source": source,
                "record_id": record_id,
                "title": title,
                "snippet": snippet,
                "ts": ts,
                "meta": meta if isinstance(meta, dict) else {},
                "score": round(score, 4),
            }
        )
    matches.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return matches[: max(1, limit)]


def build_context_block(matches: list[dict[str, Any]], *, lang: str) -> str:
    if not matches:
        return ""
    header = "Personal sources for this answer (cite as [n]):" if lang == "en" else "Личные источники для ответа (цитируйте как [n]):"
    lines = [header]
    for idx, match in enumerate(matches, start=1):
        title = _short_text(str(match.get("title") or ""), 140)
        snippet = _short_text(str(match.get("snippet") or ""), 320)
        source = str(match.get("source") or "")
        ts = str(match.get("ts") or "")
        lines.append(f"[{idx}] {title} | source={source} | ts={ts}")
        lines.append(f"[{idx}] quote: {snippet}")
    return "\n".join(lines)


def format_citations_block(matches: list[dict[str, Any]], *, lang: str) -> str:
    if not matches:
        return ""
    title = "Sources:" if lang == "en" else "Источники:"
    lines = [title]
    for idx, match in enumerate(matches, start=1):
        src = str(match.get("source") or "")
        rec = str(match.get("record_id") or "")
        ts = str(match.get("ts") or "")
        head = _short_text(str(match.get("title") or ""), 100)
        lines.append(f"[{idx}] {head} ({src}:{rec}, {ts})")
    return "\n".join(lines)


def no_source_message(*, lang: str) -> str:
    if lang == "en":
        return (
            "I cannot answer from personal data without sources.\n"
            "Please clarify the query or add data to ingest sources (IMAP/local files)."
        )
    return (
        "Не могу отвечать по личным данным без подтвержденных источников.\n"
        "Уточните запрос или добавьте данные в ingest-источники (IMAP/локальные файлы)."
    )


async def resolve_rag_for_query(*, user_id: int, query: str, lang: str) -> dict[str, Any]:
    personal = is_personal_data_query(query)
    if not _rag_enabled() or user_id <= 0:
        return {
            "enabled": _rag_enabled(),
            "personal": personal,
            "required": False,
            "context": "",
            "matches": [],
            "citations_block": "",
            "block_message": None,
        }
    if not personal:
        return {
            "enabled": True,
            "personal": False,
            "required": False,
            "context": "",
            "matches": [],
            "citations_block": "",
            "block_message": None,
        }

    await refresh_rag_index(user_id)
    matches = retrieve_matches(user_id=user_id, query=query)
    required = bool(personal and _rag_require_citations())
    if required and not matches:
        return {
            "enabled": True,
            "personal": True,
            "required": True,
            "context": "",
            "matches": [],
            "citations_block": "",
            "block_message": no_source_message(lang=lang),
        }
    return {
        "enabled": True,
        "personal": personal,
        "required": required,
        "context": build_context_block(matches, lang=lang) if matches else "",
        "matches": matches,
        "citations_block": format_citations_block(matches, lang=lang) if matches else "",
        "block_message": None,
    }
