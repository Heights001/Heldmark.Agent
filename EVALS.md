# Evals

Run on 12 October 2026 with Python 3.11, mcp 2.3.0, pytest 9.1.1.

```bash
python -m pytest -v
```

Result: **17 passed, 1 expected failure left open.** The 17 are 13 tests; the rejection test runs once for each of five forbidden requests.

## What is checked

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
| 12 | The README `add-event` and `update-profile` commands work. | `test_readme_usage_commands` | pass |
| 13 | The profile carries no label, rank, or path. A note that labels the child is cited but not repeated. A task kind that labels the child is refused. | `test_profile_does_not_label_rank_or_suggest_a_path` | pass |
| 14 | The same task under two school names is one pattern. | `test_same_task_under_two_school_names_is_one_pattern` | **fail, left open** |

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
- `add-event` with no `--date` records today's date as the event date.
