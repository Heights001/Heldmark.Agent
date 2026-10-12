# Teaching contract: how day one of Heldmark was built

This is a walk through the build in the order it was done, so you can rebuild it yourself later. Each step says what was made, why it was made that way, and what to try on your own.

The README was treated as the contract. Nothing in the product was redesigned. The job was to make its commands true.

## The shape of the whole thing

```
data/fixture/five_schools.json     the anonymised test learner
heldmark/store.py                  SQLite: tables and append-only triggers
heldmark/rules.py                  the rules, as plain functions
heldmark/records.py                the three operations and the audit log
heldmark/server.py                 the MCP server, heldmark-records
heldmark/__main__.py               the command line
heldmark/demo.py                   python -m heldmark.demo
tests/test_heldmark.py             the evals
```

The layers only point one way: command line and MCP server → records → rules and store. `rules.py` knows nothing about SQLite or MCP. That is what lets you test the rules with plain dictionaries.

## Step 1. Set up the project

1. Create a virtual environment with Python 3.11. On this Mac the default `python3` is 3.9, which is too old, so use `python3.11 -m venv .venv`.
2. Write `pyproject.toml`. It names the package, says it needs Python 3.11+, and lists one dependency, `mcp`. pytest is an optional extra called `dev`.
3. Add the MIT `LICENSE`.
4. Run `pip install -e .`. The `-e` means "editable": Python imports the code straight from this folder, so edits take effect without reinstalling.

The package folder is `heldmark/` at the top level, not `src/heldmark/`. That keeps `python -m heldmark.demo` working from the repo root.

**Try it:** delete `.venv`, rebuild it, and run `python -m heldmark.demo`.

## Step 2. Write the store first (`store.py`)

Three tables:

- `events`: one row per quiz, project, or note. Columns: learner, kind, source, score, text, school, event date, recorded time.
- `profiles`: one row per learner. This is the only row that is ever rewritten.
- `audit_log`: one row per call, with input, output, timestamp, learner id, and `ok` or `rejected`.

Two ideas to learn here:

- **The database enforces the rule, not the programmer's memory.** "Append-only" is a SQLite trigger: `BEFORE UPDATE ON events ... RAISE(ABORT, 'events are append-only')`, and the same for DELETE. Even a mistake in later code cannot edit a past event.
- **A CHECK constraint refuses an empty source.** `source TEXT NOT NULL CHECK (length(trim(source)) > 0)`. This is the last line of defence behind the check in `records.py`.

**Try it:** open `heldmark.db` with `sqlite3` and run `UPDATE events SET score = 99;`. Read the error.

## Step 3. Write the rules as pure functions (`rules.py`)

`build_profile(learner_id, events)` takes a list of dictionaries and returns a `Profile`, which is a list of `Line` objects. Each `Line` has a section, a sentence, and its `cites`. It touches no database and no model.

The rules, in the order the code applies them:

1. Drop any event with no source, and count how many were dropped.
2. Group scored events by task kind.
3. If the kind is a combined subject (`maths`, `english`, `science`, ...): say it is a combined mark and state no pattern, however many there are.
4. If a kind has two or more results: write one "held" line and cite every result.
5. If a kind has one result: say it is on record once and is not a pattern.
6. List notes and unscored projects, each with its source. If a note's wording labels the child, cite the note but do not repeat the wording.
7. Find any calendar year between the first and last event with no events, and say it is missing.

`render()` turns the lines into the text the teacher reads. Tomorrow the local model replaces only this phrasing step. It will be handed the finished lines and cannot add one.

The key design choice: **the citation travels with the line as data.** A line is not a string with a source pasted in. That is why test 8 can check that every line cites a real stored event.

**Try it:** in a Python shell, call `rules.build_profile("L1", [...])` with two hand-written events of the same kind, then with one. Watch the line move from "held" to "once".

## Step 4. Write the three operations (`records.py`)

A `Records` class wraps the database connection and has the three operations the README names:

- `append_event` validates, then inserts. It refuses an event with no source, a kind that labels the child, a note with no text, and a bad date.
- `list_events` runs one query with `WHERE learner_id = ?`. There is no code path that returns another learner.
- `update_profile` reads the events, calls `rules.build_profile`, renders it, and overwrites the profile row.

There is also `refuse()`. Any request that is not one of the three tools goes there. It writes a `rejected` row to the audit log and raises `Rejected`.

