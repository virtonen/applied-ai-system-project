# Evaluation results

Run with `python -m src.evaluate`.

| ID | What it checks | Expected | Result | Top song | Confidence |
|---|---|---|---|---|---|
| P1 | High-Energy Pop: the pop/happy song wins | top = Sunrise City; includes Gym Hero, Rooftop Lights; confidence High; grounded explanations | PASS | Sunrise City | High (0.96) |
| P2 | Chill Lofi: both lofi/chill songs lead | includes Library Rain, Midnight Coding; confidence High | PASS | Library Rain | High (0.85) |
| P3 | Deep Intense Rock: the one rock song wins | top = Storm Runner; confidence High | PASS | Storm Runner | High (0.99) |
| P4 | Nostalgic Throwback uses decade, popularity and tags | top = Dust Road Home; confidence High | PASS | Dust Road Home | High (0.99) |
| P5 | Sad but Energetic: a compromise, so only Medium confidence | top = Adagio for Rain; confidence Medium | PASS | Adagio for Rain | Medium (0.74) |
| P6 | Extreme Targets: a poor fit must be flagged Low | top = Birchwood Lullaby; confidence Low | PASS | Birchwood Lullaby | Low (0.50) |
| P7 | Clean Workout: the explicit song stays out of the top 3 | top = Storm Runner; excludes Iron Requiem | PASS | Storm Runner | High (0.84) |
| M1 | Mood-first ranks a happy song above the intense Gym Hero | Rooftop Lights above Gym Hero | PASS | Sunrise City | High (0.97) |
| M2 | Genre-first puts the only metal song first for the metal fan | top = Iron Requiem | PASS | Iron Requiem | Medium (0.68) |
| D1 | Diversity penalty: one song per artist for Chill Lofi | max 1 per artist | PASS | Library Rain | High (0.95) |
| S1 | 'cozy rainy study' finds exactly the two songs with those tags | exactly Library Rain, Midnight Coding; confidence High; grounded explanations | PASS | Library Rain | High (0.88) |
| S2 | A one-word request is enough: 'jazz' | exactly Coffee Shop Stories | PASS | Coffee Shop Stories | High (0.82) |
| S3 | Vibe words from numbers: 'workout powerful' | exactly Gym Hero | PASS | Gym Hero | High (0.89) |
| S4 | 'calm acoustic' returns a full list that includes Library Rain | includes Library Rain; grounded explanations | PASS | Library Rain | High (0.97) |
| R1 | Glossary: 'mellow homework' reaches chill and study songs | exactly Library Rain, Midnight Coding, Focus Flow; confidence High; grounded explanations | PASS | Library Rain | High (0.88) |
| R2 | The same request without the glossary finds nothing | nothing_fits | PASS | - | - |
| R3 | Glossary: 'rnb groove' reaches the r&b song | exactly Velvet Hours; grounded explanations | PASS | Velvet Hours | Medium (0.74) |
| R4 | Glossary: 'catchy upbeat' reaches the pop songs | exactly Sunrise City, Gym Hero; grounded explanations | PASS | Sunrise City | High (0.96) |
| A1 | Agent: drops the word that matches no song ('jazz zebra') | exactly Coffee Shop Stories; agent recovered, 1 retry; final request "jazz" | PASS | Coffee Shop Stories | High (0.82) |
| A2 | Agent: nonsense words, so it ranks by the preferences alone | agent recovered, 1 retry; final request: preferences only | PASS | Library Rain | High (0.85) |
| A3 | Agent: words that never co-occur, keeps the strongest ('jazz metal') | exactly Coffee Shop Stories; agent recovered, 1 retry; final request "jazz" | PASS | Coffee Shop Stories | High (0.82) |
| A4 | Agent: Low confidence, so it switches the scoring mode | agent improved, 1 retry; final mode mood-first; confidence Medium | PASS | Birchwood Lullaby | Medium (0.69) |
| A5 | Agent: a good first search is left alone | exactly Library Rain, Midnight Coding; agent first_try, 0 retries | PASS | Library Rain | High (0.88) |
| A6 | Agent: invalid input is not retried | invalid_input; agent stopped, 0 retries | PASS | - | - |
| G1 | Nonsense words: nothing fits | nothing_fits | PASS | - | - |
| G2 | One real word and one unknown word: refused | nothing_fits | PASS | - | - |
| G3 | Only filler words: nothing fits | nothing_fits | PASS | - | - |
| G4 | Out-of-range energy is rejected with a reason | invalid_input; message has ''energy' must be between 0 and 1' | PASS | - | - |
| G5 | A 500-character request is rejected | invalid_input; message has 'too long' | PASS | - | - |

29 of 29 cases passed (100%). Average top-result confidence 0.85 across 22 cases that returned songs (High 17, Medium 4, Low 1).
