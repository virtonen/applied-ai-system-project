"""
Grounded "why this song" explanations: the generation half of the RAG loop.

The retrieved text for a song is its searchable description (title, artist, genre, mood, tags,
vibe words), plain-word versions of its numbers, and the glossary entries for its genre, mood and
tags (the second retrieval source). An explanation may only be built from that text and the
user's own request:

  template_why   builds the explanation directly from those facts (always available)
  explain_with_ai  asks Gemini to write it from the same facts, then VALIDATES every word.
                 A sentence that mentions anything not in the facts is rejected and replaced
                 by the template sentence, so an invented genre, year or artist never reaches the user.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.llm_client import LLMError
from src.logging_utils import log_event
from src.retrieval import query_terms, song_to_text, stem

MAX_CHARS = 450
MAX_SENTENCES = 5
CACHE: Dict[tuple, List["Why"]] = {}

# Plain connecting words that carry no checkable fact about a song
SAFE_WORDS = set("""
a an the and or but with for to of in on at as is are was be been it its s this that these those
your you re they their them there here not no any only just also both very more most than so
because since while when which who what how if can will would has have had by from one
song songs track pick fits fit match matches matched matching request asked looking like
sound sounds feel feels vibe mood genre tag tags description described includes include
words word listener music good great perfect glossary links
""".split())


@dataclass(frozen=True)
class Why:
    text: str
    source: str  # "template" or "ai"
    note: str = ""  # why an AI sentence was replaced, if it was


# ----- the facts an explanation may use -----

def sound_words(song: Dict) -> List[str]:
    """Plain words for the song's numbers: energy level, acoustic or electronic, instrumental."""
    energy = song["energy"]
    words = ["high-energy" if energy >= 0.7 else "low-energy" if energy <= 0.4 else "medium-energy"]
    if song["acousticness"] >= 0.7:
        words.append("acoustic")
    elif song["acousticness"] <= 0.3:
        words.append("electronic")
    if song.get("instrumentalness", 0) >= 0.7:
        words.append("instrumental")
    return words


def facts_text(song: Dict, matched: Sequence[str] = (), glossary=None) -> str:
    """One line of facts about a song, in the form given to the model."""
    line = (
        f"title={song['title']}; artist={song['artist']}; genre={song['genre']}; mood={song['mood']}; "
        f"tags={'|'.join(song.get('mood_tags', [])) or 'none'}; sound={', '.join(sound_words(song))}; "
        f"request words it matched={', '.join(matched) or 'none'}"
    )
    if glossary:
        for kind, entry in glossary.facts_for(song).items():
            if kind in ("genre", "mood"):
                line += f"; about {kind}={entry.text}"
    return line


def allowed_vocabulary(song: Dict, query: str = "", glossary=None) -> Set[str]:
    """Every word (and stem) an explanation for this song may use."""
    text = " ".join([song_to_text(song), " ".join(sound_words(song)), query])
    if glossary:  # the retrieved glossary entries for this song's genre, mood and tags
        for entry in glossary.facts_for(song).values():
            text += " " + " ".join([entry.term, *entry.related, entry.text])
    words = set(re.findall(r"[a-z0-9]+", text.lower())) | SAFE_WORDS
    return words | {stem(w) for w in words}


def _a(word: str) -> str:
    """'a' or 'an' for the word that follows ('an uplifting', 'an r&b', 'a lofi')."""
    return "an" if word[:1].lower() in "aeiou" or word.lower().startswith("r&b") else "a"


def _shown(word: str) -> str:
    """'mellow (as chill)' becomes 'mellow as chill', so the sentence has no nested brackets."""
    return word.replace(" (as ", " as ")[:-1] if " (as " in word and word.endswith(")") else word


def template_why(song: Dict, matched: Sequence[str] = (), glossary=None) -> Why:
    """Build the explanation straight from the song's facts. Never uses any other information."""
    sentences = []
    if matched:
        reason = (
            "because the glossary links those words to words in its description."
            if any(" (as " in m for m in matched)
            else "because those words are in its description."
        )
        sentences.append(f"It matches your request ({', '.join(_shown(m) for m in matched)}) {reason}")
    energy, *extra = sound_words(song)
    sound = " ".join([energy, *extra[:1]])
    genre, mood = song["genre"], song["mood"]
    sentences.append(f"It is {_a(genre)} {genre} song with {_a(mood)} {mood} mood and a {sound} sound.")
    if glossary and "genre" in glossary.facts_for(song):
        sentences.append(glossary.facts_for(song)["genre"].text)
    if song.get("mood_tags"):
        sentences.append(f"Its tags are {', '.join(song['mood_tags'])}.")
    return Why(" ".join(sentences), "template")


