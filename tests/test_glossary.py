import json
import re

import pytest

from src.explain import allowed_vocabulary, build_prompt, explain_with_ai, facts_text, template_why, validate_explanation
from src.glossary import DEFAULT_FOLDER, Glossary, parse_entries, split_into_chunks
from src.main import STANDARD_PROFILES
from src.pipeline import search
from src.recommender import load_songs
from src.retrieval import SongIndex

DOC = """# Title that is not an entry

## Calm Thing
Related words: quiet, still, laid-back, two words, ok
A calm thing is slow.
It has a second line.

## No Description
Related words: nothing

```
## fenced heading
Related words: fake
Not an entry.
```

### a smaller heading
Ignored.
"""


@pytest.fixture(scope="module")
def songs():
    return load_songs("data/songs.csv")


@pytest.fixture(scope="module")
def glossary():
    return Glossary.load()


@pytest.fixture(scope="module")
def rich(songs, glossary):
    return SongIndex(songs, glossary)


@pytest.fixture(scope="module")
def plain(songs):
    return SongIndex(songs)


def song(songs, title):
    return next(s for s in songs if s["title"] == title)


def titles(hits):
    return [s["title"] for s, _ in hits]


# ----- the documents -----

def test_chunks_split_at_headings_and_ignore_headings_inside_code_fences():
    chunks = split_into_chunks(DOC)
    assert len(chunks) == 4 and any("fenced heading" in c for c in chunks)
    assert not any(c.startswith("## fenced") for c in chunks)


def test_entries_keep_the_term_single_related_words_and_the_whole_description():
    (entry,) = parse_entries(DOC, "doc.md")  # the fenced block under "No Description" does not make it an entry
    assert entry.term == "calm thing" and entry.source == "doc.md"
    assert entry.related == ("quiet", "still", "ok")  # "laid-back" and "two words" are not single words
    assert entry.text == "A calm thing is slow. It has a second line."


def test_the_real_glossary_loads_every_entry_once(glossary):
    assert len(glossary) == 45
    terms = [e.term for e in glossary.entries]
    assert len(terms) == len(set(terms))
    assert {e.source for e in glossary.entries} == {"genres.md", "moods.md", "vibes.md"}  # the format notes are not entries


def test_every_genre_and_mood_in_the_catalog_has_an_entry(songs, glossary):
    assert {s["genre"] for s in songs} <= set(glossary.by_term)
    assert {s["mood"] for s in songs} <= set(glossary.by_term)


def test_entries_are_well_formed(glossary):
    for entry in glossary.entries:
        assert entry.text.endswith("."), entry.term
        assert entry.related and all(re.fullmatch(r"[a-z0-9]+", w) for w in entry.related), entry.term


def test_a_missing_or_empty_folder_gives_an_empty_glossary_and_a_log_line(tmp_path, log_to_a_temporary_file):
    assert len(Glossary.load(tmp_path / "nope")) == 0
    (tmp_path / "empty").mkdir()
    assert len(Glossary.load(tmp_path / "empty")) == 0
    events = [json.loads(line) for line in log_to_a_temporary_file.read_text().splitlines()]
    assert [e["event"] for e in events] == ["load_glossary", "load_glossary"] and all(e["error"] for e in events)


