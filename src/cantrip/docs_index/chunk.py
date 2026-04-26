"""Chunker for the Phase 72.1 docs index.

Splits an extracted page body into ~500-token chunks with 50-token
overlap so adjacent chunks share enough context that a query
matching the boundary is still found.

Tokenisation is approximated as 4 chars/token — same heuristic the
rest of Cantrip uses (see :mod:`cantrip.llm.base`).  Real
tokenisation is provider-specific and would tie chunking to the
model; the heuristic keeps the chunker provider-agnostic and the
size-error within ~25%.

The chunker tries to break on paragraph boundaries first, then on
sentences, then on whitespace, before falling back to a hard cut —
a chunk that ends mid-word would sit poorly with retrieval
ranking.
"""

from __future__ import annotations

import dataclasses
import re

# 4 chars/token matches ``cantrip.llm.base.estimate_tokens``.
_CHARS_PER_TOKEN = 4

DEFAULT_CHUNK_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 50


@dataclasses.dataclass(frozen=True, slots=True)
class TextChunk:
    """One ordinal-positioned slice of a page's text."""

    ordinal: int
    text: str
    char_start: int
    char_end: int


# Order matters: paragraph break → double newline; sentence → ``. ``;
# whitespace → any space.  The chunker walks down this list, picking
# the first separator that gives a clean break.
_BREAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\n\s*\n"),
    re.compile(r"(?<=[.!?])\s+(?=[A-Z])"),
    re.compile(r"\s+"),
)


def _find_break_point(text: str, target: int, *, search_window: int) -> int:
    """Return the closest break position to *target* within *search_window*.

    Walks the pattern list in priority order; the first pattern with
    a match anywhere in the window wins.  Falls back to *target* (a
    hard cut) when nothing matches — happens on dense single-token
    runs but is preferable to silently exceeding the budget.
    """
    if target >= len(text):
        return len(text)
    lo = max(0, target - search_window)
    hi = min(len(text), target + search_window)
    window = text[lo:hi]
    best_offset: int | None = None
    for pattern in _BREAK_PATTERNS:
        # Prefer the break closest to the target — match-end positions.
        candidates = [match.end() + lo for match in pattern.finditer(window)]
        if not candidates:
            continue
        best_offset = min(candidates, key=lambda pos: abs(pos - target))
        return best_offset
    return target


def chunk_text(
    text: str,
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[TextChunk]:
    """Split *text* into ordinal-ordered :class:`TextChunk`s.

    *chunk_tokens* and *overlap_tokens* are converted to character
    counts via the 4-chars/token heuristic.  Empty / whitespace-only
    input returns an empty list.

    The walker advances by ``(chunk_chars - overlap_chars)`` so each
    chunk starts where the previous one's *non-overlap* tail
    finished — adjacent chunks share ``overlap_chars`` of context so
    a query matching the boundary still hits.
    """
    text = text.strip()
    if not text:
        return []
    chunk_chars = max(1, chunk_tokens * _CHARS_PER_TOKEN)
    overlap_chars = max(0, min(overlap_tokens * _CHARS_PER_TOKEN, chunk_chars - 1))
    search_window = max(50, chunk_chars // 8)

    chunks: list[TextChunk] = []
    cursor = 0
    ordinal = 0
    n = len(text)
    while cursor < n:
        target = cursor + chunk_chars
        end = _find_break_point(text, target, search_window=search_window)
        end = max(end, cursor + 1)  # always advance
        end = min(end, n)
        body = text[cursor:end].strip()
        if body:
            chunks.append(
                TextChunk(
                    ordinal=ordinal,
                    text=body,
                    char_start=cursor,
                    char_end=end,
                )
            )
            ordinal += 1
        if end >= n:
            break
        cursor = max(cursor + 1, end - overlap_chars)
    return chunks
