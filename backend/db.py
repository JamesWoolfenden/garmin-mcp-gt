import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_KMS_KEY = os.environ.get(
    "GARMIN_TOKEN_KMS_KEY",
    "projects/pike-477416/locations/global/keyRings/fuel/cryptoKeys/garmin-tokens",
)
_USE_KMS = os.environ.get("DB_PATH", "") != ":memory:"  # skip KMS in tests


def _encrypt(plaintext: str) -> str:
    if not _USE_KMS:
        return plaintext
    from google.cloud import kms

    client = kms.KeyManagementServiceClient()
    resp = client.encrypt(request={"name": _KMS_KEY, "plaintext": plaintext.encode()})
    return base64.b64encode(resp.ciphertext).decode()


def _decrypt(ciphertext: str) -> str:
    if not _USE_KMS:
        return ciphertext
    try:
        from google.cloud import kms

        client = kms.KeyManagementServiceClient()
        resp = client.decrypt(
            request={"name": _KMS_KEY, "ciphertext": base64.b64decode(ciphertext)}
        )
        return resp.plaintext.decode()
    except Exception:
        return ciphertext  # fallback for unencrypted legacy data


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
        CREATE TABLE IF NOT EXISTS garmin_tokens (
            user_id     TEXT PRIMARY KEY,
            tokens_json TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS garmin_upload_tokens (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mcp_api_keys (
            key_hash    TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mcp_api_keys_user ON mcp_api_keys(user_id);

        CREATE TABLE IF NOT EXISTS food_entries (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            date        TEXT NOT NULL,
            text        TEXT NOT NULL,
            parsed      TEXT NOT NULL,
            kcal        INTEGER NOT NULL,
            macros_json TEXT,
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
            timezone        TEXT NOT NULL DEFAULT 'Europe/London',
            height_cm       INTEGER
        );

        CREATE TABLE IF NOT EXISTS registered_users (
            user_id     TEXT PRIMARY KEY,
            email       TEXT NOT NULL,
            registered_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            role        TEXT NOT NULL,
            content_enc TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chat_history_user_time
            ON chat_history(user_id, created_at);

        CREATE TABLE IF NOT EXISTS manual_activities (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            date        TEXT NOT NULL,
            name        TEXT NOT NULL,
            kcal        INTEGER NOT NULL,
            logged_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS manual_activities_user_date
            ON manual_activities(user_id, date);
    """)
    for migration in [
        "ALTER TABLE food_entries ADD COLUMN macros_json TEXT",
        "ALTER TABLE user_profile ADD COLUMN height_cm INTEGER",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise

    conn.commit()


# ── Chat history (KMS-encrypted) ─────────────────────────────────────────────


def save_chat_message(user_id: str, role: str, content: str) -> None:
    import uuid

    get_db().execute(
        "INSERT INTO chat_history (id, user_id, role, content_enc, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            user_id,
            role,
            _encrypt(content),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    get_db().commit()


def load_chat_history(user_id: str, limit: int = 40) -> list[dict]:
    rows = (
        get_db()
        .execute(
            "SELECT role, content_enc, created_at FROM chat_history "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        .fetchall()
    )
    # Return in chronological order with content decrypted
    return [
        {
            "role": r["role"],
            "text": _decrypt(r["content_enc"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]


# ── Registered users ─────────────────────────────────────────────────────────


def register_user(user_id: str, email: str) -> None:
    get_db().execute(
        "INSERT OR IGNORE INTO registered_users (user_id, email, registered_at) VALUES (?, ?, ?)",
        (user_id, email, datetime.now(timezone.utc).isoformat()),
    )
    get_db().commit()


def list_registered_users() -> list[dict]:
    rows = (
        get_db()
        .execute(
            "SELECT user_id, email, registered_at FROM registered_users ORDER BY registered_at DESC"
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def delete_registered_user(user_id: str) -> None:
    get_db().execute("DELETE FROM registered_users WHERE user_id=?", (user_id,))
    get_db().commit()


# ── Garmin tokens ────────────────────────────────────────────────────────────


def save_garmin_tokens(user_id: str, tokens_json: str) -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO garmin_tokens (user_id, tokens_json, updated_at) VALUES (?, ?, ?)",
        (user_id, _encrypt(tokens_json), datetime.now(timezone.utc).isoformat()),
    )
    get_db().commit()


def load_garmin_tokens(user_id: str) -> str | None:
    row = (
        get_db()
        .execute("SELECT tokens_json FROM garmin_tokens WHERE user_id=?", (user_id,))
        .fetchone()
    )
    return _decrypt(row["tokens_json"]) if row else None


# ── MCP API keys ──────────────────────────────────────────────────────────────


def create_upload_token(token: str, user_id: str, expires_at: str) -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO garmin_upload_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    get_db().commit()


def consume_upload_token(token: str) -> str | None:
    """Validate and delete the token, returning the user_id if valid and unexpired."""
    row = (
        get_db()
        .execute(
            "SELECT user_id, expires_at FROM garmin_upload_tokens WHERE token=?",
            (token,),
        )
        .fetchone()
    )
    if not row:
        return None
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None
    get_db().execute("DELETE FROM garmin_upload_tokens WHERE token=?", (token,))
    get_db().commit()
    return row["user_id"]


def upsert_mcp_api_key(key_hash: str, user_id: str) -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO mcp_api_keys (key_hash, user_id, created_at) VALUES (?, ?, ?)",
        (key_hash, user_id, datetime.now(timezone.utc).isoformat()),
    )
    get_db().commit()


def get_user_for_mcp_key(key_hash: str) -> str | None:
    row = (
        get_db()
        .execute("SELECT user_id FROM mcp_api_keys WHERE key_hash=?", (key_hash,))
        .fetchone()
    )
    return row["user_id"] if row else None


def delete_mcp_api_keys(user_id: str) -> None:
    get_db().execute("DELETE FROM mcp_api_keys WHERE user_id=?", (user_id,))
    get_db().commit()


# ── Food ──────────────────────────────────────────────────────────────────────


def insert_food_entry(entry: dict) -> None:
    get_db().execute(
        "INSERT INTO food_entries (id, user_id, date, text, parsed, kcal, macros_json, logged_at) "
        "VALUES (:id, :user_id, :date, :text, :parsed, :kcal, :macros_json, :logged_at)",
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


def get_all_subscribed_users() -> list[str]:
    rows = (
        get_db().execute("SELECT DISTINCT user_id FROM push_subscriptions").fetchall()
    )
    return [r["user_id"] for r in rows]


def get_push_subscriptions(user_id: str) -> list[dict]:
    rows = (
        get_db()
        .execute("SELECT * FROM push_subscriptions WHERE user_id=?", (user_id,))
        .fetchall()
    )
    return [{**dict(r), "keys": json.loads(r["keys"])} for r in rows]


# ── Manual activities ─────────────────────────────────────────────────────────


def insert_manual_activity(entry: dict) -> None:
    get_db().execute(
        "INSERT INTO manual_activities (id, user_id, date, name, kcal, logged_at) "
        "VALUES (:id, :user_id, :date, :name, :kcal, :logged_at)",
        entry,
    )
    get_db().commit()


def get_manual_activities(user_id: str, date: str) -> list[dict]:
    rows = (
        get_db()
        .execute(
            "SELECT * FROM manual_activities WHERE user_id=? AND date=? ORDER BY logged_at DESC",
            (user_id, date),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def delete_manual_activity(entry_id: str, user_id: str) -> None:
    get_db().execute(
        "DELETE FROM manual_activities WHERE id=? AND user_id=?", (entry_id, user_id)
    )
    get_db().commit()


# ── Profile ───────────────────────────────────────────────────────────────────

DEFAULT_PROFILE = {
    "kcal_target": 2000,
    "nudge_times": ["08:00", "13:00", "15:00", "20:00"],
    "timezone": "Europe/London",
    "height_cm": None,
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
        "INSERT OR REPLACE INTO user_profile (user_id, kcal_target, nudge_times, timezone, height_cm) "
        "VALUES (:user_id, :kcal_target, :nudge_times, :timezone, :height_cm)",
        {**merged, "nudge_times": json.dumps(merged["nudge_times"])},
    )
    get_db().commit()
    return get_profile(user_id)
