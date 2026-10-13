"""Evals for the graph, the two MCP servers, and the phrasing guard.

Model-free: every test here uses a fake model, except the one marked `ollama`,
which calls the real local model and is skipped when Ollama is not running.
The Filesystem server is replaced by an in-process stand-in with the same two
read tools, except in the one test that starts the real borrowed server.
"""

import ast
import json
import shutil
from pathlib import Path

import anyio
import pytest
from mcp import types
from mcp.server import Server

from heldmark import graph, phrase, rules, store
from heldmark.demo import FIXTURE
from heldmark.graph import run_update
from heldmark.records import Records
from heldmark.run import report
from heldmark.server import build_server
from heldmark.toolbox import FILESYSTEM_JS, Toolbox, ToolRefused, filesystem_server, records_server

CLASSMATE_FILE = {
    "learner_id": "L2",
    "schools": [
        {
            "school": "School 4",
            "events": [{"kind": "word_problem", "score": 99, "date": "2026-03-19", "source": "Classmate quiz, School 4"}],
        }
    ],
}


def stand_in_filesystem(root: Path) -> Server:
    """An in-process server with the borrowed server's read tools, and one write tool that must never be called."""

    async def on_list_tools(ctx, params):
        schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        names = ("list_directory", "read_text_file", "write_file")
        return types.ListToolsResult(tools=[types.Tool(name=n, input_schema=schema) for n in names])

    async def on_call_tool(ctx, params):
        path = Path(params.arguments["path"])
        if root not in (path, *path.parents):
            text, error = "Access denied - path outside allowed directories", True
        elif params.name == "list_directory":
            text, error = "\n".join(f"[FILE] {p.name}" for p in sorted(path.iterdir())), False
        elif params.name == "read_text_file":
            text, error = path.read_text(), False
        else:
            path.write_text("written")
            text, error = "written", False
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)

    return Server("stand-in-filesystem", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


class FakeModel:
    """Says whatever the test tells it to, and remembers everything it was shown."""

    name = "fake"

    def __init__(self, say=None):
        self.say = say or (lambda claim: claim["claim"])
        self.seen = []

    def ready(self):
        return None

    def phrase(self, claim):
        self.seen.append(claim)
        return self.say(claim)


@pytest.fixture
def intake_dir(tmp_path):
    folder = (tmp_path / "intake").resolve()
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "five_schools.json")
    return folder


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "heldmark.db")


def run_graph(db, intake_dir, model, extra=None):
    """Run one update with both servers in-process. Returns (state, tool calls made, audit rows)."""

    async def go():
        records = Records(store.connect(db))
        async with Toolbox(build_server(records), stand_in_filesystem(intake_dir), db, "L1") as tools:
            state = await run_update(tools, model, "L1", str(intake_dir))
            if extra:
                await extra(tools)
            return state, tools.calls, records.audit()

    return anyio.run(go)


def fixture_lines():
    records = Records(store.connect(":memory:"))
    from heldmark.demo import load_fixture

    load_fixture(records)
    return records.update_profile("L1")["lines"]


# 15
def test_graph_runs_one_update_through_both_servers(db, intake_dir):
    state, _, _ = run_graph(db, intake_dir, FakeModel())
    assert state["files"] == ["five_schools.json"]
    assert (state["stored"], len(state["refused"])) == (9, 1)
    assert "No source" in state["refused"][0]
    assert len(state["events"]) == 9 and {e["learner_id"] for e in state["events"]} == {"L1"}
    assert "Word problem: scores 40, 38, 41 on 3 cited results across 3 schools." in state["profile"]["text"]
    assert state["profile"]["shown_to"] == "Class 2 teacher, School 5"
    assert state["phrasing"]["status"] == "done" and all(r["kept"] for r in state["phrasing"]["results"])


# 16
def test_every_tool_call_is_in_the_audit_log_including_the_filesystem_read(db, intake_dir):
    _, calls, audit = run_graph(db, intake_dir, FakeModel())
    tools = [row["tool"] for row in audit]
    assert tools.count("filesystem.list_directory") == 1
    assert tools.count("filesystem.read_text_file") == 1
    assert tools.count("append_event") == 10
    assert tools.count("list_events") == 1 and tools.count("update_profile") == 1
    assert len(audit) == calls == 14
    read = next(row for row in audit if row["tool"] == "filesystem.read_text_file")
    assert read["learner_id"] == "L1" and read["at"] and read["outcome"] == "ok"
    assert json.loads(read["input"])["path"].endswith("five_schools.json")
    assert "Class 1 word problem quiz, 20 February, School 1" in json.loads(read["output"])["text"]
    assert [row["outcome"] for row in audit if row["tool"] == "append_event"].count("rejected") == 1
    assert all(row["learner_id"] == "L1" for row in audit)


