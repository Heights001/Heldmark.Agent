"""Phrasing. A local model may reword a line the rules already allowed, and nothing more.

The model is given a claim sheet: one claim and its sources at a time. It is
not given the events, another learner, a list of subjects or programmes, or
any way to attach a source. Code checks every sentence it returns. A sentence
that adds a label, a rank, a path, or a source that was not in the sheet is
discarded and the rule text is kept.
"""

import json
import os
import re
import urllib.error
import urllib.request

from . import rules

MODEL = "llama3.1:8b"
MAX_WORDS = 60

INSTRUCTIONS = (
    "You reword one claim from a school record as one plain sentence for a teacher. "
    "Use only what the claim and its sources say. Keep every number exactly. "
    "Do not add a source, a date, a school, or a number. "
    "Do not describe the learner: no label, no judgement, no comparison with other children. "
    "Do not say whether a result is good or bad, or whether it is getting better or worse. "
    "Do not give advice, and do not suggest a subject, programme, or career. "
    "Reply with the one sentence only."
)

JUDGEMENT_TERMS = re.compile(
    r"\b(strong\w*|strength\w*|weakness\w*|excel\w*|good|bad|well|badly|difficult\w*|trouble|behind|ahead|"
    r"talent\w*|able|ability|abilities|low|lower|lowest|high|higher|highest|impressive|concern\w*|worr\w*|"
    r"classmates?|peers?|other (children|learners|pupils))\b",
    re.IGNORECASE,
)
PATH_TERMS = re.compile(
    r"\b(recommend\w*|suggest\w*|advis\w*|should|ought|must|needs?|consider|encourag\w*|career\w*|"
    r"programmes?|courses?|streams?|track|subject choice|vocational|technical|remedial|intervention|support)\b",
    re.IGNORECASE,
)
SOURCE_TERMS = re.compile(
    r"\b(quiz(?:zes)?|tests?|exams?|examinations?|reports?|notes?|projects?|assignments?|homework|"
    r"assessments?|worksheets?|mark books?|registers?|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"school \d+|class \d+|grade \d+|term \d+)\b",
    re.IGNORECASE,
)
CLAIM_TERMS = re.compile(
    r"\b(improv\w*|declin\w*|progress\w*|better|worse|increas\w*|decreas\w*|dropp?\w*|r[io]s\w*|fell|fall\w*|"
    r"trend\w*|always|usually|tends?|typical\w*|average\w*)\b",
    re.IGNORECASE,
)
PATTERN_TERMS = re.compile(r"\b(pattern\w*|consistent\w*|repeated\w*|held|holds)\b", re.IGNORECASE)
NO_PATTERN = re.compile(r"\b(not a pattern|no pattern|not enough|does not show|cannot show)\b", re.IGNORECASE)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "twice": 2, "thrice": 3,
}  # fmt: skip


def claim_for_model(line: dict) -> dict:
    """Everything the model is shown for one line. Nothing else leaves the rules."""
    return {"claim": line["text"], "sources": [_source(cite) for cite in line["cites"]]}


def _source(cite: dict) -> str:
    score = f"{rules.fmt_score(cite['score'])}: " if cite.get("score") is not None else ""
    return f"{score}{cite['source']} ({cite['date']})"


def _stem(term: str) -> str:
    term = term.lower()
    return "quiz" if term.startswith("quiz") else term.rstrip("s") if not term[-1].isdigit() else term


def _numbers(text: str) -> set[float]:
    found = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}
    found |= {float(NUMBER_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in NUMBER_WORDS}
    return found


def _added(pattern: re.Pattern, sentence: str, sheet: str) -> list[str]:
    """Terms the sentence uses that the claim sheet does not. Echoing the sheet is allowed."""
    sheet = sheet.lower()
    return [m.group(0) for m in pattern.finditer(sentence) if _stem(m.group(0)) not in sheet]


def check(sentence: str, line: dict) -> str | None:
    """Return why a model sentence must be discarded, or None if it may stand."""
    sentence = (sentence or "").strip()
    sheet = " ".join([line["text"], *(_source(cite) for cite in line["cites"])])
    if not sentence:
        return "it was empty"
    if len(sentence.split()) > MAX_WORDS or "\n" in sentence:
        return "it was not one plain sentence"
    if _added(PATH_TERMS, sentence, sheet):
        return "it suggested a path"
    if _added(rules.LABEL_TERMS, sentence, sheet) or _added(JUDGEMENT_TERMS, sentence, sheet):
        return "it added a label or a rank"
    if _added(SOURCE_TERMS, sentence, sheet):
        return "it added a source that was not in the sheet"
    allowed = _numbers(sheet) | {float(len(line["cites"]))}
    if _numbers(sentence) - allowed:
        return "it added a number that was not in the sheet"
    scores = {float(cite["score"]) for cite in line["cites"] if cite.get("score") is not None}
    if scores - _numbers(sentence):
        return "it dropped a cited result"
    if any(quote not in sentence for quote in re.findall(r'"[^"]+"', line["text"])):
        return "it changed the wording of a note"
    if _added(CLAIM_TERMS, sentence, sheet):
        return "it added a claim the rules did not make"
    if line["section"] != "held" and PATTERN_TERMS.search(sentence) and not NO_PATTERN.search(sentence):
        return "it stated a pattern the rules did not allow"
    return None


def phrase_lines(lines: list[dict], model) -> list[dict]:
    """Ask the model for one sentence per line and keep only the sentences that pass check()."""
    results = []
    for line in lines:
        try:
            sentence = model.phrase(claim_for_model(line))
            reason = check(sentence, line)
        except Exception as error:  # the model is a guest: any failure falls back to the rule text
            sentence, reason = "", f"the model failed ({type(error).__name__})"
        kept = reason is None
        results.append(
            {
                "section": line["section"],
                "rule_text": line["text"],
                "text": sentence.strip() if kept else line["text"],
                "kept": kept,
                "discarded_because": reason,
                "cites": line["cites"],
            }
        )
    return results


def render(results: list[dict]) -> str:
    out = []
    for result in results:
        out.append(f"- {result['text']}")
        if not result["kept"]:
            out.append(f"    (rule text kept: the model's sentence was discarded because {result['discarded_because']})")
        out += [f"    source: {_source(cite)}" for cite in result["cites"]]
    return "\n".join(out)


class OllamaModel:
    """llama3.1:8b through a local Ollama. Open weights, on this machine, no account."""

    def __init__(self, name: str = MODEL, host: str | None = None):
        self.name = name
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"

    def _call(self, path: str, body: dict | None = None, timeout: float = 120) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.host}{path}", data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    def ready(self) -> str | None:
        """None if the model can be used, otherwise the reason it cannot."""
        try:
            tags = self._call("/api/tags", timeout=2)
        except (urllib.error.URLError, OSError, ValueError):
            return f"Ollama is not running at {self.host}"
        if self.name not in {model.get("name") for model in tags.get("models", [])}:
            return f"the model {self.name} is not pulled (run: ollama pull {self.name})"
        return None

    def phrase(self, claim: dict) -> str:
        reply = self._call(
            "/api/chat",
            {
                "model": self.name,
                "stream": False,
                "options": {"temperature": 0, "seed": 0},
                "format": {"type": "object", "properties": {"sentence": {"type": "string"}}, "required": ["sentence"]},
                "messages": [
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": json.dumps(claim, indent=2)},
                ],
            },
        )
        return json.loads(reply["message"]["content"])["sentence"]
