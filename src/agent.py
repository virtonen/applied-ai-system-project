"""
A small deterministic agent: plan, act, critique, revise, retry.

It wraps the search pipeline. It searches, judges the result, and if the search found nothing or
the confidence is Low it reformulates the request and tries again, at most MAX_RETRIES times. Every
step is written to a trace, so a person can see exactly what it did and why.

    PLAN    the strategies it may use, in order
    ACT     run a search (the tool)
    CHECK   critique the result: good, nothing fits, low confidence, or cannot be fixed
    REVISE  change the request, using what the check found
    DECIDE  pick the best result and say what changed

It can only change the request words, the scoring mode and the optional preferences. It cannot skip
input validation, the retrieval guardrail or the explanation validator: bad input and unexpected
errors stop it immediately, because rewording cannot fix them. No language model is involved, so
the same input always gives the same trace.

    python -m src.agent --record-examples      # write the sample traces into ai_interactions.md
"""

import argparse
import logging
import re
import sys
import textwrap
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.glossary import Glossary
from src.logging_utils import log_event
from src.pipeline import SearchOutcome, search
from src.recommender import DEFAULT_MODE, SCORING_MODES, load_songs
from src.retrieval import SongIndex

MAX_RETRIES = 3
MIN_MODE_GAIN = 0.03  # another scoring mode must beat the current confidence by at least this much
OPTIONAL_PREFS = ("avoid_explicit", "popularity", "decade", "instrumentalness", "mood_tags")
LABEL_RANK = {"High": 2, "Medium": 1, "Low": 0}
ROOT = Path(__file__).resolve().parent.parent
TRACES_START = "<!-- TRACES:START -->"
TRACES_END = "<!-- TRACES:END -->"

Searcher = Callable[..., SearchOutcome]


@dataclass(frozen=True)
class Request:
    query: str
    prefs: Dict
    mode: str = DEFAULT_MODE
    diverse: bool = False
    k: int = 5


@dataclass
class Attempt:
    number: int
    request: Request
    outcome: SearchOutcome
    change: str = ""  # what was changed to produce this attempt


@dataclass
class Revision:
    strategy: str
    request: Request
    change: str  # short, for the summary: 'dropped "zebra"'
    reason: str  # longer, for the trace


@dataclass
class AgentResult:
    original: Request
    final: Request
    outcome: SearchOutcome
    attempts: List[Attempt]
    trace: List[Tuple[str, str]]
    retries: int
    status: str  # first_try, recovered, improved, gave_up or stopped
    stopped_because: str
    changes: List[str] = field(default_factory=list)

    @property
    def request_changed(self) -> bool:
        return self.final != self.original

    def trace_text(self, width: int = 100) -> str:
        lines = []
        for label, text in self.trace:
            lines.append(textwrap.fill(text, width=width, initial_indent=f"{label:<8}", subsequent_indent=" " * 8))
        return "\n".join(lines)


# ----- looking at a result -----

def summarize(outcome: SearchOutcome) -> str:
    if outcome.status == "ok":
        top = outcome.top_confidence
        return f"ok, {len(outcome.results)} song(s), top confidence {top.label} ({top.value:.2f})"
    if outcome.status == "invalid_input":
        return f"invalid_input ({outcome.message})"
    return outcome.status


def quoted(words: List[str]) -> str:
    return ", ".join(f'"{w}"' for w in words)


def critique(outcome: SearchOutcome, hits: List[Tuple[str, int]]) -> Tuple[str, str]:
    """Judge one result. Returns (kind, explanation): good, low, nothing_fits or stop."""
    if outcome.status in ("invalid_input", "error"):
        return "stop", f"this cannot be fixed by rewording: {outcome.message}"
    if outcome.status == "nothing_fits":
        if not hits:
            return "nothing_fits", "nothing fits, and the request has no usable words."
        counts = ", ".join(f"{word} {count}" for word, count in hits)
        return "nothing_fits", f"nothing fits. Songs matching each word: {counts}."
    top = outcome.top_confidence
    if top.label == "Low":
        return "low", (
            f"low confidence ({top.value:.2f}): the best score is only {outcome.results[0].score:.2f}, "
            "so the catalog does not fit these preferences well."
        )
    return "good", f"good enough: {top.label} confidence ({top.value:.2f})."


# ----- the strategies (each returns a Revision, or None when it does not apply) -----

class Context:
    def __init__(self, index: SongIndex, request: Request, outcome: SearchOutcome, searcher: Searcher):
        self.index, self.request, self.outcome, self.searcher = index, request, outcome, searcher
        self.hits = index.term_hits(request.query if isinstance(request.query, str) else "")


