import json

import pytest

import src.agent as agent_module
from src.agent import (
    MAX_RETRIES,
    MIN_MODE_GAIN,
    TRACES_END,
    TRACES_START,
    Context,
    Request,
    best_attempt,
    critique,
    example_cases,
    plan_text,
    record_examples,
    run_agent,
)
from src.glossary import Glossary
from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.pipeline import SearchOutcome, search
from src.recommender import load_songs
from src.retrieval import SongIndex

PROFILES = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}
LOFI = PROFILES["Chill Lofi"]
EXTREME = PROFILES["Extreme Targets"]


@pytest.fixture(scope="module")
def index():
    return SongIndex(load_songs("data/songs.csv"), Glossary.load())


def titles(result):
    return [r.song["title"] for r in result.outcome.results]


def labels(result):
    return [label.split()[0] for label, _ in result.trace]


def always(status, message=""):
    """A stand-in for search() that returns the same status every time, and counts its calls."""
    calls = []

    def searcher(index, query, prefs, k=5, mode="balanced", diverse=False):
        calls.append((query, mode))
        return SearchOutcome(status=status, message=message, query=query)

    searcher.calls = calls
    return searcher


# ----- the term counts the critique uses -----

def test_term_hits_counts_the_songs_each_word_matches(index):
    assert index.term_hits("jazz zebra") == [("jazz", 1), ("zebra", 0)]
    assert index.term_hits("the and of") == [] and index.term_hits("") == []
    assert dict(index.term_hits("mellow homework"))["homework"] == 3  # through the glossary


# ----- the critique -----

def test_critique_tells_the_four_situations_apart(index):
    good = search(index, "cozy rainy study", LOFI)
    low = search(index, "", EXTREME)
    nothing = search(index, "jazz zebra", LOFI)
    invalid = search(index, "", {"energy": 9})
    assert critique(good, [])[0] == "good" and critique(low, [])[0] == "low"
    kind, text = critique(nothing, index.term_hits("jazz zebra"))
    assert kind == "nothing_fits" and "jazz 1, zebra 0" in text
    kind, text = critique(invalid, [])
    assert kind == "stop" and "energy" in text
    assert critique(search(index, "the and of", LOFI), [])[1].endswith("no usable words.")


# ----- each strategy -----

def test_a_word_that_matches_no_song_is_dropped(index):
    result = run_agent(index, "jazz zebra", LOFI)
    assert result.status == "recovered" and result.retries == 1
    assert result.final.query == "jazz" and result.original.query == "jazz zebra"
    assert titles(result) == ["Coffee Shop Stories"] and result.changes == ['dropped "zebra"']
    assert result.request_changed and len(result.attempts) == 2
    assert labels(result) == ["PLAN", "ACT", "CHECK", "REVISE", "ACT", "CHECK", "DECIDE"]
    assert 'Answered "jazz" instead of "jazz zebra"' in result.trace[-1][1]


def test_when_every_word_is_dead_the_agent_ranks_by_preferences_alone(index):
    result = run_agent(index, "xylophone zebra", LOFI)
    assert result.status == "recovered" and result.final.query == "" and len(titles(result)) == 5
    assert "Answered using the preferences alone" in result.trace[-1][1]


def test_stopword_only_requests_are_handled_the_same_way(index):
    result = run_agent(index, "the and of", LOFI)
    assert result.final.query == "" and result.outcome.status == "ok"
    assert "no usable words" in next(text for label, text in result.trace if label == "CHECK")


def test_words_that_never_appear_together_keep_the_strongest_word(index):
    result = run_agent(index, "jazz metal", LOFI)
    assert result.final.query == "jazz" and result.changes == ['kept only "jazz"']


def test_a_stronger_word_wins_over_a_weaker_one():
    songs = load_songs("data/songs.csv")
    index = SongIndex(songs)  # no glossary: "study" matches 3 songs, "metal" matches 1, and none match both
    result = run_agent(index, "study metal", LOFI)
    assert result.final.query == "study" and len(titles(result)) == 3


def test_low_confidence_tries_the_other_scoring_modes_and_keeps_the_best(index):
    result = run_agent(index, "", EXTREME)
    assert result.status == "improved" and result.final.mode == "mood-first" and result.retries == 1
    assert result.outcome.top_confidence.label == "Medium" and result.attempts[0].outcome.top_confidence.label == "Low"
    revise = dict(result.trace)["REVISE"]
    assert all(mode in revise for mode in ("genre-first", "mood-first", "energy-focused")) and "catalog" in revise
    assert result.original.mode == "balanced"


