"""Evals for today's build. Results are written up in EVALS.md."""

import sqlite3
import subprocess
import sys

import anyio
import pytest
from mcp import Client

from heldmark import rules, store
from heldmark.__main__ import main as cli
from heldmark.demo import FIXTURE, load_fixture
from heldmark.records import Records, Rejected
from heldmark.server import build_server


@pytest.fixture
def records():
    return Records(store.connect(":memory:"))


@pytest.fixture
def fixture_profile(records):
    load_fixture(records)
    return rules.build_profile("L1", records.list_events("L1"))


def texts(profile, section):
    return [line.text for line in profile.section(section)]


# 1
def test_pattern_held_across_schools(fixture_profile):
    held = {line.text.split(":")[0]: line for line in fixture_profile.section("held")}
    assert set(held) == {"Word problem", "Calculation"}
    word = held["Word problem"]
    assert [c.score for c in word.cites] == [40, 38, 41]
    assert "across 3 schools" in word.text
    assert [c.score for c in held["Calculation"].cites] == [72, 75]


# 2
def test_single_score_is_not_a_pattern(fixture_profile):
    assert not any("Reading aloud" in text for text in texts(fixture_profile, "held"))
    assert texts(fixture_profile, "once") == ["Reading aloud: 55, on record once. One result is not a pattern."]


# 3
def test_combined_subject_mark_is_not_a_pattern(records):
    records.append_event("L1", "maths", "Term 1 report, Maths, School 1", score=55, date="2024-04-01")
    records.append_event("L1", "Maths", "Term 2 report, Maths, School 2", score=57, date="2024-08-01")
    profile = rules.build_profile("L1", records.list_events("L1"))
    assert profile.section("held") == []
    assert len(profile.section("combined")) == 1
    assert "no pattern is stated" in profile.section("combined")[0].text


# 4
def test_missing_year_is_stated_as_missing(fixture_profile):
    assert texts(fixture_profile, "missing") == ["No events on record for 2025."]


# 5
def test_unsourced_note_is_refused(records):
    with pytest.raises(Rejected, match="No source"):
        records.append_event("L1", "note", "  ", text="Works carefully with numbers.", date="2026-02-03")
    assert records.list_events("L1") == []
    assert records.audit()[0]["outcome"] == "rejected"
    # The rules also refuse it if one ever reached them.
    stray = {"kind": "note", "source": "", "text": "Works carefully.", "event_date": "2026-02-03"}
    profile = rules.build_profile("L1", [stray])
    assert profile.section("record") == []
    assert "1 entry has no source and is not used." in texts(profile, "missing")


# 6
def test_list_events_never_returns_classmates(records):
    records.append_event("L1", "calculation", "Quiz A, School 1", score=70, date="2026-01-10")
    records.append_event("L2", "calculation", "Quiz A, School 1", score=90, date="2026-01-10")
    records.append_event("L1", "calculation", "Quiz B, School 1", score=72, date="2026-01-17")
    assert {e["learner_id"] for e in records.list_events("L1")} == {"L1"}
    assert [e["score"] for e in records.list_events("L1")] == [70, 72]
    text = records.update_profile("L1")["text"]
    assert "90" not in text and "L2" not in text


# 7
@pytest.mark.parametrize("request_name", ["label_learner", "rank", "score_learner", "share_profile", "recommend_path"])
def test_label_rank_share_requests_are_rejected_and_logged(records, request_name, tmp_path):
    with pytest.raises(Rejected, match="no tool to label, rank, score, share, or recommend"):
        records.refuse(request_name, {"learner_id": "L1"})
    last = records.audit()[-1]
    assert (last["tool"], last["learner_id"], last["outcome"]) == (request_name, "L1", "rejected")

    # The same request through the MCP server and through the command line.
    async def over_mcp():
        async with Client(build_server(records)) as client:
            return await client.call_tool(request_name, {"learner_id": "L1"})

    assert anyio.run(over_mcp).is_error
    assert records.audit()[-1]["outcome"] == "rejected"

    db = str(tmp_path / "h.db")
    assert cli(["--db", db, request_name.replace("_", "-"), "--learner", "L1"]) == 2
    assert Records(store.connect(db)).audit()[-1]["outcome"] == "rejected"


# 8
def test_profile_lines_cite_their_sources(records, fixture_profile):
    sources = {e["source"] for e in records.list_events("L1")}
    for line in fixture_profile.lines:
        if line.section == "missing":
            continue  # a gap has nothing to cite
        assert line.cites, line.text
        assert {c.source for c in line.cites} <= sources
    held = fixture_profile.section("held")[0]
    assert len(held.cites) == 3
    rendered = rules.render(fixture_profile, "Class 2 teacher, School 5")
    for source in {c.source for line in fixture_profile.lines for c in line.cites}:
        assert source in rendered