def drop_dead_words(ctx: Context) -> Optional[Revision]:
    dead = [word for word, count in ctx.hits if count == 0]
    live = [word for word, count in ctx.hits if count > 0]
    if not dead or not live:
        return None
    return Revision(
        "drop_dead_words", replace(ctx.request, query=" ".join(live)), f"dropped {quoted(dead)}",
        f"drop {quoted(dead)}, which matches no song even through the glossary, and keep {quoted(live)}",
    )


def keep_strongest_word(ctx: Context) -> Optional[Revision]:
    live = [(word, count) for word, count in ctx.hits if count > 0]
    if len(live) < 2:
        return None
    word, count = max(live, key=lambda item: item[1])  # the first word wins a tie
    return Revision(
        "keep_strongest_word", replace(ctx.request, query=word), f'kept only "{word}"',
        f'no song matches enough of these words together, so keep the one that matches most songs: "{word}" ({count})',
    )


def ignore_request(ctx: Context) -> Optional[Revision]:
    if not ctx.request.query:
        return None
    return Revision(
        "ignore_request", replace(ctx.request, query=""), "ignored the typed request",
        "no word of the request can be used, so rank by the listener's preferences alone",
    )


def relax_optional_prefs(ctx: Context) -> Optional[Revision]:
    present = [key for key in OPTIONAL_PREFS if key in ctx.request.prefs]
    if not present:
        return None
    prefs = {key: value for key, value in ctx.request.prefs.items() if key not in OPTIONAL_PREFS}
    return Revision(
        "relax_optional_prefs", replace(ctx.request, prefs=prefs), f"relaxed optional preferences ({', '.join(present)})",
        f"the optional preferences ({', '.join(present)}) may be too narrow, so drop them",
    )


def best_other_mode(ctx: Context) -> Optional[Revision]:
    current = ctx.outcome.top_confidence.value
    seen = {}
    for mode in SCORING_MODES:
        if mode == ctx.request.mode:
            continue
        found = ctx.searcher(ctx.index, ctx.request.query, ctx.request.prefs, k=ctx.request.k, mode=mode, diverse=ctx.request.diverse)
        if found.status == "ok":
            seen[mode] = found.top_confidence
    if not seen:
        return None
    mode, best = max(seen.items(), key=lambda item: item[1].value)
    compared = ", ".join(f"{m} {c.label} ({c.value:.2f})" for m, c in seen.items())
    if best.value < current + MIN_MODE_GAIN:
        return None
    return Revision(
        "best_other_mode", replace(ctx.request, mode=mode), f"scoring mode {ctx.request.mode} to {mode}",
        f"compare the other scoring modes on the same catalog ({compared}) and use {mode}, "
        "which puts the emphasis somewhere else; the songs available have not changed",
    )


STRATEGIES: Dict[str, List[Callable[[Context], Optional[Revision]]]] = {
    "nothing_fits": [drop_dead_words, keep_strongest_word, ignore_request],
    "low": [relax_optional_prefs, best_other_mode],
}


def plan_text(max_retries: int) -> str:
    return (
        "search as typed. If nothing fits: drop words that match no song, then keep the strongest word, "
        "then rank by the preferences alone. If confidence is Low: relax the optional preferences, then "
        f"compare the other scoring modes. At most {max_retries} retries."
    )


def best_attempt(attempts: List[Attempt]) -> Attempt:
    """The ok attempt with the highest confidence (the earliest wins a tie), else the original attempt."""
    ok = [a for a in attempts if a.outcome.status == "ok"]
    if not ok:
        return attempts[0]
    return max(ok, key=lambda a: (LABEL_RANK[a.outcome.top_confidence.label], a.outcome.top_confidence.value))


# ----- the loop -----

