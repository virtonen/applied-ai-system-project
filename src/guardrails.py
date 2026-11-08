"""
Guardrails: check user input and song data, and fail with a clear message instead of a crash.

DataError means the song file is bad. InputError means the user's request is bad. Both are
ValueErrors, so a caller can catch them (or GuardrailError) and show the message.
"""

import math
import re
from typing import Any, Dict, Optional, Sequence

MAX_QUERY_LENGTH = 200
MAX_K = 50

CSV_COLUMNS = (
    "id", "title", "artist", "genre", "mood", "energy", "tempo_bpm", "valence",
    "danceability", "acousticness", "popularity", "release_decade", "mood_tags",
    "instrumentalness", "explicit",
)
INT_COLUMNS = ("id", "popularity", "release_decade")
FLOAT_COLUMNS = ("energy", "tempo_bpm", "valence", "danceability", "acousticness", "instrumentalness")
UNIT_COLUMNS = ("energy", "valence", "acousticness", "danceability", "instrumentalness")  # 0 to 1
TEXT_COLUMNS = ("title", "artist", "genre", "mood")

# Preference ranges: key -> (low, high)
PREF_RANGES = {
    "energy": (0.0, 1.0),
    "valence": (0.0, 1.0),
    "acousticness": (0.0, 1.0),
    "instrumentalness": (0.0, 1.0),
    "popularity": (0.0, 100.0),
    "decade": (1900, 2100),
}


class GuardrailError(ValueError):
    """Base class for guardrail failures."""


class DataError(GuardrailError):
    """The song data is missing, empty or malformed."""


class InputError(GuardrailError):
    """The user's request is malformed or out of range."""


# ----- user input -----

def validate_query(query: Any) -> str:
    """Return the search text with control characters and extra spaces removed."""
    if query is None:
        return ""
    if not isinstance(query, str):
        raise InputError("Search text must be text.")
    cleaned = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", query).split())
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise InputError(f"Search text is too long ({len(cleaned)} characters, the limit is {MAX_QUERY_LENGTH}).")
    return cleaned


def validate_k(k: Any) -> int:
    """Return k if it is a whole number from 1 to MAX_K."""
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise InputError(f"The number of songs must be a whole number from 1 to {MAX_K}.")
    return k


def validate_prefs(prefs: Any) -> Dict:
    """Return a copy of the preferences if every value present has a sensible type and range."""
    if not isinstance(prefs, dict):
        raise InputError("Preferences must be a dictionary.")

    for key, (low, high) in PREF_RANGES.items():
        if key not in prefs:
            continue
        value = prefs[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InputError(f"'{key}' must be a number.")
        if not low <= value <= high:
            raise InputError(f"'{key}' must be between {low:g} and {high:g}, not {value:g}.")

    for key in ("genre", "mood"):
        if key in prefs and not isinstance(prefs[key], str):
            raise InputError(f"'{key}' must be text.")

    tags = prefs.get("mood_tags", [])
    if not isinstance(tags, (list, tuple)) or not all(isinstance(t, str) for t in tags):
        raise InputError("'mood_tags' must be a list of text tags.")

    return dict(prefs)


# ----- song data -----

def check_columns(fieldnames: Optional[Sequence[str]]) -> None:
    """Raise DataError if the CSV header is missing or lacks a required column."""
    if not fieldnames:
        raise DataError("The song file is empty (it has no header row).")
    missing = [column for column in CSV_COLUMNS if column not in fieldnames]
    if missing:
        raise DataError(f"The song file is missing required column(s): {', '.join(missing)}.")


def parse_song_row(row: Dict[str, Any], line: int) -> Dict:
    """Convert one CSV row to typed values, or raise DataError naming the line and the problem."""
    song = {key: value for key, value in row.items() if key is not None}

    for column in CSV_COLUMNS:
        if song.get(column) is None:
            raise DataError(f"Line {line}: no value for '{column}'.")

    for column in TEXT_COLUMNS:
        if not song[column].strip():
            raise DataError(f"Line {line}: '{column}' is blank.")

    for column in INT_COLUMNS:
        try:
            song[column] = int(song[column])
        except ValueError:
            raise DataError(f"Line {line}: '{column}' must be a whole number, not '{song[column]}'.") from None

    for column in FLOAT_COLUMNS:
        try:
            song[column] = float(song[column])
        except ValueError:
            raise DataError(f"Line {line}: '{column}' must be a number, not '{song[column]}'.") from None
        if not math.isfinite(song[column]):
            raise DataError(f"Line {line}: '{column}' must be a finite number.")

    for column in UNIT_COLUMNS:
        if not 0.0 <= song[column] <= 1.0:
            raise DataError(f"Line {line}: '{column}' must be between 0 and 1, not {song[column]:g}.")
    if not 0 <= song["popularity"] <= 100:
        raise DataError(f"Line {line}: 'popularity' must be between 0 and 100, not {song['popularity']}.")
    if song["tempo_bpm"] <= 0:
        raise DataError(f"Line {line}: 'tempo_bpm' must be above 0.")

    if song["explicit"] not in ("0", "1"):
        raise DataError(f"Line {line}: 'explicit' must be 0 or 1, not '{song['explicit']}'.")
    song["explicit"] = song["explicit"] == "1"

    song["mood_tags"] = [tag.strip() for tag in song["mood_tags"].split("|") if tag.strip()]
    return song
