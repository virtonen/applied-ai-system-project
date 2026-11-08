import pytest

from src.confidence import HIGH, MEDIUM, confidence, label_for
from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.pipeline import search
from src.recommender import load_songs
from src.retrieval import SongIndex


def test_value_is_always_between_zero_and_one():
    for score in (-0.5, 0.0, 0.5, 1.0, 1.7):
        for nxt in (None, 0.0, 0.5, 1.0):
            for cov in (None, 0.0, 0.5, 1.0):
                assert 0.0 <= confidence(score, nxt, cov).value <= 1.0


def test_a_stronger_score_gives_more_confidence():
    assert confidence(0.9, 0.5).value > confidence(0.5, 0.1).value


def test_a_bigger_lead_over_the_runner_up_gives_more_confidence():
    assert confidence(0.8, 0.4).value > confidence(0.8, 0.79).value


def test_matching_more_of_the_request_gives_more_confidence():
    assert confidence(0.8, 0.5, coverage=1.0).value > confidence(0.8, 0.5, coverage=0.33).value


def test_separation_is_full_when_nothing_ranks_below():
    assert confidence(0.8, None).separation == 1.0


def test_coverage_is_left_out_when_there_is_no_request():
    result = confidence(0.8, 0.5)
    assert result.coverage is None and "coverage n/a" in result.breakdown()
    # strength and separation only: (0.7 * 0.8 + 0.1 * 1.0) / 0.8
    assert result.value == pytest.approx(0.825)


def test_exact_value_with_all_three_signals():
    # 0.7 * 0.9 + 0.1 * 0.5 + 0.2 * 1.0 = 0.88
    assert confidence(0.9, 0.85, coverage=1.0).value == pytest.approx(0.88)


def test_labels_follow_the_thresholds():
    assert label_for(HIGH) == "High" and label_for(HIGH - 0.001) == "Medium"
    assert label_for(MEDIUM) == "Medium" and label_for(MEDIUM - 0.001) == "Low"


def test_two_excellent_songs_in_a_near_tie_still_have_high_confidence():
    assert confidence(0.97, 0.96).label == "High"


def test_a_clear_winner_with_a_poor_score_does_not_get_high_confidence():
    assert confidence(0.52, 0.30).label != "High"  # a clear lead cannot make up for a poor score
    assert confidence(0.52, 0.50).label == "Low"


def test_confidence_on_the_demo_profiles_matches_how_good_the_match_is():
    index = SongIndex(load_songs("data/songs.csv"))
    top = {name: search(index, "", prefs).top_confidence.label
           for name, prefs in {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}.items()}
    for name in ("High-Energy Pop", "Chill Lofi", "Deep Intense Rock", "Nostalgic Throwback", "Clean Workout"):
        assert top[name] == "High", name
    assert top["Conflicting: Sad but Energetic"] == "Medium"
    assert top["Extreme Targets"] == "Low"
