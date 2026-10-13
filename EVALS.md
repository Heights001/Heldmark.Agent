# Evals

Last run on 13 October 2026 with Python 3.11, mcp 2.3.0, langgraph 1.2.14, pytest 9.1.1.

```bash
python -m pytest -v
```

Result with Ollama stopped: **38 passed, 1 skipped, 1 expected failure left open.**
Result with Ollama running: **39 passed, 1 expected failure left open.**

The demo and every test except one are model-free. The skipped test is the one marked `ollama`, which calls the real local model and runs only when Ollama is up with `llama3.1:8b`.

## Day one: store, rules, and our MCP server

| # | Check | Test | Result |
|---|---|---|---|
| 1 | A pattern that held across schools is stated: word problem 40, 38, 41 at three schools; calculation 72, 75 at two. | `test_pattern_held_across_schools` | pass |
| 2 | A single score (reading aloud, 55) does not become a pattern. | `test_single_score_is_not_a_pattern` | pass |
| 3 | A combined "Maths" mark is not a pattern, even when there are two of them. | `test_combined_subject_mark_is_not_a_pattern` | pass |
| 4 | The year with no events (2025) is stated as missing. | `test_missing_year_is_stated_as_missing` | pass |
| 5 | A note with no source is refused at intake, logged, and ignored by the rules. | `test_unsourced_note_is_refused` | pass |
| 6 | `list_events` returns one learner and never a classmate. | `test_list_events_never_returns_classmates` | pass |
| 7 | Requests to label, rank, score, share, or recommend are rejected and logged, in code, over MCP, and on the command line. | `test_label_rank_share_requests_are_rejected_and_logged` (5 cases) | pass |
| 8 | Every profile line cites its sources, and each source is a stored event. | `test_profile_lines_cite_their_sources` | pass |
| 9 | Events and the audit log are append-only. UPDATE and DELETE abort. | `test_events_are_append_only` | pass |
| 10 | The MCP server exposes exactly `append_event`, `list_events`, `update_profile`, and the resource `learner://{id}/events`. | `test_mcp_server_has_exactly_three_tools_and_one_resource` | pass |
| 11 | `python -m heldmark.demo` loads `data/fixture/five_schools.json` and prints the profile. | `test_readme_demo_command_prints_the_fixture_profile` | pass |
| 12 | The README `add-event` and `update-profile` commands work, and the event keeps the date it was given. | `test_readme_usage_commands` | pass |
| 12b | `add-event` with no `--date` exits with an error and writes no row. The records refuse a dateless event too. | `test_add_event_without_a_date_exits_and_writes_no_row` | pass |
| 13 | The profile carries no label, rank, or path. A note that labels the child is cited but not repeated. A task kind that labels the child is refused. | `test_profile_does_not_label_rank_or_suggest_a_path` | pass |
| 14 | The same task under two school names is one pattern. | `test_same_task_under_two_school_names_is_one_pattern` | **fail, left open** |

## Day two: graph, Filesystem server, and phrasing

| # | Check | Test | Result |
|---|---|---|---|
| 15 | The graph runs one update: read intake, append, list, update profile, phrase. 9 events stored, 1 refused. | `test_graph_runs_one_update_through_both_servers` | pass |
| 16 | Every tool call is in the audit log with input, output, timestamp, and learner id, including the filesystem read. 14 calls, 14 rows. | `test_every_tool_call_is_in_the_audit_log_including_the_filesystem_read` | pass |
| 17 | The Filesystem server is used for reading only. A write and a read outside the intake folder are refused and logged. | `test_the_filesystem_server_is_used_for_reading_only` | pass |
| 18 | The graph nodes do not import the database. | `test_graph_nodes_do_not_import_the_database` | pass |
| 19 | A fake model's sentence that adds a label, a rank, a path, a source, or a number, or drops a result, is discarded and the rule text is kept. | `test_a_sentence_that_adds_a_label_rank_path_or_source_is_discarded` (6 cases) | pass |
| 20 | A faithful sentence is kept and keeps its sources. | `test_a_faithful_sentence_is_kept_and_keeps_its_sources` | pass |
| 21 | A single score cannot be phrased into a pattern. | `test_a_single_score_cannot_be_phrased_into_a_pattern` | pass |
| 21b | A score rewritten as a count or a repeated action ("read aloud 55 times") is discarded and the rule line remains. | `test_a_score_rewritten_as_a_count_is_discarded` (5 cases) | pass |
| 22 | The model receives only the claim sheet: no classmate data, no learner id, no path menu. A classmate's file in the intake folder is not stored. | `test_the_model_receives_only_the_claim_sheet` | pass |
| 23 | With Ollama down, the rule profile is printed and the phrasing is reported as skipped. | `test_with_ollama_down_the_rule_profile_is_printed_and_phrasing_is_skipped` | pass |
| 24 | The full graph works with the real borrowed Filesystem server and our server as child processes. | `test_full_graph_with_the_real_filesystem_server_and_our_server_over_stdio` | pass (skipped if `npm install` was not run) |
| 25 | The open-weights task: the real `llama3.1:8b` yields only checked sentences and cannot change a source. | `test_real_local_model_only_ever_yields_checked_sentences` | pass with Ollama running; skipped when it is stopped |

