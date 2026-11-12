# AI Interactions Log

How I worked with an AI coding assistant on this project: the prompt, what it produced, and what I checked myself. (The scoring modes, diversity penalty and extra song features came from my Module 3 project. This log covers the work done in this project.)

## 1. Logging, guardrails and confidence

**Prompt:** "Log each search to a file: the query, matched words, mode, result count and any error. Validate inputs and the CSV, for example a missing column or an empty file. Add a per-result confidence score (top score, gap to the runner-up, share of query words matched) and show it in the UI. This replaces the ad hoc 0.6 check."

**What it produced:** `src/guardrails.py` (CSV and input checks with clear errors), `src/logging_utils.py` (JSON-lines log that never raises), `src/confidence.py`, `src/pipeline.py` (validate, retrieve, rank, confidence, log; never raises), UI changes, and about 66 new tests.

**What I checked:**
- I ran the confidence formula on all 10 demo profiles. The first version (0.6 / 0.2 / 0.2) rated the poor "Extreme Targets" result Medium and penalized two great songs for nearly tying, so I changed it to 0.7 / 0.1 / 0.2 and left coverage out when there is no request.
- I broke the code on purpose (weaker confidence weights, no CSV range check) and confirmed tests failed.
- One test assertion was stricter than its stated intent, so I corrected the test, not the code.

## 2. Evaluation harness

**Prompt:** "A script that runs predefined queries and profiles against expected songs. It prints pass/fail and average confidence, and writes a markdown table for the README."

**What it produced:** `src/evaluate.py` with 19 cases (later 30), a markdown report, an optional README refresh, and an exit code for failures; plus `tests/test_evaluate.py`.

**What I checked:** I weakened the retrieval guardrail on purpose and the harness flagged 3 of 19 cases (it now has 30 cases, including the glossary, agent and prompt-injection ones). I also noted in the README that the expected results came from behavior I had already inspected, so the harness guards against regressions and is not an independent measure of quality.

## 3. Grounded explanations (RAG with validation)

**Prompt:** "Add a grounded 'why this song' explanation built from the retrieved text. If you use an LLM, add a validator that rejects any sentence mentioning facts not in the retrieved song text."

**What it produced:** `src/explain.py` (facts, template sentence, word-level validator, one Gemini call per search with fallback and caching), `src/llm_client.py` (standard-library Gemini client, key from `.env`), a sidebar option, and 31 offline tests (they use a fake model, so they make no API calls).

**What I checked:**
- I confirmed that the template passes its own validator for every song, with and without a request.
- I broke the validator on purpose and 10 tests failed.
- I made twenty-five real Gemini calls in total (one probe, one live test, one for the README screenshot, three for README sample runs, and nineteen for the prompt experiment); every reply passed validation.
- I made tests unable to find the real key, so they cannot make live calls, and I searched the repo to confirm the key appears nowhere but `.env`.
- I stated in the docs that the validator checks words, not meaning.

## 4. A second retrieval source: the glossary (RAG enhancement)

**Prompt:** "Add a second retrieval source, a short genre and mood glossary in markdown, reusing DocuBot's heading-based chunking. It would handle synonyms and explain terms. Document a before/after example." I also asked whether a dataset or an API such as MusicBrainz or TheAudioDB made more sense. The assistant recommended a self-written glossary: a bigger song dataset is more rows of the same source, and a live API adds network dependence and describes artists, not vibe words.

**What it produced:** `docs/glossary/` (45 entries), `src/glossary.py` (heading chunking ported from DocuBot, expansion, facts for a song), glossary support in retrieval, the explanation template, the Gemini prompt and the validator, a `--no-glossary` switch and a sidebar checkbox, four evaluation cases, and 30 tests.

**What I checked:**
- **A wrong example, caught.** The assistant first suggested "relaxing" finding nothing as the before/after. Running it showed the stemmer already matches "relaxing" to "relaxed", so I used "mellow homework" instead (nothing before, three songs after) and corrected a false claim in my docs.
- **A real bug, found by a test.** A code block inside a glossary entry was counted as part of the entry's description. The test for the parser failed, and I fixed the parser to skip fenced lines.
- **No loss of precision.** Queries that already matched directly return the same songs, a multi-word term only matches as a whole phrase, and the guardrail still counts the user's own words ("mellow zebra" is refused).
- **Mutation checks.** Making expansion return nothing failed 19 tests, and letting the validator accept every glossary word failed 3 tests.
- **One live Gemini call** with glossary facts in the prompt; both sentences passed the validator.
- **My own review still needed:** the glossary's wording is mine to check, since the system treats it as true.

## 5. Agentic workflow: plan, act, critique, retry

