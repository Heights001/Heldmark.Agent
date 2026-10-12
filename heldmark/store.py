"""SQLite store for one machine.

Events and the audit log are append-only: triggers abort any UPDATE or DELETE.
The profile is the only row that is ever rewritten.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "heldmark.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id  TEXT NOT NULL CHECK (length(trim(learner_id)) > 0),
    kind        TEXT NOT NULL CHECK (length(trim(kind)) > 0),
    source      TEXT NOT NULL CHECK (length(trim(source)) > 0),
    score       REAL,
    text        TEXT,
    school      TEXT,
    event_date  TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS profiles (
    learner_id TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    shown_to   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    tool       TEXT NOT NULL,
    learner_id TEXT,
    input      TEXT NOT NULL,
    output     TEXT NOT NULL,
    outcome    TEXT NOT NULL CHECK (outcome IN ('ok', 'rejected'))
);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


def log(conn: sqlite3.Connection, tool: str, learner_id: str | None, given, output, outcome: str = "ok") -> None:
    """Append one row to the audit log: input, output, timestamp, learner id."""
    conn.execute(
        "INSERT INTO audit_log (at, tool, learner_id, input, output, outcome) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), tool, learner_id, json.dumps(given, default=str), json.dumps(output, default=str), outcome),
    )
    conn.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path(path: str | None = None) -> str:
    return path or os.environ.get("HELDMARK_DB") or DEFAULT_DB


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open the store and make sure the schema exists. Use ":memory:" for a throwaway store."""
    conn = sqlite3.connect(db_path(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
