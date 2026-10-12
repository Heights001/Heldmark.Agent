"""python -m heldmark.demo

Loads the anonymised five-school fixture into a throwaway in-memory store and
prints learner L1's sourced profile. Nothing is written to disk or sent anywhere.
"""

import json
from pathlib import Path

from . import store
from .records import Records, Rejected

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "fixture" / "five_schools.json"


def load_fixture(records: Records, path: Path = FIXTURE) -> tuple[dict, list[str]]:
    """Append every fixture event through append_event. Returns the fixture and what was refused."""
    fixture = json.loads(path.read_text())
    refused = []
    for fragment in fixture["schools"]:
        for event in fragment["events"]:
            try:
                records.append_event(fixture["learner_id"], school=fragment["school"], **event)
            except Rejected as refusal:
                refused.append(f"{fragment['school']}, {event['kind']}: {refusal}")
    return fixture, refused


def main() -> None:
    records = Records(store.connect(":memory:"))
    fixture, refused = load_fixture(records)
    stored = len(records.list_events(fixture["learner_id"]))
    print(f"Fixture: {FIXTURE.relative_to(FIXTURE.parents[2])}")
    print(f"Intake: {stored} cited events stored from {len(fixture['schools'])} schools, {len(refused)} refused.")
    for line in refused:
        print(f"  refused: {line}")
    print()
    print(records.update_profile(fixture["learner_id"], fixture["shown_to"])["text"])


if __name__ == "__main__":
    main()
