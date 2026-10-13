# Teaching contract: how Heldmark was built

Part 1 is day one: the store, the rules, our MCP server, and the command line. Part 2 is day two: the graph, the borrowed Filesystem server, and the local model.

# Part 1. Day one

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

# Part 2. Day two

Day two added four files and changed nothing about what the profile may say.

```
heldmark/intake.py      text of a prior-school file -> candidate events (pure)
heldmark/toolbox.py     the only way the graph reaches a tool
heldmark/phrase.py      the claim sheet, the guard, and the Ollama client
heldmark/graph.py       the LangGraph workflow
heldmark/run.py         python -m heldmark.run
package.json            pins the borrowed Filesystem MCP server
tests/test_graph.py     the day-two evals
```

## Step 9. Fix first: `--date` is required

On day one, `add-event` with no date stored today's date. A source that said "12 March" was saved as 12 October. That is a false fact in an append-only table, so it could never be corrected.

Two changes:

1. In `__main__.py`, `--date` got `required=True`. argparse now exits with code 2 before the database is even opened, so nothing can be written.
2. In `records.py`, `append_event` refuses an event with no date. This closes the same hole for callers that do not come through the command line, such as the graph.

The lesson: when you fix a hole at the front door, check whether there is a back door. Then write the test for the thing that must not happen: `test_add_event_without_a_date_exits_and_writes_no_row` counts the rows and expects zero.

## Step 10. Borrow the Filesystem MCP server

The official Filesystem server is a Node.js program. `package.json` pins one exact version, and `npm install` puts it in `node_modules/`. Heldmark starts it as a child process:

```
node node_modules/@modelcontextprotocol/server-filesystem/dist/index.js <intake folder>
```

The folder on the command line is the only place it may look. Ask it for `/etc/hosts` and it answers "Access denied - path outside allowed directories". It makes no network calls. Installing it once with `npm install` is the only step that needs the internet.

Why install it locally and not run `npx -y ...` each time: `npx -y` downloads whatever is newest at that moment. A pinned local copy runs offline and does not change under you.

**Try it:** run the command above by hand with a folder. It waits silently for MCP messages on standard input. Press Ctrl-C.

## Step 11. One toolbox between the graph and the tools (`toolbox.py`)

The graph never talks to a server directly. It asks a `Toolbox`, which holds two MCP clients:

- `tools.records("append_event", ...)` calls our server. Our server logs the call itself.
- `tools.filesystem("read_text_file", path=...)` calls the borrowed server.

Three things happen in this one file, and that is why it exists:

1. **Read-only is enforced here.** The borrowed server also offers `write_file`, `edit_file`, and `move_file`. The toolbox has an allow-list of two names, `list_directory` and `read_text_file`. Anything else is refused and logged without being sent.
2. **The filesystem read is logged here.** The borrowed server knows nothing about our audit log, so the toolbox appends a row for each read: input, output, timestamp, learner id. It writes audit rows only, never events or profiles.
3. **Tests can swap the servers.** `Toolbox` accepts anything `mcp.Client` accepts. In the real run those are two child processes. In the tests they are two server objects in the same process, so the tests need no Node and no network.

**Try it:** read `stand_in_filesystem` in `tests/test_graph.py`. It is a complete MCP server in about twenty lines.

## Step 12. Parse intake files in a pure function (`intake.py`)

`intake.parse(name, text, learner_id)` takes the text of a file and returns candidate events. It opens no file and calls no tool, so it is easy to test.

It makes one decision: a file for a different learner is dropped whole, and only the line "for a different learner. Not used." is passed on. It does **not** decide whether an event is valid. A note with no source is still sent to `append_event`, which refuses it and logs the refusal. Validation lives in one place.

## Step 13. The graph (`graph.py`)

LangGraph runs functions called nodes and passes a dictionary called the state from one to the next. Each node returns only the keys it wants to add or change.

```
read_intake -> append_events -> list_events -> update_profile -> phrase -> END
```

- `read_intake` lists the folder and reads each `.json` file through the Filesystem server.
- `append_events` calls `append_event` once per candidate and counts what was stored and what was refused.
- `list_events` calls `list_events` for this one learner.
- `update_profile` calls `update_profile` and keeps the lines the rules produced.
- `phrase` hands those lines to the model, or skips if the model is not there.

The edges are fixed with `add_edge`. There is no conditional edge and no step where the model picks what happens next. That is what "the model does not choose the steps" means in code.

Look at the imports at the top of `graph.py`: `intake`, `phrase`, and `toolbox`. There is no `store`, no `records`, no `sqlite3`. `test_graph_nodes_do_not_import_the_database` reads the file and fails if one ever appears.

One small change to our server made this possible: `update_profile` now also returns the lines as structured data, not only as text. The tool list did not change.

