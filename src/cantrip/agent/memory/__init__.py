"""Charm-scope and global memory subsystem.

The public API is re-exported from this package root so existing
``from cantrip.agent.memory import ...`` imports keep working after
the Phase 85.2 split.  The four modules are:

- ``core`` — :class:`MemoryEntry`, :class:`MemoryManager`,
  :class:`GlobalMemoryStore`, citation/staleness primitives.
- ``writer`` — auto-writer that proposes new entries from
  conversation context.
- ``export`` — skill / markdown export and import.
- ``commands`` — slash-command handlers (``/memory``,
  ``/remember``, ``/forget``).
"""

from cantrip.agent.memory.core import (
    DEFAULT_HARD_EXPIRY_DAYS,
    DEFAULT_SOFT_EXPIRY_DAYS,
    INDEX_FILENAME,
    MEMORY_INDEX_MAX_LINES,
    TEAM_MEMORY_WRITES_ASK,
    TEAM_MEMORY_WRITES_LOCAL,
    TEAM_MEMORY_WRITES_SHARED,
    VALID_KINDS,
    VALID_STATUSES,
    VALID_TEAM_MEMORY_WRITES,
    CitationCheck,
    GlobalMemoryStore,
    MemoryEntry,
    MemoryManager,
    MemoryScopeError,
    RevalidationResult,
    SharedMemoryStore,
    SweepResult,
    sha_for_range,
    shared_memory_dir,
    slugify_title,
    validate_citation,
)
from cantrip.agent.memory.writer import (
    AutoWriter,
    TriggerKind,
    WriteMemoryContext,
    collect_file_citations,
)

__all__ = [
    "DEFAULT_HARD_EXPIRY_DAYS",
    "DEFAULT_SOFT_EXPIRY_DAYS",
    "INDEX_FILENAME",
    "MEMORY_INDEX_MAX_LINES",
    "TEAM_MEMORY_WRITES_ASK",
    "TEAM_MEMORY_WRITES_LOCAL",
    "TEAM_MEMORY_WRITES_SHARED",
    "VALID_KINDS",
    "VALID_STATUSES",
    "VALID_TEAM_MEMORY_WRITES",
    "AutoWriter",
    "CitationCheck",
    "GlobalMemoryStore",
    "MemoryEntry",
    "MemoryManager",
    "MemoryScopeError",
    "RevalidationResult",
    "SharedMemoryStore",
    "SweepResult",
    "TriggerKind",
    "WriteMemoryContext",
    "collect_file_citations",
    "sha_for_range",
    "shared_memory_dir",
    "slugify_title",
    "validate_citation",
]
