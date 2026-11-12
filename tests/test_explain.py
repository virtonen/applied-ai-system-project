import json
import os

import pytest

from src import llm_client
from src.explain import (
    MAX_CHARS,
    allowed_vocabulary,
    build_prompt,
    explain_with_ai,
    facts_text,
    parse_lines,
    sound_words,
    template_why,
    validate_explanation,
)
from src.llm_client import GeminiClient, LLMError, load_dotenv, make_client
from src.main import STANDARD_PROFILES
from src.pipeline import search
from src.recommender import load_songs
from src.retrieval import SongIndex

QUERY = "cozy rainy study"


@pytest.fixture(scope="module")
def songs():
    return load_songs("data/songs.csv")


@pytest.fixture(scope="module")
def index(songs):
    return SongIndex(songs)


@pytest.fixture()
def results(index):
    return search(index, QUERY, STANDARD_PROFILES["Chill Lofi"], k=3).results  # Library Rain, Midnight Coding


def song(songs, title):
    return next(s for s in songs if s["title"] == title)


class FakeClient:
    """Stands in for Gemini: returns a canned reply (or raises) and counts the calls."""

    def __init__(self, reply="", error=None):
        self.reply, self.error, self.calls, self.prompts = reply, error, 0, []

    def generate(self, prompt, max_tokens=300):
        self.calls += 1
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.reply


# ----- the facts and the template -----

def test_sound_words_describe_the_numbers(songs):
    assert sound_words(song(songs, "Library Rain")) == ["low-energy", "acoustic", "instrumental"]
    assert sound_words(song(songs, "Gym Hero")) == ["high-energy", "electronic"]


def test_every_search_result_carries_a_template_explanation(results):
    assert all(r.why and r.why.source == "template" for r in results)
    assert "cozy, rainy, study" in results[0].why.text and "lofi song with a chill mood" in results[0].why.text


def test_the_template_is_built_only_from_the_facts_and_passes_its_own_validator(songs):
    for s in songs:
        for matched in ([], ["cozy", "study"]):
            why = template_why(s, matched)
            ok, reason = validate_explanation(why.text, s, "cozy study")
            assert ok, (s["title"], reason, why.text)


# ----- the validator -----

GOOD = "Library Rain fits your cozy rainy study request because it has rainy, cozy, and study tags."


def test_a_sentence_made_of_song_facts_is_accepted(songs):
    assert validate_explanation(GOOD, song(songs, "Library Rain"), QUERY) == (True, "")


@pytest.mark.parametrize(
    "text, rejected_word",
    [
        ("It is a jazz song with a cozy feel.", "jazz"),                              # wrong genre
        ("Library Rain is a lofi song released in 1995.", "1995"),                    # invented year
        ("It is a lofi song by Taylor Swift.", "taylor"),                             # invented artist
        ("It has soothing piano melodies and a lofi beat.", "piano"),                 # invented instrument
        ("It is a relaxing lofi song.", "relaxing"),                                  # synonym not in the facts
        ("It has 0.35 energy.", "35"),                                                # numbers that are not facts
    ],
)
def test_invented_facts_are_rejected_and_named(songs, text, rejected_word):
    ok, reason = validate_explanation(text, song(songs, "Library Rain"), QUERY)
    assert not ok and rejected_word in reason


def test_words_from_the_users_request_are_allowed_but_only_for_that_request(songs):
    library = song(songs, "Library Rain")
    assert validate_explanation("It is a lofi song with tea.", library, "tea")[0]
    assert not validate_explanation("It is a lofi song with tea.", library, "")[0]


def test_empty_long_and_wordy_text_is_rejected(songs):
    library = song(songs, "Library Rain")
    assert validate_explanation("", library) == (False, "empty explanation")
    assert "too long" in validate_explanation("lofi " * MAX_CHARS, library)[1]
    assert "too many sentences" in validate_explanation("Lofi. Lofi. Lofi. Lofi.", library)[1]


def test_allowed_words_come_from_this_songs_facts_only(songs):
    words = allowed_vocabulary(song(songs, "Library Rain"))
    assert {"lofi", "chill", "rainy", "paper", "acoustic"} <= words
    assert "jazz" not in words and "metal" not in words


# ----- the AI step -----

def test_the_prompt_contains_the_facts_the_request_and_the_rules(results):
    prompt = build_prompt(QUERY, results)
    assert facts_text(results[0].song, results[0].matched_words) in prompt
    assert QUERY in prompt and "ONLY the facts" in prompt and prompt.count("\n1.") == 1


def test_numbered_lines_are_parsed_in_several_styles():
    assert parse_lines("1: First one.\n2. Second one.\n**3:** Third one.\nnoise line") == {
        1: "First one.", 2: "Second one.", 3: "Third one."
    }


def test_a_valid_ai_reply_is_used(results):
    client = FakeClient(f"1: {GOOD}\n2: Midnight Coding fits your cozy rainy study request because it has cozy and study tags.")
    whys = explain_with_ai(results, QUERY, client)
    assert [w.source for w in whys[:2]] == ["ai", "ai"] and whys[0].text == GOOD
    assert client.calls == 1  # one call for all results


