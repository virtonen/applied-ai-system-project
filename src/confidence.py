"""
Confidence score for a recommendation, from 0 to 1.

It combines three signals, each from 0 to 1:
  strength    how high the song's score is
  separation  how far it is ahead of the next song (a clear winner is more trustworthy)
  coverage    the share of the typed request's words that the song matched

confidence = 0.7 * strength + 0.1 * separation + 0.2 * coverage

With no typed request, coverage does not apply, so only strength and separation are used
(their weights are scaled up to add to 1). Strength dominates on purpose: two excellent songs
that nearly tie should still give high confidence, and a clear winner with a poor score should not.
"""

from dataclasses import dataclass
from typing import Optional

STRENGTH_WEIGHT = 0.7
SEPARATION_WEIGHT = 0.1
COVERAGE_WEIGHT = 0.2
GAP_FOR_FULL_SEPARATION = 0.10  # a lead of 0.10 or more counts as fully separated

HIGH = 0.80    # at or above: "High"
MEDIUM = 0.55  # at or above: "Medium", below: "Low"


@dataclass(frozen=True)
class Confidence:
    value: float
    label: str
    strength: float
    separation: float
    coverage: Optional[float]  # None when there was no typed request

    def breakdown(self) -> str:
        coverage = "n/a" if self.coverage is None else f"{self.coverage:.2f}"
        return f"strength {self.strength:.2f}, separation {self.separation:.2f}, coverage {coverage}"


def label_for(value: float) -> str:
    if value >= HIGH:
        return "High"
    if value >= MEDIUM:
        return "Medium"
    return "Low"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def confidence(score: float, next_score: Optional[float] = None, coverage: Optional[float] = None) -> Confidence:
    """
    Confidence for one result. `next_score` is the score of the song ranked just below it
    (None if there is none). `coverage` is the share of request words matched (None if no request).
    """
    strength = _clamp(score)
    if next_score is None:  # nothing ranked below it, so nothing competes with it
        separation = 1.0
    else:
        separation = _clamp((score - next_score) / GAP_FOR_FULL_SEPARATION)

    total = STRENGTH_WEIGHT * strength + SEPARATION_WEIGHT * separation
    weight = STRENGTH_WEIGHT + SEPARATION_WEIGHT
    if coverage is not None:
        coverage = _clamp(coverage)
        total += COVERAGE_WEIGHT * coverage
        weight += COVERAGE_WEIGHT
    value = total / weight
    return Confidence(round(value, 4), label_for(value), strength, separation, coverage)