Two patterns to learn:

- **Log, then raise.** `_reject()` writes the audit row before it raises the error, so a refusal can never go unrecorded.
- **One implementation, two front doors.** The command line and the MCP server both call `Records`. Neither has its own copy of the logic.

## Step 5. Write the MCP server (`server.py`)

MCP is a standard way for an agent to call tools. A server tells a client three things here: which tools exist, what happens when one is called, and which resources can be read.

This build uses the SDK's low-level `Server` class and passes it four handler functions:

- `on_list_tools` returns the three `Tool` descriptions, each with a JSON schema for its inputs.
- `on_call_tool` receives every tool call. It dispatches the three known names to `Records`, and sends every other name to `records.refuse()`.
- `on_list_resource_templates` advertises `learner://{id}/events`.
- `on_read_resource` matches that URI with a regular expression and returns the learner's events as JSON.

Why the low-level class and not the simpler decorator style: with the simple style, the SDK itself answers "unknown tool" before your code sees the call, so the request could be rejected but not logged. Handling every call yourself is what makes "rejected and logged" true.

`python -m heldmark.server` runs it over stdio, which means a client starts it as a child process and talks to it through standard input and output.

**Try it:** read `test_mcp_server_has_exactly_three_tools_and_one_resource`. `Client(build_server(records))` connects a client to the server inside one process, with no network.

## Step 6. Write the command line and the demo

`__main__.py` is what runs for `python -m heldmark ...`. It uses `argparse` with three subcommands: `add-event`, `update-profile`, `list-events`. Before argparse runs, it looks at the command word. If it is not one of the three, for example `rank`, it is refused, logged, and the program exits with code 2.

`demo.py` opens a database in memory (`:memory:`), loads the fixture through `append_event`, and prints the profile. In-memory means the demo is the same on every run and leaves nothing on disk.

The command line and the demo use different stores on purpose. The demo is throwaway. `add-event` writes to `heldmark.db` in the current folder, or to the file named in `--db` or the `HELDMARK_DB` environment variable.

## Step 7. Build the fixture to hit every rule

`data/fixture/five_schools.json` is one anonymised learner, L1, across five schools. Each item exists to exercise one rule:

| In the fixture | Rule it exercises |
|---|---|
| Word problem 40, 38, 41 at Schools 1, 2, 4 | may be stated |
| Calculation 72, 75 at Schools 1, 3 | may be stated |
| Reading aloud 55, once | must not become a pattern |
| A combined Maths report mark | must not become a pattern |
| A note with an empty source | refused at intake |
| Nothing dated 2025 | stated as missing |
| A sourced note and an unscored project | listed with their sources |

The lesson: design test data from the rules backwards. Start from "what must be refused" and add the smallest item that would be wrongly accepted by a careless build.

## Step 8. Write the tests, and leave one honest failure

`tests/test_heldmark.py` has 14 tests. Each one starts a fresh in-memory database through a pytest fixture, so tests cannot affect each other.

Test 14 fails on purpose and is marked `xfail(strict=True)`. That mark means "this is expected to fail". The suite stays green, the failure stays visible in the output as `xfailed`, and if the test ever starts passing, the suite turns red so someone updates the record. `EVALS.md` shows the raw failure and what to try next.

**Try it:** `python -m pytest -v`, then `python -m pytest --runxfail -k two_school_names`.

## What was not built

LangGraph, Ollama, the Filesystem MCP server, `ARCHITECTURE.md`, and the video. Where they will attach:

- **LangGraph** will be an MCP client that calls `append_event`, `list_events`, and `update_profile` in a fixed order. It should not import `rules.py` directly.
- **Ollama** will take the `lines` that `update_profile` returns and rephrase each sentence. Check its output against the lines: same citations, no new line, no label word.
- **The Filesystem MCP server** will read prior-school files from a local intake folder. Those files become `append_event` calls.

## Words worth knowing

- **Append-only:** rows can be added but never changed or removed.
- **Trigger:** a rule stored in the database that runs when a row is about to change.
- **Pure function:** output depends only on its inputs; it reads and writes nothing else.
- **MCP server / client:** the server offers tools and resources; the client, usually an agent, calls them.
- **stdio transport:** client and server talk through a child process's standard input and output.
- **Fixture:** fixed, known data used by tests and the demo.
- **xfail:** a test recorded as expected to fail.
