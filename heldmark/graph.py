"""One update, as a LangGraph workflow.

    read_intake -> append_events -> list_events -> update_profile -> phrase -> END

The order is fixed. The model does not choose the steps and does not decide a
pattern. Nodes reach learner facts only through the toolbox, which calls the
MCP servers. No node imports the database.
"""

import os
from typing import TypedDict

import anyio
from langgraph.graph import END, START, StateGraph

from . import intake, phrase
from .toolbox import Toolbox, ToolRefused


class State(TypedDict, total=False):
    learner_id: str
    intake_dir: str
    shown_to: str | None
    files: list[str]
    candidates: list[dict]
    problems: list[str]
    stored: int
    refused: list[str]
    events: list[dict]
    profile: dict
    phrasing: dict


def build_graph(tools: Toolbox, model):
    """model needs .name, .ready() -> reason or None, and .phrase(claim) -> sentence."""

    async def read_intake(state: State) -> State:
        folder = os.path.realpath(state["intake_dir"])
        listing = await tools.filesystem("list_directory", path=folder)
        names = sorted(
            line.removeprefix("[FILE] ").strip()
            for line in listing.splitlines()
            if line.startswith("[FILE] ") and line.endswith(".json")
        )
        candidates, problems, shown_to = [], [], state.get("shown_to")
        for name in names:
            try:
                text = await tools.filesystem("read_text_file", path=os.path.join(folder, name))
            except ToolRefused as refusal:
                problems.append(f"{name}: {refusal}")
                continue
            found, trouble, teacher = intake.parse(name, text, state["learner_id"])
            candidates += found
            problems += trouble
            shown_to = shown_to or teacher
        return {"files": names, "candidates": candidates, "problems": problems, "shown_to": shown_to}

    async def append_events(state: State) -> State:
        stored, refused = 0, []
        for candidate in state["candidates"]:
            result = await tools.records("append_event", **candidate)
            if result.is_error:
                refused.append(f"{candidate.get('school')}, {candidate.get('kind')}: {result.content[0].text}")
            else:
                stored += 1
        return {"stored": stored, "refused": refused}

    async def list_events(state: State) -> State:
        result = await tools.records("list_events", learner_id=state["learner_id"])
        return {"events": result.structured_content["events"]}

    async def update_profile(state: State) -> State:
        named = {"shown_to": state["shown_to"]} if state.get("shown_to") else {}
        result = await tools.records("update_profile", learner_id=state["learner_id"], **named)
        return {"profile": result.structured_content}

    async def phrase_profile(state: State) -> State:
        reason = model.ready()
        if reason:
            return {"phrasing": {"status": "skipped", "reason": reason, "model": model.name}}
        # The model sees the claim sheet built from the rule lines. It never sees state["events"].
        results = await anyio.to_thread.run_sync(phrase.phrase_lines, state["profile"]["lines"], model)
        return {"phrasing": {"status": "done", "model": model.name, "results": results}}

    graph = StateGraph(State)
    graph.add_node("read_intake", read_intake)
    graph.add_node("append_events", append_events)
    graph.add_node("list_events", list_events)
    graph.add_node("update_profile", update_profile)
    graph.add_node("phrase", phrase_profile)
    graph.add_edge(START, "read_intake")
    graph.add_edge("read_intake", "append_events")
    graph.add_edge("append_events", "list_events")
    graph.add_edge("list_events", "update_profile")
    graph.add_edge("update_profile", "phrase")
    graph.add_edge("phrase", END)
    return graph.compile()


async def run_update(tools: Toolbox, model, learner_id: str, intake_dir: str, shown_to: str | None = None) -> State:
    graph = build_graph(tools, model)
    return await graph.ainvoke({"learner_id": learner_id, "intake_dir": intake_dir, "shown_to": shown_to})
