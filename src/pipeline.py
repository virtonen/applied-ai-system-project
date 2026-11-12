"""
The search pipeline the app uses: validate -> retrieve -> rank -> score confidence -> log.

search() never raises. It returns a SearchOutcome whose status says what happened:
  ok             results are ready
  nothing_fits   the guardrail found no songs for the typed request
  invalid_input  the request or preferences failed validation (message says why)
  error          something unexpected failed (details are in the log)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.confidence import Confidence, confidence
from src.explain import Why, template_why
from src.guardrails import InputError, validate_k, validate_prefs, validate_query
from src.logging_utils import log_event
from src.recommender import DEFAULT_MODE, SCORING_MODES, recommend_songs
from src.retrieval import SongIndex, query_terms


@dataclass
class Ranked:
    song: Dict
    score: float
    explanation: str
    confidence: Confidence
    matched_words: List[str] = field(default_factory=list)
    why: Optional[Why] = None  # a grounded explanation built from the retrieved song facts


@dataclass
class SearchOutcome:
    status: str
    results: List[Ranked] = field(default_factory=list)
    message: str = ""
    query: str = ""
    elapsed_ms: float = 0.0

    @property
    def top_confidence(self) -> Optional[Confidence]:
        return self.results[0].confidence if self.results else None


def search(
    index: SongIndex,
    query: str,
    prefs: Dict,
    k: int = 5,
    mode: str = DEFAULT_MODE,
    diverse: bool = False,
) -> SearchOutcome:
    """Run one search end to end. Logs one line per call, including any error."""
    started = time.perf_counter()
    outcome = SearchOutcome(status="error", query=query if isinstance(query, str) else "")
    error_text = None

    try:
        query = validate_query(query)
        prefs = validate_prefs(prefs)
        k = validate_k(k)
        if mode not in SCORING_MODES:
            raise InputError(f"Unknown mode '{mode}'. Choose from: {', '.join(SCORING_MODES)}.")
        outcome.query = query

        terms = query_terms(query)
        matched_by_id: Dict[int, List[str]] = {}
        candidates = index.songs
        if query:
            hits = index.retrieve(query)
            if not hits:
                outcome.status = "nothing_fits"
                outcome.message = f'Nothing fits: no songs match "{query}".'
                return outcome
            matched_by_id = {song["id"]: matched for song, matched in hits}
            candidates = [song for song, _ in hits]

        # Rank one extra song so the last result still has a runner-up for its confidence
        ranked = recommend_songs(prefs, candidates, k=k + 1, mode=mode, diverse=diverse)
        for position, (song, score, explanation) in enumerate(ranked[:k]):
            matched = matched_by_id.get(song["id"], [])
            coverage = len(matched) / len(terms) if terms else None
            next_score = ranked[position + 1][1] if position + 1 < len(ranked) else None
            if matched:
                explanation = f"search match: {', '.join(matched)}; {explanation}"
            outcome.results.append(
                Ranked(song, score, explanation, confidence(score, next_score, coverage), matched, template_why(song, matched, index.glossary))
            )
        outcome.status = "ok"
        return outcome

    except InputError as error:
        outcome.status = "invalid_input"
        outcome.message = str(error)
        error_text = f"invalid input: {error}"
        return outcome
    except Exception as error:  # the app should show a message, not crash
        outcome.status = "error"
        outcome.message = "Something went wrong while searching. The details were written to the log."
        error_text = f"{type(error).__name__}: {error}"
        return outcome

    finally:
        outcome.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        top = outcome.top_confidence
        log_event(
            "search",
            level=logging.INFO if error_text is None else logging.WARNING if outcome.status == "invalid_input" else logging.ERROR,
            query=outcome.query,
            matched_words=sorted({word for r in outcome.results for word in r.matched_words}),
            via_glossary=sorted({word for r in outcome.results for word in r.matched_words if " (as " in word}),
            mode=mode,
            diverse=diverse,
            k=k if isinstance(k, int) else None,
            status=outcome.status,
            result_count=len(outcome.results),
            top_title=outcome.results[0].song["title"] if outcome.results else None,
            top_confidence=top.value if top else None,
            confidence_label=top.label if top else None,
            elapsed_ms=outcome.elapsed_ms,
            error=error_text,
        )