**Prompt:** "Implement an agentic workflow: a plan, search, critique and retry loop. If the result is 'Nothing fits' or low confidence, it reformulates the request (for example with glossary synonyms), retries up to 3 times, and saves the trace to ai_interactions.md. This is deterministic and testable, and it builds on the glossary."

**What it produced:** `src/agent.py` (the loop, five strategies, the trace and a command that records the traces below), a `--agent` option on `python -m src.search`, an "Let the assistant retry" option in the web app, six agent cases in the evaluation harness, and 37 tests (28 for the agent, 5 for the command line and 4 for the web app).

**How it works.** It searches (ACT), judges the result (CHECK: good, nothing fits, low confidence, or cannot be fixed), changes the request (REVISE) and searches again, at most 3 times:

| Situation | Strategies, in order |
|---|---|
| Nothing fits | drop words that match no song (even through the glossary), keep the single strongest word, rank by the preferences alone |
| Low confidence | relax the optional preferences, compare the other scoring modes and use the best |
| Invalid input or an unexpected error | stop at once, because rewording cannot fix it |

It changes only the request words, the scoring mode and the optional preferences. It cannot skip input validation, the retrieval guardrail or the explanation validator. No language model is used, so the same input always gives the same trace. The glossary is used inside every search, and the per-word match counts the agent uses to decide which words to drop include glossary matches.

**What I checked:**
- **Bugs found by the traces and tests:** invalid input was reported as `first_try` ("kept the original result") when the agent had really given up; ignoring the request ended with the awkward `Answered ""`; with no result at all it reported "recovered" and returned the last rewording instead of the user's own request; and I had coerced bad argument types into valid-looking ones, which would have hidden invalid input from the guardrails. Each now has a test.
- **The retry limit is a tested bound.** A stand-in search function that always fails shows exactly 3 retries and 4 searches, and no strategy is used twice.
- **The agent is honest about changes.** Whenever the answer comes from a reformulated request, the output says what it changed and quotes the original request.
- **Limits I accepted:** ignoring a nonsense request and ranking by preferences gives results that look normal, so the trace and the "Note" line carry the explanation. Switching the scoring mode raises confidence by changing the emphasis, not because the catalog fits better, and the trace says that too.

**Traces.** Real output of `python -m src.agent --record-examples`. A test checks that this block matches what the agent produces now.

<!-- TRACES:START -->
### A word that matches nothing

Request: `jazz zebra` with the Chill Lofi profile (genre lofi, mood chill, energy 0.4, valence 0.6, acousticness 0.8).

```
PLAN    search as typed. If nothing fits: drop words that match no song, then keep the strongest
        word, then rank by the preferences alone. If confidence is Low: relax the optional
        preferences, then compare the other scoring modes. At most 3 retries.
ACT 0   search("jazz zebra", mode=balanced) -> nothing_fits
CHECK   nothing fits. Songs matching each word: jazz 1, zebra 0.
REVISE  drop "zebra", which matches no song even through the glossary, and keep "jazz".
ACT 1   search("jazz", mode=balanced) -> ok, 1 song(s), top confidence High (0.82)
CHECK   good enough: High confidence (0.82).
DECIDE  recovered after 1 retry by changing: dropped "zebra". Answered "jazz" instead of "jazz
        zebra".
```

### No usable words at all

Request: `xylophone zebra` with the Chill Lofi profile (genre lofi, mood chill, energy 0.4, valence 0.6, acousticness 0.8).

```
PLAN    search as typed. If nothing fits: drop words that match no song, then keep the strongest
        word, then rank by the preferences alone. If confidence is Low: relax the optional
        preferences, then compare the other scoring modes. At most 3 retries.
ACT 0   search("xylophone zebra", mode=balanced) -> nothing_fits
CHECK   nothing fits. Songs matching each word: xylophone 0, zebra 0.
REVISE  no word of the request can be used, so rank by the listener's preferences alone.
ACT 1   search("", mode=balanced) -> ok, 5 song(s), top confidence High (0.85)
CHECK   good enough: High confidence (0.85).
DECIDE  recovered after 1 retry by changing: ignored the typed request. Answered using the
        preferences alone instead of "xylophone zebra".
```

### Words that never appear together

Request: `jazz metal` with the Chill Lofi profile (genre lofi, mood chill, energy 0.4, valence 0.6, acousticness 0.8).

