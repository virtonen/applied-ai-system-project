import json
import re

import pytest

import src.specialization as spec
from src.glossary import Glossary
from src.llm_client import LLMError
from src.recommender import load_songs
from src.retrieval import SongIndex
from src.specialization import (
    CASES,
    INJECTION_VARIANTS,
    VARIANTS,
    build_cases,
    judge,
    main,
    parse_numbered,
    prompt_for,
    run_experiment,
    summarize,
    to_markdown,
)

N_NORMAL = sum(1 for c in CASES if c.kind == "normal")
N_INJECTION = sum(1 for c in CASES if c.kind == "injection")
N_CALLS = N_NORMAL * len(VARIANTS) + N_INJECTION * len(INJECTION_VARIANTS)


@pytest.fixture(scope="module")
def glossary():
    return Glossary.load()


@pytest.fixture(scope="module")
def built(glossary):
    return build_cases(SongIndex(load_songs("data/songs.csv"), glossary))


def song_count(prompt):
    return len(re.findall(r"^\d+\. title=", prompt, re.M))


class FakeGemini:
    """Answers each prompt the way each kind of prompt tends to be answered, and counts calls."""

    def __init__(self, fail_at=None, error="Gemini returned HTTP 429"):
        self.calls, self.prompts, self.fail_at, self.error = 0, [], fail_at, error

    def generate(self, prompt, max_tokens=300):
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail_at is not None and self.calls >= self.fail_at:
            raise LLMError(self.error)
        n = song_count(prompt)
        if "A listener asked for" in prompt:  # plain: chatty and invents facts
            return "\n".join(f"{i}. This is a wonderful song by a famous artist, released in 1995 with lovely piano." for i in range(1, n + 1))
        if "Listener request:" in prompt:  # the whole request was pasted in, and the model obeys it
            return "\n".join(f"{i}: It is a good song, banana." for i in range(1, n + 1))
        return "\n".join(f"{i}: It is a good song." for i in range(1, n + 1))


# ----- the prompts differ only in their instructions -----

def facts_lines(prompt):
    return re.findall(r"^\d+\. title=.*$", prompt, re.M)


def test_every_case_retrieves_songs(built):
    assert [case.id for case, _, _ in built] == [c.id for c in CASES]
    assert all(results for _, _, results in built)


def test_all_prompts_give_the_model_exactly_the_same_facts(built, glossary):
    case, query, results = built[0]
    lines = {v: facts_lines(prompt_for(v, query, results, glossary)) for v in (*VARIANTS, "sanitized-request")}
    assert len({tuple(v) for v in lines.values()}) == 1 and len(lines["plain"]) == len(results)


def test_the_plain_prompt_has_no_rules_and_the_constrained_one_does(built, glossary):
    _, query, results = built[0]
    plain, constrained = (prompt_for(v, query, results, glossary) for v in ("plain", "constrained"))
    assert "ONLY" not in plain and "25 words" not in plain and "exact format" not in plain
    assert "Use ONLY the facts" in constrained and "at most 25 words" in constrained and "exact format" in constrained


def test_the_few_shot_prompt_adds_an_example_and_keeps_the_rules(built, glossary):
    _, query, results = built[0]
    few, constrained = prompt_for("few-shot", query, results, glossary), prompt_for("constrained", query, results, glossary)
    assert "Sample Song fits your study request" in few and "Use ONLY the facts" in few and "Sample Song" not in constrained
    assert len(few) > len(constrained)


def test_the_injection_case_shows_the_raw_request_only_in_the_raw_variant(built, glossary):
    case, query, results = built[-1]
    assert case.kind == "injection"
    assert "banana" in prompt_for("raw-request", query, results, glossary)
    assert "banana" not in prompt_for("sanitized-request", query, results, glossary)
    assert prompt_for("sanitized-request", query, results, glossary) == prompt_for("constrained", query, results, glossary)


# ----- reading and judging replies -----

def test_numbered_answers_are_read_in_several_styles():
    assert parse_numbered("1: One.\n2. Two.\n**3.** Three.\n4) Four.") == {1: "One.", 2: "Two.", 3: "Three.", 4: "Four."}
    assert parse_numbered("Sure! Here you go:\n1. **Library Rain**\n   A calm song.\n2. Next one.") == {1: "Library Rain A calm song.", 2: "Next one."}
    assert parse_numbered("no numbers here") == {} and parse_numbered(None) == {}


