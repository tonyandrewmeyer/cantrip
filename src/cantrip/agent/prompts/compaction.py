"""Loader for the conversation-compaction prompt.

The prompt instructs the LLM to summarise conversation history while
preserving decisions, charm state, and tool results.  It's stored as
plain markdown (no variable substitution) and loaded once on first
access.
"""

import pathlib

_PROMPT_PATH = pathlib.Path(__file__).parent / "compaction.md"

# Lazy cache — populated on first call to avoid import-time I/O.
_CACHED: str | None = None


def load_compaction_prompt() -> str:
    """Return the compaction prompt text, reading the file on first call."""
    global _CACHED
    if _CACHED is None:
        _CACHED = _PROMPT_PATH.read_text().rstrip("\n")
    return _CACHED
