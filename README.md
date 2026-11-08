# 🎧 VibeMatch: a music recommender with search, guardrails and confidence

VibeMatch recommends songs from a small catalog. You describe your taste with sliders and an optional typed request ("cozy rainy study"). It returns ranked songs, the reasons behind each score, and a **confidence level** that says how far to trust the result. If nothing fits, it says so instead of guessing.

## Original project

This extends my **Module 3 project, the Music Recommender Simulation**. That project loaded 18 songs from a CSV, scored every song against a listener profile (energy, valence and acousticness closeness, plus mood and genre matches), and printed the top results with a plain-English reason for each score. It also gained scoring modes (genre-first, mood-first, energy-focused), a diversity penalty and five extra song features. This project turns it into a small applied AI system: a web UI, keyword retrieval ported from my DocuBot project, and (this step) logging, guardrails and confidence scoring.

## Architecture overview

The diagram is in [diagrams/architecture.mmd](diagrams/architecture.mmd) (Mermaid source). Data flows like this:

1. **UI** ([app.py](app.py)) collects a typed request and preferences.
2. **Input guardrails** check them. Bad input gets a clear message, never a crash.
3. **Retriever** ([src/retrieval.py](src/retrieval.py)) finds songs whose text matches the request. If too few words match, it returns nothing and the UI says "Nothing fits".
4. **Scorer** ([src/recommender.py](src/recommender.py)) ranks the candidates with the chosen mode and an optional diversity penalty.
5. **Confidence** ([src/confidence.py](src/confidence.py)) rates each result.
6. **Logger** ([src/logging_utils.py](src/logging_utils.py)) writes one line per search to `logs/recommender.log`.
7. **People and tests check the output:** a person reads the table, reasons, confidence and log, and 149 automated tests check each stage.

## Setup

Run these from the project root (the folder containing `app.py`).