def test_judge_accepts_facts_rejects_inventions_and_notes_missing_answers(built, glossary):
    _, query, results = built[0]
    reply = "1: It is a good song.\n"
    judged = judge(reply, results, query, glossary)
    assert [j.returned for j in judged] == [True, False] and judged[0].accepted and not judged[1].accepted
    assert judged[1].reason == "no numbered sentence returned"
    invented = judge("1: Released in 1995 with piano.", results[:1], query, glossary)[0]
    assert not invented.accepted and "1995" in invented.reason and "piano" in invented.reason


def test_the_first_validator_accepted_planted_request_words_and_the_current_one_does_not(built, glossary):
    _, query, results = built[-1]
    reply = "\n".join(f"{i}: It is a good song, banana." for i in range(1, len(results) + 1))
    assert all(j.accepted for j in judge(reply, results, query, glossary, legacy=True))
    assert not any(j.accepted for j in judge(reply, results, query, glossary))


def test_summaries_count_rates_and_the_words_that_were_rejected(built, glossary):
    _, query, results = built[1]
    judged = judge("1: It is a good song.\n2: A wonderful famous song.\n3: Good.", results, query, glossary)
    s = summarize("x", judged)
    assert (s.songs, s.returned, s.accepted) == (3, 3, 2)
    assert s.rejection_rate == pytest.approx(1 / 3) and s.fallback_rate == pytest.approx(1 / 3) and s.format_rate == 1.0
    assert s.unsupported["wonderful"] == 1 and s.within_limit == 1.0
    empty = summarize("y", [])
    assert empty.rejection_rate is None and empty.mean_words == 0.0


# ----- running it: cached, bounded, polite -----

def test_a_full_run_makes_one_call_per_case_and_variant(built, glossary, tmp_path):
    client = FakeGemini()
    raw = run_experiment(built, glossary, client, tmp_path / "raw.json", delay=0, sleep=lambda s: None)
    assert client.calls == N_CALLS == raw["calls_this_run"] and len(raw["entries"]) == N_CALLS
    assert all(entry["reply"] and entry["error"] is None for entry in raw["entries"].values())


def test_saved_replies_are_reused_so_a_rerun_costs_nothing(built, glossary, tmp_path):
    path = tmp_path / "raw.json"
    run_experiment(built, glossary, FakeGemini(), path, delay=0, sleep=lambda s: None)
    again = FakeGemini()
    raw = run_experiment(built, glossary, again, path, delay=0, sleep=lambda s: None)
    assert again.calls == 0 and raw["calls_this_run"] == 0


def test_a_changed_prompt_invalidates_the_saved_reply(built, glossary, tmp_path):
    path = tmp_path / "raw.json"
    run_experiment(built, glossary, FakeGemini(), path, delay=0, sleep=lambda s: None)
    data = json.loads(path.read_text())
    data["entries"]["C1|plain"]["prompt_sha"] = "stale"
    path.write_text(json.dumps(data))
    again = FakeGemini()
    run_experiment(built, glossary, again, path, delay=0, sleep=lambda s: None)
    assert again.calls == 1


def test_replay_makes_no_calls_even_when_replies_are_missing(built, glossary, tmp_path):
    client = FakeGemini()
    raw = run_experiment(built, glossary, client, tmp_path / "raw.json", replay=True)
    assert client.calls == 0 and raw["entries"] == {}


def test_the_call_limit_is_respected_and_the_rest_is_marked_not_run(built, glossary, tmp_path):
    client = FakeGemini()
    raw = run_experiment(built, glossary, client, tmp_path / "raw.json", max_calls=4, delay=0, sleep=lambda s: None)
    assert client.calls == 4
    skipped = [k for k, v in raw["entries"].items() if v["error"] == "not run: call limit reached"]
    assert len(skipped) == N_CALLS - 4


def test_a_rate_limit_stops_the_run_and_keeps_what_was_collected(built, glossary, tmp_path):
    client = FakeGemini(fail_at=4)
    raw = run_experiment(built, glossary, client, tmp_path / "raw.json", delay=0, sleep=lambda s: None)
    assert client.calls == 4  # it did not keep hammering a rate-limited API
    good = [k for k, v in raw["entries"].items() if v["reply"]]
    assert len(good) == 3 and "HTTP 429" in raw["entries"]["C2|plain"]["error"]
    report = to_markdown(built, glossary, raw)
    assert "Not run (no saved reply)" in report