## A failure found with the real model, now fixed

On 12 October 2026, `python -m heldmark.run` with `llama3.1:8b` turned the rule line

```
Reading aloud: 55, on record once. One result is not a pattern.
```

into

```
The learner read aloud 55 times, which is a single instance.
```

55 is a score. The sentence made it a count. The guard of that day kept the sentence, because it added no label, rank, path, source, or new number.

The guard now rejects a sentence when a cited score is written as a count or a repeated action: a count word such as "times", "occasions", or "words" beside a number from the claim sheet, or a sentence about a scored line that no longer says score, mark, or result. The sentence is discarded and the rule text is kept. `test_a_score_rewritten_as_a_count_is_discarded` feeds the model's exact sentence through a fake model and checks that the rule line remains. This is a check on words beside a cited number, not a grammar checker.

## The one failure left open

**Name:** the same task under two school names is not recognised as the same kind.

School 1 records a `word_problem` quiz. School 4 calls the same kind of task `story_sums`. Heldmark matches task kinds by exact name, so it sees two single scores and states no pattern. The result is quiet: nothing wrong is printed, but a pattern that held is missed, which is the case the product exists for.

The test is marked `xfail(strict=True)`, so the suite stays green while the failure stays on record, and the suite turns red the day it starts passing unnoticed. To see the raw failure:

```bash
python -m pytest --runxfail -k two_school_names
```

```
    def test_same_task_under_two_school_names_is_one_pattern(records):
        records.append_event("L1", "word_problem", "Class 1 word problem quiz, School 1", score=40, date="2024-02-20")
        records.append_event("L1", "story_sums", "Class 2 story sums quiz, School 4", score=41, date="2026-03-19")
        profile = rules.build_profile("L1", records.list_events("L1"))
>       assert len(profile.section("held")) == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = len([])

FAILED tests/test_heldmark.py::test_same_task_under_two_school_names_is_one_pattern
1 failed, 17 deselected
```

**Why it is not fixed today.** Spelling differences are already handled (`Word Problem`, `word-problem`, and `word_problem` are one kind). Real synonyms are different: deciding that "story sums" and "word problem" are the same task is a teaching judgement, and guessing it in code or handing it to the model would let the software invent a pattern.

**What I would try next.** A small alias table in code, `story_sums -> word_problem`, that only a teacher can add to, one line at a time. Each alias would be an audited entry naming who agreed it. The profile line would then show both original names beside their sources, so the teacher can see that two names were joined and can disagree.

## Known limits seen while testing

- A "year" is a calendar year, not a school year.
- Scores are compared as written. A mark out of 20 and a mark out of 100 would be listed side by side.
- Events are append-only and not de-duplicated. `python -m heldmark.run` uses a fresh store each time; pointing `--db` at a kept store and running the same intake folder twice would store each event twice.
- The phrasing guard works on words. It is strict, so it also discards some harmless sentences, and the rule text is shown in their place.
- The guard does not require the task kind to be named. On 12 October 2026 it kept "Scores of 72 and 75 were achieved on two quizzes", which drops "calculation". The rule profile is always printed above the model's sentences, so the teacher can see the difference.