```bash
python3 -m venv .venv
source .venv/bin/activate        # Mac or Linux
.venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

## Run

```bash
python -m streamlit run app.py          # web app, usually http://localhost:8501
python -m src.main --table              # terminal view of the demo profiles
python -m pytest                        # all tests (use python -m, not bare pytest)
```

Optional environment variables: `VIBEMATCH_DATA` (path to another song CSV) and `VIBEMATCH_LOG_FILE` (path for the log).

## What's new in this step: logging, guardrails and confidence

**Logging.** Every search writes one JSON line to `logs/recommender.log` (ignored by git): the query, matched words, mode, result count, top song, confidence, time taken and any error. Load failures are logged too. Logging never raises, so a full disk or a bad path cannot break the app.

```json
{"ts": "2026-11-08T15:17:39+00:00", "event": "search", "query": "cozy rainy study", "matched_words": ["cozy", "rainy", "study"], "mode": "balanced", "diverse": false, "k": 3, "status": "ok", "result_count": 2, "top_title": "Library Rain", "top_confidence": 0.8822, "confidence_label": "High", "elapsed_ms": 0.07, "error": null}
```

**Guardrails** ([src/guardrails.py](src/guardrails.py)):

| Where | What is checked | What the user sees |
|---|---|---|
| Song file | file exists, not empty, has a header and every required column, no duplicate ids, every value has the right type and range (0–1 features, 0–100 popularity, explicit is 0 or 1) | "The song list could not be loaded. Line 7: 'energy' must be between 0 and 1, not 1.5." |
| Typed request | is text, control characters removed, spaces cleaned, at most 200 characters | "Please check your input. Search text is too long." |
| Preferences, k, mode | numbers in range, tags are a list of text, k from 1 to 50, mode exists | "'energy' must be between 0 and 1, not 9." |
| Retrieval | at least 2 request words must match a song (1 for a one-word request) | "Nothing fits: no songs match "xylophone zebra"." |
| Anything unexpected | caught in the pipeline | a short message, with the full error in the log |

**Confidence** ([src/confidence.py](src/confidence.py)). Each result gets a value from 0 to 1 and a label, shown in the table and in each result's reasons:

`confidence = 0.7 × strength + 0.1 × separation + 0.2 × coverage`

- **strength:** the song's score.
- **separation:** how far it leads the next song (a lead of 0.10 or more counts as full).
- **coverage:** the share of typed-request words the song matched. With no request this part is left out and the other two are scaled up.
- **Labels:** High at 0.80 or more, Medium at 0.55 or more, otherwise Low. A Low top result shows a warning. This replaced my earlier fixed "score below 0.6" check.

## Sample interactions

Profile: **Chill Lofi** (lofi, chill, energy 0.4, valence 0.6, acousticness 0.8).

**1. A typed request**, input `cozy rainy study`:

| # | Song | Score | Confidence | Matched words |
|---|---|---|---|---|
| 1 | Library Rain, Paper Lanterns | 0.97 | High (0.88) | cozy, rainy, study |
| 2 | Midnight Coding, LoRoom | 0.96 | High (0.91) | cozy, study |

Only these two songs share enough words with the request. Midnight Coding matched 2 of 3 words, so its coverage is 0.67.

**2. Nonsense**, input `xylophone zebra`: status `nothing_fits`, message `Nothing fits: no songs match "xylophone zebra".` No songs are shown.

**3. A poor fit**, profile **Extreme Targets** (metal, peaceful, energy 0, valence 1, acousticness 0), no typed request:

| # | Song | Score | Confidence |
|---|---|---|---|
| 1 | Birchwood Lullaby, Moss & Ember | 0.52 | Low (0.50) |
| 2 | Velvet Hours, Marisol Kane | 0.48 | Low (0.43) |
| 3 | Island Sway, Sol Rivera | 0.48 | Low (0.47) |

The app still shows the closest songs, but with a "Low confidence" warning that they are not a good fit.

**4. Bad input**, preference `energy: 9`: status `invalid_input`, message `'energy' must be between 0 and 1, not 9.`

## Design decisions

- **Keyword retrieval, not embeddings.** It is simple, deterministic and testable, and it reuses DocuBot's tokenizer, index and refusal guardrail. The cost: it only finds words that appear in a song's title, artist, genre, mood, tags or a few vibe words, so "relaxing" will not find "relaxed".
- **Retrieval narrows, the scorer ranks.** The sliders decide the order among the songs the request found.
- **Strength dominates confidence.** My first formula (0.6 / 0.2 / 0.2) rated the poor "Extreme Targets" result Medium and punished two great songs for nearly tying. I changed it to 0.7 / 0.1 / 0.2 and left coverage out when there is no request.
- **Strict CSV validation that fails fast.** A bad file stops the app with the line number, which is better than quietly ranking bad data.
- **JSON-lines log.** Easy to read and to parse.

## Testing summary

All **149 tests pass** (`python -m pytest`).

| File | Tests | Covers |
|---|---|---|
| `test_guardrails.py` | 31 | every CSV and input check, with the exact error text |
| `test_pipeline.py` | 18 | statuses, matched words, contained failures, and the content of each log line |
| `test_confidence.py` | 11 | bounds, monotonic behavior, exact values, labels, calibration on the demo profiles |
| `test_retrieval.py` | 22 | stemming, stopwords, expected hits per query, the guardrail on nonsense |
| `test_app.py` | 17 | the Streamlit page (via `AppTest`): results, search box, confidence, error screens |
| `test_evaluate.py` | 23 | the evaluation harness itself: it passes every built-in case, catches each kind of failure, writes a stable report, updates the README, sets the exit code |
| `test_scoring_modes.py`, `test_diversity.py`, `test_table.py`, `test_recommender.py` | 27 | scoring modes, diversity penalty, table output, starter tests |

Confidence on the 10 demo profiles (no typed request):

| Profile | Top score | Confidence |
|---|---|---|
| High-Energy Pop, Chill Lofi, Deep Intense Rock, Mainstream Hits, Nostalgic Throwback, Instrumental Study Session, Clean Workout | 0.91–0.99 | High |
| Conflicting: Sad but Energetic | 0.71 | Medium |
| Unknown Genre and Mood | 0.72 | Medium |
| Extreme Targets | 0.52 | Low |

### Evaluation harness

`python -m src.evaluate` runs 19 predefined cases (listener profiles, scoring modes, the diversity penalty, typed requests and guardrails) through the real search pipeline. It checks each against what it should return (top song, exact list, songs included or excluded, confidence label, status), prints pass/fail with confidence, writes [reports/evaluation.md](reports/evaluation.md), and exits with code 1 if any case fails. `python -m src.evaluate --readme` refreshes the table below.

<!-- EVAL:START -->
| ID | What it checks | Expected | Result | Top song | Confidence |
|---|---|---|---|---|---|
| P1 | High-Energy Pop: the pop/happy song wins | top = Sunrise City; includes Gym Hero, Rooftop Lights; confidence High | PASS | Sunrise City | High (0.96) |
| P2 | Chill Lofi: both lofi/chill songs lead | includes Library Rain, Midnight Coding; confidence High | PASS | Library Rain | High (0.85) |
| P3 | Deep Intense Rock: the one rock song wins | top = Storm Runner; confidence High | PASS | Storm Runner | High (0.99) |
| P4 | Nostalgic Throwback uses decade, popularity and tags | top = Dust Road Home; confidence High | PASS | Dust Road Home | High (0.99) |
| P5 | Sad but Energetic: a compromise, so only Medium confidence | top = Adagio for Rain; confidence Medium | PASS | Adagio for Rain | Medium (0.74) |
| P6 | Extreme Targets: a poor fit must be flagged Low | top = Birchwood Lullaby; confidence Low | PASS | Birchwood Lullaby | Low (0.50) |
| P7 | Clean Workout: the explicit song stays out of the top 3 | top = Storm Runner; excludes Iron Requiem | PASS | Storm Runner | High (0.84) |
| M1 | Mood-first ranks a happy song above the intense Gym Hero | Rooftop Lights above Gym Hero | PASS | Sunrise City | High (0.97) |
| M2 | Genre-first puts the only metal song first for the metal fan | top = Iron Requiem | PASS | Iron Requiem | Medium (0.68) |
| D1 | Diversity penalty: one song per artist for Chill Lofi | max 1 per artist | PASS | Library Rain | High (0.95) |
| S1 | 'cozy rainy study' finds exactly the two songs with those tags | exactly Library Rain, Midnight Coding; confidence High | PASS | Library Rain | High (0.88) |
| S2 | A one-word request is enough: 'jazz' | exactly Coffee Shop Stories | PASS | Coffee Shop Stories | High (0.82) |
| S3 | Vibe words from numbers: 'workout powerful' | exactly Gym Hero | PASS | Gym Hero | High (0.89) |
| S4 | 'calm acoustic' returns a full list that includes Library Rain | includes Library Rain | PASS | Library Rain | High (0.97) |
| G1 | Nonsense words: nothing fits | nothing_fits | PASS | - | - |
| G2 | One real word and one unknown word: refused | nothing_fits | PASS | - | - |
| G3 | Only filler words: nothing fits | nothing_fits | PASS | - | - |
| G4 | Out-of-range energy is rejected with a reason | invalid_input; message has ''energy' must be between 0 and 1' | PASS | - | - |
| G5 | A 500-character request is rejected | invalid_input; message has 'too long' | PASS | - | - |

19 of 19 cases passed (100%). Average top-result confidence 0.86 across 14 cases that returned songs (High 11, Medium 2, Low 1).
<!-- EVAL:END -->

The expected results were written from behavior I had already inspected, so this harness guards against regressions and checks the guardrails. It is not an independent measure of recommendation quality.

What worked: breaking the code on purpose made tests fail (weakening the confidence weights failed 7 tests, and removing the CSV range check failed 1). What I learned: my first confidence formula looked fine until I ran it on the adversarial profiles.

## Limitations

- Only 18 songs, and I wrote the mood tags by hand.
- The confidence weights and thresholds were tuned by looking at the same 10 demo profiles used in the tests, so they are not independently validated. Confidence says how well the catalog fits the request, not whether you will like the song.
- Retrieval needs exact words (after light stemming).

## What's next

An evaluation script with expected results, grounded explanations built from the retrieved text, a larger dataset, and possibly a self-critique retry loop. The diagram will be updated after each step. My responsible-AI reflection is in [model_card.md](model_card.md).
