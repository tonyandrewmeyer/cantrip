"""Tests for ``BackgroundExecutor`` ↔ ``WorktreeAllocator`` integration.

Covers both the in-memory wiring (a ``FakeAllocator`` plugged into the
executor) and the real ``_merge_worktree`` against a real git repo via
``tmp_path`` — the merge strategy is the interesting bit and is hard to
exercise with mocks alone.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.agent.worktree import WorktreeHandle, _DefaultWorktreeAllocator
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.support.tools import make_stub_tool as _make_tool
from tests.support.worktrees import FakeAllocator, ReleaseCall


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git CLI not available")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_executor(
    allocator: FakeAllocator,
    *,
    charm_path: str | pathlib.Path | None = "/tmp/charm",
) -> BackgroundExecutor:
    return BackgroundExecutor(
        queue=WorkQueue(),
        tools=[_make_tool("read_file")],
        provider=FakeProvider(responses=[Response(content="done")]),
        state=AgentState(charm_path=pathlib.Path(charm_path) if charm_path else None),
        worktree_allocator=allocator,
    )


# ---------------------------------------------------------------------------
# Allocator → executor integration (in-memory fakes)
# ---------------------------------------------------------------------------


def _handle_for(task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle:
    root = pathlib.Path(base_path) / ".cantrip-worktrees" / task_id
    return WorktreeHandle(
        task_id=task_id,
        path=root,
        branch=f"cantrip/wt/{task_id}",
        base_sha="deadbeefdeadbeef",
    )


class TestAllocateFallback:
    """When the allocator returns None, subagent runs in the main tree."""

    @pytest.mark.asyncio
    async def test_non_git_fallback_uses_main_charm_path(self) -> None:
        allocator = FakeAllocator(handle_factory=lambda *_a, **_kw: None)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=SubagentResult(ExitState.COMPLETED, "done"))
            await executor._execute_task(task)

        # Allocator was asked, declined, and the context kept the main path.
        assert len(allocator.alloc_calls) == 1
        assert allocator.alloc_calls[0].task_id == task.id
        # No release because no handle was ever taken.
        assert allocator.release_calls == []
        context = mock_cls.call_args[0][0]
        assert context.charm_path == "/tmp/charm"

    @pytest.mark.asyncio
    async def test_allocator_error_does_not_break_executor(self) -> None:
        """A broken allocator must not take down the executor."""

        class _Broken:
            async def allocate(self, *_a: Any, **_kw: Any) -> WorktreeHandle | None:
                raise ValueError("intentional")

            async def release(self, *_a: Any, **_kw: Any) -> None:
                pass

            def get(self, *_a: Any, **_kw: Any) -> None:
                return None

            def all_worktrees(self) -> dict[str, WorktreeHandle]:
                return {}

            async def reap_orphans(self, _active: set[str]) -> int:
                return 0

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=pathlib.Path("/tmp/charm")),
            worktree_allocator=_Broken(),
        )
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "ok")
            )
            # Must not raise despite the allocator blowing up.
            await executor._execute_task(task)

        assert executor._queue.get_task(task.id).status == TaskStatus.DONE


class TestAllocateAndRelease:
    """Successful subagent run allocates, runs inside the worktree, merges, releases."""

    @pytest.mark.asyncio
    async def test_subagent_receives_worktree_path(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=AsyncMock(return_value=None)),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "done")
            )
            await executor._execute_task(task)

        context = mock_cls.call_args[0][0]
        expected = pathlib.Path("/tmp/charm/.cantrip-worktrees/t1")
        assert context.charm_path == str(expected)

    @pytest.mark.asyncio
    async def test_task_worktree_path_is_set_and_cleared(self) -> None:
        """The task's ``worktree_path`` reflects the live allocation state."""
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        observed: list[str | None] = []

        def _record(changed: AgentTask) -> None:
            if changed.id == task.id:
                observed.append(changed.worktree_path)

        executor._queue._on_task_changed = _record

        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=AsyncMock(return_value=None)),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "done")
            )
            await executor._execute_task(task)

        # At least one notification saw the worktree set and one saw it cleared.
        expected_path = str(pathlib.Path("/tmp/charm/.cantrip-worktrees/t1"))
        assert expected_path in observed
        assert observed[-1] is None
        assert task.worktree_path is None

    @pytest.mark.asyncio
    async def test_success_merges_and_releases_without_keeping_branch(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        merge = AsyncMock(return_value=None)
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=merge),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "ok")
            )
            await executor._execute_task(task)

        merge.assert_awaited_once()
        assert allocator.release_calls == [ReleaseCall("t1", keep_branch=False)]
        assert executor._queue.get_task(task.id).status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_merge_error_blocks_task_and_keeps_branch(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        merge = AsyncMock(return_value="Main tree has uncommitted changes")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=merge),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "ok")
            )
            await executor._execute_task(task)

        assert allocator.release_calls == [ReleaseCall("t1", keep_branch=True)]
        blocked = executor._queue.get_task(task.id)
        assert blocked.status == TaskStatus.BLOCKED
        assert blocked.blocked_reason == "Main tree has uncommitted changes"

    @pytest.mark.asyncio
    async def test_subagent_exception_releases_without_merge(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        merge = AsyncMock(return_value=None)
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=merge),
        ):
            mock_cls.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
            await executor._execute_task(task)

        merge.assert_not_awaited()
        assert allocator.release_calls == [ReleaseCall("t1", keep_branch=False)]
        assert executor._queue.get_task(task.id).status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_blocked_result_does_not_trigger_merge(self) -> None:
        """Subagent returning BLOCKED must not merge a possibly-broken worktree."""
        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="t1", title="Research", category=TaskCategory.RESEARCH)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        merge = AsyncMock(return_value=None)
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_merge_worktree", new=merge),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.BLOCKED, "needs input")
            )
            await executor._execute_task(task)

        merge.assert_not_awaited()
        # Still released so the worktree doesn't leak.
        assert allocator.release_calls == [ReleaseCall("t1", keep_branch=False)]


