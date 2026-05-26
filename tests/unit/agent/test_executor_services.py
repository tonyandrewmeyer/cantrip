"""Tests for executor protocol-based service injection (Phase 21.2).

These tests exercise the BackgroundExecutor using fake service
implementations injected via constructor parameters, proving the
executor is testable without subprocess calls, real LLM providers,
or filesystem access.
"""

from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.llm.base import Response
from tests.conftest import (
    FakeEnvironmentChecker,
    FakeFollowupPlanner,
    FakeGitService,
    FakeProvider,
    FakeStateService,
)
from tests.support.tools import make_stub_tool as _make_tool


def _make_executor(
    queue: WorkQueue | None = None,
    state: AgentState | None = None,
    provider: FakeProvider | None = None,
    *,
    git_service: FakeGitService | None = None,
    env_checker: FakeEnvironmentChecker | None = None,
    state_service: FakeStateService | None = None,
    followup_planner: FakeFollowupPlanner | None = None,
    on_task_done: Any = None,
    on_task_failed: Any = None,
) -> BackgroundExecutor:
    """Build a BackgroundExecutor with injected fake services."""
    return BackgroundExecutor(
        queue=queue or WorkQueue(),
        tools=[_make_tool("read_file")],
        provider=provider or FakeProvider(responses=[Response(content="done")]),
        state=state or AgentState(),
        git_service=git_service or FakeGitService(),
        env_checker=env_checker or FakeEnvironmentChecker(),
        state_service=state_service or FakeStateService(),
        followup_planner=followup_planner or FakeFollowupPlanner(),
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
    )


# ===================================================================
# TestServiceInjection — verify services are wired up
# ===================================================================


class TestServiceInjection:
    """Verify that injected services are used instead of defaults."""

    def test_git_fingerprint_uses_fake(self) -> None:
        git = FakeGitService(fingerprints=["hash-123"])
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        executor = _make_executor(state=state, git_service=git)
        assert executor._fingerprint() == "hash-123"

    def test_git_snapshot_head_uses_fake(self) -> None:
        git = FakeGitService(head="deadbeef")
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        executor = _make_executor(state=state, git_service=git)
        assert executor._snapshot_head() == "deadbeef"

    def test_env_checker_uses_fake(self) -> None:
        checker = FakeEnvironmentChecker(error="no model")
        executor = _make_executor(env_checker=checker)
        task = AgentTask(title="Deploy", category=TaskCategory.DEPLOY)
        assert executor._pre_check_environment(task) == "no model"

    def test_env_checker_passes_when_no_error(self) -> None:
        checker = FakeEnvironmentChecker(error=None)
        executor = _make_executor(env_checker=checker)
        task = AgentTask(title="Deploy", category=TaskCategory.DEPLOY)
        assert executor._pre_check_environment(task) is None

    def test_state_service_records_events(self) -> None:
        svc = FakeStateService()
        executor = _make_executor(state_service=svc)
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        executor._record_status_change(task, "active", old_status="pending")
        assert len(svc.events) == 1
        assert svc.events[0][0] == "task_status_change"
        assert svc.events[0][1]["task_id"] == "t1"

    def test_state_service_persists_tasks(self) -> None:
        svc = FakeStateService()
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        executor = _make_executor(queue=queue, state_service=svc)
        executor._persist()
        assert len(svc.saved_tasks) == 1
        assert svc.saved_tasks[0][0].id == "t1"


# ===================================================================
# TestExecuteTaskWithFakes — full task execution using fakes
# ===================================================================


class TestExecuteTaskWithFakes:
    """Test _execute_task using injected fake services."""

    @pytest.mark.asyncio
    async def test_successful_build_task(self) -> None:
        """A successful BUILD task uses git fingerprint and state service."""
        git = FakeGitService(fingerprints=["fp-before", "fp-after"])
        svc = FakeStateService()
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        done_tasks: list[AgentTask] = []
        executor = _make_executor(
            queue=queue,
            state=state,
            git_service=git,
            state_service=svc,
            on_task_done=done_tasks.append,
        )

        result = SubagentResult(
            exit_state=ExitState.COMPLETED,
            summary="Built charm",
            detail="Charm built successfully",
        )
        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.run.return_value = result
            mock_cls.return_value = mock_instance
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert len(done_tasks) == 1
        # State service should have recorded status change and persisted.
        status_events = [e for e in svc.events if e[0] == "task_status_change"]
        assert any(e[1]["new_status"] == "done" for e in status_events)
        assert len(svc.saved_tasks) >= 1

    @pytest.mark.asyncio
    async def test_env_check_failure_uses_injected_checker(self) -> None:
        """When the env checker returns an error, the task fails immediately."""
        checker = FakeEnvironmentChecker(error="Missing charm path")
        svc = FakeStateService()
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Deploy", category=TaskCategory.DEPLOY)
        queue.add_task(task)
        queue.set_active(task.id)

        failed_tasks: list[AgentTask] = []
        executor = _make_executor(
            queue=queue,
            env_checker=checker,
            state_service=svc,
            on_task_failed=failed_tasks.append,
        )

        await executor._execute_task(task)
        assert task.status == TaskStatus.FAILED
        assert len(failed_tasks) == 1

    @pytest.mark.asyncio
    async def test_noop_detected_via_fake_git(self) -> None:
        """Noop detection works through the fake git service."""
        # Same fingerprint before and after → noop.
        git = FakeGitService(fingerprints=["same", "same"])
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state, git_service=git)

        result = SubagentResult(
            exit_state=ExitState.COMPLETED,
            summary="Done",
            detail="Completed work",
        )
        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.run.return_value = result
            mock_cls.return_value = mock_instance
            await executor._execute_task(task)

        # First noop → reset to pending.
        assert task.status == TaskStatus.PENDING
        assert task.noop_count == 1

    @pytest.mark.asyncio
    async def test_revert_on_failure_uses_fake_git(self) -> None:
        """Git revert on BUILD failure delegates to the fake git service."""
        git = FakeGitService(fingerprints=["fp1", "fp2"])
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state, git_service=git)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.run.side_effect = RuntimeError("build broke")
            mock_cls.return_value = mock_instance
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert len(git.revert_calls) == 1
        assert git.revert_calls[0][1] == "t1"

    @pytest.mark.asyncio
    async def test_followup_planner_creates_tasks(self) -> None:
        """Follow-up tasks are created via the injected planner."""
        followup = AgentTask(id="f1", title="Verify deploy", category=TaskCategory.TEST)
        planner = FakeFollowupPlanner(followups=[followup])
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        git = FakeGitService(fingerprints=["a", "b"])
        executor = _make_executor(
            queue=queue,
            state=state,
            git_service=git,
            followup_planner=planner,
        )

        result = SubagentResult(
            exit_state=ExitState.COMPLETED,
            summary="Built",
            detail="OK",
        )
        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.run.return_value = result
            mock_cls.return_value = mock_instance
            await executor._execute_task(task)

        # Follow-up should have been added to the queue.
        assert queue.get_task("f1") is not None


