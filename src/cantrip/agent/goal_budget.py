"""Per-goal iteration and token budget (Phase 55.3 follow-up).

The primitive scoped in Phase 55.3's investigation: a hard per-goal
circuit-breaker on how much autonomous work the agent will do before
the operator confirms continuation.  Today's executor drains the
work queue on its own schedule; a runaway planner could in principle
spawn follow-up tasks without an aggregate cap.  ``GoalBudget`` adds
that cap.

The primitive is intentionally small — a dataclass plus a single
``check_budget()`` function.  The executor gate consults it before
spawning each task; tripping the cap marks the task ``BLOCKED`` with
``budget_exceeded`` and emits a ``GOAL_BUDGET_EXCEEDED`` UI event so
the user sees the stop in the chat rather than the TUI silently
stalling.  Once the operator raises the cap (``/budget`` slash
command or a new CLI flag) the blocked task re-runs.

Pairs with Phase 80.3's ``max_calls_per_request`` policy rate limit:
``GoalBudget`` is goal-scoped ("this build shouldn't cost more than
$5"), ``max_calls_per_request`` is task-scoped ("no single subagent
should call more than 50 tools").  The two compose cleanly — both
produce a ``BLOCKED`` verdict with a ``blocked_reason`` string; the
chat renders each uniformly.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.agent.store import SessionStore


#: Environment-variable names callers check via :func:`from_cli_args`.
#: Documented in ``docs/`` and the ``--max-iterations`` / ``--max-tokens``
#: CLI help so operators have a single answer to "how do I cap this".
ENV_MAX_ITERATIONS = "CANTRIP_MAX_ITERATIONS"
ENV_MAX_TOKENS = "CANTRIP_MAX_TOKENS"

log = logging.getLogger(__name__)


@dataclasses.dataclass
class GoalBudget:
    """Hard caps on autonomous work for a single goal.

    *started_at* is a timestamp in SQLite's ``datetime('now')``
    format (``%Y-%m-%d %H:%M:%S`` UTC) the budget started counting
    from.  We match SQLite's shape rather than Python's
    ``isoformat`` so string comparison in ``WHERE timestamp >= ?``
    works as expected against the token_usage table.  Every cap is
    optional — a ``None`` field means "no limit at this axis" — so
    an operator can combine iteration and token caps freely.

    The dataclass is *mutable* so the ``/budget`` slash command can
    raise a cap in place without reconstructing the whole state.
    The set-once semantics (``started_at`` never changes once stamped)
    are enforced by not exposing a setter in the slash command.
    """

    max_iterations: int | None = None
    max_prompt_tokens: int | None = None
    max_completion_tokens: int | None = None
    started_at: str = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
    )


@dataclasses.dataclass(frozen=True)
class BudgetUsage:
    """Snapshot of usage against a :class:`GoalBudget`.

    Returned by :func:`measure_usage` so callers (the ``/budget``
    slash command, the status-bar indicator once Phase 80.3 ships)
    can render a uniform "used / cap" summary without each
    re-running the SQLite query.
    """

    iterations: int
    prompt_tokens: int
    completion_tokens: int


def measure_usage(store: SessionStore, budget: GoalBudget) -> BudgetUsage:
    """Query the session store for usage since the budget started.

    ``iterations`` maps to ``request_count`` from
    :meth:`SessionStore.get_usage_since` — the Ralph-loop notion of
    "one LLM invocation per iteration" translates naturally to
    Cantrip's request count.
    """
    stats = store.get_usage_since(budget.started_at)
    return BudgetUsage(
        iterations=int(stats.get("request_count", 0) or 0),
        prompt_tokens=int(stats.get("prompt_tokens", 0) or 0),
        completion_tokens=int(stats.get("completion_tokens", 0) or 0),
    )


def check_budget(store: SessionStore, budget: GoalBudget) -> str | None:
    """Return a block reason if *budget* is exceeded, or ``None`` if OK.

    The block string is suitable for ``AgentTask.blocked_reason`` —
    short, user-facing, and names the axis that tripped.  Callers
    hand it back up through the executor so the task appears in the
    TUI with the same shape as any other blocked task.
    """
    usage = measure_usage(store, budget)

    if budget.max_iterations is not None and usage.iterations >= budget.max_iterations:
        return (
            f"Goal budget exceeded: {usage.iterations} iterations "
            f"(cap: {budget.max_iterations}).  Raise with "
            "``/budget --max-iterations N`` or start a new session."
        )
    if budget.max_prompt_tokens is not None and usage.prompt_tokens >= budget.max_prompt_tokens:
        return (
            f"Goal budget exceeded: {usage.prompt_tokens:,} prompt tokens "
            f"(cap: {budget.max_prompt_tokens:,}).  Raise with "
            "``/budget --max-prompt-tokens N`` or start a new session."
        )
    if (
        budget.max_completion_tokens is not None
        and usage.completion_tokens >= budget.max_completion_tokens
    ):
        return (
            f"Goal budget exceeded: {usage.completion_tokens:,} "
            f"completion tokens (cap: {budget.max_completion_tokens:,}).  "
            "Raise with ``/budget --max-completion-tokens N`` or start a "
            "new session."
        )
    return None


def from_cli_args(
    max_iterations: int | None = None,
    max_tokens: int | None = None,
) -> GoalBudget | None:
    """Build a :class:`GoalBudget` from CLI flags with env-var fallback.

    ``--max-tokens N`` is interpreted as a combined prompt +
    completion cap split evenly (``N // 2`` each) — the most common
    mental model and what matches the single-axis env var.  Callers
    that want asymmetric caps set the dataclass fields directly via
    ``/budget`` instead of the CLI shorthand.

    Returns ``None`` when neither flag nor env var is set so the
    caller can leave ``state.goal_budget`` as ``None`` (uncapped).
    """

    def _env_int(name: str) -> int | None:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return None
        try:
            value = int(raw)
        except ValueError:
            log.warning("Ignoring non-integer %s=%r", name, raw)
            return None
        if value < 0:
            log.warning("Ignoring negative %s=%d", name, value)
            return None
        return value

    effective_iterations = max_iterations
    if effective_iterations is None:
        effective_iterations = _env_int(ENV_MAX_ITERATIONS)
    effective_tokens = max_tokens
    if effective_tokens is None:
        effective_tokens = _env_int(ENV_MAX_TOKENS)

    if effective_iterations is None and effective_tokens is None:
        return None

    budget = GoalBudget(max_iterations=effective_iterations)
    if effective_tokens is not None:
        half = effective_tokens // 2
        budget.max_prompt_tokens = half
        budget.max_completion_tokens = effective_tokens - half
    return budget


def format_summary(budget: GoalBudget, usage: BudgetUsage) -> str:
    """One-line "used / cap" summary for the ``/budget`` slash command."""
    parts: list[str] = []
    if budget.max_iterations is not None:
        parts.append(f"iterations {usage.iterations}/{budget.max_iterations}")
    else:
        parts.append(f"iterations {usage.iterations} (uncapped)")
    if budget.max_prompt_tokens is not None:
        parts.append(f"prompt {usage.prompt_tokens:,}/{budget.max_prompt_tokens:,}")
    else:
        parts.append(f"prompt {usage.prompt_tokens:,} (uncapped)")
    if budget.max_completion_tokens is not None:
        parts.append(f"completion {usage.completion_tokens:,}/{budget.max_completion_tokens:,}")
    else:
        parts.append(f"completion {usage.completion_tokens:,} (uncapped)")
    return " · ".join(parts)