**Try it:** add `print(state.keys())` at the top of each node and run `python -m heldmark.run`. Watch the state grow.

## Step 14. The claim sheet and the guard (`phrase.py`)

This is the most important file of day two.

**What the model is given.** For each line the rules allowed, `claim_for_model` builds a dictionary with exactly two keys: `claim` (the rule sentence) and `sources` (its citations). One line at a time. The model never sees the events table, another learner, the learner id, or any list of subjects or programmes.

**What the model gives back.** One sentence. The citations are not part of its answer. Code attaches the original citations to whatever sentence survives, so the model has no way to add or remove a source.

**The guard.** `check(sentence, line)` returns the reason a sentence must be discarded, or `None`. The checks, in order:

| Check | Discarded when the sentence |
|---|---|
| path | uses advice or path words: should, recommend, programme, career, remedial |
| label or rank | uses a label, a judgement, or a comparison: weak, strong, low, bottom of, classmates |
| source | names a quiz, test, exam, report, month, school, or class that is not in the sheet |
| number | contains a number that is not in the sheet |
| dropped result | leaves out one of the cited scores |
| score as count | puts a count word beside a cited score ("55 times"), or stops calling it a score, mark, or result |
| note wording | changes the quoted words of a teacher note |
| new claim | adds a trend: improved, declined, always, on average |
| pattern | says "pattern" or "consistent" about a line the rules did not put under "held" |

A word is only "added" if it is not already in the claim sheet. If the source says "term report", the model may say "report".

When a sentence is discarded, `phrase_lines` puts the rule text back and records the reason. One bad sentence does not affect the other lines. If the model crashes or times out, that also counts as a discard.

The lesson: do not ask a model to behave. Give it less, then check what it returns with ordinary code, and keep a safe answer ready.

**Try it:** in a Python shell, take one line from `update_profile(...)["lines"]` and call `phrase.check("The learner is weak at word problems, scoring 40, 38 and 41.", line)`.

The "score as count" row was added after the first real run. `llama3.1:8b` turned "Reading aloud: 55, on record once" into "The learner read aloud 55 times", and the guard kept it, because every earlier check looked for something *added* and this sentence added nothing. The lesson: run the real model early, read its output yourself, and turn each bad sentence you find into a fake-model test before you fix the guard.

## Step 15. Talking to Ollama

`OllamaModel` uses only the standard library (`urllib`) to call Ollama on `http://localhost:11434`. There is no cloud account and no API key.

- `ready()` asks `/api/tags` which models are present. It returns `None` if `llama3.1:8b` can be used, or a sentence saying why not.
- `phrase(claim)` posts to `/api/chat` with temperature 0 and a JSON schema, so the reply is always `{"sentence": "..."}`.

`python -m heldmark.run` calls `ready()` first. If Ollama is down it prints the rule profile and the line "PHRASING SKIPPED". The rule profile is always printed first, so the teacher can compare.

## Step 16. Testing without the model

`FakeModel` in `tests/test_graph.py` is a class with the same three members as `OllamaModel`: `name`, `ready()`, `phrase()`. It says whatever the test tells it to say and remembers everything it was shown.

- To test the guard, the fake returns a sentence with a label, a rank, a path, a new source, or a new number.
- To test what the model receives, the test puts a classmate's file in the intake folder and then searches everything the fake was shown.

Exactly one test calls the real model. It carries `@pytest.mark.ollama` and a `skipif` that calls `ready()`, so it runs when Ollama is up and is skipped when it is not. It does not check the model's wording, because wording changes. It checks what must always hold: same citations, and every kept sentence passes the guard.

**Try it:** `python -m pytest -m ollama -v` with Ollama running, then stop Ollama and run it again.

## What is still not built

`ARCHITECTURE.md` and the video.

## Words worth knowing

- **Append-only:** rows can be added but never changed or removed.
- **Trigger:** a rule stored in the database that runs when a row is about to change.
- **Pure function:** output depends only on its inputs; it reads and writes nothing else.
- **MCP server / client:** the server offers tools and resources; the client, usually an agent, calls them.
- **stdio transport:** client and server talk through a child process's standard input and output.
- **Fixture:** fixed, known data used by tests and the demo.
- **xfail:** a test recorded as expected to fail.
- **LangGraph node / state / edge:** a node is a function, the state is the dictionary passed between nodes, an edge says which node runs next.
- **Claim sheet:** the only text the model is shown: one rule sentence and its sources.
- **Guard:** ordinary code that decides whether a model sentence may be kept.
- **Fake model:** a stand-in used by tests so they do not need Ollama.
- **Pinned dependency:** an exact version number, so the code you run tomorrow is the code you ran today.
