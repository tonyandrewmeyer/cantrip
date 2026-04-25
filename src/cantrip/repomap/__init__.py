"""Repository map — graph-ranked symbol view for the system prompt.

A compact, ranked listing of the most-referenced classes, functions,
config options, actions, and relations in the active charm repo.  The
agent sees it on every turn, so it can jump to the right file without
grep-and-guess.

The map is built once per process (lazy) and refreshed when source
files change.  Token budget is configurable and shrinks under
compaction pressure so the bird's-eye view never crowds out real
conversation.

Public API:
    RepoMap   — top-level orchestrator (parse, rank, render, cache)
    Symbol    — a named definition (class / function / config / ...)
"""

from cantrip.repomap.repomap import (
    DEFAULT_TOKEN_BUDGET,
    RepoMap,
)
from cantrip.repomap.symbols import Symbol, SymbolKind

__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "RepoMap",
    "Symbol",
    "SymbolKind",
]
