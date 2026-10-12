"""Command line.

python -m heldmark add-event --learner L1 --source "..." --kind word_problem --score 40
python -m heldmark update-profile --learner L1
python -m heldmark list-events --learner L1
"""

import argparse
import json
import sys

from . import store
from .records import DEFAULT_TEACHER, Records, Rejected

COMMANDS = ("add-event", "update-profile", "list-events")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heldmark", description="One learner, cited events, a sourced profile.")
    parser.add_argument("--db", help="SQLite file (default: $HELDMARK_DB or heldmark.db)")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add-event", help="store one cited quiz, project, or note")
    add.add_argument("--learner", required=True)
    add.add_argument("--source", required=True, help="the quiz, project, or note this came from")
    add.add_argument("--kind", required=True, help="task kind, e.g. word_problem, calculation, note")
    add.add_argument("--score", type=float)
    add.add_argument("--text", help="the wording of a teacher note")
    add.add_argument("--school")
    add.add_argument("--date", help="ISO date of the event (default: today)")

    update = commands.add_parser("update-profile", help="rewrite and print the sourced profile")
    update.add_argument("--learner", required=True)
    update.add_argument("--teacher", default=DEFAULT_TEACHER, help="the named teacher the profile is shown to")

    listing = commands.add_parser("list-events", help="print one learner's events in order")
    listing.add_argument("--learner", required=True)
    return parser


def _requested_command(argv: list[str]) -> str | None:
    skip = False
    for arg in argv:
        if skip:
            skip = False
        elif arg == "--db":
            skip = True
        elif not arg.startswith("-"):
            return arg
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command = _requested_command(argv)
    if command is not None and command not in COMMANDS:
        # label, rank, score, share, recommend, or anything else: refuse and log it.
        db = argv[argv.index("--db") + 1] if "--db" in argv[:-1] else None
        learner = argv[argv.index("--learner") + 1] if "--learner" in argv[:-1] else None
        try:
            Records(store.connect(db)).refuse(command, {"learner_id": learner, "argv": argv})
        except Rejected as refusal:
            print(refusal, file=sys.stderr)
        return 2

    args = build_parser().parse_args(argv)
    records = Records(store.connect(args.db))
    try:
        if args.command == "add-event":
            event = records.append_event(
                args.learner, args.kind, args.source, args.score, args.text, args.school, args.date
            )
            print(f"Stored event {event['id']} for learner {event['learner_id']}: {event['kind']}, {event['source']}")
        elif args.command == "update-profile":
            print(records.update_profile(args.learner, args.teacher)["text"])
        else:
            print(json.dumps(records.list_events(args.learner), indent=2))
    except Rejected as refusal:
        print(f"Refused: {refusal}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
