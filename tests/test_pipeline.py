import json
import logging

import pytest

import src.pipeline as pipeline
from src.main import STANDARD_PROFILES
from src.pipeline import search
from src.recommender import load_songs, recommend_songs
from src.retrieval import SongIndex

LOFI = STANDARD_PROFILES["Chill Lofi"]


@pytest.fixture(scope="module")
def index():
    return SongIndex(load_songs("data/songs.csv"))


def log_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# ----- behavior -----

def test_a_normal_search_is_ok_with_confidence_on_every_result(index):
    outcome = search(index, "", LOFI, k=5)
    assert outcome.status == "ok" and len(outcome.results) == 5
    assert all(0.0 <= r.confidence.value <= 1.0 for r in outcome.results)


def test_results_match_the_plain_ranking(index):
    plain = recommend_songs(LOFI, index.songs, k=5)
    outcome = search(index, "", LOFI, k=5)
    assert [r.song["title"] for r in outcome.results] == [s["title"] for s, _, _ in plain]
    assert [round(r.score, 6) for r in outcome.results] == [round(sc, 6) for _, sc, _ in plain]


def test_search_text_filters_and_records_the_matched_words(index):
    outcome = search(index, "cozy rainy study", LOFI)
    assert [r.song["title"] for r in outcome.results] == ["Library Rain", "Midnight Coding"]
    assert outcome.results[0].matched_words == ["cozy", "rainy", "study"]
    assert outcome.results[0].explanation.startswith("search match: cozy, rainy, study;")
    assert outcome.results[1].confidence.coverage == pytest.approx(2 / 3)


def test_nonsense_search_is_nothing_fits_not_a_crash(index):
    outcome = search(index, "xylophone zebra", LOFI)
    assert outcome.status == "nothing_fits" and outcome.results == [] and "xylophone zebra" in outcome.message


@pytest.mark.parametrize(
    "kwargs",
    [dict(query="x" * 500), dict(query=123), dict(k=0), dict(k="5"), dict(mode="nope"), dict(prefs={"energy": 9})],
)
def test_bad_input_returns_invalid_input_with_a_message(index, kwargs):
    args = dict(query="", prefs=LOFI, k=5, mode="balanced") | kwargs
    outcome = search(index, **args)
    assert outcome.status == "invalid_input" and outcome.message and outcome.results == []


def test_an_unexpected_failure_is_contained(index, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(pipeline, "recommend_songs", boom)
    outcome = search(index, "", LOFI)
    assert outcome.status == "error" and "log" in outcome.message and "exploded" not in outcome.message


def test_diversity_and_modes_still_work_through_the_pipeline(index):
    assert any("diversity penalty" in r.explanation for r in search(index, "study", LOFI, diverse=True).results)
    assert search(index, "", LOFI, mode="mood-first").status == "ok"


# ----- logging -----

def test_each_search_writes_one_json_line_with_the_key_fields(index, log_to_a_temporary_file):
    search(index, "cozy rainy study", LOFI, k=5, mode="genre-first", diverse=True)
    (entry,) = log_lines(log_to_a_temporary_file)
    assert entry["event"] == "search" and entry["status"] == "ok"
    assert entry["query"] == "cozy rainy study"
    assert entry["matched_words"] == ["cozy", "rainy", "study"]
    assert entry["mode"] == "genre-first" and entry["diverse"] is True and entry["k"] == 5
    assert entry["result_count"] == 2 and entry["top_title"] == "Library Rain"
    assert entry["confidence_label"] in ("High", "Medium", "Low") and entry["elapsed_ms"] >= 0
    assert entry["error"] is None and entry["ts"].endswith("+00:00")


def test_nothing_fits_is_logged_with_zero_results(index, log_to_a_temporary_file):
    search(index, "xylophone zebra", LOFI)
    (entry,) = log_lines(log_to_a_temporary_file)
    assert entry["status"] == "nothing_fits" and entry["result_count"] == 0 and entry["top_title"] is None


def test_invalid_input_is_logged_as_a_warning_with_the_reason(index, log_to_a_temporary_file):
    search(index, "", {"energy": 9})
    (entry,) = log_lines(log_to_a_temporary_file)
    assert entry["status"] == "invalid_input" and "'energy' must be between 0 and 1" in entry["error"]


def test_unexpected_errors_are_logged_with_the_exception(index, log_to_a_temporary_file, monkeypatch):
    monkeypatch.setattr(pipeline, "recommend_songs", lambda *a, **k: 1 / 0)
    search(index, "", LOFI)
    (entry,) = log_lines(log_to_a_temporary_file)
    assert entry["status"] == "error" and entry["error"].startswith("ZeroDivisionError")


def test_every_call_adds_a_line(index, log_to_a_temporary_file):
    for query in ("", "jazz", "xylophone zebra"):
        search(index, query, LOFI)
    assert len(log_lines(log_to_a_temporary_file)) == 3


def test_logging_to_an_unwritable_place_does_not_break_search(index, tmp_path):
    from src.logging_utils import configure_logging, log_event

    blocker = tmp_path / "a_file"
    blocker.write_text("x")
    assert configure_logging(blocker / "sub" / "x.log") is None  # parent is a file, cannot be created
    log_event("test", level=logging.INFO)  # must not raise
    assert search(index, "", LOFI).status == "ok"