class TestSnapshotInteraction:
    """Worktree presence turns off the main-tree snapshot/revert path."""

    @pytest.mark.asyncio
    async def test_worktree_allocation_skips_main_snapshot(self) -> None:
        """BUILD tasks normally take a main-tree snapshot for revert; with a
        worktree the failure revert is replaced by dropping the worktree."""
        from unittest.mock import MagicMock

        allocator = FakeAllocator(handle_factory=_handle_for)
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        snapshot = MagicMock(return_value="abc123")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", snapshot),
            patch.object(executor, "_merge_worktree", new=AsyncMock(return_value=None)),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "ok")
            )
            await executor._execute_task(task)

        snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_worktree_build_still_snapshots(self) -> None:
        """Fallback mode (allocator returns None) preserves snapshot/revert."""
        from unittest.mock import MagicMock

        allocator = FakeAllocator(handle_factory=lambda *_a, **_kw: None)
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        executor = _make_executor(allocator)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        snapshot = MagicMock(return_value="abc123")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", snapshot),
        ):
            mock_cls.return_value.run = AsyncMock(
                return_value=SubagentResult(ExitState.COMPLETED, "ok")
            )
            await executor._execute_task(task)

        snapshot.assert_called_once()


# ---------------------------------------------------------------------------
# _merge_worktree against a real git repo
# ---------------------------------------------------------------------------


def _init_repo(path: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)


class TestStartupReaper:
    """The executor drops orphan worktrees on start()."""

    @pytest.mark.asyncio
    async def test_reap_called_for_terminal_tasks(self) -> None:
        """Tasks in ``DONE`` / ``FAILED`` / ``BLOCKED`` states are excluded
        from the active set the reaper receives."""
        allocator = FakeAllocator(handle_factory=_handle_for)
        reap_calls: list[set[str]] = []

        async def _reap_disk(base: Any, active: set[str]) -> int:
            reap_calls.append(active)
            return 0

        allocator.reap_disk_orphans = _reap_disk  # type: ignore[attr-defined]

        executor = _make_executor(allocator)
        # Mix of states — only PENDING and ACTIVE should propagate.
        pending = AgentTask(id="p", title="p", category=TaskCategory.RESEARCH)
        active = AgentTask(id="a", title="a", category=TaskCategory.BUILD)
        done = AgentTask(id="d", title="d", category=TaskCategory.TEST)
        failed = AgentTask(id="f", title="f", category=TaskCategory.DEPLOY)
        blocked = AgentTask(id="b", title="b", category=TaskCategory.DEBUG)

        for t in (pending, active, done, failed, blocked):
            executor._queue.add_task(t)
        executor._queue.set_active(active.id)
        executor._queue.set_done(done.id, "ok")
        executor._queue.set_failed(failed.id, "oh no")
        executor._queue.set_blocked(blocked.id, "needs input")

        await executor._reap_worktree_orphans()

        assert reap_calls == [{"p", "a"}]

    @pytest.mark.asyncio
    async def test_reap_noop_when_no_charm_path(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)
        called = False

        async def _reap_disk(base: Any, active: set[str]) -> int:
            nonlocal called
            called = True
            return 0

        allocator.reap_disk_orphans = _reap_disk  # type: ignore[attr-defined]
        executor = _make_executor(allocator, charm_path=None)
        await executor._reap_worktree_orphans()

        assert called is False

    @pytest.mark.asyncio
    async def test_reap_failure_is_non_fatal(self) -> None:
        allocator = FakeAllocator(handle_factory=_handle_for)

        async def _reap_disk(*_a: Any, **_kw: Any) -> int:
            raise OSError("disk exploded")

        allocator.reap_disk_orphans = _reap_disk  # type: ignore[attr-defined]

        executor = _make_executor(allocator)
        # Must not raise.
        await executor._reap_worktree_orphans()


