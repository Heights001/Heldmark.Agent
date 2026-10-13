# Architecture

Heldmark follows one learner across schools. One new quiz, project, or note starts one update, and the update stops at a named teacher.

## One update

`python -m heldmark.run` runs a LangGraph workflow (`heldmark/graph.py`) with five nodes in a fixed order:

```
read_intake -> append_events -> list_events -> update_profile -> phrase -> END
```

There are no conditional edges. The model does not choose a step and cannot add one. The graph ends by printing the profile for the named teacher. Nothing is sent to the learner or the guardian, and no tool exists to send it.

The nodes do not import the database. They reach tools only through `heldmark/toolbox.py`, which holds one MCP client for each of the two servers below.

## heldmark-records: the server we wrote

`heldmark/server.py` is our MCP server. It has exactly three tools and one resource:

| Name | What it does |
|---|---|
| `append_event` | Stores one cited quiz, project, or note. Refuses an event with no source or no date. |
| `list_events` | Returns one learner's events in order. The query cannot reach a classmate. |
| `update_profile` | Rewrites the sourced profile from the rules, and nothing else. |
| `learner://{id}/events` | The same learner's events, as a read-only resource. |

All writing of learner facts stays in this server so that there is one place to check. Every validation, every refusal, and every audit row for a learner fact is in `heldmark/records.py`. A call to any other tool name, such as one to label, rank, score, share, or recommend, is rejected and logged.

## The Filesystem server: borrowed

Prior-school files are read through the official Filesystem MCP server, which we did not write. It is started with one argument, the local intake folder, and refuses any path outside it. It makes no network calls.

Heldmark uses it for reading only. The toolbox allows two of its tools, `list_directory` and `read_text_file`. A call to any other, including its write tools, is refused and logged without being sent.

It is pinned in `package.json` to release `2026.8.31`. Release `1.0.0` was published on 11 October 2026, one day before this was built. The older release had been in use for six weeks, so it was chosen over a release nobody had yet had time to examine.

## SQLite

`heldmark/store.py` holds three tables: events, profiles, and the audit log. Events and the audit log are append-only. Database triggers abort any UPDATE or DELETE, so a past event cannot be edited by later code. The profile row is the only thing that is rewritten.

Every tool call is appended to the audit log with its input, output, timestamp, and learner id. Our server logs its own calls. The toolbox logs each filesystem read.

Each `heldmark.run` uses a fresh database file. Events are not de-duplicated, so reusing a database for the same intake folder would store each event twice.

## Rules, then the model

`heldmark/rules.py` decides what the profile may say. A pattern needs the same task kind at least twice, with every result cited. One score, a combined subject mark, or an entry with no source produces no pattern.

`llama3.1:8b`, run locally through Ollama, only rephrases. For each line the rules allowed, it is shown a claim sheet: that line and its sources. It is not shown the events, the learner id, another learner, or any list of subjects or programmes. The sources are attached by code, so the model cannot add one.

`heldmark/phrase.py` checks each sentence the model returns. A sentence that adds a label, a rank, a path, a source, or a number is discarded and the rule line is kept. So is a score rewritten as a count: the model once turned a reading-aloud score of 55 into "read aloud 55 times". If Ollama is not running, the rule profile is printed and the phrasing is skipped.

## What is still open

Task kinds are matched by exact name. If one school records `word_problem` and another records `story_sums`, Heldmark sees two single scores and states no pattern. The test for this is kept as an expected failure, and `EVALS.md` describes it. The code contains no fix.
