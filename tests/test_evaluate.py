import pytest

import src.evaluate as evaluate
from src.evaluate import (
    CASES,
    README_END,
    README_START,
    Case,
    check,
    main,
    run_cases,
    summarize,
    to_markdown,
    update_readme,
)
from src.pipeline import search
from src.recommender import load_songs
from src.retrieval import SongIndex


@pytest.fixture(scope="module")
def index():
    return SongIndex(load_songs("data/songs.csv"))


@pytest.fixture(scope="module")
def results(index):
    return run_cases(index, CASES)


def failing_case():
    return Case("X1", "Deliberately wrong", evaluate.PROFILES["Chill Lofi"], expect=dict(top="Iron Requiem", confidence="Low"))


# ----- the built-in cases -----

def test_every_built_in_case_passes(results):
    failed = [(r.case.id, r.failures) for r in results if not r.passed]
    assert failed == []


def test_case_ids_are_unique_and_every_status_is_covered():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    assert {c.expect.get("status", "ok") for c in CASES} == {"ok", "nothing_fits", "invalid_input"}
    assert {"balanced", "mood-first", "genre-first"} <= {c.mode for c in CASES}
    assert any(c.diverse for c in CASES) and any(c.query for c in CASES)


def test_summary_numbers(results):
    summary = summarize(results)
    assert summary["total"] == len(CASES) and summary["passed"] == len(CASES)
    assert 0.0 <= summary["average_confidence"] <= 1.0
    assert sum(summary["labels"].values()) == summary["with_results"]
    assert summary["with_results"] == sum(1 for r in results if r.outcome.results)


# ----- the harness can tell a pass from a fail -----

def test_a_wrong_expectation_is_reported_as_a_failure(index):
    (result,) = run_cases(index, [failing_case()])
    assert not result.passed
    assert any("top was" in f for f in result.failures) and any("confidence was" in f for f in result.failures)


@pytest.mark.parametrize(
    "expect, fragment",
    [
        (dict(status="nothing_fits"), "status was ok"),
        (dict(count=2), "5 results, expected 2"),
        (dict(exact=["Library Rain"]), "results were"),
        (dict(includes=["Iron Requiem"]), "missing Iron Requiem"),
        (dict(excludes=["Library Rain"]), "should not include Library Rain"),
        (dict(before=("Focus Flow", "Library Rain")), "should rank above"),
        (dict(max_per_artist=1), "appears 2 times"),
        (dict(message="zzz"), "lacks"),
    ],
)
def test_each_kind_of_check_can_fail(index, expect, fragment):
    outcome = search(index, "", evaluate.PROFILES["Chill Lofi"], k=5)
    assert any(fragment in problem for problem in check(outcome, expect))


def test_an_empty_expectation_always_passes(index):
    assert check(search(index, "", evaluate.PROFILES["Chill Lofi"]), {}) == []


# ----- the markdown report -----

def test_markdown_has_a_header_one_row_per_case_and_a_summary(results):
    lines = to_markdown(results).splitlines()
    assert lines[0].startswith("| ID | What it checks | Expected | Result | Top song | Confidence |")
    assert lines[1] == "|---|---|---|---|---|---|"
    rows = [line for line in lines if line.startswith("| P1 ") or line.startswith("| G5 ")]
    assert len(rows) == 2
    assert f"{len(CASES)} of {len(CASES)} cases passed (100%)." in "\n".join(lines)


def test_markdown_is_deterministic(results, index):
    assert to_markdown(results) == to_markdown(run_cases(index, CASES))


def test_failures_show_the_reason_in_the_table(index):
    assert "FAIL: " in to_markdown(run_cases(index, [failing_case()]))


def test_pipes_in_cells_do_not_break_the_table(index):
    case = Case("X2", "has | a pipe", evaluate.PROFILES["Chill Lofi"], expect=dict(top="Library Rain"))
    row = [line for line in to_markdown(run_cases(index, [case])).splitlines() if line.startswith("| X2")][0]
    assert "has \\| a pipe" in row


# ----- README update and the command line -----

def test_readme_block_is_replaced_and_the_rest_is_kept(tmp_path, results):
    readme = tmp_path / "README.md"
    readme.write_text(f"before\n{README_START}\nOLD TABLE\n{README_END}\nafter\n")
    assert update_readme(results, readme) is True
    text = readme.read_text()
    assert text.startswith("before\n") and text.endswith("after\n") and "OLD TABLE" not in text
    assert "| P1 |" in text and text.count(README_START) == 1
    assert update_readme(results, readme) is True and readme.read_text() == text  # running twice changes nothing


def test_readme_without_markers_is_left_alone(tmp_path, results):
    readme = tmp_path / "README.md"
    readme.write_text("no markers here\n")
    assert update_readme(results, readme) is False
    assert readme.read_text() == "no markers here\n"


def test_command_line_writes_the_report_and_exits_zero(tmp_path, capsys):
    out = tmp_path / "reports" / "evaluation.md"
    assert main(["--out", str(out)]) == 0
    assert out.read_text().startswith("# Evaluation results")
    assert f"{len(CASES)} of {len(CASES)} cases passed" in capsys.readouterr().out


def test_command_line_exits_one_when_a_case_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "CASES", [*CASES, failing_case()])
    assert main(["--out", str(tmp_path / "r.md")]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_command_line_reports_missing_readme_markers(tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text("nothing\n")
    assert main(["--out", str(tmp_path / "r.md"), "--readme", "--readme-path", str(readme)]) == 1
    assert "markers" in capsys.readouterr().err


def test_a_bad_data_file_stops_the_harness_with_a_clear_error(tmp_path):
    from src.guardrails import DataError

    with pytest.raises(DataError, match="not found"):
        main(["--data", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "r.md")])


def test_the_grounded_check_catches_an_explanation_with_invented_facts(index):
    from src.explain import Why

    outcome = search(index, "", evaluate.PROFILES["Chill Lofi"], k=3)
    assert check(outcome, dict(grounded=True)) == []
    outcome.results[0].why = Why("It is a jazz song from 1995.", "ai")
    problems = check(outcome, dict(grounded=True))
    assert len(problems) == 1 and "not grounded" in problems[0] and "1995" in problems[0]


def test_brief_output_has_one_line_per_case_and_the_summary(results, tmp_path, capsys):
    from src.evaluate import to_brief

    lines = to_brief(results).splitlines()
    assert sum(1 for line in lines if line[:2] in ("P1", "G5") and "PASS" in line) == 2
    assert lines[-1].startswith(f"{len(CASES)} of {len(CASES)} cases passed")
    assert max(len(line) for line in lines if line.startswith(("P", "M", "D", "S", "G"))) < 130

    assert main(["--brief", "--out", str(tmp_path / "r.md")]) == 0
    assert "PASS" in capsys.readouterr().out


def test_brief_output_lists_the_reasons_for_a_failure(index):
    from src.evaluate import to_brief

    text = to_brief(run_cases(index, [failing_case()]))
    assert "FAIL" in text and "-> top was" in text
