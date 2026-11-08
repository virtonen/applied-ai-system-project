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
- **Guardrails and logging.** Bad input or a bad song file gives a clear message. Every search is logged as one JSON line. Details are in the [README](README.md#whats-new-in-this-step-logging-guardrails-and-confidence).

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
- **The validator checks words, not meaning.** It stops invented genres, years, artists, instruments and numbers, but a sentence made only of allowed words could still say something false. It is also strict, so a harmless synonym is rejected and the fact-based sentence is shown instead.
- **Confidence is not accuracy.** It measures how well the catalog fits the request, not whether the listener will like the song. Its weights and thresholds were tuned on the same 10 demo profiles used in the tests, so they are not independently validated.

## 5. Evaluation

186 automated tests pass (`python -m pytest`). The 10 demo profiles are 3 typical listeners (High-Energy Pop, Chill Lofi, Deep Intense Rock), 3 adversarial ones (Sad but Energetic, Unknown Genre and Mood, Extreme Targets) and 4 using the advanced features.

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
| Live Gemini call (2 real calls during development) | Reply validated and accepted for both songs |

Breaking the code on purpose made tests fail: weakening the confidence weights failed 7 tests, and removing the CSV range check failed 1.

**What surprised me.** My first confidence formula (0.6 strength, 0.2 separation, 0.2 coverage, coverage 1.0 by default) rated the poor Extreme Targets result Medium, and it penalized two excellent songs for nearly tying. I only saw this by running it on the adversarial profiles.

## 6. Reflection and ethics

**Privacy and key handling (so far).** The API key is read from a gitignored `.env` or the environment, sent in a request header, and never logged. When the Gemini option is on, the song facts and the typed request are sent to Google. Nothing is sent unless the checkbox is ticked.

_To be completed at the end of the project: misuse and how to prevent it, how I collaborated with AI, one suggestion I accepted and one I rejected or changed._

The AI's first confidence formula was revised after testing (see the surprise above) to weight the song's score more and leave out coverage when there is no typed request.
