"""Executor tests: Phase 55.3 per-goal goal_budget gate."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.goal_budget import GoalBudget
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.unit.executor.conftest import _make_tool


@pytest.fixture
def store(tmp_path: pathlib.Path) -> SessionStore:
    db = tmp_path / ".cantrip"
    s = SessionStore(db)
    s.open()
    s.save_session(AgentState(charm_name="x", charm_path=tmp_path))
    return s


class TestBudgetGate:
    """The executor's per-goal budget gate blocks spawns when tripped."""

    def _make_executor_with_budget(
        self,
        store: SessionStore,
        state: AgentState,
        callback_target: list,
    ) -> BackgroundExecutor:
        return BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=store,
            on_budget_exceeded=lambda task, reason: callback_target.append((task.id, reason)),
        )

    def test_gate_passes_without_budget(self, store: SessionStore) -> None:
        state = AgentState(goal_budget=None)
        executor = self._make_executor_with_budget(store, state, [])
        assert executor._check_goal_budget() is None

    def test_gate_passes_when_under_cap(self, store: SessionStore) -> None:
        state = AgentState(goal_budget=GoalBudget(max_iterations=10))
        executor = self._make_executor_with_budget(store, state, [])
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
        )
        assert executor._check_goal_budget() is None

    def test_gate_trips_when_cap_exceeded(self, store: SessionStore) -> None:
        state = AgentState(goal_budget=GoalBudget(max_iterations=2))
        executor = self._make_executor_with_budget(store, state, [])
        for _ in range(2):
            store.record_usage(
                provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
            )
        reason = executor._check_goal_budget()
        assert reason is not None
        assert "iterations" in reason

    def test_gate_is_noop_without_store(self) -> None:
        """No store means we can't measure usage — gate must not claim trip."""
        state = AgentState(goal_budget=GoalBudget(max_iterations=1))
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=None,
        )
        assert executor._check_goal_budget() is None


class TestBudgetBlocksSpawn:
    """End-to-end: a tripped budget blocks the task and fires the callback."""

    @pytest.mark.asyncio
    async def test_exceeded_budget_blocks_ready_task(self, store: SessionStore) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        # Fill the store with exactly one iteration, then set a cap of 1
        # so the very next spawn attempt trips.
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
        )
        state = AgentState(goal_budget=GoalBudget(max_iterations=1))
        triggered: list[tuple[str, str]] = []

        executor = BackgroundExecutor(
            queue=queue,
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=store,
            on_budget_exceeded=lambda t, r: triggered.append((t.id, r)),
        )
        executor.start()

        # Give the loop enough time to pick up the task and trip the gate.
        await asyncio.sleep(0.2)
        await executor.stop()

        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason is not None
        assert "iterations" in task.blocked_reason.lower()
        assert len(triggered) == 1
        assert triggered[0][0] == "t1"
        assert "iterations" in triggered[0][1].lower()

    @pytest.mark.asyncio
    async def test_raised_cap_releases_previously_blocked_task(self, store: SessionStore) -> None:
        """Raising the cap + flipping the task back to pending lets it run.

        Mirrors what the ``/budget`` slash command does when the user
        raises the cap: blocked-for-budget tasks go back to pending
        and the executor's next poll picks them up.
        """
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
        )
        state = AgentState(goal_budget=GoalBudget(max_iterations=1))

        executor = BackgroundExecutor(
            queue=queue,
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=store,
        )
        executor.start()
        await asyncio.sleep(0.2)
        assert task.status == TaskStatus.BLOCKED

        # Operator raises the cap and unblocks the task (the
        # ``/budget`` handler does both).
        state.goal_budget.max_iterations = 100  # type: ignore[union-attr]
        queue.set_pending(task.id)

        # Wait for the executor's next poll to pick the task up and
        # for the subagent to finish.  The poll interval is 1s so we
        # have to be patient here — a shorter sleep is flaky.
        await asyncio.sleep(2.0)
        await executor.stop()

        assert task.status == TaskStatus.DONE
