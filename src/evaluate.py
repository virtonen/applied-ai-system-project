"""
Evaluation harness: run predefined requests through the real search pipeline, check each one
against what it should return, and report pass/fail and confidence.

    python -m src.evaluate                  # print the table, write reports/evaluation.md
    python -m src.evaluate --brief          # one short line per case
    python -m src.evaluate --readme         # also refresh the table inside README.md
    python -m src.evaluate --data other.csv

The exit code is 0 when every case passes and 1 otherwise, so it can run in a check or CI job.
Searches made by the harness are logged to logs/evaluation.log (or VIBEMATCH_EVAL_LOG_FILE), not the app's log.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.logging_utils import configure_logging
from src.explain import validate_explanation
from src.pipeline import SearchOutcome, search
from src.recommender import load_songs
from src.report import format_table
from src.retrieval import SongIndex

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "songs.csv"
DEFAULT_REPORT = ROOT / "reports" / "evaluation.md"
DEFAULT_README = ROOT / "README.md"
README_START = "<!-- EVAL:START -->"
README_END = "<!-- EVAL:END -->"

PROFILES = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}


@dataclass
class Case:
    """One predefined request and what it should produce.

    expect keys (all optional): status (default "ok"), message (text the message contains),
    top (title ranked first), exact (full ordered list of titles), includes, excludes (lists of
    titles), before ((a, b): a ranks above b), count, confidence (label of the top result),
    max_per_artist, grounded (True: every result's explanation uses only that song's facts and the request).
    """

    id: str
    what: str
    prefs: Dict
    query: str = ""
    k: int = 5
    mode: str = "balanced"
    diverse: bool = False
    expect: Dict = field(default_factory=dict)


CASES: List[Case] = [
    # Listener profiles, no typed request
    Case("P1", "High-Energy Pop: the pop/happy song wins", PROFILES["High-Energy Pop"],
         expect=dict(top="Sunrise City", includes=["Gym Hero", "Rooftop Lights"], confidence="High", grounded=True)),
    Case("P2", "Chill Lofi: both lofi/chill songs lead", PROFILES["Chill Lofi"],
         expect=dict(includes=["Library Rain", "Midnight Coding"], confidence="High")),
    Case("P3", "Deep Intense Rock: the one rock song wins", PROFILES["Deep Intense Rock"],
         expect=dict(top="Storm Runner", confidence="High")),
    Case("P4", "Nostalgic Throwback uses decade, popularity and tags", PROFILES["Nostalgic Throwback"],
         expect=dict(top="Dust Road Home", confidence="High")),
    Case("P5", "Sad but Energetic: a compromise, so only Medium confidence", PROFILES["Conflicting: Sad but Energetic"],
         expect=dict(top="Adagio for Rain", confidence="Medium")),
    Case("P6", "Extreme Targets: a poor fit must be flagged Low", PROFILES["Extreme Targets"],
         expect=dict(top="Birchwood Lullaby", confidence="Low")),
    Case("P7", "Clean Workout: the explicit song stays out of the top 3", PROFILES["Clean Workout"], k=3,
         expect=dict(top="Storm Runner", excludes=["Iron Requiem"])),
    # Scoring modes and diversity
    Case("M1", "Mood-first ranks a happy song above the intense Gym Hero", PROFILES["High-Energy Pop"], mode="mood-first",
         expect=dict(before=("Rooftop Lights", "Gym Hero"))),
    Case("M2", "Genre-first puts the only metal song first for the metal fan", PROFILES["Extreme Targets"], mode="genre-first",
         expect=dict(top="Iron Requiem")),
    Case("D1", "Diversity penalty: one song per artist for Chill Lofi", PROFILES["Chill Lofi"], diverse=True,
         expect=dict(max_per_artist=1, count=5)),
    # Typed requests (retrieval and its guardrail)
    Case("S1", "'cozy rainy study' finds exactly the two songs with those tags", PROFILES["Chill Lofi"], query="cozy rainy study",
         expect=dict(exact=["Library Rain", "Midnight Coding"], confidence="High", grounded=True)),
    Case("S2", "A one-word request is enough: 'jazz'", PROFILES["Chill Lofi"], query="jazz",
         expect=dict(exact=["Coffee Shop Stories"])),
    Case("S3", "Vibe words from numbers: 'workout powerful'", PROFILES["High-Energy Pop"], query="workout powerful",
         expect=dict(exact=["Gym Hero"])),
    Case("S4", "'calm acoustic' returns a full list that includes Library Rain", PROFILES["Chill Lofi"], query="calm acoustic",
         expect=dict(includes=["Library Rain"], count=5, grounded=True)),
    # Guardrails
    Case("G1", "Nonsense words: nothing fits", PROFILES["Chill Lofi"], query="xylophone zebra",
         expect=dict(status="nothing_fits", count=0)),
    Case("G2", "One real word and one unknown word: refused", PROFILES["Chill Lofi"], query="jazz zebra",
         expect=dict(status="nothing_fits", count=0)),
    Case("G3", "Only filler words: nothing fits", PROFILES["Chill Lofi"], query="the and of",
         expect=dict(status="nothing_fits", count=0)),
    Case("G4", "Out-of-range energy is rejected with a reason", {"energy": 9},
         expect=dict(status="invalid_input", message="'energy' must be between 0 and 1", count=0)),
    Case("G5", "A 500-character request is rejected", PROFILES["Chill Lofi"], query="x" * 500,
         expect=dict(status="invalid_input", message="too long", count=0)),
]


@dataclass
class Result:
    case: Case
    outcome: SearchOutcome
    failures: List[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def check(outcome: SearchOutcome, expect: Dict) -> List[str]:
    """Return a list of problems (empty means the case passed)."""
    problems = []
    titles = [r.song["title"] for r in outcome.results]

    wanted_status = expect.get("status", "ok")
    if outcome.status != wanted_status:
        problems.append(f"status was {outcome.status}, expected {wanted_status}")
    if "message" in expect and expect["message"] not in outcome.message:
        problems.append(f"message {outcome.message!r} lacks {expect['message']!r}")
    if "count" in expect and len(titles) != expect["count"]:
        problems.append(f"{len(titles)} results, expected {expect['count']}")
    if "top" in expect and titles[:1] != [expect["top"]]:
        problems.append(f"top was {titles[:1] or 'nothing'}, expected {expect['top']}")
    if "exact" in expect and titles != expect["exact"]:
        problems.append(f"results were {titles}, expected {expect['exact']}")
    for title in expect.get("includes", []):
        if title not in titles:
            problems.append(f"missing {title}")
    for title in expect.get("excludes", []):
        if title in titles:
            problems.append(f"should not include {title}")
    if "before" in expect:
        first, second = expect["before"]
        if first not in titles or (second in titles and titles.index(second) < titles.index(first)):
            problems.append(f"{first} should rank above {second}")
    if "confidence" in expect:
        top = outcome.top_confidence
        if top is None or top.label != expect["confidence"]:
            problems.append(f"confidence was {top.label if top else 'none'}, expected {expect['confidence']}")
    if expect.get("grounded"):
        for r in outcome.results:
            ok, reason = validate_explanation(r.why.text, r.song, outcome.query)
            if not ok:
                problems.append(f"explanation for {r.song['title']} is not grounded: {reason}")
    if "max_per_artist" in expect:
        artists = [r.song["artist"] for r in outcome.results]
        worst = max((artists.count(a) for a in artists), default=0)
        if worst > expect["max_per_artist"]:
            problems.append(f"an artist appears {worst} times, expected at most {expect['max_per_artist']}")
    return problems


def run_cases(index: SongIndex, cases: List[Case]) -> List[Result]:
    results = []
    for case in cases:
        outcome = search(index, case.query, case.prefs, k=case.k, mode=case.mode, diverse=case.diverse)
        results.append(Result(case, outcome, check(outcome, case.expect)))
    return results


# ----- reporting -----

def describe(expect: Dict) -> str:
    """A short plain-text summary of what a case expects."""
    parts = []
    status = expect.get("status", "ok")
    if status != "ok":
        parts.append(status)
    if "top" in expect:
        parts.append(f"top = {expect['top']}")
    if "exact" in expect:
        parts.append("exactly " + ", ".join(expect["exact"]))
    if "includes" in expect:
        parts.append("includes " + ", ".join(expect["includes"]))
    if "excludes" in expect:
        parts.append("excludes " + ", ".join(expect["excludes"]))
    if "before" in expect:
        parts.append(f"{expect['before'][0]} above {expect['before'][1]}")
    if "max_per_artist" in expect:
        parts.append(f"max {expect['max_per_artist']} per artist")
    if "confidence" in expect:
        parts.append(f"confidence {expect['confidence']}")
    if expect.get("grounded"):
        parts.append("grounded explanations")
    if "message" in expect:
        parts.append(f"message has '{expect['message']}'")
    return "; ".join(parts)


def summarize(results: List[Result]) -> Dict:
    scored = [r.outcome.top_confidence for r in results if r.outcome.top_confidence]
    labels = {label: sum(1 for c in scored if c.label == label) for label in ("High", "Medium", "Low")}
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "with_results": len(scored),
        "average_confidence": round(sum(c.value for c in scored) / len(scored), 2) if scored else None,
        "labels": labels,
    }


def summary_line(results: List[Result]) -> str:
    s = summarize(results)
    text = f"{s['passed']} of {s['total']} cases passed ({s['passed'] / s['total']:.0%})."
    if s["average_confidence"] is not None:
        labels = ", ".join(f"{name} {count}" for name, count in s["labels"].items())
        text += f" Average top-result confidence {s['average_confidence']:.2f} across {s['with_results']} cases that returned songs ({labels})."
    return text


def _rows(results: List[Result]) -> List[List[str]]:
    rows = []
    for r in results:
        top = r.outcome.top_confidence
        rows.append([
            r.case.id,
            r.case.what,
            describe(r.case.expect),
            "PASS" if r.passed else "FAIL: " + " | ".join(r.failures),
            r.outcome.results[0].song["title"] if r.outcome.results else "-",
            f"{top.label} ({top.value:.2f})" if top else "-",
        ])
    return rows


HEADERS = ["ID", "What it checks", "Expected", "Result", "Top song", "Confidence"]


def to_markdown(results: List[Result]) -> str:
    """A markdown table (no dates or timings, so the same data always gives the same text)."""
    lines = ["| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
    for row in _rows(results):
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines) + "\n\n" + summary_line(results) + "\n"


def to_terminal(results: List[Result]) -> str:
    rows = [[r[0], r[1], r[3], r[4], r[5]] for r in _rows(results)]
    return format_table(["ID", "What it checks", "Result", "Top song", "Confidence"], rows) + "\n" + summary_line(results)


def to_brief(results: List[Result]) -> str:
    """One short line per case plus the summary, narrow enough for a README code block."""
    lines = []
    for r in results:
        top = r.outcome.top_confidence
        shown = f"{r.outcome.results[0].song['title']}, {top.label} ({top.value:.2f})" if top else r.outcome.status
        lines.append(f"{r.case.id:<3} {'PASS' if r.passed else 'FAIL'}  {shown:<34} {r.case.what}")
        lines += [f"      -> {problem}" for problem in r.failures]
    return "\n".join(lines) + "\n\n" + summary_line(results)


def write_report(results: List[Result], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Evaluation results\n\nRun with `python -m src.evaluate`.\n\n" + to_markdown(results), encoding="utf-8")


def update_readme(results: List[Result], path: Path) -> bool:
    """Replace the text between the EVAL markers in the README. Returns False if they are missing."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    if not pattern.search(text):
        return False
    block = f"{README_START}\n{to_markdown(results)}{README_END}"
    path.write_text(pattern.sub(lambda _: block, text), encoding="utf-8")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation cases against the recommender.")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="song CSV to evaluate against")
    parser.add_argument("--out", default=str(DEFAULT_REPORT), help="where to write the markdown report")
    parser.add_argument("--brief", action="store_true", help="print one short line per case instead of the wide table")
    parser.add_argument("--readme", action="store_true", help="also refresh the table between the EVAL markers in README.md")
    parser.add_argument("--readme-path", default=str(DEFAULT_README), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    configure_logging(os.environ.get("VIBEMATCH_EVAL_LOG_FILE") or ROOT / "logs" / "evaluation.log")
    results = run_cases(SongIndex(load_songs(args.data)), CASES)

    print(to_brief(results) if args.brief else to_terminal(results))
    write_report(results, Path(args.out))
    print(f"\nReport written to {args.out}")
    if args.readme:
        if update_readme(results, Path(args.readme_path)):
            print(f"README table updated ({args.readme_path}).")
        else:
            print(f"README not updated: add {README_START} and {README_END} markers to {args.readme_path}.", file=sys.stderr)
            return 1
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
