import pytest

from src.recommender import load_songs
from src.retrieval import (
    MIN_MATCHED_WORDS,
    SongIndex,
    query_terms,
    search_and_rank,
    song_to_text,
    stem,
    tokenize,
)

PREFS = {"genre": "lofi", "mood": "chill", "energy": 0.4, "valence": 0.6, "acousticness": 0.8}


@pytest.fixture(scope="module")
def songs():
    return load_songs("data/songs.csv")


@pytest.fixture(scope="module")
def index(songs):
    return SongIndex(songs)


def titles(hits):
    return [song["title"] for song, *_ in hits]


# ----- tokenizer, stopwords and stemming -----

def test_stemming_joins_word_forms():
    assert stem("studying") == stem("study") == "stud"
    assert stem("rainy") == stem("rain") == "rain"
    assert stem("cozy") == "cozy"  # too short to strip


def test_tokenize_drops_stopwords_and_punctuation():
    assert tokenize("Play some music for the Rainy day!") == ["rain", "day"]


def test_query_terms_remember_the_original_word():
    assert query_terms("cozy rainy study") == {"cozy": "cozy", "rain": "rainy", "stud": "study"}


def test_song_to_text_has_the_labels_tags_and_vibe_words(songs):
    text = song_to_text(next(s for s in songs if s["title"] == "Library Rain"))
    for word in ("Library Rain", "Paper Lanterns", "lofi", "chill", "rainy", "cozy", "study", "calm", "acoustic", "instrumental"):
        assert word in text


# ----- expected hits per query -----

def test_vibe_query_finds_the_songs_with_those_tags(index):
    hits = index.retrieve("cozy rainy study")
    assert titles(hits) == ["Library Rain", "Midnight Coding"]  # best match first
    assert hits[0][1] == ["cozy", "rainy", "study"]
    assert hits[1][1] == ["cozy", "study"]


def test_single_word_queries_need_only_one_match(index):
    assert titles(index.retrieve("jazz")) == ["Coffee Shop Stories"]
    assert titles(index.retrieve("nostalgic")) == ["Dust Road Home"]


def test_artist_names_are_searchable_and_case_does_not_matter(index):
    assert titles(index.retrieve("LoRoom")) == ["Midnight Coding", "Focus Flow"]


def test_vibe_words_made_from_numbers_are_searchable(index):
    assert "Gym Hero" in titles(index.retrieve("energetic popular"))
    assert "Birchwood Lullaby" in titles(index.retrieve("calm acoustic"))


def test_filler_words_do_not_change_the_hits(index):
    assert titles(index.retrieve("play me some cozy rainy study music")) == titles(index.retrieve("cozy rainy study"))


def test_results_are_deterministic_and_keep_catalog_order_on_ties(index):
    first = titles(index.retrieve("calm acoustic"))
    assert first == titles(index.retrieve("calm acoustic"))
    assert first == ["Library Rain", "Spacewalk Thoughts", "Focus Flow", "Adagio for Rain", "Birchwood Lullaby"]


# ----- the guardrail -----

@pytest.mark.parametrize("nonsense", ["xylophone zebra", "qwertyuiop", "the and of", "!!! ???", "jazz zebra"])
def test_guardrail_returns_nothing_for_nonsense_or_too_little_overlap(index, nonsense):
    assert index.retrieve(nonsense) == []


def test_guardrail_needs_the_minimum_number_of_matched_words(index):
    # "study" alone matches Focus Flow, but with two other unknown words it must not
    assert MIN_MATCHED_WORDS == 2
    assert "Focus Flow" in titles(index.retrieve("study"))
    assert index.retrieve("study zebra giraffe") == []
    for _, matched in index.retrieve("cozy rainy study"):
        assert len(matched) >= MIN_MATCHED_WORDS


# ----- retrieve, then rank with score_song -----

def test_search_ranks_only_the_retrieved_songs(index):
    results = search_and_rank(index, "cozy rainy study", PREFS)
    assert [song["title"] for song, _, _ in results] == ["Library Rain", "Midnight Coding"]


def test_ranking_among_hits_follows_the_sliders(index):
    # Both songs are hits. Energy 0.35 is closer to Library Rain, 0.42 to Midnight Coding.
    low = search_and_rank(index, "cozy study", {**PREFS, "energy": 0.0, "genre": "x", "mood": "x"})
    high = search_and_rank(index, "cozy study", {**PREFS, "energy": 0.6, "genre": "x", "mood": "x"})
    assert [s["title"] for s, _, _ in low][0] == "Library Rain"
    assert [s["title"] for s, _, _ in high][0] == "Midnight Coding"


def test_explanations_start_with_the_matched_words(index):
    results = search_and_rank(index, "cozy rainy study", PREFS)
    assert results[0][2].startswith("search match: cozy, rainy, study; ")
    assert "genre match: lofi" in results[0][2]


def test_nonsense_search_gives_an_empty_list(index):
    assert search_and_rank(index, "xylophone zebra", PREFS) == []


def test_blank_search_ranks_the_whole_catalog(index, songs):
    results = search_and_rank(index, "   ", PREFS, k=len(songs))
    assert len(results) == len(songs)
    assert not any(e.startswith("search match") for _, _, e in results)


def test_k_mode_and_diversity_still_work_with_search(index):
    assert len(search_and_rank(index, "calm acoustic", PREFS, k=3)) == 3
    plain = search_and_rank(index, "study", PREFS, mode="mood-first")
    assert plain  # every mode accepts a search
    diverse = search_and_rank(index, "study", PREFS, diverse=True)
    assert any("diversity penalty" in e for _, _, e in diverse)
