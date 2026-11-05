from collections import Counter

import pytest

from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.recommender import ARTIST_PENALTY, GENRE_PENALTY, load_songs, recommend_songs

USER = {"genre": "pop", "mood": "happy", "energy": 0.5}


def song(title, artist, genre, mood="happy", energy=0.5):
    return {"title": title, "artist": artist, "genre": genre, "mood": mood, "energy": energy}


def titles(results):
    return [s["title"] for s, _, _ in results]


def test_diverse_is_off_by_default():
    songs = [song("A1", "Same", "pop"), song("A2", "Same", "pop"), song("B", "Other", "rock", "sad", 0.4)]
    assert titles(recommend_songs(USER, songs, k=3)) == titles(recommend_songs(USER, songs, k=3, diverse=False))
    assert titles(recommend_songs(USER, songs, k=2)) == ["A1", "A2"]


def test_second_song_by_same_artist_is_penalized_and_pushed_down():
    songs = [
        song("A1", "Same", "pop"),
        song("A2", "Same", "pop"),                 # ties A1, but shares artist and genre
        song("B", "Other", "rock", "happy", 0.5),  # lower score, different artist and genre
    ]
    results = recommend_songs(USER, songs, k=3, diverse=True)
    assert titles(results) == ["A1", "B", "A2"]
    a2_score = dict((s["title"], sc) for s, sc, _ in results)["A2"]
    a1_score = dict((s["title"], sc) for s, sc, _ in results)["A1"]
    assert a1_score - a2_score == pytest.approx(ARTIST_PENALTY + GENRE_PENALTY)


def test_penalty_explains_itself():
    songs = [song("A1", "Same", "pop"), song("A2", "Same", "pop")]
    results = recommend_songs(USER, songs, k=2, diverse=True)
    first_reasons, second_reasons = results[0][2], results[1][2]
    assert "diversity" not in first_reasons
    assert "diversity penalty: artist Same already picked" in second_reasons
    assert "diversity penalty: genre pop already picked" in second_reasons


def test_no_penalty_when_everything_is_different():
    songs = [song("A", "X", "pop"), song("B", "Y", "rock"), song("C", "Z", "jazz")]
    plain = recommend_songs(USER, songs, k=3)
    diverse = recommend_songs(USER, songs, k=3, diverse=True)
    assert [round(sc, 6) for _, sc, _ in plain] == [round(sc, 6) for _, sc, _ in diverse]


def test_penalty_stacks_per_repeat():
    songs = [song("A1", "Same", "pop"), song("A2", "Same", "pop"), song("A3", "Same", "pop")]
    scores = [sc for _, sc, _ in recommend_songs(USER, songs, k=3, diverse=True)]
    one = ARTIST_PENALTY + GENRE_PENALTY
    assert scores[0] - scores[1] == pytest.approx(one)
    assert scores[0] - scores[2] == pytest.approx(2 * one)


def test_respects_k_and_small_catalogs():
    songs = [song("A", "X", "pop"), song("B", "Y", "rock")]
    assert len(recommend_songs(USER, songs, k=5, diverse=True)) == 2
    assert len(recommend_songs(USER, songs, k=1, diverse=True)) == 1
    assert recommend_songs(USER, [], k=3, diverse=True) == []


def test_scores_never_go_negative_and_never_exceed_the_plain_score():
    catalog = load_songs("data/songs.csv")
    for prefs in {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}.values():
        plain = {s["title"]: sc for s, sc, _ in recommend_songs(prefs, catalog, k=len(catalog))}
        for s, sc, _ in recommend_songs(prefs, catalog, k=len(catalog), diverse=True):
            assert 0.0 <= sc <= plain[s["title"]] + 1e-9


def test_real_catalog_has_fewer_repeats_with_diversity_on():
    catalog = load_songs("data/songs.csv")

    def repeats(results, field):
        counts = Counter(s[field] for s, _, _ in results)
        return sum(n - 1 for n in counts.values())

    profiles = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}.values()
    for field in ("artist", "genre"):
        before = sum(repeats(recommend_songs(p, catalog), field) for p in profiles)
        after = sum(repeats(recommend_songs(p, catalog, diverse=True), field) for p in profiles)
        assert after < before


def test_chill_lofi_no_longer_gets_two_songs_from_one_artist():
    catalog = load_songs("data/songs.csv")
    prefs = STANDARD_PROFILES["Chill Lofi"]
    plain = Counter(s["artist"] for s, _, _ in recommend_songs(prefs, catalog))
    diverse = Counter(s["artist"] for s, _, _ in recommend_songs(prefs, catalog, diverse=True))
    assert plain["LoRoom"] == 2
    assert diverse["LoRoom"] == 1
