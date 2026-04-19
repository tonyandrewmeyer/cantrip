"""Executor tests: lifecycle."""

import asyncio

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from tests.unit.executor.conftest import _make_executor

# ===================================================================
# TestBackgroundExecutorLifecycle
# ===================================================================


class TestBackgroundExecutorLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self) -> None:
        executor = _make_executor()
        executor.start()
        assert executor.running is True
        await executor.stop()

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        executor = _make_executor()
        executor.start()
        first_task = executor._task
        executor.start()
        assert executor._task is first_task
        await executor.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self) -> None:
        executor = _make_executor()
        executor.start()
        await executor.stop()
        assert executor.running is False
        assert executor._task is None

    @pytest.mark.asyncio
    async def test_double_stop_is_noop(self) -> None:
        executor = _make_executor()
        executor.start()
        await executor.stop()
        await executor.stop()
        assert executor.running is False

    def test_not_running_initially(self) -> None:
        executor = _make_executor()
        assert executor.running is False

    def test_not_paused_initially(self) -> None:
        executor = _make_executor()
        assert executor.paused is False


# ===================================================================
# TestBackgroundExecutorPauseResume
# ===================================================================


class TestBackgroundExecutorPauseResume:
    """Tests for pause/resume behaviour."""

    @pytest.mark.asyncio
    async def test_pause_sets_paused(self) -> None:
        executor = _make_executor()
        executor.start()
        executor.pause()
        assert executor.paused is True
        await executor.stop()

    @pytest.mark.asyncio
    async def test_resume_clears_paused(self) -> None:
        executor = _make_executor()
        executor.start()
        executor.pause()
        executor.resume()
        assert executor.paused is False
        await executor.stop()

    @pytest.mark.asyncio
    async def test_pause_when_not_running_is_noop(self) -> None:
        executor = _make_executor()
        executor.pause()
        assert executor.paused is False

    @pytest.mark.asyncio
    async def test_resume_when_not_paused_is_noop(self) -> None:
        executor = _make_executor()
        executor.start()
        executor.resume()
        assert executor.paused is False
        await executor.stop()

    @pytest.mark.asyncio
    async def test_paused_executor_does_not_pick_tasks(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        executor.start()
        executor.pause()

        # Give the loop time to run while paused.
        await asyncio.sleep(0.15)

        # Task should still be pending (not picked up).
        assert task.status == TaskStatus.PENDING
        await executor.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_paused(self) -> None:
        executor = _make_executor()
        executor.start()
        executor.pause()
        await executor.stop()
        assert executor.paused is False


# ===================================================================
# TestGracefulShutdown
# ===================================================================


class TestGracefulShutdown:
    """Tests for two-stage graceful shutdown."""

    def test_cleanup_resets_active_to_pending(self) -> None:
        """ACTIVE tasks are reset to PENDING on startup/force-stop."""
        queue = WorkQueue()
        t1 = AgentTask(id="a1", title="Active task", category=TaskCategory.BUILD)
        t2 = AgentTask(id="a2", title="Pending task", category=TaskCategory.BUILD)
        queue.add_task(t1)
        queue.add_task(t2)
        queue.set_active(t1.id)

        executor = _make_executor(queue=queue)
        executor._cleanup_active_tasks()

        assert t1.status == TaskStatus.PENDING
        assert t2.status == TaskStatus.PENDING

    def test_cleanup_leaves_done_tasks(self) -> None:
        """DONE tasks are not touched by cleanup."""
        queue = WorkQueue()
        t1 = AgentTask(id="d1", title="Done task", category=TaskCategory.BUILD)
        queue.add_task(t1)
        queue.set_done(t1.id, "completed")

        executor = _make_executor(queue=queue)
        executor._cleanup_active_tasks()

        assert t1.status == TaskStatus.DONE

    def test_draining_property(self) -> None:
        executor = _make_executor()
        assert executor.draining is False

    @pytest.mark.asyncio
    async def test_drain_sets_paused_and_draining(self) -> None:
        executor = _make_executor()
        executor.start()

        # Drain immediately (no in-flight tasks).
        await executor.drain()

        assert executor.running is False

    @pytest.mark.asyncio
    async def test_force_stop_cancels_and_cleans_up(self) -> None:
        queue = WorkQueue()
        t1 = AgentTask(id="a1", title="Active task", category=TaskCategory.BUILD)
        queue.add_task(t1)
        queue.set_active(t1.id)

        executor = _make_executor(queue=queue)
        executor._running = True

        await executor.force_stop()

        assert executor.running is False
        # Active task should be reset to pending.
        assert t1.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_start_resets_active_tasks(self) -> None:
        """Starting the executor resets stuck ACTIVE tasks."""
        queue = WorkQueue()
        t1 = AgentTask(id="a1", title="Stuck task", category=TaskCategory.BUILD)
        queue.add_task(t1)
        queue.set_active(t1.id)

        executor = _make_executor(queue=queue)
        executor.start()

        assert t1.status == TaskStatus.PENDING
        # Clean up.
        await executor.stop()
