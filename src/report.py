"""Plain-ASCII table output for the recommender (no extra libraries needed)."""

import textwrap
from typing import Dict, List, Sequence, Tuple

REASON_WIDTH = 46


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Draw a bordered table. A cell may hold several lines (separated by newlines)."""
    cells = [[str(c).split("\n") for c in row] for row in rows]
    widths = [
        max([len(headers[i])] + [len(line) for row in cells for line in row[i]])
        for i in range(len(headers))
    ]
    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def draw(parts: List[List[str]]) -> List[str]:
        height = max(len(p) for p in parts)
        return [
            "| " + " | ".join((p[n] if n < len(p) else "").ljust(w) for p, w in zip(parts, widths)) + " |"
            for n in range(height)
        ]

    lines = [border, *draw([[h] for h in headers]), border]
    for row in cells:
        lines += draw(row)
        lines.append(border)
    return "\n".join(lines)


def recommendations_table(recommendations: List[Tuple[Dict, float, str]]) -> str:
    """Table of ranked songs with their score and the reasons behind it."""
    rows = []
    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        reasons = "\n".join(
            textwrap.fill(
                reason.replace(" close to target", ""),
                width=REASON_WIDTH,
                initial_indent="- ",
                subsequent_indent="  ",
            )
            for reason in explanation.split("; ")
            if reason
        )
        rows.append([rank, song["title"], song["artist"], f"{song['genre']} / {song['mood']}", f"{score:.2f}", reasons])
    return format_table(["#", "Song", "Artist", "Genre / Mood", "Score", "Reasons"], rows)
