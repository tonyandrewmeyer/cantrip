"""``/budget`` — show or raise the per-goal iteration / token cap.

Phase 55.3 introduced the goal-budget concept; the slash surface lets
users inspect current usage and raise / clear the cap interactively.
Lifted out of the dispatcher in Phase 85.3 alongside the other
handler clusters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.agent.runtime.goal_budget import GoalBudget, format_summary, measure_usage

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


def handle_budget(agent: CantripAgent, args: str) -> str:
    """Phase 55.3: show or raise the per-goal budget.

    ``/budget`` with no args prints current usage against the cap.
    ``/budget --max-iterations N`` sets or raises the iteration cap.
    ``/budget --max-prompt-tokens N`` / ``--max-completion-tokens N``
    set the equivalent token caps.  ``/budget --clear`` drops the
    budget entirely so the autonomous loop runs uncapped again.
    When a cap is raised, previously blocked tasks are moved back to
    pending so the executor picks them up on the next poll.
    """
    tokens = args.split()
    state = agent.state

    # Raise / clear path.
    if tokens:
        if tokens[0] == "--clear":
            state.goal_budget = None
            _unblock_tasks(agent)
            return "Goal budget cleared.  Autonomous work is now uncapped."

        flag = tokens[0]
        if flag not in ("--max-iterations", "--max-prompt-tokens", "--max-completion-tokens"):
            return (
                "Usage: ``/budget`` (show) / "
                "``/budget --max-iterations N`` / "
                "``/budget --max-prompt-tokens N`` / "
                "``/budget --max-completion-tokens N`` / "
                "``/budget --clear``."
            )
        if len(tokens) != 2:
            return f"Usage: ``/budget {flag} N``"
        try:
            value = int(tokens[1])
        except ValueError:
            return f"Cap must be an integer: {tokens[1]!r}"
        if value < 0:
            return f"Cap must be >= 0: {value}"

        if state.goal_budget is None:
            state.goal_budget = GoalBudget()
        if flag == "--max-iterations":
            state.goal_budget.max_iterations = value
        elif flag == "--max-prompt-tokens":
            state.goal_budget.max_prompt_tokens = value
        else:
            state.goal_budget.max_completion_tokens = value

        _unblock_tasks(agent)
        return f"Goal budget updated.  {_format_summary(agent)}"

    return _format_summary(agent)


def _format_summary(agent: CantripAgent) -> str:
    """Return the one-line "used / cap" summary for the chat."""
    state = agent.state
    if state.goal_budget is None:
        return (
            "No goal budget set.  Set a cap with ``/budget --max-iterations N`` "
            "or ``/budget --max-tokens N`` to add a hard stop."
        )
    store = agent.store
    if store is None:
        return (
            f"Goal budget set (iterations={state.goal_budget.max_iterations}, "
            f"prompt={state.goal_budget.max_prompt_tokens}, "
            f"completion={state.goal_budget.max_completion_tokens}).  Usage "
            "unavailable until the store opens."
        )
    usage = measure_usage(store, state.goal_budget)
    return format_summary(state.goal_budget, usage)


def _unblock_tasks(agent: CantripAgent) -> None:
    """Move every budget-blocked task back to pending.

    Called after a cap is raised or cleared — the executor's next
    poll will re-evaluate them against the new budget.  Tasks
    blocked for any other reason stay put.
    """
    queue = agent.work_queue
    for task in queue.all_tasks():
        reason = task.blocked_reason or ""
        if task.status.value == "blocked" and "Goal budget exceeded" in reason:
            queue.set_pending(task.id)