def test_an_invented_fact_is_rejected_and_replaced_by_the_template(results):
    client = FakeClient("1: Library Rain is a jazz classic from 1995.\n2: Midnight Coding fits your cozy study request because it has cozy and study tags.")
    whys = explain_with_ai(results, QUERY, client)
    assert whys[0].source == "template" and "jazz" in whys[0].note and "1995" in whys[0].note
    assert whys[0].text == results[0].why.text
    assert whys[1].source == "ai"  # the good sentence is kept, only the bad one is replaced


def test_a_missing_line_falls_back_for_that_song_only(results):
    whys = explain_with_ai(results, QUERY, FakeClient(f"1: {GOOD}"))
    assert whys[0].source == "ai" and whys[1].source == "template" and "no sentence returned" in whys[1].note


@pytest.mark.parametrize("error", [LLMError("Gemini returned HTTP 429"), RuntimeError("boom")])
def test_a_failing_model_falls_back_to_the_template_for_everything(results, error):
    whys = explain_with_ai(results, QUERY, FakeClient(error=error))
    assert [w.source for w in whys] == ["template"] * len(results)
    assert all(w.text == r.why.text for w, r in zip(whys, results))


def test_garbage_output_falls_back_safely(results):
    whys = explain_with_ai(results, QUERY, FakeClient("I am sorry, I cannot help with that."))
    assert all(w.source == "template" for w in whys)


def test_the_same_request_is_cached_so_it_costs_one_call(results):
    client = FakeClient(f"1: {GOOD}\n2: Midnight Coding fits your cozy study request because it has cozy and study tags.")
    first = explain_with_ai(results, QUERY, client)
    assert explain_with_ai(results, QUERY, client) == first and client.calls == 1


def test_failures_are_not_cached_so_a_retry_can_work(results):
    explain_with_ai(results, QUERY, FakeClient(error=LLMError("HTTP 500")))
    good = FakeClient(f"1: {GOOD}")
    assert explain_with_ai(results, QUERY, good)[0].source == "ai" and good.calls == 1


def test_the_ai_step_is_logged(results, log_to_a_temporary_file):
    explain_with_ai(results, QUERY, FakeClient("1: Library Rain is a jazz classic from 1995."))
    entry = [json.loads(line) for line in log_to_a_temporary_file.read_text().splitlines()][-1]
    assert entry["event"] == "explain" and entry["ai_used"] == 0 and entry["results"] == len(results)
    assert entry["rejected"][0]["song"] == "Library Rain" and "jazz" in entry["rejected"][0]["reason"]


def test_a_failed_call_is_logged_with_the_error_but_never_the_key(results, log_to_a_temporary_file, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-KEY-123")
    explain_with_ai(results, QUERY, FakeClient(error=LLMError("Gemini returned HTTP 429")))
    log = log_to_a_temporary_file.read_text()
    assert "HTTP 429" in log and "SECRET-KEY-123" not in log


# ----- the client and the API key -----

def test_no_key_means_no_client():
    assert make_client() is None


def test_a_key_in_the_environment_gives_a_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    assert isinstance(make_client(), GeminiClient)


def test_the_key_can_come_from_a_dotenv_file(tmp_path, monkeypatch):
    env = tmp_path / "x.env"
    env.write_text("# comment\n\nGEMINI_API_KEY='from-file'\nOTHER=1\n")
    monkeypatch.setattr(llm_client, "ENV_FILE", env)
    assert make_client().api_key == "from-file"


def test_an_existing_environment_variable_beats_the_dotenv_file(tmp_path, monkeypatch):
    env = tmp_path / "x.env"
    env.write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    load_dotenv(env)
    assert os.environ["GEMINI_API_KEY"] == "from-shell"


def test_a_missing_dotenv_file_is_fine(tmp_path):
    load_dotenv(tmp_path / "nope.env")


def test_network_errors_become_safe_llm_errors(monkeypatch):
    import urllib.error
    import urllib.request

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test/?key=SECRET", 429, "Too Many", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(LLMError) as caught:
        GeminiClient("SECRET").generate("hi")
    assert str(caught.value) == "Gemini returned HTTP 429" and "SECRET" not in str(caught.value)


@pytest.mark.skipif(not os.environ.get("RUN_LIVE_LLM_TESTS"), reason="set RUN_LIVE_LLM_TESTS=1 to spend one real API call")
def test_live_gemini_reply_is_validated(index, monkeypatch):
    monkeypatch.setattr(llm_client, "ENV_FILE", llm_client.Path(__file__).resolve().parent.parent / ".env")
    client = make_client()
    assert client is not None, "no GEMINI_API_KEY available"
    outcome = search(index, QUERY, STANDARD_PROFILES["Chill Lofi"], k=3)
    whys = explain_with_ai(outcome.results, QUERY, client)
    assert len(whys) == len(outcome.results) and all(w.text for w in whys)
    for why, r in zip(whys, outcome.results):
        assert validate_explanation(why.text, r.song, QUERY)[0], why


def test_the_template_uses_a_or_an_correctly(songs):
    assert "It is an r&b song with a romantic mood" in template_why(song(songs, "Velvet Hours")).text
    assert "with an uplifting mood" in template_why(song(songs, "Island Sway")).text
    assert "It is a lofi song with a chill mood" in template_why(song(songs, "Library Rain")).text
    assert "It is an indie pop song" in template_why(song(songs, "Rooftop Lights")).text
