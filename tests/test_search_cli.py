import subprocess
import sys

import pytest

from src import llm_client
from src.search import find_profile, main

LOFI = ["--profile", "Chill Lofi"]


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


class FakeGemini:
    calls = 0

    def generate(self, prompt, max_tokens=300):
        type(self).calls += 1
        return "1: It is a good song.\n2: It is a jazz song from 1995."


def test_a_typed_request_returns_the_retrieved_songs_with_reasons(capsys):
    code, out, _ = run(capsys, "cozy rainy study", *LOFI)
    assert code == 0
    assert "Status  : ok, 2 song(s), overall confidence High" in out
    assert out.index("1. Library Rain") < out.index("2. Midnight Coding") and "Focus Flow" not in out
    assert "search match: cozy, rainy, study" in out and "coverage 1.00" in out
    assert "(built from the song facts)" in out


def test_nonsense_says_nothing_fits_with_exit_code_1(capsys):
    code, out, _ = run(capsys, "xylophone zebra", *LOFI)
    assert code == 1 and "Status  : nothing_fits" in out and "Nothing fits" in out and "1. " not in out


def test_a_poor_fit_shows_the_low_confidence_warning(capsys):
    code, out, _ = run(capsys, "--profile", "Extreme Targets", "-k", "3")
    assert code == 0 and "Warning : low confidence" in out and "Low (0.50)" in out
    assert out.count("\n1. ") == 1 and "\n3. " in out and "\n4. " not in out


def test_out_of_range_input_is_rejected_with_exit_code_2(capsys):
    code, out, _ = run(capsys, *LOFI, "--energy", "9")
    assert code == 2 and "Status  : invalid_input" in out and "'energy' must be between 0 and 1" in out


def test_no_preferences_at_all_is_an_error(capsys):
    code, out, err = run(capsys, "jazz")
    assert code == 2 and out == "" and "give a --profile" in err


def test_an_unknown_profile_lists_the_choices(capsys):
    code, _, err = run(capsys, "x", "--profile", "Nope")
    assert code == 2 and 'Unknown profile "Nope"' in err and '"Chill Lofi"' in err


def test_profiles_match_loosely_and_flags_override_them():
    assert find_profile("chill lofi")["genre"] == "lofi" and find_profile("chill-lofi") == find_profile("Chill Lofi")
    assert find_profile("Mainstream Hits")["popularity"] == 90 and find_profile("nope") is None


def test_flags_without_a_profile_work(capsys):
    code, out, _ = run(capsys, "jazz", "--genre", "jazz", "--mood", "relaxed", "--energy", "0.4", "--tags", "cozy, warm")
    assert code == 0
    assert "Prefs   : genre jazz, mood relaxed, energy 0.4, mood_tags cozy,warm" in out
    assert out.index("1. Coffee Shop Stories")  # the only song that matches the word "jazz"


def test_mode_diversity_and_k_are_passed_through(capsys):
    _, out, _ = run(capsys, "--profile", "Chill Lofi", "--mode", "mood-first", "--diverse", "-k", "4")
    assert "Mode    : mood-first + diversity penalty" in out and "\n4. " in out and "\n5. " not in out
    assert "diversity penalty: " in out


def test_a_bad_song_file_gives_a_clear_error(capsys, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    code, out, err = run(capsys, *LOFI, "--data", str(empty))
    assert code == 2 and "could not be loaded" in err and "empty" in err


def test_ai_option_without_a_key_falls_back_with_a_note(capsys):
    code, out, err = run(capsys, "cozy rainy study", *LOFI, "--ai")
    assert code == 0 and "needs GEMINI_API_KEY" in err and "(built from the song facts)" in out


def test_ai_option_uses_valid_sentences_and_rejects_invented_ones(capsys, monkeypatch):
    FakeGemini.calls = 0
    monkeypatch.setattr(llm_client, "make_client", lambda: FakeGemini())
    code, out, _ = run(capsys, *LOFI, "--ai", "-k", "2")
    first, second = out.split("\n1. ")[1].split("\n2. ")
    assert code == 0 and FakeGemini.calls == 1  # one call for all results
    assert "why: It is a good song. (written by Gemini, checked against the song facts)" in first
    assert "It is a jazz song from 1995" not in second          # the invented sentence is never shown
    assert "(built from the song facts)" in second               # the fact-based sentence is shown instead
    assert "note: the model's wording was not used" in second and "1995" in second  # with the reason


def test_the_command_runs_end_to_end_as_a_module():
    result = subprocess.run(
        [sys.executable, "-m", "src.search", "cozy rainy study", "--profile", "Chill Lofi"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0 and "1. Library Rain by Paper Lanterns" in result.stdout


def test_the_glossary_is_used_by_default_and_can_be_switched_off(capsys):
    code, out, _ = run(capsys, "mellow homework", *LOFI)
    flat = " ".join(out.split())  # long lines wrap in the output
    assert code == 0 and "mellow (as chill)" in out and "homework (as study)" in out
    assert "Lofi is mellow, slightly worn-sounding beats" in flat and "the glossary links those words" in flat
    code, out, _ = run(capsys, "mellow homework", *LOFI, "--no-glossary")
    assert code == 1 and "Status  : nothing_fits" in out
