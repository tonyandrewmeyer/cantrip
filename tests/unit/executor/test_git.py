"""Executor tests: git."""

import pathlib
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    _DefaultGitService,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from tests.unit.executor.conftest import _make_executor

# ===================================================================
# TestCheckUncommitted
# ===================================================================


class TestCheckUncommitted:
    """Tests for _check_uncommitted — post-task uncommitted change detection."""

    def test_logs_warning_when_uncommitted_changes(self) -> None:
        """A warning is logged when git reports uncommitted changes."""
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
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
            patch("cantrip.agent.executor.git_service.subprocess.run", return_value=completed),
            patch("cantrip.agent.executor.core.log") as mock_log,
        ):
            executor._check_uncommitted(task)

        mock_log.warning.assert_called_once()
        assert "uncommitted" in mock_log.warning.call_args[0][0]

    def test_no_warning_when_clean(self) -> None:
        """No warning is logged when the working tree is clean."""
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
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
            patch("cantrip.agent.executor.git_service.subprocess.run", return_value=completed),
            patch("cantrip.agent.executor.core.log") as mock_log,
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

        with patch("cantrip.agent.executor.git_service.subprocess.run") as mock_run:
            executor._check_uncommitted(task)

        mock_run.assert_not_called()


# ===================================================================
# TestPreCheckEnvironment
# ===================================================================


class TestPreCheckEnvironment:
    """Tests for _pre_check_environment — pre-task validation."""

    def test_deploy_fails_without_dev_model(self) -> None:
        """DEPLOY pre-check rejects when no development model is set."""
        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        executor = _make_executor(state=state)
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No development model set" in result

    def test_deploy_passes_with_dev_model_and_charm_path(self, tmp_path: pathlib.Path) -> None:
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
        state = AgentState(dev_model="dev", charm_path=pathlib.Path("/nonexistent/path"))
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

    def test_test_fails_without_charm_file(self, tmp_path: pathlib.Path) -> None:
        """TEST pre-check rejects when no .charm file exists."""
        state = AgentState(charm_path=tmp_path)
        executor = _make_executor(state=state)
        task = AgentTask(id="t1", title="Test", category=TaskCategory.TEST)

        result = executor._pre_check_environment(task)

        assert result is not None
        assert "No packed charm found" in result

    def test_test_passes_with_charm_file(self, tmp_path: pathlib.Path) -> None:
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

        state = AgentState(charm_path=pathlib.Path("/tmp/charm"))
        failed_cb = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=failed_cb)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
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
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
        executor = _make_executor(state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=0,
            stdout="abc123def456\n",
            stderr="",
        )
        with patch("cantrip.agent.executor.git_service.subprocess.run", return_value=completed):
            result = executor._snapshot_head()

        assert result == "abc123def456"

    def test_returns_none_on_git_failure(self) -> None:
        """Returns None when git rev-parse fails."""
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
        executor = _make_executor(state=state)

        completed = subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )
        with patch("cantrip.agent.executor.git_service.subprocess.run", return_value=completed):
            result = executor._snapshot_head()

        assert result is None


# ===================================================================
# TestRevertOnFailure
# ===================================================================


class TestRevertOnFailure:
    """Tests for _revert_on_failure — restoring tracked files after failure."""

    def test_runs_git_checkout_and_logs_warning(self) -> None:
        """Reverts tracked files and logs a warning."""
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
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
        clean_result = subprocess.CompletedProcess(
            args=["git", "clean", "-fd"], returncode=0, stdout="", stderr=""
        )

        with (
            patch(
                "cantrip.agent.executor.git_service.subprocess.run",
                side_effect=[diff_result, checkout_result, clean_result],
            ),
            patch("cantrip.agent.executor.git_service.log") as mock_log,
        ):
            executor._revert_on_failure("abc123def456", task)

        mock_log.warning.assert_called_once()
        assert "Reverted" in mock_log.warning.call_args[0][0]

    def test_prepends_diff_to_task_result(self) -> None:
        """The captured diff is prepended to the task result."""
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
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
        clean_result = subprocess.CompletedProcess(
            args=["git", "clean", "-fd"], returncode=0, stdout="", stderr=""
        )

        with patch(
            "cantrip.agent.executor.git_service.subprocess.run",
            side_effect=[diff_result, checkout_result, clean_result],
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
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
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
        state = AgentState(charm_path=pathlib.Path("/tmp/test-charm"))
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = _make_executor(queue=queue, state=state)

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
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
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
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
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_revert_on_failure") as mock_revert,
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(side_effect=RuntimeError("boom"))
            await executor._execute_task(task)

        mock_revert.assert_not_called()


# ===================================================================
# TestRevertCleansUntrackedFiles
# ===================================================================


class TestRevertCleansUntrackedFiles:
    """Tests for git clean in revert_to_clean (Phase 28.11)."""

    def test_revert_runs_git_clean(self) -> None:
        """revert_to_clean runs 'git clean -fd' after 'git checkout .'."""
        git_service = _DefaultGitService()
        task = AgentTask(title="Build charm", category=TaskCategory.BUILD)

        calls: list[list[str]] = []

        def tracking_run(cmd, **kwargs):
            calls.append(list(cmd))
            # Return a clean result for all commands.
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("cantrip.agent.executor.git_service.subprocess.run", side_effect=tracking_run):
            git_service.revert_to_clean("/tmp/test-charm", task, "abc123")

        # Verify git checkout . was called.
        checkout_calls = [c for c in calls if c == ["git", "checkout", "."]]
        assert len(checkout_calls) == 1

        # Verify git clean -fd was called.
        clean_calls = [c for c in calls if c == ["git", "clean", "-fd"]]
        assert len(clean_calls) == 1

        # Verify clean runs after checkout.
        checkout_idx = next(i for i, c in enumerate(calls) if c == ["git", "checkout", "."])
        clean_idx = next(i for i, c in enumerate(calls) if c == ["git", "clean", "-fd"])
        assert clean_idx > checkout_idx
