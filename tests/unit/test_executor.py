"""Tests for the background executor."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    _MAX_NOOP_COUNT,
    DEFAULT_MAX_CONCURRENCY,
    BackgroundExecutor,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
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
    async def test_value_error_marks_task_failed(self) -> None:
        """A ValueError from a subagent marks the task as failed."""
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=ValueError("bad data"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert task.result == "bad data"

    @pytest.mark.asyncio
    async def test_key_error_marks_task_failed(self) -> None:
        """A KeyError from a subagent marks the task as failed."""
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=KeyError("missing_key"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED

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
    async def test_deploy_task_creates_verify_followup(self, tmp_path: Path) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy app", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(dev_model="dev", charm_path=tmp_path)
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
    async def test_followup_tasks_added_to_queue(self, tmp_path: Path) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(dev_model="dev", charm_path=tmp_path)
        provider = FakeProvider(responses=[Response(content="Done.")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        followups = [t for t in queue.all_tasks() if t.id != "d1"]
        assert len(followups) == 1
        assert followups[0].status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_no_followup_without_dev_model(self, tmp_path: Path) -> None:
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(charm_path=tmp_path)  # No dev_model.
        provider = FakeProvider(responses=[Response(content="ok")])
        executor = _make_executor(queue=queue, provider=provider, state=state)

        await executor._execute_task(task)

        # Pre-check fails (no dev_model), so task is failed + an INFRA fix task is queued.
        assert task.status == TaskStatus.FAILED
        all_tasks = queue.all_tasks()
        assert len(all_tasks) == 2
        assert all_tasks[1].category == TaskCategory.INFRA

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
    async def test_failed_verify_creates_debug_followup(self, tmp_path: Path) -> None:
        queue = WorkQueue()
        task = AgentTask(
            id="v1",
            title="Verify deployment: Deploy app",
            category=TaskCategory.DEPLOY,
        )
        queue.add_task(task)

        state = AgentState(dev_model="dev", charm_path=tmp_path)
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


# ===================================================================
# TestDesignContentHandoff
# ===================================================================


class TestDesignContentHandoff:
    """Tests for design content passthrough from state to SubagentContext."""

    def test_build_context_includes_design_content(self) -> None:
        """When state.design_proposal is set, design_content is passed through."""
        from cantrip.agent.design import DesignProposal

        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        state = AgentState()
        state.design_proposal = DesignProposal(raw_design_md="# Design: Redis\n## Substrate\nK8s")

        executor = _make_executor(queue=queue, state=state)
        ctx = executor._build_context(task)

        assert ctx.design_content == "# Design: Redis\n## Substrate\nK8s"

    def test_build_context_none_without_proposal(self) -> None:
        """When state.design_proposal is None, design_content is None."""
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)

        state = AgentState()
        executor = _make_executor(queue=queue, state=state)
        ctx = executor._build_context(task)

        assert ctx.design_content is None


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


# ===================================================================
# TestCheckUncommitted
# ===================================================================


class TestCheckUncommitted:
    """Tests for _check_uncommitted — post-task uncommitted change detection."""

    def test_logs_warning_when_uncommitted_changes(self) -> None:
        """A warning is logged when git reports uncommitted changes."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "status", "--porcelain"],
            returncode=0,
            stdout=" M src/charm.py\n",
            stderr="",
        )
        with (
            patch("cantrip.agent.executor.subprocess.run", return_value=completed),
            patch("cantrip.agent.executor.log") as mock_log,
        ):
            executor._check_uncommitted(task)

        mock_log.warning.assert_called_once()
        assert "uncommitted" in mock_log.warning.call_args[0][0]

    def test_no_warning_when_clean(self) -> None:
        """No warning is logged when the working tree is clean."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "status", "--porcelain"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with (
            patch("cantrip.agent.executor.subprocess.run", return_value=completed),
            patch("cantrip.agent.executor.log") as mock_log,
        ):
            executor._check_uncommitted(task)

        mock_log.warning.assert_not_called()

    def test_noop_when_charm_path_not_set(self) -> None:
        """Does nothing when charm_path is None."""
        state = AgentState()
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with patch("cantrip.agent.executor.subprocess.run") as mock_run:
            executor._check_uncommitted(task)

        mock_run.assert_not_called()


# ===================================================================
# TestPreCheckEnvironment
# ===================================================================


class TestPreCheckEnvironment:
    """Tests for _pre_check_environment — pre-task validation."""

    def test_deploy_fails_without_dev_model(self) -> None:
        """DEPLOY pre-check rejects when no development model is set."""
        state = AgentState(charm_path=Path("/tmp/charm"))
        executor = _make_executor(state=state)
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No development model set" in result

    def test_deploy_passes_with_dev_model_and_charm_path(self, tmp_path: Path) -> None:
        """DEPLOY pre-check passes when dev_model and charm_path are set."""
        state = AgentState(dev_model="dev", charm_path=tmp_path)
        executor = _make_executor(state=state)
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)

        result = executor._pre_check_environment(task)

        assert result is None

    def test_deploy_fails_when_charm_path_missing(self) -> None:
        """DEPLOY pre-check rejects when charm_path is not set."""
        state = AgentState(dev_model="dev")
        executor = _make_executor(state=state)
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No charm path set" in result

    def test_deploy_fails_when_charm_path_does_not_exist(self) -> None:
        """DEPLOY pre-check rejects when charm directory does not exist."""
        state = AgentState(dev_model="dev", charm_path=Path("/nonexistent/path"))
        executor = _make_executor(state=state)
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "does not exist" in result

    def test_test_fails_without_charm_path(self) -> None:
        """TEST pre-check rejects when charm_path is not set."""
        state = AgentState()
        executor = _make_executor(state=state)
        task = AgentTask(id="t1", title="Test", category=TaskCategory.TEST)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No charm path set" in result

    def test_test_fails_without_charm_file(self, tmp_path: Path) -> None:
        """TEST pre-check rejects when no .charm file exists."""
        state = AgentState(charm_path=tmp_path)
        executor = _make_executor(state=state)
        task = AgentTask(id="t1", title="Test", category=TaskCategory.TEST)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No packed charm found" in result

    def test_test_passes_with_charm_file(self, tmp_path: Path) -> None:
        """TEST pre-check passes when a .charm file exists."""
        (tmp_path / "myapp.charm").touch()
        state = AgentState(charm_path=tmp_path)
        executor = _make_executor(state=state)
        task = AgentTask(id="t1", title="Test", category=TaskCategory.TEST)

        result = executor._pre_check_environment(task)

        assert result is None

    def test_research_always_passes(self) -> None:
        """RESEARCH pre-check always returns None."""
        state = AgentState()
        executor = _make_executor(state=state)
        task = AgentTask(id="r1", title="Research", category=TaskCategory.RESEARCH)

        result = executor._pre_check_environment(task)

        assert result is None

    @pytest.mark.asyncio
    async def test_deploy_without_dev_model_marked_failed(self) -> None:
        """A DEPLOY task with no dev_model is failed without running a subagent."""
        queue = WorkQueue()
        task = AgentTask(id="d1", title="Deploy app", category=TaskCategory.DEPLOY)
        queue.add_task(task)

        state = AgentState(charm_path=Path("/tmp/charm"))
        failed_cb = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=failed_cb)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            await executor._execute_task(task)
            mock_cls.assert_not_called()

        assert task.status == TaskStatus.FAILED
        assert "No development model set" in (task.result or "")
        failed_cb.assert_called_once_with(task)

        # Should also queue an INFRA task to fix the missing model.
        infra_tasks = [t for t in queue.all_tasks() if t.category == TaskCategory.INFRA]
        assert len(infra_tasks) == 1
        assert "development model" in infra_tasks[0].title.lower()


# ===================================================================
# TestSnapshotHead
# ===================================================================


class TestSnapshotHead:
    """Tests for _snapshot_head — capturing git HEAD before task execution."""

    def test_returns_none_when_charm_path_not_set(self) -> None:
        """Returns None when no charm path is configured."""
        state = AgentState()
        executor = _make_executor(state=state)

        assert executor._snapshot_head() is None

    def test_returns_commit_hash_when_charm_path_set(self) -> None:
        """Returns the HEAD commit hash from subprocess output."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        executor = _make_executor(state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=0,
            stdout="abc123def456\n",
            stderr="",
        )
        with patch("cantrip.agent.executor.subprocess.run", return_value=completed):
            result = executor._snapshot_head()

        assert result == "abc123def456"

    def test_returns_none_on_git_failure(self) -> None:
        """Returns None when git rev-parse fails."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        executor = _make_executor(state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )
        with patch("cantrip.agent.executor.subprocess.run", return_value=completed):
            result = executor._snapshot_head()

        assert result is None


# ===================================================================
# TestRevertOnFailure
# ===================================================================


class TestRevertOnFailure:
    """Tests for _revert_on_failure — restoring tracked files after failure."""

    def test_runs_git_checkout_and_logs_warning(self) -> None:
        """Reverts tracked files and logs a warning."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        diff_result = subprocess.CompletedProcess(
            args=["git", "diff"], returncode=0, stdout="diff --git ...\n", stderr=""
        )
        checkout_result = subprocess.CompletedProcess(
            args=["git", "checkout", "."], returncode=0, stdout="", stderr=""
        )

        with (
            patch(
                "cantrip.agent.executor.subprocess.run",
                side_effect=[diff_result, checkout_result],
            ),
            patch("cantrip.agent.executor.log") as mock_log,
        ):
            executor._revert_on_failure("abc123def456", task)

        mock_log.warning.assert_called_once()
        assert "Reverted" in mock_log.warning.call_args[0][0]

    def test_prepends_diff_to_task_result(self) -> None:
        """The captured diff is prepended to the task result."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.result = "original error"
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        diff_result = subprocess.CompletedProcess(
            args=["git", "diff"],
            returncode=0,
            stdout="+added line\n-removed line\n",
            stderr="",
        )
        checkout_result = subprocess.CompletedProcess(
            args=["git", "checkout", "."], returncode=0, stdout="", stderr=""
        )

        with patch(
            "cantrip.agent.executor.subprocess.run",
            side_effect=[diff_result, checkout_result],
        ):
            executor._revert_on_failure("abc123def456", task)

        assert task.result is not None
        assert task.result.startswith("[reverted diff]")
        assert "original error" in task.result


# ===================================================================
# TestGitRevertOnTaskFailure
# ===================================================================


class TestGitRevertOnTaskFailure:
    """Tests for git-revert-on-failure integration in _execute_task."""

    @pytest.mark.asyncio
    async def test_revert_called_on_build_failure(self) -> None:
        """_revert_on_failure is called when a BUILD task fails."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123") as mock_snap,
            patch.object(executor, "_revert_on_failure") as mock_revert,
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("build broke"))
            await executor._execute_task(task)

        mock_snap.assert_called_once()
        mock_revert.assert_called_once_with("abc123", task)

    @pytest.mark.asyncio
    async def test_revert_called_on_build_timeout(self) -> None:
        """_revert_on_failure is called when a BUILD task times out."""
        state = AgentState(charm_path=Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123"),
            patch.object(executor, "_revert_on_failure") as mock_revert,
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=TimeoutError)
            await executor._execute_task(task)

        mock_revert.assert_called_once_with("abc123", task)

    @pytest.mark.asyncio
    async def test_no_revert_on_research_failure(self) -> None:
        """_revert_on_failure is NOT called when a RESEARCH task fails."""
        queue = WorkQueue()
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        queue.add_task(task)

        executor = _make_executor(queue=queue)

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head") as mock_snap,
            patch.object(executor, "_revert_on_failure") as mock_revert,
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("research failed"))
            await executor._execute_task(task)

        mock_snap.assert_not_called()
        mock_revert.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_revert_when_snapshot_is_none(self) -> None:
        """_revert_on_failure is NOT called when _snapshot_head returns None."""
        state = AgentState()  # No charm_path.
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_revert_on_failure") as mock_revert,
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("boom"))
            await executor._execute_task(task)

        mock_revert.assert_not_called()


