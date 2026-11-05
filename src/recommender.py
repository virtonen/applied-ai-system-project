import csv
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

# Scoring modes (a simple Strategy pattern). Each mode is a table of weights, and one
# shared scorer reads the table it is given. To add a mode, add one entry here.
# A feature only counts when the user sets its preference, and the final score is
# divided by the weights in use, so it always stays between 0 and 1.
BALANCED = {
    "energy": 0.35, "acousticness": 0.25, "valence": 0.20,  # numeric closeness
    "mood": 0.12, "genre": 0.08,                            # exact label matches
    "popularity": 0.10, "decade": 0.10, "mood_tags": 0.15,  # advanced features
    "instrumentalness": 0.10, "clean": 0.05,
}

SCORING_MODES: Dict[str, Dict[str, float]] = {
    "balanced": BALANCED,
    "genre-first": {**BALANCED, "genre": 0.45, "mood": 0.10, "energy": 0.20,
                    "acousticness": 0.15, "valence": 0.10},
    "mood-first": {**BALANCED, "mood": 0.40, "genre": 0.10, "mood_tags": 0.25,
                   "energy": 0.20, "acousticness": 0.15, "valence": 0.15},
    "energy-focused": {**BALANCED, "energy": 0.60, "acousticness": 0.15, "valence": 0.10,
                       "mood": 0.08, "genre": 0.07},
}
DEFAULT_MODE = "balanced"
DECADE_SPAN = 40  # a release-decade gap of 40 years or more earns nothing

# Diversity penalty, used when recommend_songs(..., diverse=True). Each song already
# picked by the same artist or in the same genre lowers the score of a later song.
ARTIST_PENALTY = 0.15
GENRE_PENALTY = 0.08


@dataclass
class Song:
    """
    Represents a song and its attributes.
    Required by tests/test_recommender.py
    """
    id: int
    title: str
    artist: str
    genre: str
    mood: str
    energy: float
    tempo_bpm: float
    valence: float
    danceability: float
    acousticness: float
    popularity: int = 50
    release_decade: int = 2020
    mood_tags: List[str] = field(default_factory=list)
    instrumentalness: float = 0.0
    explicit: bool = False

@dataclass
class UserProfile:
    """
    Represents a user's taste preferences.
    Required by tests/test_recommender.py
    """
    favorite_genre: str
    favorite_mood: str
    target_energy: float
    likes_acoustic: bool

class Recommender:
    """
    OOP implementation of the recommendation logic.
    Required by tests/test_recommender.py
    """
    def __init__(self, songs: List[Song]):
        self.songs = songs

    def recommend(self, user: UserProfile, k: int = 5) -> List[Song]:
        # TODO: Implement recommendation logic
        return self.songs[:k]

    def explain_recommendation(self, user: UserProfile, song: Song) -> str:
        # TODO: Implement explanation logic
        return "Explanation placeholder"

