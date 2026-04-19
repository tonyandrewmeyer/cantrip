"""Executor tests: execution."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    _DEFAULT_TASK_TIMEOUT,
    _TASK_TIMEOUTS,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.unit.executor.conftest import _make_executor

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
# TestCategorySpecificTimeouts
# ===================================================================


class TestCategorySpecificTimeouts:
    """Tests for per-category task timeout values (Phase 28.12)."""

    def test_research_timeout_is_300(self) -> None:
        """RESEARCH tasks get a shorter timeout since they are lightweight."""
        assert _TASK_TIMEOUTS[TaskCategory.RESEARCH] == 300

    def test_build_timeout_is_900(self) -> None:
        """BUILD tasks get a longer timeout for charmcraft pack."""
        assert _TASK_TIMEOUTS[TaskCategory.BUILD] == 900

    def test_deploy_timeout_is_900(self) -> None:
        """DEPLOY tasks get a longer timeout for juju operations."""
        assert _TASK_TIMEOUTS[TaskCategory.DEPLOY] == 900

    def test_test_timeout_is_600(self) -> None:
        """TEST tasks use the standard timeout."""
        assert _TASK_TIMEOUTS[TaskCategory.TEST] == 600

    def test_debug_timeout_is_600(self) -> None:
        """DEBUG tasks use the standard timeout."""
        assert _TASK_TIMEOUTS[TaskCategory.DEBUG] == 600

    def test_unknown_category_uses_default(self) -> None:
        """Categories not in the dict fall back to _DEFAULT_TASK_TIMEOUT."""
        assert _TASK_TIMEOUTS.get(TaskCategory.INFRA) is None
        assert _DEFAULT_TASK_TIMEOUT == 600

    @pytest.mark.asyncio
    async def test_execute_task_uses_category_timeout(self) -> None:
        """The executor passes the category-specific timeout to wait_for."""
        queue = WorkQueue()
        task = AgentTask(title="Pack charm", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        state = AgentState()
        executor = _make_executor(queue=queue, state=state)

        mock_result = SubagentResult(summary="ok", exit_state=ExitState.COMPLETED)
        captured_timeout: float | None = None

        async def fake_wait_for(coro, *, timeout=None):
            nonlocal captured_timeout
            captured_timeout = timeout
            # Cancel the real coroutine and return a fake result.
            coro.close()
            return mock_result

        with patch("cantrip.agent.executor.asyncio.wait_for", side_effect=fake_wait_for):
            await executor._execute_task(task)

        assert captured_timeout == 900
