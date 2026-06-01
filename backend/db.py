import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/fuel.db")

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS food_entries (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            date        TEXT NOT NULL,
            text        TEXT NOT NULL,
            parsed      TEXT NOT NULL,
            kcal        INTEGER NOT NULL,
            logged_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS food_entries_user_date
            ON food_entries(user_id, date);

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            endpoint    TEXT NOT NULL UNIQUE,
            keys        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_profile (
            user_id         TEXT PRIMARY KEY,
            kcal_target     INTEGER NOT NULL DEFAULT 2000,
            nudge_times     TEXT NOT NULL DEFAULT '["08:00","13:00","15:00","20:00"]',
            timezone        TEXT NOT NULL DEFAULT 'Europe/London'
        );
    """)
    conn.commit()


# ── Food ──────────────────────────────────────────────────────────────────────


def insert_food_entry(entry: dict) -> None:
    get_db().execute(
        "INSERT INTO food_entries (id, user_id, date, text, parsed, kcal, logged_at) "
        "VALUES (:id, :user_id, :date, :text, :parsed, :kcal, :logged_at)",
        entry,
    )
    get_db().commit()


def get_food_entries(user_id: str, date: str) -> list[dict]:
    rows = (
        get_db()
        .execute(
            "SELECT * FROM food_entries WHERE user_id=? AND date=? ORDER BY logged_at DESC",
            (user_id, date),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def delete_food_entry(entry_id: str, user_id: str) -> None:
    get_db().execute(
        "DELETE FROM food_entries WHERE id=? AND user_id=?", (entry_id, user_id)
    )
    get_db().commit()


# ── Push subscriptions ────────────────────────────────────────────────────────


def upsert_push_subscription(
    sub_id: str, user_id: str, endpoint: str, keys: dict, created_at: str
) -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO push_subscriptions (id, user_id, endpoint, keys, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sub_id, user_id, endpoint, json.dumps(keys), created_at),
    )
    get_db().commit()


def delete_push_subscription(endpoint: str, user_id: str) -> None:
    get_db().execute(
        "DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?",
        (endpoint, user_id),
    )
    get_db().commit()


def get_push_subscriptions(user_id: str) -> list[dict]:
    rows = (
        get_db()
        .execute("SELECT * FROM push_subscriptions WHERE user_id=?", (user_id,))
        .fetchall()
    )
    return [{**dict(r), "keys": json.loads(r["keys"])} for r in rows]


# ── Profile ───────────────────────────────────────────────────────────────────

DEFAULT_PROFILE = {
    "kcal_target": 2000,
    "nudge_times": ["08:00", "13:00", "15:00", "20:00"],
    "timezone": "Europe/London",
}


def get_profile(user_id: str) -> dict:
    row = (
        get_db()
        .execute("SELECT * FROM user_profile WHERE user_id=?", (user_id,))
        .fetchone()
    )
    if not row:
        return {**DEFAULT_PROFILE, "user_id": user_id}
    d = dict(row)
    d["nudge_times"] = json.loads(d["nudge_times"])
    return d


def upsert_profile(user_id: str, updates: dict) -> dict:
    current = get_profile(user_id)
    merged = {**current, **updates, "user_id": user_id}
    get_db().execute(
        "INSERT OR REPLACE INTO user_profile (user_id, kcal_target, nudge_times, timezone) "
        "VALUES (:user_id, :kcal_target, :nudge_times, :timezone)",
        {**merged, "nudge_times": json.dumps(merged["nudge_times"])},
    )
    get_db().commit()
    return get_profile(user_id)
