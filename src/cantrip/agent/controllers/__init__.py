"""Controllers — the ``X_controller`` orchestration layer.

Each controller drives a long-running agent concern (background
execution, MCP server lifecycle, the event watcher, issue triage, the
race arena) on behalf of ``CantripAgent``.  They are grouped here by
role rather than co-located with the domain modules they drive; see the
controller convention in ``CLAUDE.md``.
"""
