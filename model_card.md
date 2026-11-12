# Model Card: VibeMatch

## 1. Model name and purpose

**VibeMatch 1.0** recommends songs from a small catalog. You give it sliders (genre, mood, energy, valence, acousticness and a few optional ones) and an optional typed request. It returns ranked songs with the reasons for each score and a confidence level.

**Intended use:** learning, demos and experiments with scoring, retrieval and reliability checks.

**Not intended for:** a real music service, judging an artist or a listener, or any decision where a wrong match could cause harm. The catalog has only 18 songs.

## 2. How it works

- **Retrieval.** If the user types a request, only songs that share enough words with it are kept. The words are matched against each song's title, artist, genre, mood, tags and a few vibe words made from its numbers ("calm", "acoustic", "energetic"). A multi-word request needs at least two matching words, otherwise the app says "Nothing fits".
- **Scoring.** Each remaining song scores by how close it is to the listener's targets (energy 0.35, acousticness 0.25, valence 0.20) plus bonuses for a mood match (0.12) and a genre match (0.08). Optional preferences (popularity, decade, mood tags, instrumentalness, clean lyrics) join in only when set, and the score is scaled to stay between 0 and 1. Four modes change the weights: balanced, genre-first, mood-first and energy-focused. An optional diversity penalty lowers songs whose artist or genre was already picked.
- **Confidence.** Each result gets 0.7 × strength (its score) + 0.1 × separation (lead over the next song) + 0.2 × coverage (share of request words matched). Labels: High at 0.80 or more, Medium at 0.55 or more, otherwise Low.
- **Grounded explanations.** Each result gets a "why this song" sentence built from that song's retrieved facts. With Gemini switched on, the model writes it, and a validator rejects any sentence containing a word that is not in the song's facts, the user's request or a short list of plain connecting words. A rejected or failed answer is replaced by a fact-based sentence.
- **Guardrails and logging.** Bad input or a bad song file gives a clear message. Every search is logged as one JSON line. Details are in the [README](README.md#reliability-logging-guardrails-and-confidence).

## 3. Data

- 18 songs in `data/songs.csv`, 15 genres (13 with one song) and 14 moods.
- Columns: title, artist, genre, mood, energy, tempo, valence, danceability, acousticness, and five added ones: popularity, release decade, mood tags, instrumentalness and explicit.
- **The five added columns are made up.** They look plausible, but they are not real data. I also wrote the mood tags by hand.
- Missing: lyrics, language, real popularity, listening history.

## 4. Limitations and bias

- **Extreme tastes are served worse than average ones.** Most songs sit in the middle ranges, so a listener with middle targets has many near matches and one with extreme targets has few. In the "Extreme Targets" test (metal, peaceful, energy 0), the best score was only 0.52. Confidence now flags this as Low instead of hiding it.
- **Exact labels.** "indie pop" earns nothing for a "pop" fan, and "relaxed" nothing for "chill". Retrieval also needs exact words, so "relaxing" will not find "relaxed".
- **Low genre weight.** A genre-first listener can lose their only matching song to closer audio numbers. Genre-first mode helps.
- **Conflicting tastes get a compromise.** Nothing is both sad and energetic, so a "sad but energetic" listener gets one sad song and then loud ones. Confidence is Medium.
- **The validator checks words.** It stops invented genres, years, artists, instruments and numbers, but a sentence made only of allowed words could still say something false. It is also strict, so a harmless synonym is rejected and the fact-based sentence is shown instead.
- **Confidence is not accuracy.** It measures how well the catalog fits the request, not whether the listener will like the song. Its weights and thresholds were tuned on the same 10 demo profiles used in the tests, so they are not independently validated.

## 5. Evaluation

184 automated tests pass (`python -m pytest`). The 10 demo profiles are 3 typical listeners (High-Energy Pop, Chill Lofi, Deep Intense Rock), 3 adversarial ones (Sad but Energetic, Unknown Genre and Mood, Extreme Targets) and 4 using the advanced features.

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
| Live Gemini calls (3 real calls during development, including the README screenshot) | Replies passed validation |
| Evaluation harness (`python -m src.evaluate`) | 19 of 19 cases pass, average top-result confidence 0.86 |

Breaking the code on purpose made tests fail: weakening the confidence weights failed 7 tests, and removing the CSV range check failed 1.

## 6. Misuse and prevention

- **Prompt injection and quota abuse.** The typed request is placed in the model's prompt, so someone could try to steer the model or burn API calls. Prevention: the request is limited to 200 characters and stripped of control characters; the model is off unless the user ticks a box; one call covers a whole search and repeats are cached; and the output is checked word by word, so injected instructions cannot make the app show text that is not in the song facts.
- **Leaking the API key.** The key lives in a gitignored `.env` or the environment, is sent in a request header (not a URL) and is never logged. Tests cannot see the real key.
- **Privacy.** With the Gemini option on, the typed request and the song facts are sent to Google. Nothing is sent otherwise, and the README says so.
- **Confidence read as accuracy.** A High label could be mistaken for "you will like this". The docs say it only measures how well the catalog fits the request.
- **Judging people or artists.** The popularity values are made up, so the system must not be used to rank artists or to profile listeners.

## 7. What surprised me

My first confidence formula (0.6 strength, 0.2 separation, 0.2 coverage, coverage 1.0 by default) rated the poor Extreme Targets result Medium, and it penalized two excellent songs for nearly tying. I only saw this by running it on the adversarial profiles.

Two more surprises: the live Gemini reply passed the validator on the first try, but the validator is strict enough that I expect harmless synonyms to be rejected often, so that is untested. And weakening the retrieval guardrail by one word made 3 of 19 harness cases fail at once, which showed the harness really does watch the guardrail.

## 8. Collaboration with AI

_Drafted from the record of this project. Edit it so it matches your own experience._

I used an AI coding assistant for most of the implementation and the documentation, and I reviewed its output by running the code and the tests.

- **A suggestion I accepted:** for the scoring modes, the AI proposed one shared scorer that reads a weight table per mode, instead of an `if/elif` chain or four copies of the scoring function. I accepted it because the modes differ only in their weights, so a bug fix in one place fixes every mode. `tests/test_scoring_modes.py` checks that each mode ranks as intended.
- **A suggestion I changed:** the AI's first confidence formula (0.6 strength, 0.2 separation, 0.2 coverage, coverage 1.0 with no request) looked reasonable, but running it on my adversarial profiles showed it rated the poor Extreme Targets result Medium and punished two excellent songs for nearly tying. I changed it to 0.7 / 0.1 / 0.2 and left coverage out when there is no request. I also corrected one of the AI's own test assertions that was stricter than its intent.
- **Where I had to check the AI's claims:** a stale cache once made a revert look like it had failed, and an early statement that the recommender was "working" was only partly true. Running the code and comparing saved output caught both.
