import subprocess
import sys

from src.main import ADVANCED_PROFILES, ADVERSARIAL_PROFILES, STANDARD_PROFILES
from src.recommender import SCORING_MODES, load_songs, recommend_songs
from src.report import REASON_WIDTH, format_table, recommendations_table


def split_reasons(explanation):
    return [r.replace(" close to target", "") for r in explanation.split("; ")]


def test_every_line_of_a_table_has_the_same_width():
    table = format_table(["A", "Longer header"], [["x", "one\ntwo\nthree"], ["longer cell", "y"]])
    assert len({len(line) for line in table.splitlines()}) == 1


def test_multiline_cells_stay_in_their_own_row():
    table = format_table(["Name", "Notes"], [["a", "first\nsecond"], ["b", "third"]])
    lines = table.splitlines()
    assert "| a    | first  |" in lines
    assert "|      | second |" in lines
    assert "| b    | third  |" in lines


def test_empty_results_still_draw_a_header():
    table = recommendations_table([])
    assert "Reasons" in table
    assert len({len(line) for line in table.splitlines()}) == 1


def test_every_song_score_and_reason_appears_in_the_table():
    songs = load_songs("data/songs.csv")
    picks = recommend_songs(STANDARD_PROFILES["High-Energy Pop"], songs)
    table = recommendations_table(picks)
    for song, score, explanation in picks:
        assert song["title"] in table
        assert song["artist"] in table
        assert f"{score:.2f}" in table
        for reason in split_reasons(explanation):
            assert reason in table, reason


def test_long_reasons_wrap_but_keep_all_their_words():
    song = {"title": "T", "artist": "A", "genre": "g", "mood": "m"}
    reason = "diversity penalty: artist Someone With A Very Long Name already picked (-0.15)"
    table = recommendations_table([(song, 0.5, reason)])
    reason_lines = [line.split("|")[-2].strip() for line in table.splitlines() if "diversity" in line or "picked" in line]
    assert len(reason_lines) >= 2  # it wrapped
    assert all(len(line) <= REASON_WIDTH for line in reason_lines)
    assert " ".join(l.lstrip("- ") for l in reason_lines) == reason


def test_table_works_for_every_profile_mode_and_diversity_setting():
    songs = load_songs("data/songs.csv")
    profiles = {**STANDARD_PROFILES, **ADVERSARIAL_PROFILES, **ADVANCED_PROFILES}.values()
    for mode in SCORING_MODES:
        for diverse in (False, True):
            for prefs in profiles:
                picks = recommend_songs(prefs, songs, mode=mode, diverse=diverse)
                table = recommendations_table(picks)
                assert len({len(line) for line in table.splitlines()}) == 1
                assert table.count("| 1 |") == 1 and table.count("| 5 |") == 1


def test_table_flag_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--table", "--mode", "mood-first", "--diverse"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Reasons" in result.stdout
    assert "Chill Lofi" in result.stdout
    assert "diversity penalty" in result.stdout