def test_the_folder_can_be_changed_with_an_environment_variable(tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text(DOC)
    monkeypatch.setenv("VIBEMATCH_GLOSSARY", str(tmp_path))
    assert [e.term for e in Glossary.load().entries] == ["calm thing"]


# ----- expansion -----

def test_expand_gives_the_term_and_related_words_but_not_the_word_itself(glossary):
    shown = [text for _, text in glossary.expand("mellow")]
    assert {"chill", "relaxed", "calm"} <= set(shown) and "mellow" not in shown
    assert glossary.expand("xylophone") == []


def test_a_multi_word_term_only_counts_as_a_whole_phrase(glossary):
    options = dict((text, stems) for stems, text in glossary.expand("indie"))
    assert len(options["indie pop"]) == 2           # both words must be present
    assert glossary.expand("pop")                   # "pop" has its own entry...
    assert "indie pop" not in [t for _, t in glossary.expand("pop")]  # ...but does not expand to indie pop


# ----- retrieval: before and after -----

@pytest.mark.parametrize(
    "query, expected",
    [
        ("mellow homework", {"Library Rain", "Midnight Coding", "Focus Flow"}),
        ("rnb groove", {"Velvet Hours"}),
        ("catchy upbeat", {"Sunrise City", "Gym Hero"}),
        ("gym loud", {"Gym Hero"}),
        ("relaxing study", {"Library Rain", "Focus Flow"}),
    ],
)
def test_the_glossary_finds_songs_that_plain_retrieval_cannot(rich, plain, query, expected):
    assert plain.retrieve(query) == []
    assert set(titles(rich.retrieve(query))) == expected


def test_synonym_matches_are_reported_as_word_as_term(rich):
    ((first, matched), *_) = rich.retrieve("mellow homework")
    assert matched == ["mellow (as chill)", "homework (as study)"] and first["title"] == "Midnight Coding"


def test_direct_matches_are_reported_plainly_and_unchanged(rich, plain):
    assert rich.retrieve("cozy rainy study") == plain.retrieve("cozy rainy study")
    assert rich.retrieve("jazz") == plain.retrieve("jazz")


def test_the_guardrail_still_counts_the_users_own_words(rich):
    assert rich.retrieve("mellow zebra") == []                  # one real word and one unknown word
    assert rich.retrieve("xylophone zebra") == []
    assert titles(rich.retrieve("sad")) == ["Adagio for Rain"]  # a single word still needs only one match


def test_the_glossary_does_not_widen_unrelated_requests(rich, plain):
    for query in ("workout powerful", "cozy rainy study", "jazz", "calm acoustic"):
        assert set(titles(rich.retrieve(query))) >= set(titles(plain.retrieve(query)))
    assert titles(rich.retrieve("workout powerful")) == ["Gym Hero"]


# ----- explanations use the glossary, and the validator still guards them -----

def test_the_template_adds_the_genre_description_only_with_a_glossary(songs, glossary):
    library = song(songs, "Library Rain")
    assert "Lofi is mellow, slightly worn-sounding beats" in template_why(library, [], glossary).text
    assert "slightly worn-sounding" not in template_why(library, []).text


def test_synonym_matches_are_explained_without_nested_brackets(songs, glossary):
    text = template_why(song(songs, "Library Rain"), ["mellow (as chill)", "homework (as study)"], glossary).text
    assert "(mellow as chill, homework as study) because the glossary links those words" in text


def test_every_song_has_a_grounded_template_with_the_glossary(songs, glossary, rich):
    for s in songs:
        ok, reason = validate_explanation(template_why(s, [], glossary).text, s, "", glossary)
        assert ok, (s["title"], reason)
    for query in ("mellow homework", "rnb groove", "catchy upbeat", "gym loud", "relaxing study", "cozy rainy study"):
        for r in search(rich, query, STANDARD_PROFILES["Chill Lofi"], k=10).results:
            ok, reason = validate_explanation(r.why.text, r.song, query, glossary)
            assert ok, (query, r.song["title"], reason)


def test_glossary_words_are_allowed_only_for_songs_that_have_those_entries(songs, glossary):
    lofi, rock = song(songs, "Library Rain"), song(songs, "Storm Runner")
    sentence = "Lofi is mellow, slightly worn-sounding beats."
    assert validate_explanation(sentence, lofi, "", glossary)[0]
    assert not validate_explanation(sentence, rock, "", glossary)[0]
    assert "beats" in allowed_vocabulary(lofi, "", glossary) and "beats" not in allowed_vocabulary(lofi, "")


def test_invented_facts_are_still_rejected_with_the_glossary(songs, glossary):
    library = song(songs, "Library Rain")
    for text in ("It is a jazz song.", "Lofi was invented in 1995.", "Library Rain has piano melodies."):
        assert not validate_explanation(text, library, "", glossary)[0], text


def test_the_prompt_carries_the_genre_and_mood_facts_only_with_a_glossary(songs, glossary):
    library = song(songs, "Library Rain")
    assert "about genre=Lofi is mellow" in facts_text(library, [], glossary)
    assert "about mood=Chill music is easygoing" in facts_text(library, [], glossary)
    assert "about genre" not in facts_text(library, [])


def test_the_ai_step_accepts_glossary_facts_and_rejects_inventions(rich, glossary):
    results = search(rich, "mellow homework", STANDARD_PROFILES["Chill Lofi"], k=2).results

    class Fake:
        def generate(self, prompt, max_tokens=300):
            assert "about genre=Lofi is mellow" in prompt
            return "1: Lofi is mellow beats that people play while studying.\n2: It is a jazz song from 1995."

    whys = explain_with_ai(results, "mellow homework", Fake(), glossary=glossary)
    assert whys[0].source == "ai" and whys[1].source == "template" and "jazz" in whys[1].note


# ----- the pipeline -----

def test_the_pipeline_uses_logs_and_explains_glossary_matches(rich, log_to_a_temporary_file):
    outcome = search(rich, "mellow homework", STANDARD_PROFILES["Chill Lofi"])
    assert outcome.status == "ok" and outcome.results[0].confidence.coverage == 1.0
    assert "mellow as chill" in outcome.results[0].why.text
    assert outcome.results[0].explanation.startswith("search match: mellow (as chill), homework (as study);")
    entry = json.loads(log_to_a_temporary_file.read_text().splitlines()[-1])
    assert entry["via_glossary"] == ["homework (as study)", "mellow (as calm)", "mellow (as chill)"]


def test_the_default_glossary_folder_is_the_docs_folder():
    assert DEFAULT_FOLDER.name == "glossary" and DEFAULT_FOLDER.parent.name == "docs" and DEFAULT_FOLDER.exists()
