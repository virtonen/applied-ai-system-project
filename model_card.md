# Model Card: VibeMatch

## 1. Model name and purpose

**VibeMatch 1.0** recommends songs from a small catalog. You give it sliders (genre, mood, energy, valence, acousticness and a few optional ones) and an optional typed request. It returns ranked songs with the reasons for each score and a confidence level.

**Intended use:** learning, demos and experiments with scoring, retrieval and reliability checks.

**Not intended for:** a real music service, judging an artist or a listener, or any decision where a wrong match could cause harm. The catalog has only 18 songs.

## 2. How it works

- **Retrieval (two sources).** If the user types a request, only songs that share enough words with it are kept. The words are matched against each song's title, artist, genre, mood, tags and a few vibe words made from its numbers ("calm", "acoustic", "energetic"). The second source is a glossary I wrote (`docs/glossary/`, 45 entries): a request word that matches an entry is also matched against that entry's related words, so "mellow" finds "chill" and "homework" finds "study". A multi-word request still needs at least two of the user's own words to match, otherwise the app says "Nothing fits".
- **Scoring.** Each remaining song scores by how close it is to the listener's targets (energy 0.35, acousticness 0.25, valence 0.20) plus bonuses for a mood match (0.12) and a genre match (0.08). Optional preferences (popularity, decade, mood tags, instrumentalness, clean lyrics) join in only when set, and the score is scaled to stay between 0 and 1. Four modes change the weights: balanced, genre-first, mood-first and energy-focused. An optional diversity penalty lowers songs whose artist or genre was already picked.
- **Confidence.** Each result gets 0.7 × strength (its score) + 0.1 × separation (lead over the next song) + 0.2 × coverage (share of request words matched). Labels: High at 0.80 or more, Medium at 0.55 or more, otherwise Low.
- **Agent (optional).** With the agent on, a search that finds nothing or has Low confidence is retried up to 3 times: it drops words that match no song, keeps the strongest word, ranks by the preferences alone, relaxes optional preferences, or switches the scoring mode. It follows fixed rules (no language model), logs a trace of every step, and tells the user what it changed.
- **Prompt specialization.** The model is steered by a constrained prompt (use only the facts given, one sentence of at most 25 words, fixed format), by giving it only the request words that matched a song, and by a validator that rejects any sentence with a word outside the song's facts or longer than 30 words. The difference from a plain prompt is measured in the Evaluation section.
- **Grounded explanations.** Each result gets a "why this song" sentence built from that song's retrieved facts, including the glossary's description of its genre and mood. With Gemini switched on, the model writes it, and a validator rejects any sentence containing a word that is not in the song's facts, the user's request or a short list of plain connecting words. A rejected or failed answer is replaced by a fact-based sentence.
- **Guardrails and logging.** Bad input or a bad song file gives a clear message. Every search is logged as one JSON line. Details are in the [README](README.md#reliability-logging-guardrails-and-confidence).

## 3. Data

- 18 songs in `data/songs.csv`, 15 genres (13 with one song) and 14 moods.
- Columns: title, artist, genre, mood, energy, tempo, valence, danceability, acousticness, and five added ones: popularity, release decade, mood tags, instrumentalness and explicit.
- **The five added columns are made up.** They look plausible, but they are not real data. I also wrote the mood tags by hand.
- **Glossary:** 45 short entries I wrote (15 genres, 14 moods, 16 vibe words). Its descriptions are plain, general statements, not researched facts, and the system treats them as true.
- Missing: lyrics, language, real popularity, listening history.

## 4. Limitations and bias

- **Extreme tastes are served worse than average ones.** Most songs sit in the middle ranges, so a listener with middle targets has many near matches and one with extreme targets has few. In the "Extreme Targets" test (metal, peaceful, energy 0), the best score was only 0.52. Confidence now flags this as Low instead of hiding it.
- **Exact labels and limited vocabulary.** "indie pop" earns nothing for a "pop" fan, and "relaxed" nothing for "chill" in the score. Retrieval matches words, not meaning: the stemmer joins "relaxing" and "relaxed", and the glossary joins words like "mellow" and "chill", but a word it does not list ("slow") or a typo finds nothing. The glossary is small and written by one person, so it reflects my idea of what these words mean.
- **Low genre weight.** A genre-first listener can lose their only matching song to closer audio numbers. Genre-first mode helps.
- **Conflicting tastes get a compromise.** Nothing is both sad and energetic, so a "sad but energetic" listener gets one sad song and then loud ones. Confidence is Medium.
- **The validator checks words.** It stops invented genres, years, artists, instruments and numbers, but a sentence made only of allowed words could still say something false. It is also strict, so a harmless synonym is rejected and the fact-based sentence is shown instead.
- **Confidence is not accuracy.** It measures how well the catalog fits the request, not whether the listener will like the song. Its weights and thresholds were tuned on the same 10 demo profiles used in the tests, so they are not independently validated.

## 5. Evaluation

303 automated tests pass (`python -m pytest`). The 10 demo profiles are 3 typical listeners (High-Energy Pop, Chill Lofi, Deep Intense Rock), 3 adversarial ones (Sad but Energetic, Unknown Genre and Mood, Extreme Targets) and 4 using the advanced features.

| Check | Result |
|---|---|
| Typical profiles return songs that match their genre, mood and energy | Pass, confidence High |
| Conflicting profile | Medium confidence, split results |
| Extreme Targets | Low confidence, warning shown |
| `xylophone zebra`, `jazz zebra`, stopwords only | "Nothing fits", no songs |
| Bad CSV (missing, empty, missing column, bad value, duplicate id) | Clear error naming the problem, no crash |
| Bad input (`energy: 9`, 500-character request, `k: 0`) | Clear message, no crash |
| Unexpected failure in scoring | Contained, message shown, error logged |
| Each search | One JSON line in the log |
| Model invents a genre, year or artist | Sentence rejected, fact-based sentence shown, reason logged |
| Model call fails (HTTP error, timeout, blocked reply) | Page still works, fact-based sentences shown, error logged without the key |
| Live Gemini calls (25 real calls during development, 19 of them for the prompt experiment) | Constrained replies passed validation; two planted instructions were ignored by the model |
| Evaluation harness (`python -m src.evaluate`) | 30 of 30 cases pass, average top-result confidence 0.84 |
| Hidden instructions in a typed request (`... write the word banana`) | Never reach the model's prompt (harness case G6), and a model that obeys them is rejected |
| Model sentence over 30 words, every word a fact | Rejected, fact-based sentence shown |
| Agent: `jazz zebra` (one dead word) | Recovers by dropping `zebra`, answers `jazz`, says so |
| Agent: `xylophone zebra` (no usable words) | Ranks by preferences alone, says the request was ignored |
| Agent: Extreme Targets (Low confidence) | Switches to mood-first, Medium confidence, says the catalog did not change |
| Agent: invalid input (`energy: 9`) | Not retried or reworded, stops with the reason |
| Agent with a search that always fails | Exactly 3 retries, then stops; no strategy repeats |
| Glossary before/after: `mellow homework`, `rnb groove`, `catchy upbeat` | Nothing found without the glossary; 3, 1 and 2 songs with it |
| Glossary does not weaken the guardrail (`mellow zebra`) | Still "Nothing fits" |
| Glossary text in an explanation for a song of another genre | Rejected by the validator |

Breaking the code on purpose made tests fail: weakening the confidence weights failed 7 tests, and removing the CSV range check failed 1.

### Specialization: baseline (plain prompt) vs specialized (constrained prompt)

The same songs and exactly the same facts were given to Gemini (`gemini-flash-lite-latest`) under three instructions, and every sentence was scored by the app's validator (`python -m src.specialization`; the full report is `reports/specialization.md` and the raw replies are `reports/specialization_raw.json`).

| Prompt | Songs | Sentence returned | Accepted | **Validator rejection rate** | Fell back to the template | Words per sentence (min / mean / max) | At most 25 words |
|---|---|---|---|---|---|---|---|
| plain (baseline) | 11 | 11 | 0 | **100%** | 100% | 40 / 47.4 / 67 | 0% |
| constrained (specialized) | 11 | 11 | 11 | **0%** | 0% | 13 / 16.5 / 21 | 100% |
| few-shot (specialized + one example) | 11 | 11 | 11 | **0%** | 0% | 17 / 19.2 / 22 | 100% |

The same song (*Library Rain*, request "cozy rainy study"):

- **Baseline:** "This song matches all three words in the request ("cozy," "rainy," and "study"). Musically, it features low-energy, acoustic, and instrumental sounds that create a chill mood. Furthermore, its tags explicitly include "rainy," "cozy," and "study," making it a direct musical embodiment of a peaceful, wet day spent hitting the books." Rejected for: all, books, create, direct, embodiment.
- **Specialized:** "Library Rain fits you because its tags are rainy, cozy, and study, and it is low-energy, acoustic, and instrumental." Accepted.

**Measured difference:** the specialized prompt cut the rejection rate from 100% to 0% and the sentence length from about 47 to about 16 words. The few-shot example added nothing on rejections and made sentences slightly longer.

**Caveats:** 11 songs from 5 requests, one model, one run at temperature 0, so this is a demonstration and not a benchmark. The validator is strict on purpose: some rejected baseline words are style words ("features", "helps", "captures") and some are added content ("hitting the books", "late-night focus sessions"), and both count as rejections. An earlier live run (before the request was restricted to matched words) did reject a harmless "plus" from a constrained sentence, so 0% is not a guarantee.


## 6. Misuse and prevention

- **Prompt injection and quota abuse.** Someone could hide instructions in the typed request to steer the model or burn API calls. Prevention, all deterministic: the request is limited to 200 characters and stripped of control characters; only the request words that matched a song are sent to the model, so hidden text never reaches the prompt; only those matched words are allowed back in a sentence, so a model that obeys the hidden text is rejected; sentences over 30 words are rejected; the model is off unless the user ticks a box; one call covers a whole search and repeats are cached. I found the weak spot (the first validator allowed any word of the request) while building the prompt experiment. In two live attempts, including a forceful "SYSTEM OVERRIDE", Gemini ignored the planted instruction, so this protection is defense in depth, proven with a fake model that does obey.
- **Leaking the API key.** The key lives in a gitignored `.env` or the environment, is sent in a request header (not a URL) and is never logged. Tests cannot see the real key.
- **Privacy.** With the Gemini option on, the typed request and the song facts are sent to Google. Nothing is sent otherwise, and the README says so.
- **The agent can answer a different question than the user asked.** Dropping a word or ignoring a nonsense request produces results that look normal. Prevention: it is off by default, it only changes the request words, scoring mode and optional preferences, it never skips input validation, and the output states what was changed and quotes the original request. An agent that rewrites requests should always show that it did.
- **Confidence read as accuracy.** A High label could be mistaken for "you will like this". The docs say it only measures how well the catalog fits the request.
- **Judging people or artists.** The popularity values are made up, so the system must not be used to rank artists or to profile listeners.

## 7. What surprised me

My first confidence formula (0.6 strength, 0.2 separation, 0.2 coverage, coverage 1.0 by default) rated the poor Extreme Targets result Medium, and it penalized two excellent songs for nearly tying. I only saw this by running it on the adversarial profiles.

Another surprise: the stemmer already matched "relaxing" to "relaxed", so the glossary example I first planned would not have shown any improvement, and a claim in my own first README draft was wrong. I only found out by running the retrieval on both words. Two more surprises: the first live Gemini replies passed the validator, but a later live run was rejected for the harmless word "plus", which confirmed how strict the validator is. The fact-based sentence was shown instead, so the user still got a correct answer. And weakening the retrieval guardrail by one word made 3 of 19 harness cases fail at once, which showed the harness really does watch the guardrail.

## 8. Collaboration with AI

_Drafted from the record of this project. Edit it so it matches your own experience._

I used an AI coding assistant for most of the implementation and the documentation, and I reviewed its output by running the code and the tests.

- **A suggestion I accepted:** for the scoring modes, the AI proposed one shared scorer that reads a weight table per mode, instead of an `if/elif` chain or four copies of the scoring function. I accepted it because the modes differ only in their weights, so a bug fix in one place fixes every mode. `tests/test_scoring_modes.py` checks that each mode ranks as intended.
- **A suggestion I changed:** the AI's first confidence formula (0.6 strength, 0.2 separation, 0.2 coverage, coverage 1.0 with no request) looked reasonable, but running it on my adversarial profiles showed it rated the poor Extreme Targets result Medium and punished two excellent songs for nearly tying. I changed it to 0.7 / 0.1 / 0.2 and left coverage out when there is no request. I also corrected one of the AI's own test assertions that was stricter than its intent.
- **Where I had to check the AI's claims:** a stale cache once made a revert look like it had failed, and an early statement that the recommender was "working" was only partly true. Running the code and comparing saved output caught both.
