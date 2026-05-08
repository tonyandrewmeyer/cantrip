"""Phase 99.4: read-only projection of goal lifecycle state.

Every UI surface (TUI status bar, Web UI status indicator) shows a
single Codex-style label summarising where the autonomous loop is
right now.  This module is the one place that picks the label so the
two surfaces never disagree and a future surface (e.g. the CLI
``--print`` exit summary) gets it for free.

The projection is intentionally pure — it takes the user-paused
flag and the work-queue task list and returns a string.  No event
bus access, no executor state, no persistence.  That makes it
trivial to test against contrived task lists, and means the same
helper can compute the label at any consumption point without
worrying about whose turn it is to publish.

The label set is deliberately closed:

* ``"running"`` — the loop has pending or active work.
* ``"paused"`` — the user issued ``/pause``.  Beats every other
  label; the user's intent is the load-bearing signal.
* ``"done"`` — no pending, active, or blocked tasks remain.  The
  queue has nothing to do, the user can move on.
* ``"blocked"`` — only blocked tasks remain, none with a
  budget-related reason.  Generic "stuck" state.
* ``"budget-limited"`` — only blocked tasks remain *and* at least
  one of them is blocked because of a goal-budget trip.  More
  specific than ``"blocked"`` so the user sees an actionable cause
  directly.

Precedence (matches the ROADMAP 99.4 hints — ``paused`` beats
``blocked``; ``budget-limited`` beats ``running``):

1. ``paused`` (user intent)
2. ``done`` (truly nothing to do)
3. ``budget-limited`` (only blocked tasks, with budget cause)
4. ``blocked`` (only blocked tasks, no budget cause)
5. ``running`` (default — pending or active work exists)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.agent.queue import AgentTask


#: Prefix on ``AgentTask.blocked_reason`` written by
#: :func:`cantrip.agent.goal_budget.check_budget` when a budget cap
#: trips.  Used by :func:`lifecycle_label` to distinguish the
#: actionable "budget-limited" state from a generic "blocked" state
#: without coupling to the SQLite event log.
GOAL_BUDGET_BLOCK_PREFIX = "Goal budget exceeded"


#: Closed set of valid lifecycle labels.  Surfaces that map labels
#: to badge text or CSS classes can iterate this for completeness.
LIFECYCLE_LABELS: tuple[str, ...] = (
    "running",
    "paused",
    "done",
    "blocked",
    "budget-limited",
)


def lifecycle_label(*, user_paused: bool, tasks: Iterable[AgentTask]) -> str:
    """Return the Codex-style lifecycle label for the current state.

    *user_paused* mirrors :attr:`ExecutorController.user_paused`.
    *tasks* is the live task list from
    :meth:`WorkQueue.all_tasks` — every status counts, but only
    pending / active / blocked influence the label (done and failed
    tasks are historical record).

    Pure function — no I/O, no event bus.  Callers re-evaluate on
    every state-change event (task update, ``/pause``, ``/budget``)
    and republish the result; the caller decides how to surface the
    string.
    """
    # Fast path — the user pressed pause, that's the answer regardless
    # of what the queue looks like underneath.
    if user_paused:
        return "paused"

    # Single-pass scan over the task list so this stays O(N) on every
    # status_bar_changed publish.  Real queues are tiny (tens of tasks)
    # but this still beats three separate ``any(...)`` walks.
    has_pending_or_active = False
    has_blocked = False
    has_budget_blocked = False

    # Late import — lifecycle.py is imported by goal_budget.py's
    # caller chain, so importing TaskStatus at module load time risks
    # a future circular dependency that this file shouldn't own.
    from cantrip.agent.queue import TaskStatus

    for task in tasks:
        status = task.status
        if status in (TaskStatus.PENDING, TaskStatus.ACTIVE):
            has_pending_or_active = True
        elif status == TaskStatus.BLOCKED:
            has_blocked = True
            reason = task.blocked_reason or ""
            if reason.startswith(GOAL_BUDGET_BLOCK_PREFIX):
                has_budget_blocked = True

    if not has_pending_or_active and not has_blocked:
        # Empty queue or all tasks done / failed.
        return "done"

    if not has_pending_or_active:
        # Only blocked tasks remain — pick the more specific label
        # when at least one blocker is the goal budget.
        if has_budget_blocked:
            return "budget-limited"
        return "blocked"

    # Pending or active work exists.  Even if some tasks are blocked
    # and others are pending, the loop is still making progress so
    # ``running`` is the truthful label.
    return "running"
