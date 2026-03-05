import ast
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

DATABASE_NAME = os.getenv("DATABASE_NAME", "jarvis.db")

FITNESS_PRESET_WORKOUTS: list[dict[str, Any]] = [
    {
        "title": "База: подтягивания + отжимания",
        "tags": "pull,push,bodyweight,home",
        "equipment": "турник",
        "difficulty": 3,
        "duration_sec": 1800,
        "notes": "5 кругов: подтягивания 5-8, отжимания 12-20, планка 40 сек. Отдых 60-90 сек.",
    },
    {
        "title": "Силовой верх с гантелями",
        "tags": "dumbbells,push,pull,home",
        "equipment": "гантели",
        "difficulty": 3,
        "duration_sec": 2100,
        "notes": "4 круга: жим гантелей 8-12, тяга гантели в наклоне 10-12/рука, отжимания 10-15.",
    },
    {
        "title": "Ноги + корпус дома",
        "tags": "legs,core,bodyweight,home",
        "equipment": "без инвентаря",
        "difficulty": 2,
        "duration_sec": 1800,
        "notes": "4 круга: присед 20, выпады 12/нога, ягодичный мост 20, hollow hold 25-35 сек.",
    },
    {
        "title": "EMOM 20: берпи и тяги",
        "tags": "burpee,conditioning,dumbbells,home",
        "equipment": "гантели",
        "difficulty": 4,
        "duration_sec": 1200,
        "notes": "EMOM 20 минут: нечётная минута берпи 8-12, чётная тяга гантелей 12-16.",
    },
    {
        "title": "Лестница подтягиваний",
        "tags": "pull,bodyweight,bar,home",
        "equipment": "турник",
        "difficulty": 4,
        "duration_sec": 1500,
        "notes": "Лестница 1-2-3-4-5 повторов x 3 волны. Между волнами отдых 2-3 минуты.",
    },
    {
        "title": "Push-плотность 15 минут",
        "tags": "push,bodyweight,home",
        "equipment": "без инвентаря",
        "difficulty": 3,
        "duration_sec": 900,
        "notes": "За 15 минут максимум качественных раундов: отжимания 12-20, узкие отжимания 8-12, планка 30 сек.",
    },
    {
        "title": "Full Body 30 с гантелями",
        "tags": "fullbody,dumbbells,home",
        "equipment": "гантели",
        "difficulty": 3,
        "duration_sec": 1800,
        "notes": "5 кругов: goblet squat 12, румынская тяга 12, жим стоя 10, тяга в наклоне 12, берпи 8.",
    },
    {
        "title": "Кардио-силовой комплекс",
        "tags": "burpee,conditioning,bodyweight,home",
        "equipment": "без инвентаря",
        "difficulty": 4,
        "duration_sec": 1500,
        "notes": "5 раундов по 4 минуты: 30с берпи, 30с mountain climbers, 30с приседания, 30с отдых.",
    },
    {
        "title": "Тяга + хват + кора",
        "tags": "pull,core,bar,home",
        "equipment": "турник",
        "difficulty": 3,
        "duration_sec": 1200,
        "notes": "4 круга: подтягивания 4-8, вис на турнике 30-45 сек, подъём коленей в висе 10-15.",
    },
    {
        "title": "Восстановительная техника",
        "tags": "recovery,mobility,home",
        "equipment": "без инвентаря",
        "difficulty": 1,
        "duration_sec": 1200,
        "notes": "Мобилизация плеч/таза 8-10 минут + лёгкий комплекс: присед 15, отжимания 8-12, планка 30 сек x 3 круга.",
    },
]


GARAGE_DEFAULT_ASSETS: list[dict[str, Any]] = [
    {
        "kind": "car",
        "title": "Mitsubishi Outlander 3G",
        "year": 2013,
        "nickname": "Outlander",
        "maintenance_interval_km": 10000,
        "docs": [
            {
                "label": "Mitsubishi manuals hub (official)",
                "url": "https://www.mitsubishi-motors.co.uk/manuals",
                "official": True,
            },
            {
                "label": "Outlander Diesel owners manual PDF (official Mitsubishi UK)",
                "url": "https://www.mitsubishi-motors.co.uk/files/owners-manuals/Outlander_Diesel_12my_Owners_Manual.pdf",
                "official": True,
            },
        ],
    },
    {
        "kind": "car",
        "title": "BMW 420i Gran Coupe",
        "year": 2015,
        "nickname": "BMW 420i",
        "maintenance_interval_km": 12000,
        "docs": [
            {
                "label": "BMW owners manual access (official, VIN required)",
                "url": "https://www.bmwusa.com/owners-manuals.html",
                "official": True,
            },
            {
                "label": "BMW Driver's Guide / Know your BMW (official)",
                "url": "https://www.bmw.co.uk/en/topics/owners/bmw-apps/driver-guide.html",
                "official": True,
            },
        ],
    },
    {
        "kind": "moto",
        "title": "Triumph Trident 660 Black Sapphire",
        "year": 2023,
        "nickname": "Trident 660",
        "maintenance_interval_km": 8000,
        "docs": [
            {
                "label": "Triumph handbooks library (official)",
                "url": "https://www.triumphinstructions.com/",
                "official": True,
            },
        ],
    },
]


def _connect():
    return sqlite3.connect(DATABASE_NAME)


def _table_columns(cursor: sqlite3.Cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cursor.fetchall() if row and len(row) > 1}


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, ddl_suffix: str) -> None:
    columns = _table_columns(cursor, table)
    if column in columns:
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_suffix}")


