"""
control-api/db.py
SQLite database layer.  All schema creation happens here on startup.
Database file: /app/data/tcad.db  (persisted via Docker volume)
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/app/data/tcad.db")

# Use a thread-local connection so tests can override DB_PATH per-process
_local = threading.local()

# Test override: when set, all get_db() calls use this single shared
# connection instead of thread-local ones. This is needed because
# FastAPI sync endpoints run in a thread pool, and SQLite WAL mode
# gives each connection its own snapshot — writes from one thread
# may not be visible to reads in another thread's connection.
_shared_test_conn = None


def set_shared_test_connection(conn):
    """Set a single shared connection for all database access (test mode only)."""
    global _shared_test_conn
    _shared_test_conn = conn


def _get_conn() -> sqlite3.Connection:
    # Test mode: return the shared connection
    if _shared_test_conn is not None:
        return _shared_test_conn

    # Read DB_PATH fresh each call so test env overrides take effect
    db_path = os.environ.get("DB_PATH", DB_PATH)
    # Reconnect if path changed (test isolation)
    existing_path = getattr(_local, "db_path", None)
    if not hasattr(_local, "conn") or _local.conn is None or existing_path != db_path:
        if hasattr(_local, "conn") and _local.conn is not None:
            try:
                _local.conn.close()
            except Exception:
                pass
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        _local.conn = sqlite3.connect(db_path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.db_path = db_path
    return _local.conn


@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """Create all tables.  Safe to call multiple times (IF NOT EXISTS)."""
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          TEXT    PRIMARY KEY,
            ts          TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            severity    TEXT    NOT NULL,
            mode        INTEGER NOT NULL DEFAULT 1,
            src_ip      TEXT    NOT NULL,
            identity    TEXT    NOT NULL,
            session_id  TEXT    NOT NULL,
            method      TEXT    NOT NULL,
            path        TEXT    NOT NULL,
            user_agent  TEXT    NOT NULL DEFAULT '',
            status      INTEGER NOT NULL,
            detail      TEXT    NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

        CREATE TABLE IF NOT EXISTS quarantine (
            identity        TEXT    PRIMARY KEY,
            quarantined_at  TEXT    NOT NULL,
            expires_at      TEXT    NOT NULL,
            reason          TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS honeytokens (
            token       TEXT    PRIMARY KEY,
            session_id  TEXT    NOT NULL,
            identity    TEXT    NOT NULL,
            issued_at   TEXT    NOT NULL,
            active      INTEGER NOT NULL DEFAULT 1
        );

        -- Monotonic reset epoch — incremented by POST /reset.
        -- Gateway uses this to deterministically clear confirmed quarantines
        -- without relying on "list is empty" inference.
        CREATE TABLE IF NOT EXISTS metadata (
            key     TEXT PRIMARY KEY,
            value   INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO metadata (key, value) VALUES ('quarantine_epoch', 0);

        CREATE TABLE IF NOT EXISTS sim_runs (
            run_id      TEXT    PRIMARY KEY,
            scenario    TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'idle',
            started_at  TEXT,
            finished_at TEXT,
            result      TEXT
        );
        """)
