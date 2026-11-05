"""
Keyword retrieval for songs, ported from DocuBot (ai110-module4tinker-docubot-starter).

The idea is the same as DocuBot's: turn each item into a short text document, build an
inverted index (word -> items), and retrieve only items that share enough words with the
typed request. The refusal guardrail returns nothing when too few query words match, so the
app can say "nothing fits" instead of showing a coincidence. Retrieved songs are then
ranked by score_song, so retrieval narrows the catalog and the scorer orders what is left.

Changes from DocuBot: documents are songs, not heading sections; the stopword list drops
doc words and adds music words; stemming also strips a trailing "y" ("rainy" -> "rain").
"""

import re
from typing import Dict, List, Tuple

from src.recommender import DEFAULT_MODE, recommend_songs

# Common words that match almost every request and add only noise to retrieval
STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "of", "on", "or", "that", "the",
    "this", "to", "what", "when", "where", "which", "with",
    # music-request filler
    "give", "im", "listen", "me", "music", "my", "need", "play", "some",
    "something", "song", "songs", "track", "tracks", "want",
}

# Refusal guardrail: a song counts as a match only if it contains at least this many
# distinct query words (or all of them, for very short queries)
MIN_MATCHED_WORDS = 2


def stem(word: str) -> str:
    """Crude suffix stripping so 'studying' matches 'study' and 'rainy' matches 'rain'."""
    for _ in range(2):  # two passes, so "studying" and "study" both end at "stud"
        for suffix in ("ion", "ing", "ed", "y", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
    return word


def query_terms(text: str) -> Dict[str, str]:
    """Return {stem: original word} for the useful words in a request, in order."""
    terms: Dict[str, str] = {}
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word not in STOPWORDS:
            terms.setdefault(stem(word), word)
    return terms


def tokenize(text: str) -> List[str]:
    """Lowercase, split into alphanumeric words, drop stopwords, stem the rest."""
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def song_to_text(song: Dict) -> str:
    """Turn a song into a short searchable document: its labels, tags and vibe words."""
    words = [song["title"], song["artist"], song["genre"], song["mood"], *song.get("mood_tags", [])]
    # Plain-word versions of a few numbers, so "calm" or "acoustic" can be searched
    if song["energy"] >= 0.8:
        words.append("energetic")
    elif song["energy"] <= 0.35:
        words.append("calm")
    if song["acousticness"] >= 0.7:
        words.append("acoustic")
    if song.get("instrumentalness", 0) >= 0.7:
        words.append("instrumental")
    if song.get("popularity", 0) >= 80:
        words.append("popular")
    return " ".join(words)


class SongIndex:
    """An inverted index over the songs, with a guardrail on how many words must match."""

    def __init__(self, songs: List[Dict]):
        self.songs = songs
        self.tokens = [set(tokenize(song_to_text(song))) for song in songs]
        self.index: Dict[str, List[int]] = {}
        for song_id, tokens in enumerate(self.tokens):
            for token in tokens:
                self.index.setdefault(token, []).append(song_id)

    def retrieve(self, query: str) -> List[Tuple[Dict, List[str]]]:
        """
        Return (song, matched query words) for every song that passes the guardrail,
        best match first. Ties keep catalog order. An empty list means "nothing fits".
        """
        terms = query_terms(query)
        if not terms:
            return []

        candidates = set()
        for token in terms:
            candidates.update(self.index.get(token, []))

        min_matched = min(MIN_MATCHED_WORDS, len(terms))
        hits = []
        for song_id in candidates:
            matched = [word for token, word in terms.items() if token in self.tokens[song_id]]
            if len(matched) >= min_matched:
                hits.append((song_id, matched))

        hits.sort(key=lambda item: (-len(item[1]), item[0]))
        return [(self.songs[song_id], matched) for song_id, matched in hits]


def search_and_rank(
    index: SongIndex,
    query: str,
    user_prefs: Dict,
    k: int = 5,
    mode: str = DEFAULT_MODE,
    diverse: bool = False,
) -> List[Tuple[Dict, float, str]]:
    """
    Retrieve songs for a typed request, then rank them with score_song.

    A blank request skips retrieval and ranks the whole catalog. Otherwise only retrieved
    songs are ranked, and the result is an empty list when the guardrail finds nothing.
    Each explanation starts with the words that matched the request.
    """
    if not query.strip():
        return recommend_songs(user_prefs, index.songs, k=k, mode=mode, diverse=diverse)

    hits = index.retrieve(query)
    if not hits:
        return []

    matched_by_title = {song["title"]: matched for song, matched in hits}
    ranked = recommend_songs(user_prefs, [song for song, _ in hits], k=k, mode=mode, diverse=diverse)
    return [
        (song, score, f"search match: {', '.join(matched_by_title[song['title']])}; {explanation}")
        for song, score, explanation in ranked
    ]
