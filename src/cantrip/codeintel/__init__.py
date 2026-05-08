"""Read-only code intelligence — exact symbols, definitions, references.

Phase 72b.  Sits next to :mod:`cantrip.repomap`: ``repomap`` answers
"what matters in this repo?" via PageRank-ranked summaries; this
subsystem answers "where is :pyfunc:`Foo.bar` defined?" and "who
references :pyclass:`SubagentContext`?".  It reuses the parser
helpers in :mod:`cantrip.repomap.symbols` rather than maintaining a
second symbol-extraction stack.

Public API:

    CodeIntel              — orchestrator (build, query, cache)
    SymbolMatch            — one workspace_symbols hit
    Definition             — one go_to_definition result
    ReferenceLocation      — one find_references hit (re-exported from repomap)
    DefinitionResult       — go_to_definition response
    ReferencesResult       — find_references response
    SymbolMatchKind        — exact_qualified / exact / prefix / fuzzy
"""

from __future__ import annotations

from cantrip.codeintel.index import (
    CodeIntel,
    Definition,
    DefinitionResult,
    ReferencesResult,
    SymbolMatch,
    SymbolMatchKind,
)
from cantrip.repomap.symbols import ReferenceLocation, Symbol, SymbolKind

__all__ = [
    "CodeIntel",
    "Definition",
    "DefinitionResult",
    "ReferenceLocation",
    "ReferencesResult",
    "Symbol",
    "SymbolKind",
    "SymbolMatch",
    "SymbolMatchKind",
]
