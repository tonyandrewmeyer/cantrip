"""Executor tests: followup."""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    _MAX_NOOP_COUNT,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.unit.executor.conftest import _make_executor

# ===================================================================
# TestFollowupTaskCreation
# ===================================================================


class TestFollowupTaskCreation:
    """Tests for automatic follow-up task creation after task execution."""

    @pytest.mark.asyncio
    async def test_deploy_task_creates_verify_followup(self, tmp_path: pathlib.Path) -> None:
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
    async def test_followup_tasks_added_to_queue(self, tmp_path: pathlib.Path) -> None:
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
    async def test_no_followup_without_dev_model(self, tmp_path: pathlib.Path) -> None:
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
    async def test_failed_verify_creates_debug_followup(self, tmp_path: pathlib.Path) -> None:
        queue = WorkQueue()
        task = AgentTask(
            id="v1",
            title="Verify deployment: Deploy app",
            category=TaskCategory.DEPLOY,
        )
        queue.add_task(task)

        state = AgentState(dev_model="dev", charm_path=tmp_path)
        executor = _make_executor(queue=queue, state=state)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
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
# TestNoopDetection
# ===================================================================


class TestNoopDetection:
    """Tests for noop detection in _execute_task."""

    @pytest.mark.asyncio
    async def test_noop_resets_to_pending(self) -> None:
        """First noop resets the task to pending for another attempt."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
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
        executor = _make_executor(queue=queue, state=state, on_task_failed=on_failed)

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
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
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        call_count = 0

        def _changing_fingerprint(_path: object = None) -> str:
            nonlocal call_count
            call_count += 1
            return f"hash-{call_count}"

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", side_effect=_changing_fingerprint),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "completed work")
            )
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.noop_count == 0

    @pytest.mark.asyncio
    async def test_no_noop_when_no_charm_path(self) -> None:
        """Without a charm path, fingerprint is empty and noop is skipped."""
        state = AgentState()  # No charm_path.
        queue = WorkQueue()
        task = AgentTask(id="r1", title="Research", category=TaskCategory.RESEARCH)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "research done")
            )
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