def test_other_errors_do_not_stop_the_run(built, glossary, tmp_path):
    client = FakeGemini(fail_at=2, error="Gemini returned HTTP 503")
    raw = run_experiment(built, glossary, client, tmp_path / "raw.json", delay=0, sleep=lambda s: None)
    assert client.calls == N_CALLS  # a 503 is recorded and the next prompt is still tried


def test_a_failed_reply_is_not_saved_as_a_success_and_is_retried_next_time(built, glossary, tmp_path):
    path = tmp_path / "raw.json"
    run_experiment(built, glossary, FakeGemini(fail_at=3), path, delay=0, sleep=lambda s: None)
    later = FakeGemini()
    run_experiment(built, glossary, later, path, delay=0, sleep=lambda s: None)
    assert later.calls == N_CALLS - 2  # only the two good replies were kept


def test_it_waits_between_calls_but_not_before_the_first(built, glossary, tmp_path):
    waits = []
    run_experiment(built, glossary, FakeGemini(), tmp_path / "raw.json", delay=7.5, sleep=waits.append)
    assert waits == [7.5] * (N_CALLS - 1)


def test_no_client_means_only_saved_replies_are_used(built, glossary, tmp_path):
    raw = run_experiment(built, glossary, None, tmp_path / "raw.json")
    assert raw["entries"] == {}


# ----- the report -----

@pytest.fixture()
def raw_store(built, glossary, tmp_path):
    return run_experiment(built, glossary, FakeGemini(), tmp_path / "raw.json", delay=0, sleep=lambda s: None)


def test_the_report_shows_the_measured_difference(built, glossary, raw_store):
    report = to_markdown(built, glossary, raw_store)
    rows = {line.split("|")[1].strip(): line for line in report.splitlines() if line.startswith("| ") and "|" in line[2:]}
    assert "**100%**" in rows["plain"] and "**0%**" in rows["constrained"] and "**0%**" in rows["few-shot"]
    assert "1995" in report and "piano" in report and "wonderful" in report  # what the plain prompt invented
    assert 'Library Rain: "This is a wonderful song' in report


def test_the_report_shows_the_hidden_instruction_test(built, glossary, raw_store):
    report = to_markdown(built, glossary, raw_store)
    assert "Hidden instructions in the typed request" in report
    rows = [line for line in report.splitlines() if "first validator" in line or "current validator" in line]
    assert len(rows) == 3 * N_INJECTION
    for first, current, sanitized in zip(rows[0::3], rows[1::3], rows[2::3]):
        assert first.endswith("| 2 | 2 | 2 |") and current.endswith("| 2 | 2 | 0 |") and sanitized.endswith("| 2 | 0 | 0 |")


def test_the_report_is_the_same_every_time(built, glossary, raw_store):
    assert to_markdown(built, glossary, raw_store) == to_markdown(built, glossary, raw_store)


def test_rescoring_saved_replies_needs_no_calls(built, glossary, raw_store, tmp_path):
    path = tmp_path / "raw2.json"
    path.write_text(json.dumps(raw_store))
    client = FakeGemini()
    again = run_experiment(built, glossary, client, path, replay=True)
    assert client.calls == 0 and to_markdown(built, glossary, again) == to_markdown(built, glossary, raw_store)


# ----- the command -----

def test_the_command_writes_the_raw_replies_and_the_report(tmp_path, capsys):
    out, raw = tmp_path / "r.md", tmp_path / "raw.json"
    assert main(["--delay", "0", "--raw", str(raw), "--out", str(out)], client=FakeGemini()) == 0
    assert out.read_text().startswith("# Specialization experiment") and json.loads(raw.read_text())["entries"]
    assert f"API calls this run: {N_CALLS}" in capsys.readouterr().out


def test_dry_run_prints_the_prompts_and_makes_no_calls(capsys, tmp_path):
    assert main(["--dry-run", "--raw", str(tmp_path / "x.json")], client=FakeGemini()) == 0
    out = capsys.readouterr().out
    assert "===== plain" in out and "===== constrained" in out and "===== few-shot" in out
    assert not (tmp_path / "x.json").exists()


def test_the_real_saved_replies_file_is_valid_json_if_present():
    if spec.RAW_PATH.exists():
        data = json.loads(spec.RAW_PATH.read_text())
        assert data["model"] and all({"prompt_sha", "reply", "error"} <= set(v) for v in data["entries"].values())
