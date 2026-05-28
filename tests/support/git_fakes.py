"""Shared doubles for the git-branch / PR-body helpers.

:func:`cantrip.agent.git_branch.build_pr_body` reads a small,
duck-typed task shape — ``title`` / ``category`` / ``status`` /
``result`` — off each task it summarises.  Two test modules used to
define their own identical ``_FakeTask`` for this; :class:`FakeTask`
is the single home for that shape.

It is deliberately *not* :class:`cantrip.agent.queue.AgentTask` — the
PR-body builder only touches these four attributes, so the minimal
stand-in keeps the tests focused on rendering rather than task
construction.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class FakeTask:
    """Minimal task-like object for ``build_pr_body`` tests."""

    title: str = ""
    category: str = ""
    status: str = "done"
    result: str | None = None
