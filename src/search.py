"""
Run one search from the terminal, with the same pipeline the web app uses.

    python -m src.search "cozy rainy study" --profile "Chill Lofi"
    python -m src.search "jazz" --genre jazz --mood relaxed --energy 0.4 --mode mood-first
    python -m src.search "cozy rainy study" --profile "Chill Lofi" --ai     # Gemini writes the "why"
    python -m src.search "mellow homework" --profile "Chill Lofi" --no-glossary   # without the glossary

Exit code: 0 results, 1 nothing fits, 2 bad input or bad song file, 3 unexpected error.
"""

import argparse
import os
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional

from src import llm_client
from src.explain import explain_with_ai
from src.glossary import Glossary
from src.guardrails import DataError
from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.pipeline import SearchOutcome, search
from src.recommender import DEFAULT_MODE, SCORING_MODES, load_songs
from src.retrieval import SongIndex

PROFILES = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}
DEFAULT_DATA = os.environ.get("VIBEMATCH_DATA") or str(Path(__file__).resolve().parent.parent / "data" / "songs.csv")
WIDTH = 100

EXIT_CODES = {"ok": 0, "nothing_fits": 1, "invalid_input": 2, "error": 3}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.search",
        description="Search the song catalog: retrieve, rank, score confidence and explain.",
    )
    parser.add_argument("query", nargs="?", default="", help="what you want, in words (optional)")
    parser.add_argument("--profile", help="start from a demo profile: " + ", ".join(f'"{n}"' for n in PROFILES))
    parser.add_argument("--genre")
    parser.add_argument("--mood")
    parser.add_argument("--energy", type=float, help="0 to 1")
    parser.add_argument("--valence", type=float, help="0 to 1")
    parser.add_argument("--acousticness", type=float, help="0 to 1")
    parser.add_argument("--instrumentalness", type=float, help="0 to 1")
    parser.add_argument("--popularity", type=float, help="0 to 100")
    parser.add_argument("--decade", type=int, help="for example 1990")
    parser.add_argument("--tags", help="comma-separated mood tags, for example cozy,study")
    parser.add_argument("--avoid-explicit", action="store_true")
    parser.add_argument("--mode", choices=list(SCORING_MODES), default=DEFAULT_MODE)
    parser.add_argument("--diverse", action="store_true", help="penalize repeated artists and genres")
    parser.add_argument("-k", type=int, default=5, help="how many songs (default 5)")
    parser.add_argument("--no-glossary", action="store_true", help="do not use the glossary (no synonyms, no genre or mood explanations)")
    parser.add_argument("--ai", action="store_true", help="ask Gemini to write the 'why' (needs GEMINI_API_KEY)")
    parser.add_argument("--data", default=DEFAULT_DATA, help="song CSV to use")
    return parser


def find_profile(name: str) -> Optional[Dict]:
    wanted = name.strip().lower().replace("_", " ").replace("-", " ")
    for key, prefs in PROFILES.items():
        if key.lower().replace("-", " ") == wanted:
            return dict(prefs)
    return None


def build_prefs(args: argparse.Namespace) -> Dict:
    """Start from the chosen profile, then let any flag the user typed override it."""
    prefs: Dict = {}
    if args.profile:
        prefs = find_profile(args.profile)
        if prefs is None:
            raise ValueError(f'Unknown profile "{args.profile}". Choose from: ' + ", ".join(f'"{n}"' for n in PROFILES))
    for key in ("genre", "mood", "energy", "valence", "acousticness", "instrumentalness", "popularity"):
        if getattr(args, key) is not None:
            prefs[key] = getattr(args, key)
    if args.decade is not None:
        prefs["decade"] = args.decade
    if args.tags:
        prefs["mood_tags"] = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    if args.avoid_explicit:
        prefs["avoid_explicit"] = True
    return prefs


def describe_prefs(prefs: Dict) -> str:
    parts = []
    for key, value in prefs.items():
        parts.append(f"{key} {','.join(value) if isinstance(value, list) else value}")
    return ", ".join(parts)


def _wrapped(label: str, text: str) -> str:
    return textwrap.fill(text, width=WIDTH, initial_indent=f"   {label}", subsequent_indent=" " * (3 + len(label)))


def format_outcome(outcome: SearchOutcome, prefs: Dict, mode: str, whys: List, diverse: bool) -> str:
    lines = [
        f'Request : {outcome.query or "(none, ranking by preferences only)"}',
        f"Prefs   : {describe_prefs(prefs)}",
        f"Mode    : {mode}{' + diversity penalty' if diverse else ''}",
    ]
    if outcome.status != "ok":
        lines.append(f"Status  : {outcome.status}")
        lines.append(f"Message : {outcome.message}")
        return "\n".join(lines)

    top = outcome.top_confidence
    lines.append(f"Status  : ok, {len(outcome.results)} song(s), overall confidence {top.label} ({top.value:.2f})")
    if top.label == "Low":
        lines.append("Warning : low confidence, these are the closest songs, not a good fit")
    for rank, (r, why) in enumerate(zip(outcome.results, whys), start=1):
        source = "written by Gemini, checked against the song facts" if why.source == "ai" else "built from the song facts"
        lines += [
            "",
            f"{rank}. {r.song['title']} by {r.song['artist']}  [{r.song['genre']} / {r.song['mood']}]",
            f"   score {r.score:.2f} | confidence {r.confidence.label} ({r.confidence.value:.2f}): {r.confidence.breakdown()}",
            _wrapped("why: ", f"{why.text} ({source})"),
        ]
        if why.note:
            lines.append(_wrapped("note: ", f"the model's wording was not used: {why.note}"))
        lines.append(_wrapped("scored by: ", r.explanation))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        prefs = build_prefs(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_CODES["invalid_input"]
    if not prefs:
        print("error: give a --profile or at least one preference (--genre, --mood, --energy, ...).", file=sys.stderr)
        return EXIT_CODES["invalid_input"]

    try:
        index = SongIndex(load_songs(args.data), None if args.no_glossary else Glossary.load())
    except DataError as error:
        print(f"error: the song list could not be loaded. {error}", file=sys.stderr)
        return EXIT_CODES["invalid_input"]

    outcome = search(index, args.query, prefs, k=args.k, mode=args.mode, diverse=args.diverse)

    whys = [r.why for r in outcome.results]
    if args.ai and outcome.status == "ok":
        client = llm_client.make_client()
        if client is None:
            print("note: --ai needs GEMINI_API_KEY (in the environment or .env); using the song facts instead.", file=sys.stderr)
        else:
            whys = explain_with_ai(outcome.results, outcome.query, client, glossary=index.glossary)

    print(format_outcome(outcome, prefs, args.mode, whys, args.diverse))
    return EXIT_CODES[outcome.status]


if __name__ == "__main__":
    sys.exit(main())