def test_optional_preferences_are_relaxed_before_modes_are_tried(index):
    prefs = {**EXTREME, "instrumentalness": 1.0, "decade": 2020}
    assert search(index, "", prefs).top_confidence.label == "Low"
    result = run_agent(index, "", prefs)
    revisions = [text for label, text in result.trace if label == "REVISE"]
    assert revisions[0].startswith("the optional preferences (decade, instrumentalness)")
    assert not any(key in result.attempts[1].request.prefs for key in ("decade", "instrumentalness"))
    assert "genre" in result.attempts[1].request.prefs  # the core preferences are never dropped
    assert result.attempts[1].outcome.top_confidence.label == "Low"  # still Low, so it went on to the modes
    assert result.retries == 2 and result.final.mode == "mood-first" and result.status == "improved"


def test_a_mode_must_beat_the_current_confidence_by_a_margin(index, monkeypatch):
    low = search(index, "", EXTREME)
    ctx = Context(index, Request("", EXTREME), low, search)
    assert agent_module.best_other_mode(ctx) is not None
    monkeypatch.setattr(agent_module, "MIN_MODE_GAIN", 1.0)  # nothing can beat it by that much
    assert agent_module.best_other_mode(ctx) is None
    assert 0 < MIN_MODE_GAIN < 0.2


# ----- when it does not retry -----

def test_a_good_first_result_is_left_alone(index):
    result = run_agent(index, "cozy rainy study", LOFI)
    assert result.status == "first_try" and result.retries == 0 and len(result.attempts) == 1
    assert not result.request_changed and "REVISE" not in labels(result)
    plain = search(index, "cozy rainy study", LOFI)
    assert [r.song["title"] for r in result.outcome.results] == [r.song["title"] for r in plain.results]


def test_invalid_input_is_never_retried_and_never_reworded(index):
    result = run_agent(index, "jazz zebra", {**LOFI, "energy": 9})
    assert result.status == "stopped" and result.retries == 0 and len(result.attempts) == 1
    assert result.outcome.status == "invalid_input" and "cannot be fixed by rewording" in dict(result.trace)["CHECK"]
    assert result.final == result.original


def test_an_unexpected_error_is_not_retried():
    stub = always("error", "Something went wrong while searching.")
    result = run_agent(SongIndex(load_songs("data/songs.csv")), "jazz", LOFI, searcher=stub)
    assert result.status == "stopped" and len(stub.calls) == 1


def test_bad_arguments_do_not_crash_the_agent(index):
    result = run_agent(index, None, "not a dict")
    assert result.outcome.status == "invalid_input" and result.status == "stopped"


# ----- the loop is bounded -----

def test_it_never_retries_more_than_the_limit(index):
    stub = always("nothing_fits", "nothing")
    result = run_agent(index, "jazz zebra metal", LOFI, searcher=stub)
    assert result.retries == MAX_RETRIES == 3 and len(stub.calls) == 4 and len(result.attempts) == 4
    assert "retry budget (3) is used up" in result.stopped_because and result.status == "gave_up"
    assert result.final == result.original and "none of the retries found any songs" in result.trace[-1][1]
    assert [a.change for a in result.attempts[1:]] == ['dropped "zebra"', 'kept only "jazz"', "ignored the typed request"]


def test_the_limit_can_be_lowered(index):
    stub = always("nothing_fits")
    result = run_agent(index, "jazz zebra metal", LOFI, max_retries=1, searcher=stub)
    assert result.retries == 1 and len(stub.calls) == 2


def test_it_stops_when_no_strategy_applies(index):
    stub = always("nothing_fits")
    result = run_agent(index, "", LOFI, searcher=stub)  # no request words, so nothing to reword
    assert result.retries == 0 and "no strategy is left" in result.stopped_because and result.status == "gave_up"


def test_a_strategy_is_never_used_twice(index):
    stub = always("nothing_fits")
    result = run_agent(index, "jazz zebra metal xylophone", LOFI, searcher=stub)
    changes = [a.change for a in result.attempts[1:]]
    assert len(changes) == len(set(changes))