# ===================================================================
# TestNoopDetection
# ===================================================================


class TestNoopDetection:
    """Tests for noop detection in _execute_task."""

    @pytest.mark.asyncio
    async def test_noop_resets_to_pending(self) -> None:
        """First noop resets the task to pending for another attempt."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(
            id="b1", title="Build charm", category=TaskCategory.BUILD
        )
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", return_value="same-hash"),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=SubagentResult(ExitState.COMPLETED, "done"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.PENDING
        assert task.noop_count == 1

    @pytest.mark.asyncio
    async def test_noop_escalation_blocks_task(self) -> None:
        """After MAX_NOOP_COUNT noops, the task is blocked for user intervention."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(
            id="b1",
            title="Build charm",
            category=TaskCategory.BUILD,
            noop_count=_MAX_NOOP_COUNT - 1,
        )
        queue.add_task(task)
        queue.set_active(task.id)

        on_failed = MagicMock()
        executor = _make_executor(
            queue=queue, state=state, on_task_failed=on_failed
        )

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", return_value="same-hash"),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=SubagentResult(ExitState.COMPLETED, "done"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.BLOCKED
        assert task.noop_count == _MAX_NOOP_COUNT
        on_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_noop_when_fingerprint_changes(self) -> None:
        """Normal execution with changes is not flagged as noop."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(
            id="b1", title="Build charm", category=TaskCategory.BUILD
        )
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        call_count = 0

        def _changing_fingerprint() -> str:
            nonlocal call_count
            call_count += 1
            return f"hash-{call_count}"

        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", side_effect=_changing_fingerprint),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=SubagentResult(ExitState.COMPLETED, "completed work"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.noop_count == 0

    @pytest.mark.asyncio
    async def test_no_noop_when_no_charm_path(self) -> None:
        """Without a charm path, fingerprint is empty and noop is skipped."""
        state = AgentState()  # No charm_path.
        queue = WorkQueue()
        task = AgentTask(
            id="r1", title="Research", category=TaskCategory.RESEARCH
        )
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        with patch("cantrip.agent.executor.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=SubagentResult(ExitState.COMPLETED, "research done"))
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.noop_count == 0

    def test_fingerprint_without_charm_path(self) -> None:
        """Fingerprint returns empty string when no charm path is set."""
        state = AgentState()
        executor = _make_executor(state=state)
        assert executor._fingerprint() == ""

    def test_is_noop_identical(self) -> None:
        state = AgentState()
        executor = _make_executor(state=state)
        assert executor._is_noop("abc", "abc") is True

    def test_is_noop_different(self) -> None:
        state = AgentState()
        executor = _make_executor(state=state)
        assert executor._is_noop("abc", "def") is False

    def test_is_noop_empty_before(self) -> None:
        """Empty before-fingerprint means we can't detect noop."""
        state = AgentState()
        executor = _make_executor(state=state)
        assert executor._is_noop("", "") is False