```
PLAN    search as typed. If nothing fits: drop words that match no song, then keep the strongest
        word, then rank by the preferences alone. If confidence is Low: relax the optional
        preferences, then compare the other scoring modes. At most 3 retries.
ACT 0   search("jazz metal", mode=balanced) -> nothing_fits
CHECK   nothing fits. Songs matching each word: jazz 1, metal 1.
REVISE  no song matches enough of these words together, so keep the one that matches most songs:
        "jazz" (1).
ACT 1   search("jazz", mode=balanced) -> ok, 1 song(s), top confidence High (0.82)
CHECK   good enough: High confidence (0.82).
DECIDE  recovered after 1 retry by changing: kept only "jazz". Answered "jazz" instead of "jazz
        metal".
```

### Low confidence, so try another scoring mode

Request: `(none)` with the Extreme Targets profile (genre metal, mood peaceful, energy 0.0, valence 1.0, acousticness 0.0).

```
PLAN    search as typed. If nothing fits: drop words that match no song, then keep the strongest
        word, then rank by the preferences alone. If confidence is Low: relax the optional
        preferences, then compare the other scoring modes. At most 3 retries.
ACT 0   search("", mode=balanced) -> ok, 5 song(s), top confidence Low (0.50)
CHECK   low confidence (0.50): the best score is only 0.52, so the catalog does not fit these
        preferences well.
REVISE  compare the other scoring modes on the same catalog (genre-first Medium (0.68), mood-first
        Medium (0.69), energy-focused Medium (0.61)) and use mood-first, which puts the emphasis
        somewhere else; the songs available have not changed.
ACT 1   search("", mode=mood-first) -> ok, 5 song(s), top confidence Medium (0.69)
CHECK   good enough: Medium confidence (0.69).
DECIDE  improved the result by changing: scoring mode balanced to mood-first.
```

### Invalid input is not retried

Request: `(none)` with the Chill Lofi profile and energy 9 (genre lofi, mood chill, energy 9, valence 0.6, acousticness 0.8).

```
PLAN    search as typed. If nothing fits: drop words that match no song, then keep the strongest
        word, then rank by the preferences alone. If confidence is Low: relax the optional
        preferences, then compare the other scoring modes. At most 3 retries.
ACT 0   search("", mode=balanced) -> invalid_input ('energy' must be between 0 and 1, not 9.)
CHECK   this cannot be fixed by rewording: 'energy' must be between 0 and 1, not 9.
DECIDE  stopped without a result and without retrying. 'energy' must be between 0 and 1, not 9.
```
<!-- TRACES:END -->

## 6. Specialization: plain prompt vs constrained prompt

**Prompt:** "Implement and test: compare a plain Gemini prompt against your constrained prompt, with the validator-rejection rate as the measured difference. I have a limited Gemini free tier, so do as much as possible with few calls, and add a simple guardrail if the results suggest one. I don't know which deterministic guardrail works best for nonsense."

**What it produced:** `src/specialization.py` (three prompts with identical facts, a numbered-answer parser, the scoring, a cached and rate-limit-aware runner, and a report), `reports/specialization_raw.json` and `reports/specialization.md` (committed evidence), two guardrails in `src/explain.py`, a harness case, and 26 + 8 tests. It made 19 real Gemini calls, 4 seconds apart, and was built to stop cleanly on a rate limit and to re-score saved replies with no calls.

**What I checked:**
- **Cost control.** All tests use a fake model, so the experiment's logic was verified before any call. A full re-run costs 0 calls because replies are cached by prompt hash, and a rate limit (HTTP 429) stops the run and keeps what was collected.
- **A fair comparison.** A test checks that all three prompts contain exactly the same fact lines, so only the instructions differ.
- **The result.** Plain prompt: 100% of sentences rejected, 47 words on average. Constrained: 0% rejected, 16.5 words. Few-shot: 0% rejected, 19 words (no gain over constrained).
- **A weakness in my own validator.** While designing the injection test, I checked it without any API call: the validator allowed every word of the typed request, so planted text such as "banana" would pass. Fix: only matched request words are sent to the model and only those are allowed back. Three mutation checks (word cap off, request words allowed again, whole request sent to the model again) failed 1, 5 and 7 tests.
- **A guardrail chosen from data, not guesswork.** Constrained sentences never exceeded 22 words and plain ones never went below 40, so a 30-word cap separates them. The most effective guardrail against nonsense in the request turned out to be structural, not a blocklist: retrieval already refuses requests with too few matching words, and now the model never sees the unmatched words at all.
- **An honest null result.** Two live injection attempts (one forceful "SYSTEM OVERRIDE") were both ignored by Gemini, so the new protection is defense in depth that I proved with a fake model that obeys, not a leak I observed.
- **What I did not do:** I did not add "plus" (a harmless word the validator once rejected) to the allowed list. One observation is not enough evidence, and the strictness is the point.