def test_low_confidence_that_nothing_can_fix_is_reported_honestly(index):
    result = run_agent(index, "", EXTREME, max_retries=0)
    assert result.status == "gave_up" and result.retries == 0 and result.outcome.top_confidence.label == "Low"
    assert "retry budget (0)" in result.stopped_because and "nothing could be improved" in result.trace[-1][1]


def test_the_best_attempt_wins_not_just_the_last_one(index):
    result = run_agent(index, "", EXTREME)
    assert best_attempt(result.attempts) is result.attempts[-1]
    worse_last = list(result.attempts)[::-1]  # put the better attempt first and the worse one last
    assert best_attempt(worse_last) is worse_last[0]


# ----- the trace -----

def test_the_same_request_gives_the_same_trace(index):
    assert run_agent(index, "jazz zebra", LOFI).trace_text() == run_agent(index, "jazz zebra", LOFI).trace_text()


def test_the_trace_names_every_step_and_wraps_to_a_readable_width(index):
    result = run_agent(index, "jazz zebra", LOFI)
    text = result.trace_text()
    assert text.startswith("PLAN    search as typed.") and plan_text(3) in " ".join(text.split())
    assert all(len(line) <= 100 for line in text.splitlines())
    assert 'ACT 0   search("jazz zebra", mode=balanced) -> nothing_fits' in text


def test_the_agent_is_logged(index, log_to_a_temporary_file):
    run_agent(index, "jazz zebra", LOFI)
    entries = [json.loads(line) for line in log_to_a_temporary_file.read_text().splitlines()]
    entry = next(e for e in entries if e["event"] == "agent")
    assert entry["original_query"] == "jazz zebra" and entry["final_query"] == "jazz"
    assert entry["retries"] == 1 and entry["status"] == "recovered" and entry["strategies"] == ['dropped "zebra"']
    assert entry["final_confidence"] > 0.8 and entry["confidence_label"] == "High" and entry["final_status"] == "ok"


# ----- the saved traces -----

def test_record_examples_writes_a_block_and_keeps_the_rest(index, tmp_path):
    target = tmp_path / "log.md"
    target.write_text(f"before\n\n{TRACES_START}\nOLD\n{TRACES_END}\n\nafter\n")
    block = record_examples(target, index)
    text = target.read_text()
    assert text.startswith("before\n") and text.endswith("after\n") and "OLD" not in text
    assert all(title in text for title, *_ in example_cases())
    assert text.count(TRACES_START) == 1 and block in text
    record_examples(target, index)
    assert target.read_text() == text  # running twice changes nothing


def test_record_examples_adds_the_block_when_the_markers_are_missing(index, tmp_path):
    target = tmp_path / "new.md"
    target.write_text("# Notes\n")
    record_examples(target, index)
    assert target.read_text().startswith("# Notes\n") and TRACES_START in target.read_text()


def test_the_traces_saved_in_ai_interactions_are_the_real_ones(index, tmp_path):
    """If the agent changes, ai_interactions.md must be regenerated with: python -m src.agent --record-examples"""
    from pathlib import Path

    committed = Path("ai_interactions.md").read_text()
    fresh = record_examples(tmp_path / "x.md", index)
    assert fresh in committed


def test_the_command_writes_the_traces(tmp_path, capsys):
    out = tmp_path / "t.md"
    assert agent_module.main(["--record-examples", "--out", str(out)]) == 0
    assert "Traces written" in capsys.readouterr().out and TRACES_START in out.read_text()
    assert agent_module.main([]) == 2  # no action given


def test_a_strategy_that_keeps_applying_is_still_used_only_once(index):
    """Every search looks a little better than the last one, so comparing modes would always find a 'gain'."""
    from dataclasses import replace

    from src.confidence import confidence

    base = search(index, "", EXTREME)
    counter = {"n": 0}

    def improving(index_, query, prefs, k=5, mode="balanced", diverse=False):
        counter["n"] += 1
        score = 0.10 + 0.03 * counter["n"]  # always Low, always higher than the call before
        top = replace(base.results[0], score=score, confidence=confidence(score, None, None))
        return SearchOutcome(status="ok", results=[top], query=query)

    result = run_agent(index, "", EXTREME, searcher=improving)
    mode_changes = [a.change for a in result.attempts if a.change.startswith("scoring mode")]
    assert len(mode_changes) == 1 and result.retries == 1
    assert "no strategy is left that applies" in result.stopped_because