# ===================================================================
# TestExitStateHandling
# ===================================================================


class TestExitStateHandling:
    """Tests for structured subagent exit state handling."""

    @pytest.mark.asyncio
    async def test_blocked_exit_blocks_task(self) -> None:
        """Subagent signalling BLOCKED causes the task to be blocked."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        on_failed = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=on_failed)

        result = SubagentResult(ExitState.BLOCKED, "Need database credentials")
        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.BLOCKED
        on_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_exit_fails_task(self) -> None:
        """Subagent signalling FAILED causes the task to fail."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        on_failed = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=on_failed)

        result = SubagentResult(ExitState.FAILED, "charmcraft pack error", "Full error details")
        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert "Full error details" in (task.result or "")
        on_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_exit_triggers_noop_handling(self) -> None:
        """Subagent signalling NOOP triggers the noop counter."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        result = SubagentResult(ExitState.NOOP, "Nothing to do")
        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", return_value="different"),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.PENDING
        assert task.noop_count == 1

    @pytest.mark.asyncio
    async def test_completed_exit_marks_done(self) -> None:
        """Subagent signalling COMPLETED marks the task as done."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="r1", title="Research", category=TaskCategory.RESEARCH)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        result = SubagentResult(ExitState.COMPLETED, "Research complete", "Found 3 sources")
        with (
            patch("cantrip.agent.executor.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", side_effect=["a", "b"]),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.result == "Found 3 sources"