def load_songs(csv_path: str) -> List[Dict]:
    """
    Loads songs from a CSV file.
    Required by src/main.py
    """
    int_fields = ("id", "popularity", "release_decade")
    float_fields = ("energy", "valence", "acousticness", "tempo_bpm", "danceability", "instrumentalness")

    songs: List[Dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for name in int_fields:
                row[name] = int(row[name])
            for name in float_fields:
                row[name] = float(row[name])
            row["explicit"] = bool(int(row["explicit"]))
            row["mood_tags"] = row["mood_tags"].split("|")
            songs.append(row)
    return songs

def score_song(user_prefs: Dict, song: Dict, mode: str = DEFAULT_MODE) -> Tuple[float, List[str]]:
    """
    Scores a single song against user preferences, using the weights of the chosen mode.
    Required by recommend_songs() and src/main.py
    """
    if mode not in SCORING_MODES:
        raise ValueError(f"Unknown mode '{mode}'. Choose from: {', '.join(SCORING_MODES)}")
    weights = SCORING_MODES[mode]

    # Each part is (weight, similarity from 0 to 1, reason text, show when similarity is 0)
    parts: List[Tuple[float, float, str, bool]] = []

    # Numeric features: closeness to the target, sim = 1 - |song - target|
    for feature in ("energy", "acousticness", "valence"):
        weight = weights[feature]
        if feature in user_prefs:
            sim = 1.0 - abs(song[feature] - user_prefs[feature])
            label = f"{feature} close to target: {song[feature]:.2f} vs {user_prefs[feature]:.2f}"
            parts.append((weight, sim, label, True))

    # Categorical features: exact match earns the full weight, otherwise nothing
    if "mood" in user_prefs:
        sim = 1.0 if user_prefs["mood"] == song["mood"] else 0.0
        parts.append((weights["mood"], sim, f"mood match: {song['mood']}", False))
    if "genre" in user_prefs:
        sim = 1.0 if user_prefs["genre"] == song["genre"] else 0.0
        parts.append((weights["genre"], sim, f"genre match: {song['genre']}", False))

    # Advanced features (only used when the user sets them)
    if "popularity" in user_prefs:
        sim = 1.0 - abs(song["popularity"] - user_prefs["popularity"]) / 100
        label = f"popularity close to target: {song['popularity']} vs {user_prefs['popularity']}"
        parts.append((weights["popularity"], sim, label, True))
    if "decade" in user_prefs:
        gap = abs(song["release_decade"] - user_prefs["decade"])
        sim = max(0.0, 1.0 - gap / DECADE_SPAN)
        label = f"release decade: {song['release_decade']}s vs {user_prefs['decade']}s"
        parts.append((weights["decade"], sim, label, True))
    if user_prefs.get("mood_tags"):
        wanted = user_prefs["mood_tags"]
        matched = [tag for tag in wanted if tag in song["mood_tags"]]
        sim = len(matched) / len(wanted)
        parts.append((weights["mood_tags"], sim, f"mood tags match: {', '.join(matched)}", False))
    if "instrumentalness" in user_prefs:
        sim = 1.0 - abs(song["instrumentalness"] - user_prefs["instrumentalness"])
        label = (
            f"instrumentalness close to target: "
            f"{song['instrumentalness']:.2f} vs {user_prefs['instrumentalness']:.2f}"
        )
        parts.append((weights["instrumentalness"], sim, label, True))
    if user_prefs.get("avoid_explicit"):
        sim = 0.0 if song["explicit"] else 1.0
        label = "explicit lyrics" if song["explicit"] else "clean lyrics"
        parts.append((weights["clean"], sim, label, True))

    # Scale by the weights in use so the score always falls between 0 and 1
    total_weight = sum(weight for weight, _, _, _ in parts)
    if total_weight == 0:
        return 0.0, []

    score = 0.0
    reasons: List[str] = []
    for weight, sim, label, show_if_zero in parts:
        points = weight * sim / total_weight
        score += points
        if sim > 0 or show_if_zero:
            reasons.append(f"{label} (+{points:.2f})")

    return score, reasons

def recommend_songs(
    user_prefs: Dict, songs: List[Dict], k: int = 5, mode: str = DEFAULT_MODE, diverse: bool = False
) -> List[Tuple[Dict, float, str]]:
    """
    Functional implementation of the recommendation logic.
    Required by src/main.py
    """
    # Judge every song with score_song, then rank; sorted() leaves `songs` untouched
    judged = [(song, *score_song(user_prefs, song, mode)) for song in songs]
    ranked = sorted(judged, key=lambda item: item[1], reverse=True)
    if diverse:
        return _pick_diverse(ranked, k)
    return [(song, score, "; ".join(reasons)) for song, score, reasons in ranked[:k]]


def _pick_diverse(ranked: List[Tuple[Dict, float, List[str]]], k: int) -> List[Tuple[Dict, float, str]]:
    """
    Greedy re-ranking. Pick the best song, then charge every remaining song a penalty
    for each already-picked song by the same artist or in the same genre, and repeat.
    """
    pool = list(ranked)
    picks: List[Tuple[Dict, float, str]] = []
    while pool and len(picks) < k:
        chosen = None  # (adjusted score, pool index, song, reasons)
        for index, (song, score, reasons) in enumerate(pool):
            artist_hits = sum(1 for p, _, _ in picks if p["artist"] == song["artist"])
            genre_hits = sum(1 for p, _, _ in picks if p["genre"] == song["genre"])
            artist_cut = ARTIST_PENALTY * artist_hits
            genre_cut = GENRE_PENALTY * genre_hits
            adjusted = max(0.0, score - artist_cut - genre_cut)
            if chosen is None or adjusted > chosen[0]:
                notes = list(reasons)
                if artist_hits:
                    notes.append(f"diversity penalty: artist {song['artist']} already picked (-{artist_cut:.2f})")
                if genre_hits:
                    notes.append(f"diversity penalty: genre {song['genre']} already picked (-{genre_cut:.2f})")
                chosen = (adjusted, index, song, notes)
        adjusted, index, song, notes = chosen
        picks.append((song, adjusted, "; ".join(notes)))
        pool.pop(index)
    return picks