# ----- the validator -----

def validate_explanation(text: str, song: Dict, query: str = "", glossary=None) -> Tuple[bool, str]:
    """
    Accept the text only if every word comes from the song's facts, the user's request or the
    plain connecting words. Returns (ok, reason). The reason names the words that were rejected.
    """
    text = (text or "").strip()
    if not text:
        return False, "empty explanation"
    if len(text) > MAX_CHARS:
        return False, f"too long ({len(text)} characters)"
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    if len(sentences) > MAX_SENTENCES:
        return False, f"too many sentences ({len(sentences)})"

    allowed = allowed_vocabulary(song, query, glossary)
    unsupported = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in allowed and stem(w) not in allowed]
    if unsupported:
        shown = ", ".join(sorted(set(unsupported))[:5])
        return False, f"mentions words not in the song facts: {shown}"
    return True, ""


# ----- the AI step -----

def build_prompt(query: str, results: Sequence, glossary=None) -> str:
    lines = [f"{i}. {facts_text(r.song, r.matched_words, glossary)}" for i, r in enumerate(results, start=1)]
    return (
        "You explain why songs fit a listener. Use ONLY the facts given for each song. "
        "Do not add anything that is not in the facts: no other genres, artists, years, instruments, "
        "moods or opinions. Use short plain words. Write exactly one sentence of at most 25 words per song, "
        "in this exact format, one line per song:\n"
        "1: <sentence>\n"
        "2: <sentence>\n\n"
        f'Listener request: "{query or "none (the listener only used sliders)"}"\n'
        "Songs:\n" + "\n".join(lines)
    )


def parse_lines(reply: str) -> Dict[int, str]:
    """Pick out '1: sentence' lines from the model's reply."""
    found = {}
    for line in reply.splitlines():
        match = re.match(r"^\s*\**(\d+)\**\s*[:.)\-]\s*(.+?)\s*$", line)
        if match:
            found[int(match.group(1))] = match.group(2).strip("*").strip()
    return found


def explain_with_ai(results: Sequence, query: str, client, cache: Optional[Dict] = None, glossary=None) -> List[Why]:
    """
    One model call for all results. Each sentence is validated on its own, and any sentence that
    fails (or is missing) is replaced by the template explanation. Never raises.
    `results` need .song and .matched_words. Results are cached per (request, songs) so repeated
    page reruns do not spend more API calls.
    """
    cache = CACHE if cache is None else cache
    key = (query, tuple(r.song["id"] for r in results), bool(glossary))
    if key in cache:
        return cache[key]

    fallback = [template_why(r.song, r.matched_words, glossary) for r in results]
    started = time.perf_counter()
    error = None
    reply = ""
    try:
        reply = client.generate(build_prompt(query, results, glossary), max_tokens=60 * len(results) + 60)
    except LLMError as problem:
        error = f"LLMError: {problem}"
    except Exception as problem:  # the page must still render
        error = f"{type(problem).__name__}: {problem}"

    whys, rejected = [], []
    sentences = parse_lines(reply) if reply else {}
    for number, (r, base) in enumerate(zip(results, fallback), start=1):
        text = sentences.get(number, "")
        ok, reason = validate_explanation(text, r.song, query, glossary) if text else (False, "no sentence returned")
        if ok:
            whys.append(Why(text, "ai"))
        else:
            if error is None:
                rejected.append({"song": r.song["title"], "reason": reason, "text": text})
            whys.append(Why(base.text, "template", note=error or reason))

    log_event(
        "explain",
        level=logging.WARNING if error else logging.INFO,
        query=query,
        results=len(results),
        ai_used=sum(1 for w in whys if w.source == "ai"),
        rejected=rejected,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        error=error,
    )
    if error is None:  # do not cache failures, so a later retry can succeed
        cache[key] = whys
    return whys


def clear_cache() -> None:
    CACHE.clear()
