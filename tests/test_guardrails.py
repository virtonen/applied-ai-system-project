import pytest

from src.guardrails import (
    CSV_COLUMNS,
    MAX_K,
    MAX_QUERY_LENGTH,
    DataError,
    GuardrailError,
    InputError,
    validate_k,
    validate_prefs,
    validate_query,
)
from src.recommender import load_songs

HEADER = ",".join(CSV_COLUMNS)
GOOD_ROW = "1,Sunrise City,Neon Echo,pop,happy,0.82,118,0.84,0.79,0.18,82,2020,bright|upbeat,0.02,0"


def write_csv(tmp_path, *lines):
    path = tmp_path / "songs.csv"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return str(path)


def replace_field(row, column, value):
    parts = row.split(",")
    parts[CSV_COLUMNS.index(column)] = value
    return ",".join(parts)


# ----- the song file -----

def test_the_real_song_file_loads():
    songs = load_songs("data/songs.csv")
    assert len(songs) == 18 and isinstance(songs[0]["explicit"], bool) and songs[0]["mood_tags"][0] == "bright"


def test_a_minimal_valid_file_loads(tmp_path):
    assert load_songs(write_csv(tmp_path, HEADER, GOOD_ROW))[0]["title"] == "Sunrise City"


def test_missing_file_gives_a_clear_error(tmp_path):
    with pytest.raises(DataError, match="not found"):
        load_songs(str(tmp_path / "nope.csv"))


def test_completely_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    with pytest.raises(DataError, match="empty"):
        load_songs(str(path))


def test_header_only_file_has_no_songs(tmp_path):
    with pytest.raises(DataError, match="no songs"):
        load_songs(write_csv(tmp_path, HEADER))


def test_missing_columns_are_named(tmp_path):
    header = ",".join(c for c in CSV_COLUMNS if c not in ("energy", "mood_tags"))
    with pytest.raises(DataError, match="energy, mood_tags"):
        load_songs(write_csv(tmp_path, header, GOOD_ROW))


@pytest.mark.parametrize(
    "column, value, message",
    [
        ("energy", "loud", "'energy' must be a number"),
        ("energy", "1.5", "'energy' must be between 0 and 1"),
        ("valence", "nan", "finite"),
        ("popularity", "101", "'popularity' must be between 0 and 100"),
        ("popularity", "high", "'popularity' must be a whole number"),
        ("tempo_bpm", "0", "'tempo_bpm' must be above 0"),
        ("explicit", "yes", "'explicit' must be 0 or 1"),
        ("genre", " ", "'genre' is blank"),
    ],
)
def test_bad_values_name_the_line_and_the_column(tmp_path, column, value, message):
    path = write_csv(tmp_path, HEADER, GOOD_ROW, replace_field(GOOD_ROW.replace("1,Sunrise", "2,Sunrise"), column, value))
    with pytest.raises(DataError, match=f"Line 3: .*{message}"):
        load_songs(path)


def test_a_short_row_is_rejected(tmp_path):
    with pytest.raises(DataError, match="Line 2: no value for"):
        load_songs(write_csv(tmp_path, HEADER, "1,Sunrise City,Neon Echo"))


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(DataError, match="duplicate id 1"):
        load_songs(write_csv(tmp_path, HEADER, GOOD_ROW, GOOD_ROW))


def test_data_errors_are_guardrail_errors_and_value_errors():
    assert issubclass(DataError, GuardrailError) and issubclass(InputError, ValueError)


# ----- user input -----

def test_query_is_cleaned():
    assert validate_query("  cozy \t rainy\nstudy\x00 ") == "cozy rainy study"
    assert validate_query(None) == "" and validate_query("") == ""


def test_query_rejects_wrong_types_and_huge_text():
    with pytest.raises(InputError, match="must be text"):
        validate_query(42)
    with pytest.raises(InputError, match="too long"):
        validate_query("a" * (MAX_QUERY_LENGTH + 1))
    assert validate_query("a" * MAX_QUERY_LENGTH)


def test_k_must_be_a_sensible_whole_number():
    assert validate_k(5) == 5 and validate_k(MAX_K) == MAX_K
    for bad in (0, -1, MAX_K + 1, 2.5, "5", True, None):
        with pytest.raises(InputError):
            validate_k(bad)


def test_good_preferences_pass_and_are_copied():
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.5, "popularity": 90, "decade": 2010, "mood_tags": ["cozy"]}
    cleaned = validate_prefs(prefs)
    assert cleaned == prefs and cleaned is not prefs
    assert validate_prefs({}) == {}


@pytest.mark.parametrize(
    "prefs, message",
    [
        ({"energy": 1.2}, "'energy' must be between 0 and 1"),
        ({"energy": "high"}, "'energy' must be a number"),
        ({"energy": True}, "'energy' must be a number"),
        ({"valence": float("nan")}, "'valence' must be a number"),
        ({"popularity": -5}, "'popularity' must be between 0 and 100"),
        ({"decade": 1066}, "'decade' must be between"),
        ({"genre": 7}, "'genre' must be text"),
        ({"mood_tags": "cozy"}, "'mood_tags' must be a list"),
        ({"mood_tags": ["cozy", 3]}, "'mood_tags' must be a list"),
        ("not a dict", "must be a dictionary"),
    ],
)
def test_bad_preferences_are_rejected_with_a_reason(prefs, message):
    with pytest.raises(InputError, match=message):
        validate_prefs(prefs)
