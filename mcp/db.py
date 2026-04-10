"""Database layer for Omni-Track MCP server.

Uses SQLite for local development (zero-install), with an API that can be
swapped to PostgreSQL for production Docker deployment.
"""

import os
import sqlite3
import logging
import threading
from decimal import Decimal
from datetime import datetime, date
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("OMNITRACK_DB_PATH", os.path.join(os.path.dirname(__file__), "omnitrack.db"))

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metric_types (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            unit        TEXT,
            category    TEXT NOT NULL CHECK (category IN ('biometric', 'financial', 'behavioral', 'custom', 'context')),
            viz_type    TEXT DEFAULT 'pending' CHECK (viz_type IN ('bar', 'line', 'pending')),
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metric_readings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_type_id  INTEGER REFERENCES metric_types(id),
            value           REAL NOT NULL,
            timestamp       TEXT NOT NULL,
            ingested_at     TEXT DEFAULT (datetime('now')),
            source_type     TEXT NOT NULL CHECK (source_type IN ('pdf', 'image', 'voice', 'text')),
            source_ref      TEXT,
            notes           TEXT,
            UNIQUE(metric_type_id, timestamp)
        );

        CREATE TABLE IF NOT EXISTS insights (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start   TEXT UNIQUE NOT NULL,
            content      TEXT NOT NULL,
            generated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS safe_ranges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_name TEXT UNIQUE NOT NULL,
            min_value   REAL,
            max_value   REAL,
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_readings_metric_type   ON metric_readings(metric_type_id);
        CREATE INDEX IF NOT EXISTS idx_readings_timestamp      ON metric_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_readings_metric_ts_desc ON metric_readings(metric_type_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_metric_types_category   ON metric_types(category);
    """)
    conn.commit()

    # ── Migrations for existing databases ──
    _migrate(conn)
    logger.info("Database initialized at %s", DB_PATH)


def _migrate(conn: sqlite3.Connection) -> None:
    """Run schema migrations for columns/tables added after initial release."""
    cursor = conn.execute("PRAGMA table_info(metric_types)")
    columns = {row[1] for row in cursor.fetchall()}

    if "viz_type" not in columns:
        conn.execute("ALTER TABLE metric_types ADD COLUMN viz_type TEXT DEFAULT 'pending' CHECK (viz_type IN ('bar', 'line', 'pending'))")
        conn.commit()
        logger.info("Migration: added viz_type column to metric_types")


def _serialize(value):
    """Convert DB types to JSON-safe Python types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: _serialize(row[k]) for k in row.keys()}


def fetch_all(query: str, params=None) -> list[dict]:
    conn = _get_conn()
    cursor = conn.execute(query, params or ())
    return [_row_to_dict(row) for row in cursor.fetchall()]


def fetch_one(query: str, params=None) -> dict | None:
    conn = _get_conn()
    cursor = conn.execute(query, params or ())
    row = cursor.fetchone()
    return _row_to_dict(row) if row else None


def execute(query: str, params=None) -> int:
    conn = _get_conn()
    cursor = conn.execute(query, params or ())
    conn.commit()
    return cursor.rowcount


def execute_returning(query: str, params=None) -> dict | None:
    """Execute an INSERT/UPDATE and return the affected row.

    SQLite doesn't support RETURNING, so we use last_insert_rowid()
    and re-fetch when needed.
    """
    conn = _get_conn()
    cursor = conn.execute(query, params or ())
    conn.commit()
    last_id = cursor.lastrowid
    # Return a minimal dict with the id
    return {"id": last_id, "ingested_at": datetime.utcnow().isoformat(), "generated_at": datetime.utcnow().isoformat()}