def init_db():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            user_id INTEGER PRIMARY KEY,
            history TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_last (
            symbol TEXT PRIMARY KEY,
            price REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            feedback TEXT NOT NULL,
            request_id TEXT,
            response_excerpt TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fuel95_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            action TEXT NOT NULL,
            user_id INTEGER,
            chat_id INTEGER,
            message_id INTEGER,
            digest_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fitness_workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            tags TEXT DEFAULT '',
            equipment TEXT DEFAULT '',
            difficulty INTEGER DEFAULT 2,
            duration_sec INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            vault_chat_id INTEGER NOT NULL,
            vault_message_id INTEGER NOT NULL,
            file_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(vault_chat_id, vault_message_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fitness_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            workout_id INTEGER NOT NULL,
            done_at TEXT NOT NULL,
            rpe INTEGER DEFAULT NULL,
            comment TEXT DEFAULT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fitness_favorites (
            user_id INTEGER NOT NULL,
            workout_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, workout_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fitness_progress (
            user_id INTEGER NOT NULL,
            workout_id INTEGER NOT NULL,
            last_rpe INTEGER,
            last_comment TEXT,
            next_hint TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, workout_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS todo_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            done_at TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            check_date TEXT NOT NULL,
            done_text TEXT DEFAULT '',
            carry_text TEXT DEFAULT '',
            energy INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, check_date)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            llm_mode TEXT NOT NULL DEFAULT 'normal',
            show_confidence INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            next_date TEXT NOT NULL,
            period TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            condition_expr TEXT NOT NULL,
            action_expr TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS finance_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            metric TEXT NOT NULL,
            operator TEXT NOT NULL DEFAULT '<=',
            threshold REAL,
            due_days INTEGER,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reflection_date TEXT NOT NULL,
            done_text TEXT NOT NULL DEFAULT '',
            drain_text TEXT NOT NULL DEFAULT '',
            remove_text TEXT NOT NULL DEFAULT '',
            tomorrow_rule TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, reflection_date)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            decision_text TEXT NOT NULL,
            hypothesis TEXT NOT NULL DEFAULT '',
            expected_outcome TEXT NOT NULL DEFAULT '',
            decision_date TEXT NOT NULL,
            review_after_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            actual_outcome TEXT DEFAULT '',
            score INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            duration_min INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_memory (
            user_id INTEGER NOT NULL,
            mem_key TEXT NOT NULL,
            mem_value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, mem_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_memory_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mem_key TEXT NOT NULL,
            mem_value TEXT NOT NULL DEFAULT '',
            is_verified INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.5,
            operation TEXT NOT NULL,
            changed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            snippet TEXT NOT NULL DEFAULT '',
            ts TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            embedding_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source, record_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS garage_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'car',
            title TEXT NOT NULL,
            year INTEGER,
            nickname TEXT DEFAULT '',
            vin TEXT DEFAULT '',
            plate TEXT DEFAULT '',
            mileage_km INTEGER NOT NULL DEFAULT 0,
            last_service_km INTEGER,
            maintenance_interval_km INTEGER NOT NULL DEFAULT 10000,
            maintenance_due_date TEXT,
            insurance_until TEXT,
            tech_inspection_until TEXT,
            note TEXT DEFAULT '',
            docs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(cursor, "user_settings", "lang", "TEXT")
    _ensure_column(cursor, "user_settings", "timezone_name", "TEXT")
    _ensure_column(cursor, "user_settings", "weather_city", "TEXT")
    _ensure_column(cursor, "user_settings", "digest_format", "TEXT NOT NULL DEFAULT 'compact'")
    _ensure_column(cursor, "user_settings", "quiet_start", "TEXT")
    _ensure_column(cursor, "user_settings", "quiet_end", "TEXT")
    _ensure_column(cursor, "user_settings", "response_style", "TEXT NOT NULL DEFAULT 'balanced'")
    _ensure_column(cursor, "user_settings", "response_density", "TEXT NOT NULL DEFAULT 'auto'")
    _ensure_column(cursor, "user_settings", "day_mode", "TEXT NOT NULL DEFAULT 'workday'")
    _ensure_column(cursor, "user_settings", "energy_autopilot", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "user_settings", "cognitive_profile", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "user_settings", "crisis_until", "TEXT")
    _ensure_column(cursor, "user_settings", "crisis_reason", "TEXT")

    _ensure_column(cursor, "assistant_memory", "is_verified", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(cursor, "assistant_memory", "confidence", "REAL NOT NULL DEFAULT 0.5")

    # Task scheduling/reminder extension (backward compatible columns).
    _ensure_column(cursor, "todo_items", "due_date", "TEXT")
    _ensure_column(cursor, "todo_items", "remind_at", "TEXT")
    _ensure_column(cursor, "todo_items", "remind_telegram", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "todo_items", "reminder_sent_at", "TEXT")
    _ensure_column(cursor, "todo_items", "notes", "TEXT DEFAULT ''")

    # Subscriptions financial metadata (backward compatible columns).
    _ensure_column(cursor, "subscriptions", "amount", "REAL")
    _ensure_column(cursor, "subscriptions", "currency", "TEXT NOT NULL DEFAULT 'RUB'")
    _ensure_column(cursor, "subscriptions", "note", "TEXT DEFAULT ''")
    _ensure_column(cursor, "subscriptions", "category", "TEXT DEFAULT ''")
    _ensure_column(cursor, "subscriptions", "autopay", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "subscriptions", "remind_days", "INTEGER NOT NULL DEFAULT 3")

    # Query-path indexes for daily/weekly dashboards and gamification.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_todo_user_status_done_at ON todo_items(user_id, status, done_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_todo_user_created_at ON todo_items(user_id, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_todo_user_due_date ON todo_items(user_id, due_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_todo_reminder_queue ON todo_items(status, remind_telegram, remind_at, reminder_sent_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_fitness_user_done_at ON fitness_sessions(user_id, done_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_checkins_user_date ON daily_checkins(user_id, check_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_subs_user_next_date ON subscriptions(user_id, next_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_user_started_at ON focus_sessions(user_id, started_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_user_status_started_at ON focus_sessions(user_id, status, started_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reflections_user_date ON daily_reflections(user_id, reflection_date)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_vectors_user_source ON rag_vectors(user_id, source)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_vectors_user_updated ON rag_vectors(user_id, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_garage_assets_user ON garage_assets(user_id, id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_garage_assets_user_insurance ON garage_assets(user_id, insurance_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_garage_assets_user_maintenance ON garage_assets(user_id, maintenance_due_date)"
    )

    conn.commit()
    conn.close()


def _normalize_history(raw: Any):
    if not isinstance(raw, list):
        return []
    normalized = []
    for item in raw:
        if isinstance(item, dict) and "role" in item and "content" in item:
            normalized.append({"role": str(item["role"]), "content": str(item["content"])})
            continue
        if isinstance(item, str):
            if item.startswith("User: "):
                normalized.append({"role": "user", "content": item[6:]})
            elif item.startswith("AI: "):
                normalized.append({"role": "assistant", "content": item[4:]})
            else:
                normalized.append({"role": "user", "content": item})
    return normalized


def get_conversation_history(user_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM conversations WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return []

    value = row[0]
    try:
        return _normalize_history(json.loads(value))
    except json.JSONDecodeError:
        # Migration path for old rows stored as Python repr strings.
        try:
            return _normalize_history(ast.literal_eval(value))
        except (ValueError, SyntaxError):
            return []


def save_conversation_history(user_id, history):
    payload = json.dumps(_normalize_history(history), ensure_ascii=False)
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO conversations (user_id, history)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET history = excluded.history
        """,
        (user_id, payload),
    )
    conn.commit()
    conn.close()


def get_crypto_last(symbol):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT price, updated_at FROM crypto_last WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    return row


def set_crypto_last(symbol, price, updated_at):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO crypto_last (symbol, price, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE
        SET price = excluded.price, updated_at = excluded.updated_at
        """,
        (symbol, price, updated_at),
    )
    conn.commit()
    conn.close()


def ping_db():
    try:
        conn = _connect()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        return True, "ok"
    except sqlite3.Error as exc:
        return False, str(exc)


def set_cache_value(key: str, value: str, updated_at: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO app_cache (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE
        SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )
    conn.commit()
    conn.close()


def get_cache_value(key: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT value, updated_at FROM app_cache WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row


def rag_upsert_vectors(*, user_id: int, source: str, rows: list[dict[str, Any]], updated_at: str) -> int:
    if not rows:
        return 0
    conn = _connect()
    cursor = conn.cursor()
    payload = []
    for item in rows:
        record_id = str(item.get("record_id") or "").strip()
        embedding_json = str(item.get("embedding_json") or "").strip()
        if not record_id or not embedding_json:
            continue
        payload.append(
            (
                user_id,
                source,
                record_id,
                str(item.get("title") or "").strip()[:500],
                str(item.get("snippet") or "").strip()[:4000],
                str(item.get("ts") or "").strip()[:64],
                str(item.get("meta_json") or "{}"),
                embedding_json,
                updated_at,
            )
        )
    if not payload:
        conn.close()
        return 0
    cursor.executemany(
        """
        INSERT INTO rag_vectors (
            user_id, source, record_id, title, snippet, ts, meta_json, embedding_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, source, record_id) DO UPDATE SET
            title = excluded.title,
            snippet = excluded.snippet,
            ts = excluded.ts,
            meta_json = excluded.meta_json,
            embedding_json = excluded.embedding_json,
            updated_at = excluded.updated_at
        """,
        payload,
    )
    changed = int(cursor.rowcount or 0)
    conn.commit()
    conn.close()
    return changed


def rag_delete_missing_records(*, user_id: int, source: str, keep_record_ids: list[str]) -> int:
    conn = _connect()
    cursor = conn.cursor()
    clean_ids = [str(x).strip() for x in keep_record_ids if str(x).strip()]
    if not clean_ids:
        cursor.execute(
            "DELETE FROM rag_vectors WHERE user_id = ? AND source = ?",
            (user_id, source),
        )
    else:
        placeholders = ",".join("?" for _ in clean_ids)
        params = [user_id, source, *clean_ids]
        cursor.execute(
            f"DELETE FROM rag_vectors WHERE user_id = ? AND source = ? AND record_id NOT IN ({placeholders})",
            params,
        )
    deleted = int(cursor.rowcount or 0)
    conn.commit()
    conn.close()
    return deleted


def rag_list_vectors(*, user_id: int, limit: int = 500) -> list[tuple[str, str, str, str, str, str, str]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT source, record_id, title, snippet, ts, meta_json, embedding_json
        FROM rag_vectors
        WHERE user_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        (
            str(r[0] or ""),
            str(r[1] or ""),
            str(r[2] or ""),
            str(r[3] or ""),
            str(r[4] or ""),
            str(r[5] or "{}"),
            str(r[6] or "[]"),
        )
        for r in rows
    ]


def delete_cache_prefix(prefix: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM app_cache WHERE key LIKE ?", (f"{prefix}%",))
    conn.commit()
    deleted = int(cursor.rowcount or 0)
    conn.close()
    return deleted


def save_llm_feedback(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    feedback: str,
    request_id: str | None,
    response_excerpt: str | None,
    created_at: str,
):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO llm_feedback (
            user_id, chat_id, message_id, feedback, request_id, response_excerpt, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, chat_id, message_id, feedback, request_id, response_excerpt, created_at),
    )
    conn.commit()
    conn.close()


def add_fuel95_history(*, price: float, created_at: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO fuel95_history (price, created_at)
        VALUES (?, ?)
        """,
        (price, created_at),
    )
    conn.commit()
    conn.close()


def get_fuel95_latest_before(cutoff_iso: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT price, created_at
        FROM fuel95_history
        WHERE created_at <= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (cutoff_iso,),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def get_latest_fuel95_in_range(min_price: float, max_price: float):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT price, created_at
        FROM fuel95_history
        WHERE price BETWEEN ? AND ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (min_price, max_price),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def save_ui_event(
    *,
    event_type: str,
    action: str,
    user_id: int | None,
    chat_id: int | None,
    message_id: int | None,
    digest_id: str | None,
    created_at: str,
):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ui_events (
            event_type, action, user_id, chat_id, message_id, digest_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event_type, action, user_id, chat_id, message_id, digest_id, created_at),
    )
    conn.commit()
    conn.close()


def fitness_create_workout(
    *,
    title: str,
    tags: str,
    equipment: str,
    difficulty: int,
    duration_sec: int,
    notes: str,
    vault_chat_id: int,
    vault_message_id: int,
    file_id: str,
    created_at: str,
):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO fitness_workouts (
            title, tags, equipment, difficulty, duration_sec, notes,
            vault_chat_id, vault_message_id, file_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vault_chat_id, vault_message_id) DO UPDATE SET
            title=excluded.title,
            file_id=excluded.file_id
        """,
        (
            title,
            tags,
            equipment,
            difficulty,
            duration_sec,
            notes,
            vault_chat_id,
            vault_message_id,
            file_id,
            created_at,
        ),
    )
    conn.commit()
    workout_id = cursor.lastrowid
    if not workout_id:
        cursor.execute(
            """
            SELECT id FROM fitness_workouts
            WHERE vault_chat_id = ? AND vault_message_id = ?
            """,
            (vault_chat_id, vault_message_id),
        )
        row = cursor.fetchone()
        workout_id = int(row[0]) if row and row[0] is not None else None
    conn.close()
    return workout_id


def fitness_seed_presets(*, vault_chat_id: int) -> int:
    base_message_id = 900001
    inserted = 0
    conn = _connect()
    cursor = conn.cursor()
    for idx, preset in enumerate(FITNESS_PRESET_WORKOUTS):
        vault_message_id = base_message_id + idx
        cursor.execute(
            """
            SELECT 1 FROM fitness_workouts
            WHERE vault_chat_id = ? AND vault_message_id = ?
            LIMIT 1
            """,
            (vault_chat_id, vault_message_id),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO fitness_workouts (
                title, tags, equipment, difficulty, duration_sec, notes,
                vault_chat_id, vault_message_id, file_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset["title"],
                preset["tags"],
                preset["equipment"],
                preset["difficulty"],
                preset["duration_sec"],
                preset["notes"],
                vault_chat_id,
                vault_message_id,
                "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        inserted += 1
    conn.commit()
    conn.close()
    return inserted


def fitness_get_workout(workout_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id, title, tags, equipment, difficulty, duration_sec, notes,
            vault_chat_id, vault_message_id, file_id, created_at
        FROM fitness_workouts
        WHERE id = ?
        """,
        (workout_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def fitness_get_latest_workout():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id, title, tags, equipment, difficulty, duration_sec, notes,
            vault_chat_id, vault_message_id, file_id, created_at
        FROM fitness_workouts
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    conn.close()
    return row


def fitness_workouts_count() -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM fitness_workouts")
    value = int(cursor.fetchone()[0] or 0)
    conn.close()
    return value


def fitness_list_workouts(*, page: int, limit: int):
    offset = max(page - 1, 0) * limit
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM fitness_workouts")
    total = int(cursor.fetchone()[0] or 0)
    cursor.execute(
        """
        SELECT
            id, title, tags, equipment, difficulty, duration_sec, notes,
            vault_chat_id, vault_message_id, file_id, created_at
        FROM fitness_workouts
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows, total


def fitness_get_random_workout(*, tag: str | None = None):
    conn = _connect()
    cursor = conn.cursor()
    if tag:
        pattern = f"%{tag.strip().lower()}%"
        cursor.execute(
            """
            SELECT
                id, title, tags, equipment, difficulty, duration_sec, notes,
                vault_chat_id, vault_message_id, file_id, created_at
            FROM fitness_workouts
            WHERE lower(tags) LIKE ?
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (pattern,),
        )
    else:
        cursor.execute(
            """
            SELECT
                id, title, tags, equipment, difficulty, duration_sec, notes,
                vault_chat_id, vault_message_id, file_id, created_at
            FROM fitness_workouts
            ORDER BY RANDOM()
            LIMIT 1
            """
        )
    row = cursor.fetchone()
    conn.close()
    return row


def fitness_list_workouts_by_tag(tag: str | None = None):
    conn = _connect()
    cursor = conn.cursor()
    if tag:
        pattern = f"%{tag.strip().lower()}%"
        cursor.execute(
            """
            SELECT
                id, title, tags, equipment, difficulty, duration_sec, notes,
                vault_chat_id, vault_message_id, file_id, created_at
            FROM fitness_workouts
            WHERE lower(tags) LIKE ?
            ORDER BY id ASC
            """,
            (pattern,),
        )
    else:
        cursor.execute(
            """
            SELECT
                id, title, tags, equipment, difficulty, duration_sec, notes,
                vault_chat_id, vault_message_id, file_id, created_at
            FROM fitness_workouts
            ORDER BY id ASC
            """
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def fitness_set_favorite(*, user_id: int, workout_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO fitness_favorites (user_id, workout_id)
        VALUES (?, ?)
        ON CONFLICT(user_id, workout_id) DO NOTHING
        """,
        (user_id, workout_id),
    )
    conn.commit()
    conn.close()


def fitness_remove_favorite(*, user_id: int, workout_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM fitness_favorites
        WHERE user_id = ? AND workout_id = ?
        """,
        (user_id, workout_id),
    )
    conn.commit()
    conn.close()


def fitness_is_favorite(*, user_id: int, workout_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1
        FROM fitness_favorites
        WHERE user_id = ? AND workout_id = ?
        LIMIT 1
        """,
        (user_id, workout_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def fitness_add_session(*, user_id: int, workout_id: int, done_at: str, rpe: int | None, comment: str | None):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO fitness_sessions (user_id, workout_id, done_at, rpe, comment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, workout_id, done_at, rpe, comment),
    )
    conn.commit()
    conn.close()


def fitness_get_recent_rpe(*, user_id: int, workout_id: int, limit: int = 3):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT rpe
        FROM fitness_sessions
        WHERE user_id = ? AND workout_id = ?
        ORDER BY done_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, workout_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def fitness_stats_recent(*, user_id: int, since_iso: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM fitness_sessions
        WHERE user_id = ? AND done_at >= ?
        """,
        (user_id, since_iso),
    )
    total = int(cursor.fetchone()[0] or 0)
    cursor.execute(
        """
        SELECT
            fs.workout_id,
            fw.title,
            fs.done_at,
            fw.tags
        FROM fitness_sessions fs
        JOIN fitness_workouts fw ON fw.id = fs.workout_id
        WHERE fs.user_id = ? AND fs.done_at >= ?
        ORDER BY fs.done_at DESC
        LIMIT 20
        """,
        (user_id, since_iso),
    )
    rows = cursor.fetchall()
    conn.close()
    return total, rows


def fitness_done_count_between(*, user_id: int, start_iso: str, end_iso: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM fitness_sessions
        WHERE user_id = ? AND done_at >= ? AND done_at < ?
        """,
        (user_id, start_iso, end_iso),
    )
    count = int(cursor.fetchone()[0] or 0)
    conn.close()
    return count


def fitness_current_streak_days(*, user_id: int) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT substr(done_at, 1, 10) AS day
        FROM fitness_sessions
        WHERE user_id = ?
        ORDER BY day DESC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return 0

    days: list[date] = []
    for row in rows:
        try:
            days.append(date.fromisoformat(str(row[0])))
        except ValueError:
            continue
    if not days:
        return 0

    today = date.today()
    first_day = days[0]
    if (today - first_day).days > 1:
        return 0

    streak = 0
    expected = first_day
    for day in days:
        if day == expected:
            streak += 1
            expected = expected - timedelta(days=1)
        elif day < expected:
            break
    return streak


def fitness_get_latest_session_for_user(user_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            fs.workout_id,
            fw.title,
            fs.done_at,
            fs.rpe
        FROM fitness_sessions fs
        JOIN fitness_workouts fw ON fw.id = fs.workout_id
        WHERE fs.user_id = ?
        ORDER BY fs.done_at DESC, fs.id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def fitness_week_done_dates(*, user_id: int, week_start_iso: str, week_end_iso: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT substr(done_at, 1, 10) AS day
        FROM fitness_sessions
        WHERE user_id = ? AND done_at >= ? AND done_at < ?
        ORDER BY day ASC
        """,
        (user_id, week_start_iso, week_end_iso),
    )
    rows = cursor.fetchall()
    conn.close()
    return [str(row[0]) for row in rows if row and row[0]]


def fitness_upsert_progress(
    *,
    user_id: int,
    workout_id: int,
    last_rpe: int | None,
    last_comment: str | None,
    next_hint: str,
    updated_at: str,
):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO fitness_progress (
            user_id, workout_id, last_rpe, last_comment, next_hint, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, workout_id) DO UPDATE SET
            last_rpe = excluded.last_rpe,
            last_comment = excluded.last_comment,
            next_hint = excluded.next_hint,
            updated_at = excluded.updated_at
        """,
        (user_id, workout_id, last_rpe, last_comment, next_hint, updated_at),
    )
    conn.commit()
    conn.close()


def fitness_get_progress(*, user_id: int, workout_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT last_rpe, last_comment, next_hint, updated_at
        FROM fitness_progress
        WHERE user_id = ? AND workout_id = ?
        LIMIT 1
        """,
        (user_id, workout_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def fitness_update_workout(workout_id: int, fields: dict[str, Any]) -> bool:
    if not fields:
        return False
    allowed = {"title", "tags", "equipment", "difficulty", "duration_sec", "notes"}
    updates: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = ?")
        params.append(value)
    if not updates:
        return False
    params.append(workout_id)
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        UPDATE fitness_workouts
        SET {", ".join(updates)}
        WHERE id = ?
        """,
        tuple(params),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def fitness_delete_workout(workout_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fitness_favorites WHERE workout_id = ?", (workout_id,))
    cursor.execute("DELETE FROM fitness_sessions WHERE workout_id = ?", (workout_id,))
    cursor.execute("DELETE FROM fitness_workouts WHERE id = ?", (workout_id,))
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def todo_add(
    *,
    user_id: int,
    text: str,
    created_at: str,
    notes: str | None = None,
    due_date: str | None = None,
    remind_at: str | None = None,
    remind_telegram: bool = True,
) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO todo_items (
            user_id, text, status, created_at, done_at, due_date, remind_at, remind_telegram, reminder_sent_at, notes
        )
        VALUES (?, ?, 'open', ?, NULL, ?, ?, ?, NULL, ?)
        """,
        (
            user_id,
            text,
            created_at,
            (str(due_date).strip() if due_date else None),
            (str(remind_at).strip() if remind_at else None),
            1 if remind_telegram else 0,
            str(notes or "").strip(),
        ),
    )
    conn.commit()
    todo_id = int(cursor.lastrowid)
    conn.close()
    return todo_id


def todo_list_open(*, user_id: int, limit: int = 20, include_meta: bool = False):
    conn = _connect()
    cursor = conn.cursor()
    if include_meta:
        cursor.execute(
            """
            SELECT id, text, created_at, due_date, remind_at, notes
            FROM todo_items
            WHERE user_id = ? AND status = 'open'
            ORDER BY
                CASE WHEN due_date IS NULL OR due_date = '' THEN 1 ELSE 0 END,
                due_date ASC,
                id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        )
    else:
        cursor.execute(
            """
            SELECT id, text, created_at
            FROM todo_items
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def todo_mark_done(*, user_id: int, todo_id: int, done_at: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE todo_items
        SET status = 'done', done_at = ?
        WHERE user_id = ? AND id = ? AND status = 'open'
        """,
        (done_at, user_id, todo_id),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def todo_delete(*, user_id: int, todo_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM todo_items
        WHERE user_id = ? AND id = ?
        """,
        (user_id, todo_id),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def todo_update_schedule(
    *,
    user_id: int,
    todo_id: int,
    due_date: str | None = None,
    remind_at: str | None = None,
    remind_telegram: bool = True,
) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE todo_items
        SET due_date = ?, remind_at = ?, remind_telegram = ?, reminder_sent_at = NULL
        WHERE user_id = ? AND id = ? AND status = 'open'
        """,
        (
            (str(due_date).strip() if due_date else None),
            (str(remind_at).strip() if remind_at else None),
            1 if remind_telegram else 0,
            user_id,
            todo_id,
        ),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def todo_update_item(
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
    updates: list[str] = []
    values: list[object] = []

    if has_text:
        updates.append("text = ?")
        values.append(str(text or "").strip())
    if has_notes:
        updates.append("notes = ?")
        values.append(str(notes or "").strip())

    schedule_updated = False
    if has_due_date:
        updates.append("due_date = ?")
        values.append(str(due_date).strip() if due_date else None)
        schedule_updated = True
    if has_remind_at:
        updates.append("remind_at = ?")
        values.append(str(remind_at).strip() if remind_at else None)
        schedule_updated = True
    if has_remind_telegram:
        updates.append("remind_telegram = ?")
        values.append(1 if bool(remind_telegram) else 0)
        schedule_updated = True

    if schedule_updated:
        updates.append("reminder_sent_at = NULL")

    if not updates:
        return False

    conn = _connect()
    cursor = conn.cursor()
    query = (
        "UPDATE todo_items "
        f"SET {', '.join(updates)} "
        "WHERE user_id = ? AND id = ? AND status = 'open'"
    )
    values.extend([user_id, todo_id])
    cursor.execute(query, tuple(values))
    conn.commit()
    changed = cursor.rowcount > 0
    conn.close()
    return changed


def todo_due_reminders(*, now_iso: str, limit: int = 40) -> list[tuple[int, int, str, str | None, str | None]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, text, due_date, remind_at
        FROM todo_items
        WHERE status = 'open'
          AND remind_telegram = 1
          AND remind_at IS NOT NULL
          AND remind_at <> ''
          AND remind_at <= ?
          AND (reminder_sent_at IS NULL OR reminder_sent_at = '')
        ORDER BY remind_at ASC, id ASC
        LIMIT ?
        """,
        (now_iso, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[tuple[int, int, str, str | None, str | None]] = []
    for row in rows:
        out.append(
            (
                int(row[0]),
                int(row[1]),
                str(row[2] or ""),
                (str(row[3]) if row[3] is not None else None),
                (str(row[4]) if row[4] is not None else None),
            )
        )
    return out


def todo_mark_reminder_sent(*, todo_id: int, sent_at: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE todo_items
        SET reminder_sent_at = ?
        WHERE id = ? AND status = 'open'
        """,
        (sent_at, todo_id),
    )
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok


def todo_list_calendar(
    *,
    user_id: int,
    limit: int = 800,
) -> list[tuple[int, str, str, str, str | None, str | None, str | None, str | None]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, text, status, created_at, done_at, due_date, remind_at, notes
        FROM todo_items
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[tuple[int, str, str, str, str | None, str | None, str | None, str | None]] = []
    for row in rows:
        out.append(
            (
                int(row[0]),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                (str(row[4]) if row[4] is not None else None),
                (str(row[5]) if row[5] is not None else None),
                (str(row[6]) if row[6] is not None else None),
                (str(row[7]) if row[7] is not None else None),
            )
        )
    return out


def daily_checkin_upsert(
    *,
    user_id: int,
    check_date: str,
    done_text: str,
    carry_text: str,
    energy: int | None,
    created_at: str,
    updated_at: str,
) -> None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO daily_checkins (
            user_id, check_date, done_text, carry_text, energy, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, check_date) DO UPDATE SET
            done_text = excluded.done_text,
            carry_text = excluded.carry_text,
            energy = excluded.energy,
            updated_at = excluded.updated_at
        """,
        (user_id, check_date, done_text, carry_text, energy, created_at, updated_at),
    )
    conn.commit()
    conn.close()


def daily_checkin_get(*, user_id: int, check_date: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT done_text, carry_text, energy, updated_at
        FROM daily_checkins
        WHERE user_id = ? AND check_date = ?
        LIMIT 1
        """,
        (user_id, check_date),
    )
    row = cursor.fetchone()
    conn.close()
    return row


_LLM_MODES = {"fast", "normal", "precise"}
_DIGEST_FORMATS = {"compact", "expanded"}
_RESPONSE_STYLES = {"balanced", "direct", "soft"}
_RESPONSE_DENSITY = {"auto", "short", "detailed"}
_DAY_MODES = {"workday", "maintenance", "recovery", "travel"}


def _normalize_hhmm(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        return None
    hh, mm = raw.split(":")
    h = int(hh)
    m = int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def user_settings_get_full(user_id: int) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "llm_mode": "normal",
        "show_confidence": False,
        "lang": None,
        "timezone_name": None,
        "weather_city": None,
        "digest_format": "compact",
        "quiet_start": None,
        "quiet_end": None,
        "response_style": "balanced",
        "response_density": "auto",
        "day_mode": "workday",
        "energy_autopilot": True,
        "cognitive_profile": True,
        "crisis_until": None,
        "crisis_reason": None,
    }
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            llm_mode,
            show_confidence,
            lang,
            timezone_name,
            weather_city,
            digest_format,
            quiet_start,
            quiet_end,
            response_style,
            response_density,
            day_mode,
            energy_autopilot,
            cognitive_profile,
            crisis_until,
            crisis_reason
        FROM user_settings
        WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return defaults

    mode = str(row[0] or "normal").strip().lower()
    if mode not in _LLM_MODES:
        mode = "normal"
    show_confidence = bool(int(row[1] or 0))
    lang = str(row[2]).strip().lower() if row[2] else None
    if lang not in {"ru", "en"}:
        lang = None
    digest_format = str(row[5] or "compact").strip().lower()
    if digest_format not in _DIGEST_FORMATS:
        digest_format = "compact"
    response_style = str(row[8] or "balanced").strip().lower()
    if response_style not in _RESPONSE_STYLES:
        response_style = "balanced"
    response_density = str(row[9] or "auto").strip().lower()
    if response_density not in _RESPONSE_DENSITY:
        response_density = "auto"
    day_mode = str(row[10] or "workday").strip().lower()
    if day_mode not in _DAY_MODES:
        day_mode = "workday"
    energy_autopilot = bool(int(row[11] or 0)) if len(row) > 11 else True
    cognitive_profile = bool(int(row[12] or 0)) if len(row) > 12 else True
    crisis_until = str(row[13]).strip() if len(row) > 13 and row[13] else None
    crisis_reason = str(row[14]).strip() if len(row) > 14 and row[14] else None

    return {
        "llm_mode": mode,
        "show_confidence": show_confidence,
        "lang": lang,
        "timezone_name": str(row[3]).strip() if row[3] else None,
        "weather_city": str(row[4]).strip() if row[4] else None,
        "digest_format": digest_format,
        "quiet_start": _normalize_hhmm(str(row[6])) if row[6] else None,
        "quiet_end": _normalize_hhmm(str(row[7])) if row[7] else None,
        "response_style": response_style,
        "response_density": response_density,
        "day_mode": day_mode,
        "energy_autopilot": energy_autopilot,
        "cognitive_profile": cognitive_profile,
        "crisis_until": crisis_until,
        "crisis_reason": crisis_reason,
    }


def user_settings_upsert(*, user_id: int, updated_at: str, **updates: Any) -> None:
    profile = user_settings_get_full(user_id)
    profile.update({k: v for k, v in updates.items() if k in profile})

    mode = str(profile.get("llm_mode") or "normal").strip().lower()
    if mode not in _LLM_MODES:
        mode = "normal"
    show_confidence = bool(profile.get("show_confidence"))
    lang = str(profile.get("lang")).strip().lower() if profile.get("lang") else None
    if lang not in {"ru", "en"}:
        lang = None
    timezone_name = str(profile.get("timezone_name")).strip() if profile.get("timezone_name") else None
    weather_city = str(profile.get("weather_city")).strip() if profile.get("weather_city") else None
    digest_format = str(profile.get("digest_format") or "compact").strip().lower()
    if digest_format not in _DIGEST_FORMATS:
        digest_format = "compact"
    quiet_start = _normalize_hhmm(profile.get("quiet_start"))
    quiet_end = _normalize_hhmm(profile.get("quiet_end"))
    response_style = str(profile.get("response_style") or "balanced").strip().lower()
    if response_style not in _RESPONSE_STYLES:
        response_style = "balanced"
    response_density = str(profile.get("response_density") or "auto").strip().lower()
    if response_density not in _RESPONSE_DENSITY:
        response_density = "auto"
    day_mode = str(profile.get("day_mode") or "workday").strip().lower()
    if day_mode not in _DAY_MODES:
        day_mode = "workday"
    energy_autopilot = bool(profile.get("energy_autopilot", True))
    cognitive_profile = bool(profile.get("cognitive_profile", True))
    crisis_until = str(profile.get("crisis_until")).strip() if profile.get("crisis_until") else None
    crisis_reason = str(profile.get("crisis_reason")).strip() if profile.get("crisis_reason") else None

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO user_settings (
            user_id,
            llm_mode,
            show_confidence,
            lang,
            timezone_name,
            weather_city,
            digest_format,
            quiet_start,
            quiet_end,
            response_style,
            response_density,
            day_mode,
            energy_autopilot,
            cognitive_profile,
            crisis_until,
            crisis_reason,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            llm_mode = excluded.llm_mode,
            show_confidence = excluded.show_confidence,
            lang = excluded.lang,
            timezone_name = excluded.timezone_name,
            weather_city = excluded.weather_city,
            digest_format = excluded.digest_format,
            quiet_start = excluded.quiet_start,
            quiet_end = excluded.quiet_end,
            response_style = excluded.response_style,
            response_density = excluded.response_density,
            day_mode = excluded.day_mode,
            energy_autopilot = excluded.energy_autopilot,
            cognitive_profile = excluded.cognitive_profile,
            crisis_until = excluded.crisis_until,
            crisis_reason = excluded.crisis_reason,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            mode,
            1 if show_confidence else 0,
            lang,
            timezone_name,
            weather_city,
            digest_format,
            quiet_start,
            quiet_end,
            response_style,
            response_density,
            day_mode,
            1 if energy_autopilot else 0,
            1 if cognitive_profile else 0,
            crisis_until,
            crisis_reason,
            updated_at,
        ),
    )
    conn.commit()
    conn.close()


def user_settings_get(user_id: int) -> tuple[str, bool]:
    profile = user_settings_get_full(user_id)
    return str(profile["llm_mode"]), bool(profile["show_confidence"])


def user_settings_set_mode(*, user_id: int, mode: str, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, llm_mode=mode)


def user_settings_set_confidence(*, user_id: int, show_confidence: bool, updated_at: str) -> None:
    user_settings_upsert(
        user_id=user_id,
        updated_at=updated_at,
        show_confidence=show_confidence,
    )


def user_settings_set_lang(*, user_id: int, lang: str | None, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, lang=lang)


def user_settings_set_timezone(*, user_id: int, timezone_name: str | None, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, timezone_name=timezone_name)


def user_settings_set_weather_city(*, user_id: int, weather_city: str | None, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, weather_city=weather_city)


def user_settings_set_digest_format(*, user_id: int, digest_format: str, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, digest_format=digest_format)


def user_settings_set_quiet_hours(*, user_id: int, quiet_start: str | None, quiet_end: str | None, updated_at: str) -> None:
    user_settings_upsert(
        user_id=user_id,
        updated_at=updated_at,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
    )


def user_settings_set_response_profile(
    *,
    user_id: int,
    response_style: str | None,
    response_density: str | None,
    updated_at: str,
) -> None:
    user_settings_upsert(
        user_id=user_id,
        updated_at=updated_at,
        response_style=response_style,
        response_density=response_density,
    )


def user_settings_set_day_mode(*, user_id: int, day_mode: str, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, day_mode=day_mode)


def user_settings_set_energy_autopilot(*, user_id: int, enabled: bool, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, energy_autopilot=enabled)


def user_settings_set_cognitive_profile(*, user_id: int, enabled: bool, updated_at: str) -> None:
    user_settings_upsert(user_id=user_id, updated_at=updated_at, cognitive_profile=enabled)


def user_settings_set_crisis(
    *,
    user_id: int,
    crisis_until: str | None,
    crisis_reason: str | None,
    updated_at: str,
) -> None:
    user_settings_upsert(
        user_id=user_id,
        updated_at=updated_at,
        crisis_until=crisis_until,
        crisis_reason=crisis_reason,
    )


def subs_add(
    *,
    user_id: int,
    name: str,
    next_date: str,
    period: str,
    created_at: str,
    amount: float | None = None,
    currency: str | None = "RUB",
    note: str | None = "",
    category: str | None = "",
    autopay: bool = True,
    remind_days: int = 3,
) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO subscriptions (
            user_id, name, next_date, period, created_at, updated_at,
            amount, currency, note, category, autopay, remind_days
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            name,
            next_date,
            period,
            created_at,
            created_at,
            (float(amount) if amount is not None else None),
            (str(currency or "RUB").strip().upper() or "RUB"),
            str(note or "").strip(),
            str(category or "").strip(),
            1 if autopay else 0,
            max(0, int(remind_days)),
        ),
    )
    sub_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return sub_id


def subs_list(*, user_id: int) -> list[tuple[int, str, str, str]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period
        FROM subscriptions
        WHERE user_id = ?
        ORDER BY next_date ASC, id ASC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def subs_list_detailed(
    *,
    user_id: int,
) -> list[tuple[int, str, str, str, float | None, str, str, str, int, int]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period, amount, currency, note, category, autopay, remind_days
        FROM subscriptions
        WHERE user_id = ?
        ORDER BY next_date ASC, id ASC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[tuple[int, str, str, str, float | None, str, str, str, int, int]] = []
    for row in rows:
        out.append(
            (
                int(row[0]),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                (float(row[4]) if row[4] is not None else None),
                str(row[5] or "RUB"),
                str(row[6] or ""),
                str(row[7] or ""),
                int(row[8] or 0),
                int(row[9] or 0),
            )
        )
    return out


def subs_delete(*, user_id: int, sub_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM subscriptions WHERE user_id = ? AND id = ?",
        (user_id, sub_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def subs_get(*, user_id: int, sub_id: int) -> tuple[int, str, str, str] | None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period
        FROM subscriptions
        WHERE user_id = ? AND id = ?
        """,
        (user_id, sub_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def subs_get_detailed(
    *,
    user_id: int,
    sub_id: int,
) -> tuple[int, str, str, str, float | None, str, str, str, int, int] | None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period, amount, currency, note, category, autopay, remind_days
        FROM subscriptions
        WHERE user_id = ? AND id = ?
        """,
        (user_id, sub_id),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return (
        int(row[0]),
        str(row[1] or ""),
        str(row[2] or ""),
        str(row[3] or ""),
        (float(row[4]) if row[4] is not None else None),
        str(row[5] or "RUB"),
        str(row[6] or ""),
        str(row[7] or ""),
        int(row[8] or 0),
        int(row[9] or 0),
    )


def subs_update_next_date(*, user_id: int, sub_id: int, next_date: str, updated_at: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE subscriptions
        SET next_date = ?, updated_at = ?
        WHERE user_id = ? AND id = ?
        """,
        (next_date, updated_at, user_id, sub_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def garage_seed_defaults(*, user_id: int, created_at: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(1) FROM garage_assets WHERE user_id = ?", (int(user_id),))
    row = cursor.fetchone()
    count = int(row[0] or 0) if row else 0
    if count > 0:
        conn.close()
        return 0

    inserted = 0
    for item in GARAGE_DEFAULT_ASSETS:
        docs_json = json.dumps(item.get("docs") or [], ensure_ascii=False)
        cursor.execute(
            """
            INSERT INTO garage_assets (
                user_id, kind, title, year, nickname, vin, plate,
                mileage_km, last_service_km, maintenance_interval_km,
                maintenance_due_date, insurance_until, tech_inspection_until,
                note, docs_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                str(item.get("kind") or "car"),
                str(item.get("title") or "").strip() or "Vehicle",
                int(item.get("year") or 0) or None,
                str(item.get("nickname") or "").strip(),
                "",
                "",
                0,
                None,
                max(3000, int(item.get("maintenance_interval_km") or 10000)),
                None,
                None,
                None,
                "",
                docs_json,
                str(created_at),
                str(created_at),
            ),
        )
        inserted += 1
    conn.commit()
    conn.close()
    return inserted


def garage_list_assets(
    *,
    user_id: int,
) -> list[
    tuple[
        int,
        str,
        str,
        int | None,
        str,
        str,
        str,
        int,
        int | None,
        int,
        str | None,
        str | None,
        str | None,
        str,
        str,
        str,
    ]
]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id, kind, title, year, nickname, vin, plate, mileage_km, last_service_km,
            maintenance_interval_km, maintenance_due_date, insurance_until, tech_inspection_until,
            note, docs_json, updated_at
        FROM garage_assets
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (int(user_id),),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[
        tuple[
            int,
            str,
            str,
            int | None,
            str,
            str,
            str,
            int,
            int | None,
            int,
            str | None,
            str | None,
            str | None,
            str,
            str,
            str,
        ]
    ] = []
    for row in rows:
        out.append(
            (
                int(row[0]),
                str(row[1] or "car"),
                str(row[2] or ""),
                int(row[3]) if row[3] is not None else None,
                str(row[4] or ""),
                str(row[5] or ""),
                str(row[6] or ""),
                int(row[7] or 0),
                int(row[8]) if row[8] is not None else None,
                int(row[9] or 10000),
                str(row[10] or "") or None,
                str(row[11] or "") or None,
                str(row[12] or "") or None,
                str(row[13] or ""),
                str(row[14] or "[]"),
                str(row[15] or ""),
            )
        )
    return out


def garage_update_asset(
    *,
    user_id: int,
    asset_id: int,
    updated_at: str,
    mileage_km: int | None = None,
    last_service_km: int | None = None,
    maintenance_interval_km: int | None = None,
    maintenance_due_date: str | None = None,
    insurance_until: str | None = None,
    tech_inspection_until: str | None = None,
    note: str | None = None,
) -> bool:
    fields: list[str] = []
    values: list[Any] = []

    if mileage_km is not None:
        fields.append("mileage_km = ?")
        values.append(max(0, int(mileage_km)))
    if last_service_km is not None:
        fields.append("last_service_km = ?")
        values.append(max(0, int(last_service_km)))
    if maintenance_interval_km is not None:
        fields.append("maintenance_interval_km = ?")
        values.append(max(1000, int(maintenance_interval_km)))
    if maintenance_due_date is not None:
        clean = str(maintenance_due_date).strip()
        fields.append("maintenance_due_date = ?")
        values.append(clean or None)
    if insurance_until is not None:
        clean = str(insurance_until).strip()
        fields.append("insurance_until = ?")
        values.append(clean or None)
    if tech_inspection_until is not None:
        clean = str(tech_inspection_until).strip()
        fields.append("tech_inspection_until = ?")
        values.append(clean or None)
    if note is not None:
        fields.append("note = ?")
        values.append(str(note or "").strip())

    if not fields:
        return False

    fields.append("updated_at = ?")
    values.append(str(updated_at))
    values.extend([int(user_id), int(asset_id)])

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE garage_assets SET {', '.join(fields)} WHERE user_id = ? AND id = ?",
        tuple(values),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def _memory_timeline_append(
    *,
    cursor: sqlite3.Cursor,
    user_id: int,
    key: str,
    value: str,
    is_verified: bool,
    confidence: float,
    operation: str,
    changed_at: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO assistant_memory_timeline (
            user_id, mem_key, mem_value, is_verified, confidence, operation, changed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            key,
            value,
            1 if is_verified else 0,
            max(0.0, min(1.0, float(confidence))),
            operation,
            changed_at,
        ),
    )


def memory_set(
    *,
    user_id: int,
    key: str,
    value: str,
    updated_at: str,
    is_verified: bool = False,
    confidence: float | None = None,
) -> None:
    safe_key = (key or "").strip().lower()
    safe_val = (value or "").strip()
    if not safe_key or not safe_val:
        return
    conf = float(confidence) if confidence is not None else (1.0 if is_verified else 0.5)
    conf = max(0.0, min(1.0, conf))
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO assistant_memory (user_id, mem_key, mem_value, is_verified, confidence, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, mem_key) DO UPDATE SET
            mem_value = excluded.mem_value,
            is_verified = excluded.is_verified,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at
        """,
        (user_id, safe_key, safe_val, 1 if is_verified else 0, conf, updated_at),
    )
    _memory_timeline_append(
        cursor=cursor,
        user_id=user_id,
        key=safe_key,
        value=safe_val,
        is_verified=is_verified,
        confidence=conf,
        operation="set",
        changed_at=updated_at,
    )
    conn.commit()
    conn.close()


def memory_get(*, user_id: int, key: str) -> str | None:
    safe_key = (key or "").strip().lower()
    if not safe_key:
        return None
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT mem_value
        FROM assistant_memory
        WHERE user_id = ? AND mem_key = ?
        LIMIT 1
        """,
        (user_id, safe_key),
    )
    row = cursor.fetchone()
    conn.close()
    if not row or row[0] is None:
        return None
    return str(row[0])


def memory_list(*, user_id: int, limit: int = 20) -> list[tuple[str, str, str]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT mem_key, mem_value, updated_at
        FROM assistant_memory
        WHERE user_id = ?
        ORDER BY updated_at DESC, mem_key ASC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def memory_list_detailed(*, user_id: int, limit: int = 20) -> list[tuple[str, str, bool, float, str]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT mem_key, mem_value, is_verified, confidence, updated_at
        FROM assistant_memory
        WHERE user_id = ?
        ORDER BY is_verified DESC, updated_at DESC, mem_key ASC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[tuple[str, str, bool, float, str]] = []
    for row in rows:
        key = str(row[0])
        value = str(row[1])
        verified = bool(int(row[2] or 0))
        conf = float(row[3] or 0)
        updated = str(row[4] or "")
        out.append((key, value, verified, conf, updated))
    return out


def memory_mark_verified(*, user_id: int, key: str, verified: bool, updated_at: str) -> bool:
    safe_key = (key or "").strip().lower()
    if not safe_key:
        return False
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE assistant_memory
        SET is_verified = ?, confidence = ?, updated_at = ?
        WHERE user_id = ? AND mem_key = ?
        """,
        (1 if verified else 0, 1.0 if verified else 0.5, updated_at, user_id, safe_key),
    )
    ok = cursor.rowcount > 0
    if ok:
        cursor.execute(
            """
            SELECT mem_value, is_verified, confidence
            FROM assistant_memory
            WHERE user_id = ? AND mem_key = ?
            LIMIT 1
            """,
            (user_id, safe_key),
        )
        row = cursor.fetchone()
        if row:
            _memory_timeline_append(
                cursor=cursor,
                user_id=user_id,
                key=safe_key,
                value=str(row[0] or ""),
                is_verified=bool(int(row[1] or 0)),
                confidence=float(row[2] or 0.5),
                operation="verify" if verified else "unverify",
                changed_at=updated_at,
            )
    conn.commit()
    conn.close()
    return ok


def memory_delete(*, user_id: int, key: str) -> bool:
    safe_key = (key or "").strip().lower()
    if not safe_key:
        return False
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT mem_value, is_verified, confidence
        FROM assistant_memory
        WHERE user_id = ? AND mem_key = ?
        LIMIT 1
        """,
        (user_id, safe_key),
    )
    existing = cursor.fetchone()
    cursor.execute(
        """
        DELETE FROM assistant_memory
        WHERE user_id = ? AND mem_key = ?
        """,
        (user_id, safe_key),
    )
    ok = cursor.rowcount > 0
    if ok and existing:
        _memory_timeline_append(
            cursor=cursor,
            user_id=user_id,
            key=safe_key,
            value=str(existing[0] or ""),
            is_verified=bool(int(existing[1] or 0)),
            confidence=float(existing[2] or 0.5),
            operation="delete",
            changed_at=datetime.now().isoformat(timespec="seconds"),
        )
    conn.commit()
    conn.close()
    return ok


def memory_build_context(*, user_id: int, limit: int = 8) -> str:
    rows = memory_list_detailed(user_id=user_id, limit=limit)
    if not rows:
        return ""
    verified = [row for row in rows if row[2]]
    unverified = [row for row in rows if not row[2]]
    lines = ["User profile memory:"]
    for key, value, _is_verified, _confidence, _updated_at in verified[:limit]:
        lines.append(f"- {key}: {value}")
    for key, value, _is_verified, _confidence, _updated_at in unverified[:2]:
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def todo_stats_recent(*, user_id: int, since_iso: str) -> tuple[int, int]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM todo_items
        WHERE user_id = ? AND status = 'done' AND done_at >= ?
        """,
        (user_id, since_iso),
    )
    done_count = int(cursor.fetchone()[0] or 0)
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM todo_items
        WHERE user_id = ? AND status = 'open'
        """,
        (user_id,),
    )
    open_count = int(cursor.fetchone()[0] or 0)
    conn.close()
    return done_count, open_count


def todo_done_count_between(*, user_id: int, start_iso: str, end_iso: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM todo_items
        WHERE user_id = ? AND status = 'done' AND done_at >= ? AND done_at < ?
        """,
        (user_id, start_iso, end_iso),
    )
    count = int(cursor.fetchone()[0] or 0)
    conn.close()
    return count


def daily_checkin_recent(*, user_id: int, since_iso: str, limit: int = 7) -> list[tuple[str, str, str, int | None]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT check_date, done_text, carry_text, energy
        FROM daily_checkins
        WHERE user_id = ? AND check_date >= substr(?, 1, 10)
        ORDER BY check_date DESC
        LIMIT ?
        """,
        (user_id, since_iso, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return [(str(r[0]), str(r[1] or ""), str(r[2] or ""), r[3]) for r in rows]


def daily_checkin_count_between(*, user_id: int, start_date_iso: str, end_date_iso: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM daily_checkins
        WHERE user_id = ? AND check_date >= ? AND check_date < ?
        """,
        (user_id, start_date_iso[:10], end_date_iso[:10]),
    )
    count = int(cursor.fetchone()[0] or 0)
    conn.close()
    return count


def subs_due_within(*, user_id: int, days: int = 7) -> list[tuple[int, str, str, str]]:
    today_iso = date.today().isoformat()
    end_iso = (date.today() + timedelta(days=max(0, days))).isoformat()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period
        FROM subscriptions
        WHERE user_id = ? AND next_date >= ? AND next_date <= ?
        ORDER BY next_date ASC, id ASC
        """,
        (user_id, today_iso, end_iso),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def subs_due_within_detailed(
    *,
    user_id: int,
    days: int = 7,
) -> list[tuple[int, str, str, str, float | None, str, str, str, int, int]]:
    today_iso = date.today().isoformat()
    end_iso = (date.today() + timedelta(days=max(0, days))).isoformat()
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, next_date, period, amount, currency, note, category, autopay, remind_days
        FROM subscriptions
        WHERE user_id = ? AND next_date >= ? AND next_date <= ?
        ORDER BY next_date ASC, id ASC
        """,
        (user_id, today_iso, end_iso),
    )
    rows = cursor.fetchall()
    conn.close()
    out: list[tuple[int, str, str, str, float | None, str, str, str, int, int]] = []
    for row in rows:
        out.append(
            (
                int(row[0]),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                (float(row[4]) if row[4] is not None else None),
                str(row[5] or "RUB"),
                str(row[6] or ""),
                str(row[7] or ""),
                int(row[8] or 0),
                int(row[9] or 0),
            )
        )
    return out


def todo_list_all(*, user_id: int, limit: int = 500) -> list[tuple[int, str, str, str, str | None]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, text, status, created_at, done_at
        FROM todo_items
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def fitness_sessions_all(*, user_id: int, limit: int = 500) -> list[tuple[int, str, str, int | None, str | None]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT fs.workout_id, fw.title, fs.done_at, fs.rpe, fs.comment
        FROM fitness_sessions fs
        JOIN fitness_workouts fw ON fw.id = fs.workout_id
        WHERE fs.user_id = ?
        ORDER BY fs.done_at DESC, fs.id DESC
        LIMIT ?
        """,
        (user_id, max(1, limit)),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def memory_timeline_list(
    *,
    user_id: int,
    key: str | None = None,
    limit: int = 30,
) -> list[tuple[str, str, bool, float, str, str]]:
    conn = _connect()
    cursor = conn.cursor()
    if key and key.strip():
        safe_key = key.strip().lower()
        cursor.execute(
            """
            SELECT mem_key, mem_value, is_verified, confidence, operation, changed_at
            FROM assistant_memory_timeline
            WHERE user_id = ? AND mem_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, safe_key, max(1, limit)),
        )
    else:
        cursor.execute(
            """
            SELECT mem_key, mem_value, is_verified, confidence, operation, changed_at
            FROM assistant_memory_timeline
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        )
    rows = cursor.fetchall()
    conn.close()
    return [
        (str(r[0]), str(r[1]), bool(int(r[2] or 0)), float(r[3] or 0.5), str(r[4]), str(r[5]))
        for r in rows
    ]


def automation_rule_add(*, user_id: int, condition_expr: str, action_expr: str, created_at: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO automation_rules (
            user_id, condition_expr, action_expr, is_enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        (user_id, condition_expr.strip(), action_expr.strip(), created_at, created_at),
    )
    rule_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return rule_id


def automation_rule_list(*, user_id: int, enabled_only: bool = False) -> list[tuple[int, str, str, bool, str, str]]:
    conn = _connect()
    cursor = conn.cursor()
    if enabled_only:
        cursor.execute(
            """
            SELECT id, condition_expr, action_expr, is_enabled, created_at, updated_at
            FROM automation_rules
            WHERE user_id = ? AND is_enabled = 1
            ORDER BY id DESC
            """,
            (user_id,),
        )
    else:
        cursor.execute(
            """
            SELECT id, condition_expr, action_expr, is_enabled, created_at, updated_at
            FROM automation_rules
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [
        (int(r[0]), str(r[1]), str(r[2]), bool(int(r[3] or 0)), str(r[4]), str(r[5]))
        for r in rows
    ]


def automation_rule_delete(*, user_id: int, rule_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM automation_rules WHERE user_id = ? AND id = ?",
        (user_id, rule_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def automation_rule_set_enabled(*, user_id: int, rule_id: int, enabled: bool, updated_at: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE automation_rules
        SET is_enabled = ?, updated_at = ?
        WHERE user_id = ? AND id = ?
        """,
        (1 if enabled else 0, updated_at, user_id, rule_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


_ALERT_METRICS = {"btc", "eth", "usd_rub", "eur_rub", "fuel95", "subs_due"}
_ALERT_OPERATORS = {"<=", ">="}


def finance_alert_add(
    *,
    user_id: int,
    metric: str,
    operator: str,
    threshold: float | None,
    due_days: int | None,
    created_at: str,
) -> int:
    safe_metric = metric.strip().lower()
    safe_operator = operator.strip() if operator else "<="
    if safe_metric not in _ALERT_METRICS:
        raise ValueError("unsupported metric")
    if safe_operator not in _ALERT_OPERATORS:
        raise ValueError("unsupported operator")
    if safe_metric == "subs_due":
        threshold = None
        due_days = max(1, int(due_days or 3))
    else:
        due_days = None
        if threshold is None:
            raise ValueError("threshold is required")

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO finance_alerts (
            user_id, metric, operator, threshold, due_days, is_enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, safe_metric, safe_operator, threshold, due_days, created_at, created_at),
    )
    alert_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return alert_id


def finance_alert_list(*, user_id: int, enabled_only: bool = False) -> list[tuple[int, str, str, float | None, int | None, bool]]:
    conn = _connect()
    cursor = conn.cursor()
    if enabled_only:
        cursor.execute(
            """
            SELECT id, metric, operator, threshold, due_days, is_enabled
            FROM finance_alerts
            WHERE user_id = ? AND is_enabled = 1
            ORDER BY id DESC
            """,
            (user_id,),
        )
    else:
        cursor.execute(
            """
            SELECT id, metric, operator, threshold, due_days, is_enabled
            FROM finance_alerts
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [
        (
            int(r[0]),
            str(r[1]),
            str(r[2]),
            None if r[3] is None else float(r[3]),
            None if r[4] is None else int(r[4]),
            bool(int(r[5] or 0)),
        )
        for r in rows
    ]


def finance_alert_delete(*, user_id: int, alert_id: int) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM finance_alerts WHERE user_id = ? AND id = ?",
        (user_id, alert_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def finance_alert_set_enabled(*, user_id: int, alert_id: int, enabled: bool, updated_at: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE finance_alerts
        SET is_enabled = ?, updated_at = ?
        WHERE user_id = ? AND id = ?
        """,
        (1 if enabled else 0, updated_at, user_id, alert_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def reflection_upsert(
    *,
    user_id: int,
    reflection_date: str,
    done_text: str,
    drain_text: str,
    remove_text: str,
    tomorrow_rule: str,
    created_at: str,
    updated_at: str,
) -> None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO daily_reflections (
            user_id, reflection_date, done_text, drain_text, remove_text, tomorrow_rule, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, reflection_date) DO UPDATE SET
            done_text = excluded.done_text,
            drain_text = excluded.drain_text,
            remove_text = excluded.remove_text,
            tomorrow_rule = excluded.tomorrow_rule,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            reflection_date,
            done_text.strip(),
            drain_text.strip(),
            remove_text.strip(),
            tomorrow_rule.strip(),
            created_at,
            updated_at,
        ),
    )
    conn.commit()
    conn.close()


def reflection_get(*, user_id: int, reflection_date: str) -> tuple[str, str, str, str, str] | None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT done_text, drain_text, remove_text, tomorrow_rule, updated_at
        FROM daily_reflections
        WHERE user_id = ? AND reflection_date = ?
        LIMIT 1
        """,
        (user_id, reflection_date),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))


def reflection_latest(*, user_id: int) -> tuple[str, str, str, str, str, str] | None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT reflection_date, done_text, drain_text, remove_text, tomorrow_rule, updated_at
        FROM daily_reflections
        WHERE user_id = ?
        ORDER BY reflection_date DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]))


def reflection_count_between(*, user_id: int, start_date_iso: str, end_date_iso: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(1)
        FROM daily_reflections
        WHERE user_id = ? AND reflection_date >= ? AND reflection_date < ?
        """,
        (user_id, start_date_iso[:10], end_date_iso[:10]),
    )
    count = int(cursor.fetchone()[0] or 0)
    conn.close()
    return count


def focus_session_start(*, user_id: int, duration_min: int, started_at: str) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO focus_sessions (user_id, duration_min, started_at, status)
        VALUES (?, ?, ?, 'running')
        """,
        (user_id, max(1, int(duration_min)), started_at),
    )
    focus_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return focus_id


def focus_session_finish(*, user_id: int, focus_id: int, finished_at: str, status: str) -> bool:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE focus_sessions
        SET finished_at = ?, status = ?
        WHERE id = ? AND user_id = ?
        """,
        (finished_at, status, focus_id, user_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def focus_stats_recent(*, user_id: int, since_iso: str) -> tuple[int, int]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COALESCE(SUM(duration_min), 0), COUNT(1)
        FROM focus_sessions
        WHERE user_id = ? AND status = 'done' AND started_at >= ?
        """,
        (user_id, since_iso),
    )
    row = cursor.fetchone() or (0, 0)
    conn.close()
    total_minutes = int(row[0] or 0)
    sessions = int(row[1] or 0)
    return total_minutes, sessions


def decision_log_add(
    *,
    user_id: int,
    decision_text: str,
    hypothesis: str,
    expected_outcome: str,
    decision_date: str,
    review_after_date: str,
    created_at: str,
) -> int:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO decision_journal (
            user_id,
            decision_text,
            hypothesis,
            expected_outcome,
            decision_date,
            review_after_date,
            status,
            actual_outcome,
            score,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'open', '', NULL, ?, ?)
        """,
        (
            user_id,
            decision_text.strip(),
            hypothesis.strip(),
            expected_outcome.strip(),
            decision_date,
            review_after_date,
            created_at,
            created_at,
        ),
    )
    decision_id = int(cursor.lastrowid or 0)
    conn.commit()
    conn.close()
    return decision_id


def decision_log_list(*, user_id: int, only_open: bool = False, limit: int = 20) -> list[tuple[Any, ...]]:
    conn = _connect()
    cursor = conn.cursor()
    if only_open:
        cursor.execute(
            """
            SELECT
                id, decision_text, hypothesis, expected_outcome, decision_date, review_after_date,
                status, actual_outcome, score, updated_at
            FROM decision_journal
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        )
    else:
        cursor.execute(
            """
            SELECT
                id, decision_text, hypothesis, expected_outcome, decision_date, review_after_date,
                status, actual_outcome, score, updated_at
            FROM decision_journal
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def decision_log_due_reviews(*, user_id: int, as_of_date: str) -> list[tuple[Any, ...]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id, decision_text, hypothesis, expected_outcome, decision_date, review_after_date,
            status, actual_outcome, score, updated_at
        FROM decision_journal
        WHERE user_id = ? AND status = 'open' AND review_after_date <= ?
        ORDER BY review_after_date ASC, id ASC
        LIMIT 20
        """,
        (user_id, as_of_date),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def decision_log_set_outcome(
    *,
    user_id: int,
    decision_id: int,
    actual_outcome: str,
    score: int | None,
    updated_at: str,
) -> bool:
    safe_score = None if score is None else max(1, min(10, int(score)))
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE decision_journal
        SET actual_outcome = ?, score = ?, status = 'closed', updated_at = ?
        WHERE user_id = ? AND id = ?
        """,
        (actual_outcome.strip(), safe_score, updated_at, user_id, decision_id),
    )
    ok = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return ok


