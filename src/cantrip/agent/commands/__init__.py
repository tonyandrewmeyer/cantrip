"""Slash-command surface — dispatcher plus the three command families.

Phase 85.3 grouped the three flat modules under one folder:

- ``slash`` — the shared dispatcher (:func:`dispatch`,
  :class:`SlashResult`) and the built-in command catalogue.
- ``custom`` — markdown-defined user commands and the registry that
  surfaces them in ``/help`` and the dispatcher.
- ``mcp`` — the ``/mcp`` family (status, registry, marketplace).

The :mod:`~cantrip.agent.memory.commands` module hosts the memory
slash commands (``/memory``, ``/remember``, ``/forget``); it stays in
the memory subpackage so the four memory files live together, and
the :mod:`slash` dispatcher imports it directly.
"""

from cantrip.agent.commands.slash import (
    COMMAND_CATALOGUE,
    CommandInfo,
    SlashResult,
    TreeNode,
    catalogue_for,
    dispatch,
    help_text,
)

__all__ = [
    "COMMAND_CATALOGUE",
    "CommandInfo",
    "SlashResult",
    "TreeNode",
    "catalogue_for",
    "dispatch",
    "help_text",
]
