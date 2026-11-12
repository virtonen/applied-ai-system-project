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

**What it produced:** `src/evaluate.py` with 19 cases (later 23), a markdown report, an optional README refresh, and an exit code for failures; plus `tests/test_evaluate.py`.

**What I checked:** I weakened the retrieval guardrail on purpose and the harness flagged 3 of 19 cases (it now has 23 cases, including the glossary ones). I also noted in the README that the expected results came from behavior I had already inspected, so the harness guards against regressions and is not an independent measure of quality.

## 3. Grounded explanations (RAG with validation)

**Prompt:** "Add a grounded 'why this song' explanation built from the retrieved text. If you use an LLM, add a validator that rejects any sentence mentioning facts not in the retrieved song text."

**What it produced:** `src/explain.py` (facts, template sentence, word-level validator, one Gemini call per search with fallback and caching), `src/llm_client.py` (standard-library Gemini client, key from `.env`), a sidebar option, and 31 offline tests (they use a fake model, so they make no API calls).

**What I checked:**
- I confirmed that the template passes its own validator for every song, with and without a request.
- I broke the validator on purpose and 10 tests failed.
- I made six real Gemini calls in total (one probe, one live test, one for the README screenshot, three for README sample runs); every reply passed validation.
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
