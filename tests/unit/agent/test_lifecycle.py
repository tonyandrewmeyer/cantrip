"""Tests for the Phase 99.4 lifecycle label projection.

The projection is the single source of truth for the Codex-style
"running / paused / done / blocked / budget-limited" badge that the
TUI status bar and the Web UI status indicator both render.  These
tests pin down the precedence so a future refactor can't silently
flip a label and have the two surfaces drift apart.
"""

from __future__ import annotations

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.runtime.lifecycle import LIFECYCLE_LABELS, lifecycle_label


def _task(
    title: str = "t",
    *,
    status: TaskStatus = TaskStatus.PENDING,
    blocked_reason: str | None = None,
) -> AgentTask:
    """Build an AgentTask with the minimum fields the projection cares about."""
    task = AgentTask(title=title, category=TaskCategory.BUILD)
    task.status = status
    task.blocked_reason = blocked_reason
    return task


class TestLabelSetIsClosed:
    """The label set must stay closed — UI surfaces map exact strings to badges."""

    def test_label_set_matches_documented_values(self) -> None:
        assert set(LIFECYCLE_LABELS) == {
            "running",
            "paused",
            "done",
            "blocked",
            "budget-limited",
        }


class TestEmptyQueue:
    def test_empty_queue_with_no_pause_is_done(self) -> None:
        """A session with no work and no user pause has reached ``done``."""
        assert lifecycle_label(user_paused=False, tasks=[]) == "done"

    def test_empty_queue_when_paused_is_paused(self) -> None:
        """Paused beats done — the user's intent is the load-bearing signal."""
        assert lifecycle_label(user_paused=True, tasks=[]) == "paused"


class TestRunningState:
    def test_pending_task_is_running(self) -> None:
        assert (
            lifecycle_label(user_paused=False, tasks=[_task(status=TaskStatus.PENDING)])
            == "running"
        )

    def test_active_task_is_running(self) -> None:
        assert (
            lifecycle_label(user_paused=False, tasks=[_task(status=TaskStatus.ACTIVE)])
            == "running"
        )

    def test_done_and_failed_tasks_alone_are_done(self) -> None:
        """Historical-only state — nothing to schedule."""
        tasks = [
            _task("a", status=TaskStatus.DONE),
            _task("b", status=TaskStatus.FAILED),
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "done"

    def test_running_beats_blocked_when_pending_present(self) -> None:
        """A blocked task plus a pending one is still ``running``.

        The user can still expect work to happen — the loop hasn't stalled.
        """
        tasks = [
            _task("blocked", status=TaskStatus.BLOCKED, blocked_reason="dep missing"),
            _task("pending", status=TaskStatus.PENDING),
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "running"

    def test_running_beats_budget_block_when_pending_present(self) -> None:
        """Budget-blocked tasks alongside fresh pending work are still ``running``.

        Edge case: the budget tripped earlier on one task, but the planner
        spawned more pending work after raising the cap.  The loop is
        progressing, so the truthful label is ``running``.
        """
        tasks = [
            _task(
                "old",
                status=TaskStatus.BLOCKED,
                blocked_reason="Goal budget exceeded: too many iterations",
            ),
            _task("new", status=TaskStatus.PENDING),
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "running"


class TestBlockedState:
    def test_only_blocked_task_is_blocked(self) -> None:
        tasks = [_task(status=TaskStatus.BLOCKED, blocked_reason="dep missing")]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "blocked"

    def test_blocked_plus_done_is_blocked(self) -> None:
        """Done tasks don't change the label — only outstanding work does."""
        tasks = [
            _task("a", status=TaskStatus.DONE),
            _task("b", status=TaskStatus.BLOCKED, blocked_reason="dep missing"),
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "blocked"


class TestBudgetLimitedState:
    def test_budget_blocked_task_yields_budget_limited(self) -> None:
        tasks = [
            _task(
                status=TaskStatus.BLOCKED,
                blocked_reason="Goal budget exceeded: 50 iterations (cap: 50).",
            )
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "budget-limited"

    def test_budget_block_beats_generic_block(self) -> None:
        """Mixed blockers — budget label is more specific so it wins."""
        tasks = [
            _task("dep", status=TaskStatus.BLOCKED, blocked_reason="dep missing"),
            _task(
                "budget",
                status=TaskStatus.BLOCKED,
                blocked_reason="Goal budget exceeded: too many iterations.",
            ),
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "budget-limited"

    def test_budget_prefix_match_is_anchored(self) -> None:
        """Only the documented prefix counts as a budget block.

        A task with "Goal budget exceeded" appearing mid-string in a
        description doesn't trip the label — only the prefix on
        ``blocked_reason`` is load-bearing.
        """
        tasks = [
            _task(
                status=TaskStatus.BLOCKED,
                blocked_reason="dep missing — note that Goal budget exceeded earlier",
            )
        ]
        assert lifecycle_label(user_paused=False, tasks=tasks) == "blocked"


class TestPausePrecedence:
    def test_paused_beats_running(self) -> None:
        tasks = [_task(status=TaskStatus.PENDING)]
        assert lifecycle_label(user_paused=True, tasks=tasks) == "paused"

    def test_paused_beats_blocked(self) -> None:
        """ROADMAP 99.4 explicitly calls out this precedence."""
        tasks = [_task(status=TaskStatus.BLOCKED, blocked_reason="dep missing")]
        assert lifecycle_label(user_paused=True, tasks=tasks) == "paused"

    def test_paused_beats_budget_limited(self) -> None:
        tasks = [
            _task(
                status=TaskStatus.BLOCKED,
                blocked_reason="Goal budget exceeded: too many iterations.",
            )
        ]
        assert lifecycle_label(user_paused=True, tasks=tasks) == "paused"

    def test_paused_beats_done(self) -> None:
        """Even with no work, ``paused`` is more truthful than ``done``.

        The user explicitly stopped the loop; flipping to ``done`` would
        misrepresent the next chat-turn behaviour (which won't auto-start
        background work until ``/resume``).
        """
        assert lifecycle_label(user_paused=True, tasks=[]) == "paused"


class TestAgentIntegration:
    """``CantripAgent.lifecycle_label`` wires the projection to live state.

    These tests stand up a real agent and exercise the same projection
    code the TUI status bar and Web ``/api/state`` rely on, so a future
    refactor that moved ``user_paused`` or ``work_queue`` would surface
    immediately.
    """

    def test_fresh_agent_with_no_tasks_is_done(self) -> None:
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider())
        assert agent.lifecycle_label() == "done"

    def test_pause_flips_to_paused(self) -> None:
        from cantrip.agent.commands import slash as slash_commands
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/pause")
        assert agent.lifecycle_label() == "paused"

    def test_pending_task_flips_to_running(self) -> None:
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider())
        agent.work_queue.add_task(_task("build the charm", status=TaskStatus.PENDING))
        assert agent.lifecycle_label() == "running"

    def test_budget_blocked_task_flips_to_budget_limited(self) -> None:
        from cantrip.agent.core import CantripAgent
        from tests.conftest import FakeProvider

        agent = CantripAgent(provider=FakeProvider())
        agent.work_queue.add_task(
            _task(
                "stalled",
                status=TaskStatus.BLOCKED,
                blocked_reason="Goal budget exceeded: 50 iterations.",
            )
        )
        assert agent.lifecycle_label() == "budget-limited"