def run_agent(
    index: SongIndex,
    query: str,
    prefs: Dict,
    k: int = 5,
    mode: str = DEFAULT_MODE,
    diverse: bool = False,
    max_retries: int = MAX_RETRIES,
    searcher: Searcher = search,
) -> AgentResult:
    """Plan, act, critique and retry. Never raises, and never makes more than max_retries retries."""
    # Pass the values through untouched, so bad input reaches the validators and is rejected there
    original = Request(query, dict(prefs) if isinstance(prefs, dict) else prefs, mode, diverse, k)
    trace: List[Tuple[str, str]] = [("PLAN", plan_text(max_retries))]

    def act(number: int, request: Request) -> SearchOutcome:
        outcome = searcher(index, request.query, request.prefs, k=request.k, mode=request.mode, diverse=request.diverse)
        trace.append((f"ACT {number}", f'search("{request.query}", mode={request.mode}) -> {summarize(outcome)}'))
        return outcome

    attempts = [Attempt(0, original, act(0, original))]
    tried: set = set()
    retries = 0

    while True:
        last = attempts[-1]
        ctx = Context(index, last.request, last.outcome, searcher)
        kind, text = critique(last.outcome, ctx.hits)
        trace.append(("CHECK", text))
        if kind == "good":
            stopped = "the result is good enough"
            break
        if kind == "stop":
            stopped = "the problem cannot be fixed by rewording, so it did not retry"
            break
        if retries >= max_retries:
            stopped = f"the retry budget ({max_retries}) is used up"
            break
        revision = None
        for strategy in STRATEGIES[kind]:
            if strategy.__name__ in tried:
                continue
            revision = strategy(ctx)
            if revision:
                break
        if revision is None:
            stopped = "no strategy is left that applies"
            break
        retries += 1
        tried.add(revision.strategy)
        trace.append(("REVISE", f"{revision.reason}."))
        attempts.append(Attempt(retries, revision.request, act(retries, revision.request), revision.change))

    chosen = best_attempt(attempts)
    changes = [a.change for a in attempts[1 : chosen.number + 1] if a.change]
    first = attempts[0].outcome
    if first.status in ("invalid_input", "error"):
        status, verdict = "stopped", f"stopped without a result and without retrying. {first.message}"
    elif chosen.outcome.status != "ok":
        status = "gave_up"
        verdict = (
            "none of the retries found any songs, so kept the original result" if retries
            else "no rewording was possible, so kept the original result"
        )
    elif chosen.number == 0 and critique(first, [])[0] == "good":
        status, verdict = "first_try", "the first search was good enough, so there was nothing to change"
    elif chosen.number == 0:
        status = "gave_up"
        verdict = (
            "none of the retries beat the original result, so kept it" if retries
            else "nothing could be improved by rewording, so kept the original result"
        )
    elif first.status == "ok":
        status, verdict = "improved", f"improved the result by changing: {'; '.join(changes)}"
    else:
        status = "recovered"
        verdict = f"recovered after {chosen.number} retr{'y' if chosen.number == 1 else 'ies'} by changing: {'; '.join(changes)}"
    if chosen.number != 0 and chosen.request.query != original.query:
        answered = f'"{chosen.request.query}"' if chosen.request.query else "using the preferences alone"
        verdict += f'. Answered {answered} instead of "{original.query}"'
    trace.append(("DECIDE", verdict.rstrip(".") + "."))

    result = AgentResult(original, chosen.request, chosen.outcome, attempts, trace, retries, status, stopped, changes)
    top = chosen.outcome.top_confidence
    log_event(
        "agent",
        level=logging.INFO if chosen.outcome.status in ("ok", "nothing_fits") else logging.WARNING,
        original_query=original.query, final_query=chosen.request.query,
        original_mode=original.mode, final_mode=chosen.request.mode,
        retries=retries, status=status, final_status=chosen.outcome.status,
        strategies=[a.change for a in attempts[1:]], stopped_because=stopped,
        final_confidence=top.value if top else None, confidence_label=top.label if top else None,
    )
    return result


# ----- sample traces, saved in ai_interactions.md -----

def example_cases() -> List[Tuple[str, str, str, Dict]]:
    """(title, query, profile name, extra preferences) for the traces saved in ai_interactions.md."""
    return [
        ("A word that matches nothing", "jazz zebra", "Chill Lofi", {}),
        ("No usable words at all", "xylophone zebra", "Chill Lofi", {}),
        ("Words that never appear together", "jazz metal", "Chill Lofi", {}),
        ("Low confidence, so try another scoring mode", "", "Extreme Targets", {}),
        ("Invalid input is not retried", "", "Chill Lofi", {"energy": 9}),
    ]


def record_examples(path: Path, index: Optional[SongIndex] = None) -> str:
    """Run the example cases and write their traces between the markers in `path`. Returns the text."""
    from src.main import STANDARD_PROFILES, ADVERSARIAL_PROFILES, ADVANCED_PROFILES

    profiles = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}
    index = index or SongIndex(load_songs(str(ROOT / "data" / "songs.csv")), Glossary.load())
    parts = []
    for title, query, profile, extra in example_cases():
        prefs = {**profiles[profile], **extra}
        result = run_agent(index, query, prefs)
        shown = ", ".join(f"{k} {v}" for k, v in prefs.items())
        parts.append(
            f"### {title}\n\nRequest: `{query or '(none)'}` with the {profile} profile"
            f"{' and energy 9' if extra else ''} ({shown}).\n\n```\n{result.trace_text()}\n```\n"
        )
    block = f"{TRACES_START}\n" + "\n".join(parts) + f"{TRACES_END}"

    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(TRACES_START) + r".*?" + re.escape(TRACES_END), re.S)
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
    return block


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.agent", description="Agent utilities.")
    parser.add_argument("--record-examples", action="store_true", help="write the sample traces into ai_interactions.md")
    parser.add_argument("--out", default=str(ROOT / "ai_interactions.md"), help="file to write the traces into")
    args = parser.parse_args(argv)
    if not args.record_examples:
        parser.print_help()
        return 2
    record_examples(Path(args.out))
    print(f"Traces written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