class TestMergeWorktreeAgainstRealGit:
    """End-to-end merge using the real allocator and a real git repo."""

    @pytest.mark.asyncio
    async def test_clean_merge_applies_subagent_changes_to_main(
        self, tmp_path: pathlib.Path
    ) -> None:
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()
        handle = await allocator.allocate("t1", tmp_path)
        assert handle is not None

        # Simulate subagent work: write a new file in the worktree.
        (handle.path / "hello.py").write_text("print('hi')\n")

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )

        task = AgentTask(id="t1", title="Add hello", category=TaskCategory.BUILD)
        error = await executor._merge_worktree(handle, task)

        assert error is None
        # Main tree picked up the new file.
        assert (tmp_path / "hello.py").read_text() == "print('hi')\n"
        # A merge commit should exist (``--no-ff``).
        log_result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert log_result.stdout.count("\n") >= 2

    @pytest.mark.asyncio
    async def test_merge_preserves_subagent_commits_via_no_ff(
        self, tmp_path: pathlib.Path
    ) -> None:
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()
        handle = await allocator.allocate("t1", tmp_path)
        assert handle is not None

        # Subagent commits its own work on the ephemeral branch.
        (handle.path / "step1.py").write_text("1\n")
        subprocess.run(["git", "add", "step1.py"], cwd=handle.path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "step 1", "--no-gpg-sign"],
            cwd=handle.path,
            check=True,
        )
        (handle.path / "step2.py").write_text("2\n")
        subprocess.run(["git", "add", "step2.py"], cwd=handle.path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "step 2", "--no-gpg-sign"],
            cwd=handle.path,
            check=True,
        )

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )

        task = AgentTask(id="t1", title="Two steps", category=TaskCategory.BUILD)
        assert await executor._merge_worktree(handle, task) is None

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # Both subagent commits survive on the main branch (``--no-ff``).
        assert "step 1" in log
        assert "step 2" in log

    @pytest.mark.asyncio
    async def test_merge_conflict_resets_main_and_preserves_branch(
        self, tmp_path: pathlib.Path
    ) -> None:
        _init_repo(tmp_path)
        # Commit something on main that will later collide with the worktree.
        (tmp_path / "shared.txt").write_text("main version\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "main's shared.txt", "--no-gpg-sign"],
            cwd=tmp_path,
            check=True,
        )

        allocator = _DefaultWorktreeAllocator()
        # Allocate *after* main has the file — worktree starts from current HEAD.
        handle = await allocator.allocate("t1", tmp_path)
        assert handle is not None

        # Subagent touches the same file.
        (handle.path / "shared.txt").write_text("worktree version\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=handle.path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "wt shared.txt", "--no-gpg-sign"],
            cwd=handle.path,
            check=True,
        )

        # Create a conflicting change on main by going back in time and
        # rewriting the shared file so the two diverge from a common ancestor.
        subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        (tmp_path / "shared.txt").write_text("main's other version\n")
        subprocess.run(["git", "add", "shared.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "divergent main", "--no-gpg-sign"],
            cwd=tmp_path,
            check=True,
        )

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )

        task = AgentTask(id="t1", title="Conflict", category=TaskCategory.BUILD)
        error = await executor._merge_worktree(handle, task)

        assert error is not None
        assert "conflict" in error.lower()
        # Main tree restored to its pre-merge state.
        assert (tmp_path / "shared.txt").read_text() == "main's other version\n"
        # Branch preserved for manual merge.
        branch_check = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{handle.branch}"],
            cwd=tmp_path,
            check=False,
            capture_output=True,
        )
        assert branch_check.returncode == 0

    @pytest.mark.asyncio
    async def test_merge_skipped_when_main_has_uncommitted_changes(
        self, tmp_path: pathlib.Path
    ) -> None:
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()
        handle = await allocator.allocate("t1", tmp_path)
        assert handle is not None

        (handle.path / "new.py").write_text("x = 1\n")
        # Main also has uncommitted work.
        (tmp_path / "user-edit.txt").write_text("don't stomp me\n")

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )

        task = AgentTask(id="t1", title="Worktree work", category=TaskCategory.BUILD)
        error = await executor._merge_worktree(handle, task)

        assert error is not None
        assert "uncommitted" in error.lower()
        # User's in-progress file untouched.
        assert (tmp_path / "user-edit.txt").read_text() == "don't stomp me\n"
