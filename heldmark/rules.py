"""The rules. Ordinary code decides what the profile may say; no model is involved.

A pattern needs the same task kind at least twice, and every result cited.
One score is not a pattern. A combined subject mark is not a pattern.
An entry with no source is not used. Nothing here labels, scores, or ranks
the learner, or suggests a subject, programme, or career.
"""

import re
from dataclasses import dataclass, field

NOTE_KIND = "note"

# A mark for a whole subject does not show which kind of task it came from.
COMBINED_SUBJECTS = frozenset(
    {
        "maths",
        "math",
        "mathematics",
        "english",
        "science",
        "literacy",
        "numeracy",
        "overall",
        "total",
        "average",
        "aggregate",
    }
)

# Words that label or rank a child, or point to a path. Free text containing
# any of them is not repeated in the profile.
LABEL_TERMS = re.compile(
    r"\b(slow|weak|lazy|dull|stupid|gifted|bright|clever|brilliant|poor|"
    r"below average|above average|average learner|struggl\w*|"
    r"rank\w*|position|top of|bottom of|best|worst|"
    r"should (study|take|offer|pursue)|career|programme)\b",
    re.IGNORECASE,
)

SECTIONS = (
    ("held", "Held more than once (same task kind, every result cited)"),
    ("once", "On record once (not a pattern)"),
    ("combined", "Combined subject marks (not a pattern)"),
    ("record", "Notes and projects on record"),
    ("missing", "Missing"),
)


@dataclass(frozen=True)
class Cite:
    event_id: int | None
    source: str
    date: str
    score: float | None = None


@dataclass(frozen=True)
class Line:
    section: str
    text: str
    cites: tuple[Cite, ...] = ()


@dataclass
class Profile:
    learner_id: str
    lines: list[Line] = field(default_factory=list)

    def section(self, name: str) -> list[Line]:
        return [line for line in self.lines if line.section == name]


def normalise_kind(kind: str) -> str:
    return re.sub(r"[\s\-]+", "_", kind.strip().lower())


def contains_label(text: str | None) -> bool:
    return bool(text and LABEL_TERMS.search(text.replace("_", " ")))


def fmt_score(score: float) -> str:
    return str(int(score)) if float(score).is_integer() else str(score)


def _label(kind: str) -> str:
    return kind.replace("_", " ").capitalize()


def _cite(event: dict) -> Cite:
    return Cite(event.get("id"), event["source"], event["event_date"], event.get("score"))


def build_profile(learner_id: str, events: list[dict]) -> Profile:
    """Turn one learner's events into the lines the profile is allowed to say."""
    profile = Profile(learner_id)
    sourced = [e for e in events if (e.get("source") or "").strip()]
    unsourced = len(events) - len(sourced)
    sourced.sort(key=lambda e: (e["event_date"], e.get("id") or 0))

    scored: dict[str, list[dict]] = {}
    for event in sourced:
        if event["kind"] != NOTE_KIND and event.get("score") is not None:
            scored.setdefault(event["kind"], []).append(event)

    for kind, group in scored.items():
        scores = ", ".join(fmt_score(e["score"]) for e in group)
        cites = tuple(_cite(e) for e in group)
        if kind in COMBINED_SUBJECTS:
            mark = "mark" if len(group) == 1 else "marks"
            profile.lines.append(
                Line(
                    "combined",
                    f"{_label(kind)}: combined subject {mark} {scores}. "
                    "A combined mark does not show the task kind, so no pattern is stated.",
                    cites,
                )
            )
        elif len(group) >= 2:
            schools = {e.get("school") for e in group}
            across = f" across {len(schools)} schools" if None not in schools and len(schools) > 1 else ""
            profile.lines.append(
                Line("held", f"{_label(kind)}: scores {scores} on {len(group)} cited results{across}.", cites)
            )
        else:
            profile.lines.append(
                Line("once", f"{_label(kind)}: {scores}, on record once. One result is not a pattern.", cites)
            )

    for event in sourced:
        if event["kind"] == NOTE_KIND:
            text = (event.get("text") or "").strip()
            if contains_label(text):
                said = "Teacher note on record. Its wording is not repeated here because it labels the learner."
            else:
                said = f'Teacher note: "{text}"'
            profile.lines.append(Line("record", said, (_cite(event),)))
        elif event.get("score") is None:
            profile.lines.append(Line("record", f"{_label(event['kind'])}: on record, no score given.", (_cite(event),)))

    if not sourced:
        profile.lines.append(Line("missing", "No cited events on record for this learner."))
    else:
        years = [int(e["event_date"][:4]) for e in sourced]
        for year in range(min(years), max(years) + 1):
            if year not in years:
                profile.lines.append(Line("missing", f"No events on record for {year}."))
    if unsourced:
        noun = "entry has" if unsourced == 1 else "entries have"
        profile.lines.append(Line("missing", f"{unsourced} {noun} no source and is not used."))
    return profile


def render(profile: Profile, shown_to: str) -> str:
    """Plain text for the teacher. Tomorrow a local model may rephrase these lines, and only these."""
    out = [
        f"Sourced profile: learner {profile.learner_id}",
        f"For: {shown_to}. Not sent to the learner or the guardian.",
    ]
    for name, title in SECTIONS:
        lines = profile.section(name)
        if not lines:
            continue
        out += ["", title]
        for line in lines:
            out.append(f"- {line.text}")
            for cite in line.cites:
                score = f"{fmt_score(cite.score)}: " if cite.score is not None else ""
                out.append(f"    source: {score}{cite.source} ({cite.date})")
    out += ["", "The teacher decides what to raise. This profile gives no label, no rank, and no path."]
    return "\n".join(out)
