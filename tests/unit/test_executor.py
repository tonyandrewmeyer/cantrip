"""Tests for the background executor."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str) -> Tool:
    """Build a minimal Tool stub with the given *name*."""

    class _StubTool(Tool):
        @property
        def _name(self) -> str:
            return name

        @property
        def _desc(self) -> str:
            return f"Stub tool {name}"

        @property
        def _params(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

    class StubTool(_StubTool):
        @property
        def name(self) -> str:  # type: ignore[override]
            return self._name

        @property
        def description(self) -> str:  # type: ignore[override]
            return self._desc

        @property
        def parameters(self) -> dict[str, Any]:  # type: ignore[override]
            return self._params

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            return ToolResult(success=True, output="ok")

    return StubTool()


def _make_executor(
    queue: WorkQueue | None = None,
    state: AgentState | None = None,
    provider: FakeProvider | None = None,
    store: MagicMock | None = None,
    light_provider: FakeProvider | None = None,
    on_task_done: Any = None,
    on_task_failed: Any = None,
) -> BackgroundExecutor:
    """Build a BackgroundExecutor with sensible defaults."""
    return BackgroundExecutor(
        queue=queue or WorkQueue(),
        tools=[_make_tool("read_file")],
        provider=provider or FakeProvider(responses=[Response(content="done")]),
        state=state or AgentState(),
        store=store,
        light_provider=light_provider,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
    )


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
# TestBuildContext
# ===================================================================


class TestBuildContext:
    """Tests for _build_context — SubagentContext construction."""

    def test_context_from_empty_state(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        ctx = executor._build_context(task)

        assert ctx.task is task
        assert ctx.charm_name is None
        assert ctx.charm_path is None
        assert ctx.decisions == []
        assert ctx.prior_results == {}

    def test_context_copies_state_fields(self) -> None:
        state = AgentState(
            charm_name="redis-k8s",
            charm_path=Path("/tmp/redis-k8s"),
            charm_type="k8s",
            framework="flask",
            dev_model="dev",
            cos_model="cos",
        )
        state.add_decision("substrate", "k8s", "User chose Kubernetes")

        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)
        ctx = executor._build_context(task)

        assert ctx.charm_name == "redis-k8s"
        assert ctx.charm_path == "/tmp/redis-k8s"
        assert ctx.charm_type == "k8s"
        assert ctx.framework == "flask"
        assert ctx.dev_model == "dev"
        assert ctx.cos_model == "cos"
        assert len(ctx.decisions) == 1
        assert ctx.decisions[0]["type"] == "substrate"
        assert ctx.decisions[0]["choice"] == "k8s"

    def test_prior_results_from_dependencies(self) -> None:
        queue = WorkQueue()
        dep = AgentTask(id="dep1", title="Research", category=TaskCategory.RESEARCH)
        dep.status = TaskStatus.DONE
        dep.result = "Found Redis docs"
        queue.add_task(dep)

        task = AgentTask(
            id="t1",
            title="Build",
            category=TaskCategory.BUILD,
            dependencies=["dep1"],
        )
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        ctx = executor._build_context(task)

        assert ctx.prior_results == {"dep1": "Found Redis docs"}

    def test_missing_dependency_result_omitted(self) -> None:
        queue = WorkQueue()
        dep = AgentTask(id="dep1", title="Research", category=TaskCategory.RESEARCH)
        dep.status = TaskStatus.DONE
        dep.result = None  # No result recorded.
        queue.add_task(dep)

        task = AgentTask(
            id="t1",
            title="Build",
            category=TaskCategory.BUILD,
            dependencies=["dep1"],
        )
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        ctx = executor._build_context(task)

        assert ctx.prior_results == {}

    def test_nonexistent_dependency_omitted(self) -> None:
        queue = WorkQueue()
        task = AgentTask(
            id="t1",
            title="Build",
            category=TaskCategory.BUILD,
            dependencies=["nonexistent"],
        )
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        ctx = executor._build_context(task)

        assert ctx.prior_results == {}


# ===================================================================
# TestExecuteTask
# ===================================================================


class TestExecuteTask:
    """Tests for _execute_task — subagent invocation and result recording."""

    @pytest.mark.asyncio
    async def test_successful_task_marked_done(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        provider = FakeProvider(responses=[Response(content="Build complete.")])
        executor = _make_executor(queue=queue, provider=provider)

        await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.result == "Build complete."

    @pytest.mark.asyncio
    async def test_failed_subagent_marks_task_failed(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("LLM exploded"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert task.result == "LLM exploded"

    @pytest.mark.asyncio
    async def test_timeout_marks_task_failed(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Slow", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=TimeoutError)
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert task.result == "Task timed out"

    @pytest.mark.asyncio
    async def test_store_save_tasks_called(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        store = MagicMock()
        provider = FakeProvider(responses=[Response(content="done")])
        executor = _make_executor(queue=queue, provider=provider, store=store)

        await executor._execute_task(task)

        store.save_tasks.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_save_tasks_called_on_failure(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        store = MagicMock()
        executor = _make_executor(queue=queue, store=store)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("boom"))
            await executor._execute_task(task)

        store.save_tasks.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_store_does_not_crash(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        provider = FakeProvider(responses=[Response(content="ok")])
        executor = _make_executor(queue=queue, provider=provider, store=None)

        await executor._execute_task(task)

        assert task.status == TaskStatus.DONE


# ===================================================================
# TestHandleConfirm
# ===================================================================


class TestHandleConfirm:
    """Tests for _handle_confirm — CONFIRM task blocking."""

    def test_confirm_task_set_to_blocked(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="c1", title="Confirm substrate", category=TaskCategory.CONFIRM)
        queue.add_task(task)

        executor = _make_executor(queue=queue)
        executor._handle_confirm(task)

        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == "Waiting for user confirmation"

    def test_on_task_done_callback_fired(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="c1", title="Confirm substrate", category=TaskCategory.CONFIRM)
        queue.add_task(task)

        callback = MagicMock()
        executor = _make_executor(queue=queue, on_task_done=callback)
        executor._handle_confirm(task)

        callback.assert_called_once_with(task)

    def test_confirm_persists_tasks(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="c1", title="Confirm", category=TaskCategory.CONFIRM)
        queue.add_task(task)

        store = MagicMock()
        executor = _make_executor(queue=queue, store=store)
        executor._handle_confirm(task)

        store.save_tasks.assert_called_once()


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
# TestFollowupTaskCreation
# ===================================================================


class TestFollowupTaskCreation:
    """Tests for automatic follow-up task creation after task execution."""

    @pytest.mark.asyncio
    async def test_deploy_task_creates_verify_followup(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy app", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(dev_model="dev")
        provider = FakeProvider(responses=[Response(content="Deployed.")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        all_tasks = queue.all_tasks()
        assert len(all_tasks) == 2
        verify = all_tasks[1]
        assert verify.title.startswith("Verify deployment:")
        assert verify.dependencies == ["d1"]

    @pytest.mark.asyncio
    async def test_research_task_creates_no_followup(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        queue.add_task(task)

        state = AgentState(dev_model="dev")
        provider = FakeProvider(responses=[Response(content="Researched.")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        assert len(queue.all_tasks()) == 1

    @pytest.mark.asyncio
    async def test_followup_tasks_added_to_queue(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(dev_model="dev")
        provider = FakeProvider(responses=[Response(content="Done.")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        followups = [t for t in queue.all_tasks() if t.id != "d1"]
        assert len(followups) == 1
        assert followups[0].status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_no_followup_without_dev_model(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState()  # No dev_model.
        provider = FakeProvider(responses=[Response(content="ok")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        assert len(queue.all_tasks()) == 1

    @pytest.mark.asyncio
    async def test_build_task_creates_deploy_followup(self) -> None:
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        state = AgentState(dev_model="dev")
        provider = FakeProvider(responses=[Response(content="Charm built.")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        all_tasks = queue.all_tasks()
        assert len(all_tasks) == 2
        deploy = all_tasks[1]
        assert "Deploy changes:" in deploy.title
        assert deploy.category == TaskCategory.DEPLOY
        assert deploy.dependencies == ["b1"]

    @pytest.mark.asyncio
    async def test_failed_verify_creates_debug_followup(self) -> None:
        queue = WorkQueue()
        task = AgentTask(
            id="v1",
            title="Verify deployment: Deploy app",
            category=TaskCategory.DEPLOY,
        )
        queue.add_task(task)

        state = AgentState(dev_model="dev")
        executor = _make_executor(queue=queue, state=state)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("verification failed"))
            await executor._execute_task(task)

        all_tasks = queue.all_tasks()
        assert len(all_tasks) == 2
        debug = all_tasks[1]
        assert "Diagnose" in debug.title
        assert debug.category == TaskCategory.DEBUG
