"""
A small glossary of genres, moods and vibe words: the second retrieval source.

The documents live in docs/glossary/*.md. Each `##` heading is one entry (chunking by heading
is ported from DocuBot). An entry has related words and a plain description:

    ## relaxed
    Related words: relaxing, calm, mellow
    Relaxed music is gentle and unhurried, for winding down.

It is used in two ways:
  expand()     a request word that matches an entry is also matched against that entry's term and
               related words, so "mellow homework" can find songs tagged "calm" and "study"
  facts_for()  the descriptions of a song's genre and mood become retrieved facts that the
               "why" explanation may use (and that the validator then allows)
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.logging_utils import log_event
from src.retrieval import stem

DEFAULT_FOLDER = Path(__file__).resolve().parent.parent / "docs" / "glossary"
MAX_OPTIONS_PER_WORD = 12

# One way a request word can match a song: all of these stems must be in the song's text.
Option = Tuple[Tuple[str, ...], str]  # (stems, text to show, for example "relaxed")


@dataclass(frozen=True)
class Entry:
    term: str
    related: Tuple[str, ...]
    text: str
    source: str


def split_into_chunks(text: str) -> List[str]:
    """
    Split a markdown document into heading sections (from DocuBot). A section is a heading line
    plus the lines under it, up to the next heading. Lines inside ``` fences are never headings.
    """
    chunks, current, in_fence = [], [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("#") and current:
            chunks.append("\n".join(current).strip())
            current = []
        current.append(line)
    chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def parse_entries(text: str, source: str) -> List[Entry]:
    """Turn the `##` sections of one document into entries. Other headings are ignored."""
    entries = []
    for chunk in split_into_chunks(text):
        lines = chunk.splitlines()
        if not lines[0].startswith("## "):
            continue
        term = lines[0][3:].strip().lower()
        related: List[str] = []
        description: List[str] = []
        in_fence = False
        for line in lines[1:]:
            if line.lstrip().startswith("```"):  # code blocks are never part of an entry
                in_fence = not in_fence
            elif in_fence:
                continue
            elif line.lower().startswith("related words:"):
                items = [item.strip().lower() for item in line.split(":", 1)[1].split(",")]
                related += [item for item in items if re.fullmatch(r"[a-z0-9]+", item)]
            elif line.strip():
                description.append(line.strip())
        if term and description:
            entries.append(Entry(term, tuple(related), " ".join(description), source))
    return entries


class Glossary:
    def __init__(self, entries: Sequence[Entry] = ()):
        self.entries = list(entries)
        self.by_term: Dict[str, Entry] = {}
        self.by_word: Dict[str, List[Entry]] = {}  # stem of a single-word term or related word -> entries
        for entry in self.entries:
            self.by_term.setdefault(entry.term, entry)
            for word in {entry.term, *entry.related}:
                if re.fullmatch(r"[a-z0-9]+", word):
                    self.by_word.setdefault(stem(word), []).append(entry)

    def __len__(self) -> int:
        return len(self.entries)

    @classmethod
    def load(cls, folder: Optional[Path] = None) -> "Glossary":
        """Read every .md file in the folder. A missing or empty folder gives an empty glossary."""
        folder = Path(folder or os.environ.get("VIBEMATCH_GLOSSARY") or DEFAULT_FOLDER)
        entries: List[Entry] = []
        try:
            for path in sorted(folder.glob("*.md")):
                entries += parse_entries(path.read_text(encoding="utf-8"), path.name)
        except (OSError, UnicodeDecodeError) as error:
            log_event("load_glossary", level=logging.ERROR, path=str(folder), error=f"{type(error).__name__}: {error}")
            return cls()
        if not entries:
            log_event("load_glossary", level=logging.WARNING, path=str(folder), error="no glossary entries found")
        return cls(entries)

    def expand(self, word: str) -> List[Option]:
        """
        Other ways to match a request word: the term and related words of every entry that lists
        it. A multi-word term (for example "indie pop") counts only as the whole phrase.
        """
        own = stem(word)
        options: Dict[Tuple[str, ...], str] = {}
        for entry in self.by_word.get(own, []):
            phrase = tuple(stem(w) for w in re.findall(r"[a-z0-9]+", entry.term))
            options.setdefault(phrase, entry.term)
            for related in entry.related:
                options.setdefault((stem(related),), related)
        options.pop((own,), None)
        return [(stems, shown) for stems, shown in options.items()][:MAX_OPTIONS_PER_WORD]

    def facts_for(self, song: Dict) -> Dict[str, Entry]:
        """The glossary entries for a song's genre, mood and tags (those that exist)."""
        facts = {}
        for kind, term in [("genre", song["genre"]), ("mood", song["mood"])]:
            if term in self.by_term:
                facts[kind] = self.by_term[term]
        for tag in song.get("mood_tags", []):
            if tag in self.by_term:
                facts[f"tag:{tag}"] = self.by_term[tag]
        return facts
