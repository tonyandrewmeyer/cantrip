"""``/goal`` — show, set, or clear the session's user-prose objective.

Phase 99.3: surfaces the ``objective`` field on
:class:`~cantrip.agent.state.AgentState` to the chat so the user can
update or inspect their goal sentence mid-session.  The slash entry
mirrors the ``/budget`` pattern — a bare invocation reads, a
positional payload writes, and ``clear`` resets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


_NO_OBJECTIVE_MSG = (
    "No objective set.  Stamp one with ``/goal <text>`` so Ralph "
    "re-feeds and goal-aware status surfaces use your words rather "
    "than the spec-derived paraphrase."
)


def handle_goal(agent: CantripAgent, args: str) -> str:
    """Phase 99.3: show, set, or clear the user-prose objective.

    ``/goal`` with no args prints the current value (or a hint when
    none is set).  ``/goal <text>`` sets / overwrites the objective.
    ``/goal clear`` removes it.
    """
    state = agent.state
    payload = args.strip()

    if not payload:
        if state.objective:
            return f"Current objective: {state.objective}"
        return _NO_OBJECTIVE_MSG

    if payload.lower() == "clear":
        if state.objective is None:
            return "No objective was set; nothing to clear."
        state.objective = None
        return (
            "Objective cleared.  Ralph re-feeds and status surfaces "
            "fall back to the spec-derived paraphrase."
        )

    state.objective = payload
    return f"Objective set: {payload}"