# ===================================================================
# TestDefaultFallback — verify defaults when no services injected
# ===================================================================


class TestDefaultFallback:
    """Verify that omitting service params falls back to defaults."""

    def test_no_services_uses_defaults(self) -> None:
        """Constructor works with no service params (backward compat)."""
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(),
        )
        # Should have default implementations, not None.
        assert executor._git is not None
        assert executor._env_checker is not None
        assert executor._followup_planner is not None
        # No store → no state service.
        assert executor._state_service is None

    def test_store_creates_adapter(self) -> None:
        """Passing a store (without state_service) creates the adapter."""
        from unittest.mock import MagicMock

        store = MagicMock()
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(),
            store=store,
        )
        assert executor._state_service is not None

    def test_explicit_state_service_overrides_store(self) -> None:
        """An explicit state_service takes precedence over store adapter."""
        from unittest.mock import MagicMock

        store = MagicMock()
        svc = FakeStateService()
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(),
            store=store,
            state_service=svc,
        )
        assert executor._state_service is svc


# ---------------------------------------------------------------------------
# Phase 97.3 — Default planner layers the OpenStack acceptance task on top
# ---------------------------------------------------------------------------


class TestDefaultFollowupPlannerOpenStackLayer:
    """``_DefaultFollowupPlanner.followup_tasks`` adds the OpenStack task."""

    def _done_test_task(self) -> AgentTask:
        from cantrip.agent.queue import TaskCategory, TaskStatus

        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE
        return task

    def test_layers_openstack_task_when_state_active_cloud_is_openstack(self) -> None:
        from cantrip.agent.autodeploy import _OPENSTACK_ACCEPTANCE_TITLE
        from cantrip.agent.executor.policies import _DefaultFollowupPlanner

        state = AgentState(dev_model="dev", active_cloud="openstack")
        planner = _DefaultFollowupPlanner(state)
        followups = planner.followup_tasks(self._done_test_task())
        titles = [t.title for t in followups]
        # Base acceptance task always present.
        assert any("put the charm through its paces" in t for t in titles)
        # OpenStack-specific task layered on top.
        assert _OPENSTACK_ACCEPTANCE_TITLE in titles

    def test_no_openstack_task_when_active_cloud_is_empty(self) -> None:
        from cantrip.agent.autodeploy import _OPENSTACK_ACCEPTANCE_TITLE
        from cantrip.agent.executor.policies import _DefaultFollowupPlanner

        state = AgentState(dev_model="dev", active_cloud="")
        planner = _DefaultFollowupPlanner(state)
        followups = planner.followup_tasks(self._done_test_task())
        titles = [t.title for t in followups]
        assert _OPENSTACK_ACCEPTANCE_TITLE not in titles

    def test_no_openstack_task_when_active_cloud_is_lxd(self) -> None:
        from cantrip.agent.autodeploy import _OPENSTACK_ACCEPTANCE_TITLE
        from cantrip.agent.executor.policies import _DefaultFollowupPlanner

        state = AgentState(dev_model="dev", active_cloud="localhost")
        planner = _DefaultFollowupPlanner(state)
        followups = planner.followup_tasks(self._done_test_task())
        titles = [t.title for t in followups]
        assert _OPENSTACK_ACCEPTANCE_TITLE not in titles

    def test_no_followups_when_no_dev_model(self) -> None:
        """The dev-model guard short-circuits before any base or OpenStack task."""
        from cantrip.agent.executor.policies import _DefaultFollowupPlanner

        state = AgentState(dev_model=None, active_cloud="openstack")
        planner = _DefaultFollowupPlanner(state)
        assert planner.followup_tasks(self._done_test_task()) == []
