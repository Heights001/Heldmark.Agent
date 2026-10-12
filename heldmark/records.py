"""The three operations behind the heldmark-records server.

This is the only code that stores or changes learner facts. The MCP server and
the command line both call it, and every call lands in the audit log with its
input, output, timestamp, and learner id.
"""

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import date

from . import rules, store

TOOLS = ("append_event", "list_events", "update_profile")
FORBIDDEN = ("label", "rank", "score", "share", "recommend")
DEFAULT_TEACHER = "the receiving class teacher"

KIND_SHAPE = re.compile(r"^[a-z][a-z0-9_]*$")


class Rejected(Exception):
    """A request the records refuse. It is logged before it is raised."""


class Records:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _log(self, tool: str, learner_id: str | None, given: dict, output, outcome: str = "ok") -> None:
        self.conn.execute(
            "INSERT INTO audit_log (at, tool, learner_id, input, output, outcome) VALUES (?, ?, ?, ?, ?, ?)",
            (store.now(), tool, learner_id, json.dumps(given, default=str), json.dumps(output, default=str), outcome),
        )
        self.conn.commit()

    def _reject(self, tool: str, learner_id: str | None, given: dict, reason: str):
        self._log(tool, learner_id, given, {"rejected": reason}, "rejected")
        raise Rejected(reason)

    def append_event(
        self,
        learner_id: str,
        kind: str,
        source: str,
        score: float | None = None,
        text: str | None = None,
        school: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Store one cited quiz, project, or note. Past rows are never touched."""
        given = {k: v for k, v in locals().items() if k != "self"}
        learner_id = (learner_id or "").strip()
        if not learner_id:
            self._reject("append_event", None, given, "No learner id.")
        if not (source or "").strip():
            self._reject("append_event", learner_id, given, "No source. An event must cite its source before it is stored.")
        kind = rules.normalise_kind(kind or "")
        if not KIND_SHAPE.match(kind):
            self._reject("append_event", learner_id, given, "Kind must be a short task name such as word_problem.")
        if rules.contains_label(kind):
            self._reject("append_event", learner_id, given, "Kind labels the learner. Name the task, not the child.")
        if kind == rules.NOTE_KIND and not (text or "").strip():
            self._reject("append_event", learner_id, given, "A note needs its text.")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
            self._reject("append_event", learner_id, given, "Score must be a number.")
        event_date = date or _today()
        try:
            event_date = _iso(event_date)
        except ValueError:
            self._reject("append_event", learner_id, given, "Date must look like 2026-03-12.")

        cursor = self.conn.execute(
            "INSERT INTO events (learner_id, kind, source, score, text, school, event_date, recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (learner_id, kind, source.strip(), score, text, school, event_date, store.now()),
        )
        event = self._event(cursor.lastrowid)
        self._log("append_event", learner_id, given, event)
        return event

    def list_events(self, learner_id: str) -> list[dict]:
        """One learner's events, oldest first. The query cannot reach another learner."""
        events = self._events(learner_id)
        self._log("list_events", learner_id, {"learner_id": learner_id}, {"count": len(events)})
        return events

    def update_profile(self, learner_id: str, shown_to: str = DEFAULT_TEACHER) -> dict:
        """Rewrite the sourced profile from the rules and nothing else."""
        profile = rules.build_profile(learner_id, self._events(learner_id))
        text = rules.render(profile, shown_to)
        self.conn.execute(
            "INSERT INTO profiles (learner_id, body, shown_to, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(learner_id) DO UPDATE SET body = excluded.body,"
            " shown_to = excluded.shown_to, updated_at = excluded.updated_at",
            (learner_id, text, shown_to, store.now()),
        )
        result = {
            "learner_id": learner_id,
            "shown_to": shown_to,
            "lines": [asdict(line) for line in profile.lines],
            "text": text,
        }
        self._log("update_profile", learner_id, {"learner_id": learner_id, "shown_to": shown_to}, result)
        return result

    def refuse(self, request: str, arguments: dict | None = None):
        """Anything that is not one of the three tools. Rejected and logged."""
        arguments = arguments or {}
        learner_id = arguments.get("learner_id") or arguments.get("learner")
        name = rules.normalise_kind(request)
        if any(name.startswith(word) for word in FORBIDDEN):
            reason = (
                f"Rejected: '{request}'. Heldmark has no tool to label, rank, score, share, or recommend. "
                "The teacher decides."
            )
        else:
            reason = f"Rejected: '{request}' is not a heldmark-records tool. The tools are {', '.join(TOOLS)}."
        self._reject(request, learner_id, arguments, reason)

    def audit(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM audit_log ORDER BY id")]

    def _event(self, event_id: int) -> dict:
        return dict(self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())

    def _events(self, learner_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE learner_id = ? ORDER BY event_date, id", (learner_id,)
        )
        return [dict(row) for row in rows]


def _today() -> str:
    return date.today().isoformat()


def _iso(value: str) -> str:
    return date.fromisoformat(str(value)).isoformat()