# 17
def test_the_filesystem_server_is_used_for_reading_only(db, intake_dir):
    async def try_to_write(tools):
        with pytest.raises(ToolRefused, match="reading only"):
            await tools.filesystem("write_file", path=str(intake_dir / "new.json"), content="{}")
        with pytest.raises(ToolRefused, match="outside allowed directories"):
            await tools.filesystem("read_text_file", path="/etc/hosts")

    _, _, audit = run_graph(db, intake_dir, FakeModel(), extra=try_to_write)
    assert not (intake_dir / "new.json").exists()
    assert [(row["tool"], row["outcome"]) for row in audit[-2:]] == [
        ("filesystem.write_file", "rejected"),
        ("filesystem.read_text_file", "rejected"),
    ]


# 18
def test_graph_nodes_do_not_import_the_database():
    imported = set()
    for node in ast.walk(ast.parse(Path(graph.__file__).read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module or ''}.{alias.name}".lstrip(".") for alias in node.names}
            imported.add(node.module or "")
    assert not {name for name in imported if name.split(".")[0] in ("sqlite3", "store", "records")}
    assert "intake" in imported and "toolbox.Toolbox" in imported


# 19
@pytest.mark.parametrize(
    "bad_sentence, reason",
    [
        ("The learner is a weak reader, scoring 40, 38 and 41 on word problems.", "label or a rank"),
        ("With word problem scores of 40, 38 and 41, the learner ranks near the bottom of the class.", "label or a rank"),
        ("Word problem scores were 40, 38 and 41, so the learner should take a remedial programme.", "path"),
        ("Word problem scores were 40, 38 and 41, and the end of term exam at School 9 agrees.", "source that was not in the sheet"),
        ("Word problem scores were 40, 38, 41 and 12 across the quizzes.", "number that was not in the sheet"),
        ("Word problem scores were 40 and 38 on the quizzes.", "dropped a cited result"),
    ],
)
def test_a_sentence_that_adds_a_label_rank_path_or_source_is_discarded(bad_sentence, reason):
    lines = fixture_lines()
    word = lines[0]
    assert word["text"].startswith("Word problem")
    results = phrase.phrase_lines(lines, FakeModel(lambda claim: bad_sentence if "Word problem" in claim["claim"] else claim["claim"]))
    first = results[0]
    assert first["kept"] is False and reason in first["discarded_because"]
    assert first["text"] == word["text"]  # the rule text is kept
    assert first["cites"] == word["cites"]
    assert bad_sentence not in phrase.render(results)
    assert all(r["kept"] for r in results[1:])  # one bad sentence does not sink the others


# 20
def test_a_faithful_sentence_is_kept_and_keeps_its_sources():
    lines = fixture_lines()
    good = "On three word problem quizzes at three schools, the scores were 40, 38 and 41."
    results = phrase.phrase_lines(lines[:1], FakeModel(lambda claim: good))
    assert results[0]["kept"] and results[0]["text"] == good
    assert results[0]["cites"] == lines[0]["cites"]
    rendered = phrase.render(results)
    for cite in lines[0]["cites"]:
        assert cite["source"] in rendered


# 21
def test_a_single_score_cannot_be_phrased_into_a_pattern():
    once = next(line for line in fixture_lines() if line["section"] == "once")
    results = phrase.phrase_lines([once], FakeModel(lambda claim: "Reading aloud shows a consistent pattern at 55."))
    assert results[0]["kept"] is False and results[0]["text"] == once["text"]


# 21b: llama3.1:8b really wrote this on 12 October 2026, and the guard of that day kept it.
@pytest.mark.parametrize(
    "sentence",
    [
        "The learner read aloud 55 times, which is a single instance.",
        "The learner read aloud 55 times, and that one result is not a pattern.",
        "On 55 occasions the learner read aloud, a single result.",
        "The learner read aloud 55 words in one result.",
        "Reading aloud happened once, with 55.",
    ],
)
def test_a_score_rewritten_as_a_count_is_discarded(sentence):
    once = next(line for line in fixture_lines() if line["section"] == "once")
    assert once["text"].startswith("Reading aloud: 55, on record once")
    results = phrase.phrase_lines([once], FakeModel(lambda claim: sentence))
    assert results[0]["kept"] is False
    assert results[0]["discarded_because"] == "it rewrote a score as a count"
    assert results[0]["text"] == once["text"]  # the rule line remains
    rendered = phrase.render(results)
    assert "Reading aloud: 55, on record once" in rendered and "55 times" not in rendered
    # A sentence that keeps 55 as a score still stands.
    kept = phrase.phrase_lines([once], FakeModel(lambda claim: "Reading aloud has one score on record, 55."))
    assert kept[0]["kept"]


# 22
def test_the_model_receives_only_the_claim_sheet(db, intake_dir):
    (intake_dir / "classmate.json").write_text(json.dumps(CLASSMATE_FILE))
    model = FakeModel()
    state, _, audit = run_graph(db, intake_dir, model)
    assert state["files"] == ["classmate.json", "five_schools.json"]
    assert state["problems"] == ["classmate.json: for a different learner. Not used."]
    assert len(model.seen) == len(state["profile"]["lines"])
    assert all(set(claim) == {"claim", "sources"} for claim in model.seen)
    shown = json.dumps(model.seen)
    for forbidden in ("99", "L2", "Classmate", "career", "programme", "subject choice", "learner_id", "event_id"):
        assert forbidden not in shown
    # Nothing about the classmate was stored either.
    assert store.connect(db).execute("SELECT count(*) FROM events WHERE learner_id != 'L1'").fetchone()[0] == 0
    assert not any("99" in row["input"] for row in audit if row["tool"] == "append_event")


# 23
def test_with_ollama_down_the_rule_profile_is_printed_and_phrasing_is_skipped(db, intake_dir):
    async def go():
        records = Records(store.connect(db))
        async with Toolbox(build_server(records), stand_in_filesystem(intake_dir), db, "L1") as tools:
            state = await run_update(tools, phrase.OllamaModel(host="http://127.0.0.1:1"), "L1", str(intake_dir))
            return state, report(state, tools, db)

    state, printed = anyio.run(go)
    assert state["phrasing"]["status"] == "skipped"
    assert "PHRASING SKIPPED: Ollama is not running" in printed
    assert "Word problem: scores 40, 38, 41 on 3 cited results across 3 schools." in printed
    assert "MODEL SENTENCES" not in printed


# 23b
def test_the_run_prints_the_audit_log_one_row_per_tool_call(db, intake_dir):
    async def go():
        records = Records(store.connect(db))
        async with Toolbox(build_server(records), stand_in_filesystem(intake_dir), db, "L1") as tools:
            state = await run_update(tools, FakeModel(), "L1", str(intake_dir))
            return report(state, tools, db), tools.calls

    printed, calls = anyio.run(go)
    log = printed[printed.index("AUDIT LOG") :].splitlines()
    assert log[0].startswith("AUDIT LOG: 14 tool calls for learner L1")
    rows = log[1 : 1 + calls]
    assert len(rows) == 14 and all(len(row) <= 130 for row in rows)
    assert "filesystem.list_directory" in rows[0] and "five_schools.json" in rows[0]
    assert "filesystem.read_text_file" in rows[1] and "five_schools.json" in rows[1]
    assert sum("append_event" in row for row in rows) == 10
    assert sum("REFUSED: No source" in row for row in rows) == 1
    assert "word_problem, 40, Class 1 word problem quiz" in rows[2]
    assert "list_events" in rows[12] and "learner L1" in rows[12] and "9 events" in rows[12]
    assert "update_profile" in rows[13] and "profile rewritten" in rows[13]
    assert printed.index("RULE PROFILE") < printed.index("AUDIT LOG")  # the profile comes first, unchanged


# 24
@pytest.mark.skipif(not (FILESYSTEM_JS.exists() and shutil.which("node")), reason="run `npm install` to get the Filesystem MCP server")
def test_full_graph_with_the_real_filesystem_server_and_our_server_over_stdio(db, intake_dir):
    async def go():
        async with Toolbox(records_server(db), filesystem_server(str(intake_dir)), db, "L1") as tools:
            state = await run_update(tools, FakeModel(), "L1", str(intake_dir))
            with pytest.raises(ToolRefused):
                await tools.filesystem("read_text_file", path="/etc/hosts")
            return state

    state = anyio.run(go)
    assert (state["stored"], len(state["refused"])) == (9, 1)
    audit = Records(store.connect(db)).audit()
    assert [row["tool"] for row in audit][:2] == ["filesystem.list_directory", "filesystem.read_text_file"]
    assert audit[-1]["outcome"] == "rejected"


# 25: the open-weights task. Calls llama3.1:8b through Ollama on this machine.
@pytest.mark.ollama
@pytest.mark.skipif(phrase.OllamaModel().ready() is not None, reason="Ollama with llama3.1:8b is not running")
def test_real_local_model_only_ever_yields_checked_sentences():
    lines = fixture_lines()
    results = phrase.phrase_lines(lines, phrase.OllamaModel())
    assert len(results) == len(lines)
    for line, result in zip(lines, results):
        assert result["cites"] == line["cites"]  # the model cannot add or drop a source
        if result["kept"]:
            assert phrase.check(result["text"], line) is None
        else:
            assert result["text"] == line["text"]
        assert not rules.LABEL_TERMS.search(result["text"])
    assert any(result["kept"] for result in results), [r["discarded_because"] for r in results]