# 9
def test_events_are_append_only(records):
    records.append_event("L1", "calculation", "Quiz A, School 1", score=70, date="2026-01-10")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        records.conn.execute("UPDATE events SET score = 99")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        records.conn.execute("DELETE FROM events")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        records.conn.execute("DELETE FROM audit_log")
    records.update_profile("L1")
    records.update_profile("L1")  # the profile row is the only thing rewritten
    assert records.list_events("L1")[0]["score"] == 70


# 10
def test_mcp_server_has_exactly_three_tools_and_one_resource(records):
    async def session():
        async with Client(build_server(records)) as client:
            tools = await client.list_tools()
            templates = await client.list_resource_templates()
            await client.call_tool(
                "append_event",
                {"learner_id": "L1", "kind": "word_problem", "source": "Quiz 1, School 1", "score": 40, "date": "2026-01-10"},
            )
            await client.call_tool(
                "append_event",
                {"learner_id": "L1", "kind": "word_problem", "source": "Quiz 2, School 2", "score": 38, "date": "2026-02-10"},
            )
            profile = await client.call_tool("update_profile", {"learner_id": "L1"})
            resource = await client.read_resource("learner://L1/events")
            return tools, templates, profile, resource

    tools, templates, profile, resource = anyio.run(session)
    assert sorted(t.name for t in tools.tools) == ["append_event", "list_events", "update_profile"]
    assert [t.uri_template for t in templates.resource_templates] == ["learner://{id}/events"]
    assert "Word problem: scores 40, 38 on 2 cited results." in profile.content[0].text
    assert "Quiz 1, School 1" in resource.contents[0].text and "Quiz 2, School 2" in resource.contents[0].text


# 11
def test_readme_demo_command_prints_the_fixture_profile():
    assert FIXTURE.name == "five_schools.json"
    run = subprocess.run([sys.executable, "-m", "heldmark.demo"], capture_output=True, text=True, cwd=FIXTURE.parents[2])
    assert run.returncode == 0, run.stderr
    assert "Sourced profile: learner L1" in run.stdout
    assert "Word problem: scores 40, 38, 41 on 3 cited results across 3 schools." in run.stdout
    assert "1 refused" in run.stdout


# 12
def test_readme_usage_commands(tmp_path, capsys):
    db = str(tmp_path / "h.db")
    added = ["--db", db, "add-event", "--learner", "L1", "--source", "Class 2 word problem, 12 March, School 4"]
    assert cli(added + ["--kind", "word_problem", "--score", "40", "--date", "2026-03-12"]) == 0
    assert cli(["--db", db, "update-profile", "--learner", "L1"]) == 0
    out = capsys.readouterr().out
    assert "Word problem: 40, on record once. One result is not a pattern." in out
    assert "Class 2 word problem, 12 March, School 4 (2026-03-12)" in out
    assert "Held more than once" not in out


# 12b
def test_add_event_without_a_date_exits_and_writes_no_row(tmp_path, capsys):
    db = str(tmp_path / "h.db")
    command = ["--db", db, "add-event", "--learner", "L1", "--kind", "word_problem", "--score", "40"]
    with pytest.raises(SystemExit) as stopped:
        cli(command + ["--source", "Class 2 word problem, 12 March, School 4"])
    assert stopped.value.code == 2
    assert "--date" in capsys.readouterr().err
    conn = store.connect(db)
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    # The same door is shut behind the command line: the records refuse an event with no date.
    with pytest.raises(Rejected, match="No date"):
        Records(conn).append_event("L1", "word_problem", "Class 2 word problem, 12 March, School 4", score=40)
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


# 13
def test_profile_does_not_label_rank_or_suggest_a_path(records):
    load_fixture(records)
    records.append_event(
        "L1", "note", "Class 2 teacher note, 20 June, School 5", text="A slow learner, bottom of the class.", date="2026-06-20"
    )
    with pytest.raises(Rejected, match="labels the learner"):
        records.append_event("L1", "weak_pupil", "Class 2 list, School 5", score=1, date="2026-06-20")
    text = records.update_profile("L1")["text"]
    assert "slow learner" not in text and "bottom of" not in text
    assert "Class 2 teacher note, 20 June, School 5" in text  # still cited, wording withheld
    body = "\n".join(l for l in text.splitlines() if not l.startswith("    source:"))
    body = body.replace("because it labels the learner", "").replace("gives no label, no rank, and no path", "")
    assert not rules.LABEL_TERMS.search(body)
    assert not any(word in body.lower() for word in ("label", "recommend", "subject choice"))


# 14: the one failure left open. See EVALS.md.
@pytest.mark.xfail(strict=True, reason="OPEN: schools name the same task differently; kinds are matched by exact name")
def test_same_task_under_two_school_names_is_one_pattern(records):
    records.append_event("L1", "word_problem", "Class 1 word problem quiz, School 1", score=40, date="2024-02-20")
    records.append_event("L1", "story_sums", "Class 2 story sums quiz, School 4", score=41, date="2026-03-19")
    profile = rules.build_profile("L1", records.list_events("L1"))
    assert len(profile.section("held")) == 1
    assert len(profile.section("held")[0].cites) == 2
