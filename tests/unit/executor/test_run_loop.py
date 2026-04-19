"""Executor tests: run_loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    DEFAULT_MAX_CONCURRENCY,
    BackgroundExecutor,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.unit.executor.conftest import _make_executor, _make_tool

# ===================================================================
# TestRunLoop
# ===================================================================


class TestRunLoop:
    """Tests for _run_loop — the main poll-execute cycle."""

    @pytest.mark.asyncio
    async def test_picks_and_executes_ready_task(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        provider = FakeProvider(responses=[Response(content="Built.")])
        executor = _make_executor(queue=queue, provider=provider)
        executor.start()

        # Give the loop time to pick up the task.
        await asyncio.sleep(0.1)
        await executor.stop()

        assert task.status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_skips_when_no_tasks_ready(self) -> None:
        queue = WorkQueue()
        executor = _make_executor(queue=queue)
        executor.start()

        await asyncio.sleep(0.05)
        await executor.stop()

        # No tasks in the queue — loop should have just slept.
        assert executor.running is False

    @pytest.mark.asyncio
    async def test_confirm_tasks_blocked_not_executed(self) -> None:
        queue = WorkQueue()
        confirm = AgentTask(id="c1", title="Confirm path", category=TaskCategory.CONFIRM)
        queue.add_task(confirm)

        executor = _make_executor(queue=queue)
        executor.start()

        await asyncio.sleep(0.1)
        await executor.stop()

        assert confirm.status == TaskStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_executes_non_confirm_task(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        queue.add_task(task)

        provider = FakeProvider(responses=[Response(content="Researched.")])
        executor = _make_executor(queue=queue, provider=provider)
        executor.start()

        await asyncio.sleep(0.1)
        await executor.stop()

        assert task.status == TaskStatus.DONE
        assert task.result == "Researched."

    @pytest.mark.asyncio
    async def test_loop_survives_unexpected_error(self) -> None:
        """An unexpected error in _execute_task should not kill the loop."""
        queue = WorkQueue()
        bad_task = AgentTask(id="bad", title="Explode", category=TaskCategory.BUILD)
        good_task = AgentTask(id="good", title="Build", category=TaskCategory.BUILD)
        queue.add_task(bad_task)
        queue.add_task(good_task)

        provider = FakeProvider(responses=[Response(content="ok")])
        executor = _make_executor(queue=queue, provider=provider)

        call_count = 0
        original_execute = executor._execute_task

        async def _patched_execute(task: AgentTask) -> None:
            nonlocal call_count
            call_count += 1
            if task.id == "bad":
                # Transition out of PENDING so the loop doesn't pick it again.
                queue.set_failed(task.id, "boom")
                raise RuntimeError("boom")
            await original_execute(task)

        executor._execute_task = _patched_execute  # type: ignore[assignment]
        executor.start()

        await asyncio.sleep(0.2)
        await executor.stop()

        # The loop should have attempted both tasks.
        assert call_count >= 2


# ===================================================================
# TestCallbacks
# ===================================================================


class TestCallbacks:
    """Tests for on_task_done and on_task_failed callbacks."""

    @pytest.mark.asyncio
    async def test_on_task_done_fired_on_success(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        callback = MagicMock()
        provider = FakeProvider(responses=[Response(content="done")])
        executor = _make_executor(queue=queue, provider=provider, on_task_done=callback)

        await executor._execute_task(task)

        callback.assert_called_once_with(task)

    @pytest.mark.asyncio
    async def test_on_task_failed_fired_on_failure(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        callback = MagicMock()
        executor = _make_executor(queue=queue, on_task_failed=callback)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("fail"))
            await executor._execute_task(task)

        callback.assert_called_once_with(task)

    @pytest.mark.asyncio
    async def test_on_task_failed_fired_on_timeout(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Slow", category=TaskCategory.BUILD)
        queue.add_task(task)

        callback = MagicMock()
        executor = _make_executor(queue=queue, on_task_failed=callback)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=TimeoutError)
            await executor._execute_task(task)

        callback.assert_called_once_with(task)

    @pytest.mark.asyncio
    async def test_no_callback_does_not_crash(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        provider = FakeProvider(responses=[Response(content="ok")])
        executor = _make_executor(
            queue=queue, provider=provider, on_task_done=None, on_task_failed=None
        )

        await executor._execute_task(task)

        assert task.status == TaskStatus.DONE


# ===================================================================
# TestConcurrency
# ===================================================================


class TestConcurrency:
    """Tests for concurrent task execution."""

    def test_default_max_concurrency(self) -> None:
        executor = _make_executor()
        assert executor.max_concurrency == DEFAULT_MAX_CONCURRENCY

    def test_custom_max_concurrency(self) -> None:
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[],
            provider=FakeProvider(responses=[Response(content="ok")]),
            state=AgentState(),
            max_concurrency=5,
        )
        assert executor.max_concurrency == 5

    def test_min_concurrency_is_one(self) -> None:
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[],
            provider=FakeProvider(responses=[Response(content="ok")]),
            state=AgentState(),
            max_concurrency=0,
        )
        assert executor.max_concurrency == 1

    @pytest.mark.asyncio
    async def test_independent_tasks_run_concurrently(self) -> None:
        """Two independent tasks should overlap in execution time."""
        started: list[str] = []
        finished: list[str] = []
        both_started = asyncio.Event()
        start_count = 0

        queue = WorkQueue()
        t1 = AgentTask(id="a", title="Research A", category=TaskCategory.RESEARCH)
        t2 = AgentTask(id="b", title="Research B", category=TaskCategory.RESEARCH)
        queue.add_task(t1)
        queue.add_task(t2)

        provider = FakeProvider(
            responses=[
                Response(content="done-a"),
                Response(content="done-b"),
            ]
        )
        executor = _make_executor(queue=queue, provider=provider)

        original_execute = executor._execute_task

        async def _tracked_execute(task: AgentTask) -> None:
            nonlocal start_count
            started.append(task.id)
            start_count += 1
            if start_count >= 2:
                both_started.set()
            await original_execute(task)
            finished.append(task.id)

        executor._execute_task = _tracked_execute  # type: ignore[assignment]
        executor.start()

        # Wait for both tasks to be picked up concurrently.
        try:
            await asyncio.wait_for(both_started.wait(), timeout=3.0)
        finally:
            await executor.stop()

        assert set(started) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self) -> None:
        """With max_concurrency=1, tasks run sequentially."""
        execution_order: list[str] = []

        queue = WorkQueue()
        t1 = AgentTask(id="s1", title="First", category=TaskCategory.RESEARCH)
        t2 = AgentTask(id="s2", title="Second", category=TaskCategory.RESEARCH)
        queue.add_task(t1)
        queue.add_task(t2)

        provider = FakeProvider(
            responses=[
                Response(content="done-1"),
                Response(content="done-2"),
            ]
        )
        executor = BackgroundExecutor(
            queue=queue,
            tools=[_make_tool("read_file")],
            provider=provider,
            state=AgentState(),
            max_concurrency=1,
        )

        active_count = 0
        max_active = 0

        original_execute = executor._execute_task

        async def _tracking_execute(task: AgentTask) -> None:
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await original_execute(task)
            execution_order.append(task.id)
            active_count -= 1

        executor._execute_task = _tracking_execute  # type: ignore[assignment]
        executor.start()

        # Wait for both to complete.
        for _ in range(100):
            await asyncio.sleep(0.05)
            if queue.done_count >= 2:
                break

        await executor.stop()

        assert queue.done_count == 2
        # With max_concurrency=1, at most one task ran at a time.
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_dependent_tasks_run_sequentially(self) -> None:
        """A task depending on another waits for it to complete."""
        queue = WorkQueue()
        t1 = AgentTask(id="dep", title="Dependency", category=TaskCategory.RESEARCH)
        t2 = AgentTask(
            id="child",
            title="Dependent",
            category=TaskCategory.BUILD,
            dependencies=["dep"],
        )
        queue.add_task(t1)
        queue.add_task(t2)

        provider = FakeProvider(
            responses=[
                Response(content="dep done"),
                Response(content="child done"),
            ]
        )
        executor = _make_executor(queue=queue, provider=provider)
        executor.start()

        for _ in range(100):
            await asyncio.sleep(0.05)
            if queue.done_count >= 2:
                break

        await executor.stop()

        assert t1.status == TaskStatus.DONE
        assert t2.status == TaskStatus.DONE
        assert t1.result == "dep done"
        assert t2.result == "child done"
