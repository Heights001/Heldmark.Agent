"""python -m heldmark.run

Runs the full graph once on the fixture: reads the intake folder through the
borrowed Filesystem MCP server, stores each valid cited event through
heldmark-records, rewrites the profile from the rules, then asks the local
model to phrase it. If Ollama is not running, the rule profile is still
printed and the phrasing is skipped.
"""

import argparse
import os
import tempfile
from pathlib import Path

import anyio

from . import phrase
from .graph import run_update
from .toolbox import Toolbox, filesystem_server, records_server

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "fixture"


def report(state: dict, tools: Toolbox, db: str) -> str:
    out = [
        f"Heldmark run: learner {state['learner_id']}",
        f"Intake folder: {state['intake_dir']}",
        f"Read {len(state['files'])} file(s) through the Filesystem MCP server.",
        f"Stored {state['stored']} cited events through heldmark-records, {len(state['refused'])} refused.",
    ]
    out += [f"  refused: {line}" for line in state["refused"]]
    out += [f"  not used: {line}" for line in state["problems"]]
    out += ["", "RULE PROFILE", state["profile"]["text"], ""]
    phrasing = state["phrasing"]
    if phrasing["status"] == "skipped":
        out.append(f"PHRASING SKIPPED: {phrasing['reason']}. The rule profile above stands.")
    else:
        kept = sum(result["kept"] for result in phrasing["results"])
        out += [
            f"MODEL SENTENCES ({phrasing['model']}, local): {kept} kept, {len(phrasing['results']) - kept} discarded",
            phrase.render(phrasing["results"]),
        ]
    out += ["", f"Audit log: {tools.calls} tool calls, each appended to {db}"]
    return "\n".join(out)


async def run(args) -> str:
    db = args.db or os.path.join(tempfile.mkdtemp(prefix="heldmark-run-"), "heldmark.db")
    model = phrase.OllamaModel(args.model)
    async with Toolbox(records_server(db), filesystem_server(args.intake), db, args.learner) as tools:
        state = await run_update(tools, model, args.learner, args.intake, args.teacher)
        return report(state, tools, db)


def main() -> None:
    parser = argparse.ArgumentParser(prog="heldmark.run", description="Run one update on the intake folder.")
    parser.add_argument("--learner", default="L1")
    parser.add_argument("--intake", default=str(FIXTURE_DIR), help="the one local folder of prior-school files")
    parser.add_argument("--teacher", help="the named teacher the profile is shown to")
    parser.add_argument("--db", help="SQLite file to use (default: a fresh one for this run)")
    parser.add_argument("--model", default=phrase.MODEL)
    print(anyio.run(run, parser.parse_args()))


if __name__ == "__main__":
    main()
