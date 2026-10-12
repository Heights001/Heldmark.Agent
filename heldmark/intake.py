"""Turn the text of one prior-school file into candidate events.

Pure: no files, no database, no tools. The graph reads the file through the
Filesystem MCP server and hands the text here. Whether a candidate is valid is
decided later by append_event, not here.
"""

import json

EVENT_KEYS = ("kind", "source", "score", "text", "date")


def parse(name: str, text: str, learner_id: str) -> tuple[list[dict], list[str], str | None]:
    """Return (candidate events, problems, the named teacher if the file gives one)."""
    try:
        data = json.loads(text)
        fragments = data["schools"]
    except (ValueError, KeyError, TypeError):
        return [], [f"{name}: not a prior-school file Heldmark can read."], None
    if data.get("learner_id") != learner_id:
        # Another learner's file is not opened further and nothing from it is passed on.
        return [], [f"{name}: for a different learner. Not used."], None

    candidates = []
    for fragment in fragments:
        for event in fragment.get("events", []):
            candidate = {key: event[key] for key in EVENT_KEYS if event.get(key) is not None}
            candidate.setdefault("kind", "")
            candidate.setdefault("source", "")
            candidates.append({"learner_id": learner_id, "school": fragment.get("school"), **candidate})
    return candidates, [], data.get("shown_to")
