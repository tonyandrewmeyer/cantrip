"""Tests for the per-subagent git worktree allocator."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from cantrip.agent.git.worktree import (
    _BRANCH_PREFIX,
    _WORKTREES_DIRNAME,
    WorktreeHandle,
    _DefaultWorktreeAllocator,
)


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(
    not _git_available(),
    reason="git CLI not available",
)


def _init_repo(path: pathlib.Path) -> None:
    """Initialise *path* as a git repo with one commit so HEAD exists."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=path,
        check=True,
        env={**_base_env(), "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t"},
    )


def _base_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.setdefault("HOME", str(pathlib.Path.home()))
    return env


def _worktree_list(repo: pathlib.Path) -> list[str]:
    """Return the paths git knows about via ``git worktree list``."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        line.split(" ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def _branch_exists(repo: pathlib.Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


class TestAllocate:
    """Allocation lifecycle."""

    @pytest.mark.asyncio
    async def test_allocate_returns_handle_for_git_repo(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()

        handle = await alloc.allocate("task-1", tmp_path)

        assert isinstance(handle, WorktreeHandle)
        assert handle.task_id == "task-1"
        assert handle.path == tmp_path / _WORKTREES_DIRNAME / "task-1"
        assert handle.branch == f"{_BRANCH_PREFIX}task-1"
        assert handle.path.is_dir()
        assert (handle.path / "README.md").read_text() == "hello\n"
        assert _branch_exists(tmp_path, handle.branch)

    @pytest.mark.asyncio
    async def test_allocate_returns_none_for_non_git_path(self, tmp_path: pathlib.Path) -> None:
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert handle is None

    @pytest.mark.asyncio
    async def test_allocate_returns_none_when_no_head_commit(self, tmp_path: pathlib.Path) -> None:
        """A freshly-``git init``-ed repo has no HEAD until the first commit."""
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
        alloc = _DefaultWorktreeAllocator()
        assert await alloc.allocate("task-1", tmp_path) is None

    @pytest.mark.asyncio
    async def test_duplicate_task_id_rejected(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("task-1", tmp_path)

        with pytest.raises(ValueError, match="already allocated"):
            await alloc.allocate("task-1", tmp_path)

    @pytest.mark.asyncio
    async def test_multiple_tasks_get_isolated_trees(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()

        a = await alloc.allocate("task-a", tmp_path)
        b = await alloc.allocate("task-b", tmp_path)

        assert a is not None
        assert b is not None
        assert a.path != b.path
        assert _branch_exists(tmp_path, a.branch)
        assert _branch_exists(tmp_path, b.branch)

        # Writes in one tree do not touch the other.
        (a.path / "only-in-a.txt").write_text("a")
        assert not (b.path / "only-in-a.txt").exists()


class TestRelease:
    """Release tears down the worktree and (optionally) the branch."""

    @pytest.mark.asyncio
    async def test_release_removes_worktree_and_branch(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert handle is not None

        await alloc.release("task-1")

        assert not handle.path.exists()
        assert handle.path.as_posix() not in _worktree_list(tmp_path)
        assert not _branch_exists(tmp_path, handle.branch)
        assert alloc.get("task-1") is None

    @pytest.mark.asyncio
    async def test_release_keep_branch_preserves_branch(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert handle is not None

        await alloc.release("task-1", keep_branch=True)

        assert not handle.path.exists()
        assert _branch_exists(tmp_path, handle.branch)

    @pytest.mark.asyncio
    async def test_release_unknown_task_is_noop(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        # Must not raise.
        await alloc.release("never-allocated")

    @pytest.mark.asyncio
    async def test_release_after_manual_rm_falls_back_to_prune(
        self, tmp_path: pathlib.Path
    ) -> None:
        """``git worktree remove`` fails when the path is already gone; the
        allocator must still clean up its bookkeeping."""
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert handle is not None

        shutil.rmtree(handle.path)
        await alloc.release("task-1")

        assert alloc.get("task-1") is None
        assert handle.path.as_posix() not in _worktree_list(tmp_path)


class TestNestedExclude:
    """Allocator writes the worktree dir into ``.git/info/exclude``.

    Without this, the main repo's ``git status`` sees the nested worktree as
    untracked, which blocks merge-back.
    """

    @pytest.mark.asyncio
    async def test_exclude_file_gets_worktrees_entry(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("task-1", tmp_path)

        exclude_contents = (tmp_path / ".git" / "info" / "exclude").read_text()
        assert "/.cantrip-worktrees/" in exclude_contents

    @pytest.mark.asyncio
    async def test_exclude_entry_is_idempotent(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("task-1", tmp_path)
        await alloc.allocate("task-2", tmp_path)

        exclude_contents = (tmp_path / ".git" / "info" / "exclude").read_text()
        assert exclude_contents.count("/.cantrip-worktrees/") == 1

    @pytest.mark.asyncio
    async def test_main_status_is_clean_after_worktree_write(self, tmp_path: pathlib.Path) -> None:
        """A file written in the worktree must not pollute main's status."""
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert handle is not None

        (handle.path / "new.py").write_text("x = 1\n")

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert status.stdout.strip() == ""


class TestAccessors:
    """``get`` and ``all_worktrees`` surface allocator state for callers."""

    @pytest.mark.asyncio
    async def test_get_returns_allocated_handle(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        handle = await alloc.allocate("task-1", tmp_path)
        assert alloc.get("task-1") is handle

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_task(self, tmp_path: pathlib.Path) -> None:
        alloc = _DefaultWorktreeAllocator()
        assert alloc.get("never-allocated") is None

    @pytest.mark.asyncio
    async def test_all_worktrees_is_a_snapshot(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("a", tmp_path)
        snapshot = alloc.all_worktrees()
        await alloc.allocate("b", tmp_path)

        assert set(snapshot) == {"a"}
        assert set(alloc.all_worktrees()) == {"a", "b"}


class TestReapOrphans:
    """``reap_orphans`` clears worktrees whose tasks no longer exist."""

    @pytest.mark.asyncio
    async def test_reap_removes_only_inactive_tasks(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("keep", tmp_path)
        await alloc.allocate("drop", tmp_path)

        reaped = await alloc.reap_orphans({"keep"})

        assert reaped == 1
        assert alloc.get("keep") is not None
        assert alloc.get("drop") is None

    @pytest.mark.asyncio
    async def test_reap_with_all_active_is_noop(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("a", tmp_path)
        await alloc.allocate("b", tmp_path)

        reaped = await alloc.reap_orphans({"a", "b"})

        assert reaped == 0
        assert set(alloc.all_worktrees()) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_reap_on_empty_allocator_returns_zero(self, tmp_path: pathlib.Path) -> None:
        alloc = _DefaultWorktreeAllocator()
        assert await alloc.reap_orphans(set()) == 0


class TestProtocolCompliance:
    """``_DefaultWorktreeAllocator`` satisfies the ``WorktreeAllocator`` Protocol."""

    def test_default_impl_satisfies_protocol(self) -> None:
        from cantrip.agent.services import WorktreeAllocator

        assert isinstance(_DefaultWorktreeAllocator(), WorktreeAllocator)


class TestMaxWorktreesCap:
    """``max_worktrees`` and ``CANTRIP_MAX_WORKTREES`` refuse allocation past
    the cap without raising."""

    @pytest.mark.asyncio
    async def test_cap_refuses_beyond_limit(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator(max_worktrees=2)

        assert await alloc.allocate("a", tmp_path) is not None
        assert await alloc.allocate("b", tmp_path) is not None
        # Third allocation is refused — returns None, doesn't raise.
        assert await alloc.allocate("c", tmp_path) is None

    @pytest.mark.asyncio
    async def test_cap_of_zero_disables_allocation(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator(max_worktrees=0)
        assert await alloc.allocate("a", tmp_path) is None

    @pytest.mark.asyncio
    async def test_env_var_sets_default_cap(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path)
        monkeypatch.setenv("CANTRIP_MAX_WORKTREES", "1")
        alloc = _DefaultWorktreeAllocator()
        assert await alloc.allocate("a", tmp_path) is not None
        assert await alloc.allocate("b", tmp_path) is None

    @pytest.mark.asyncio
    async def test_invalid_env_value_is_ignored(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_repo(tmp_path)
        monkeypatch.setenv("CANTRIP_MAX_WORKTREES", "not-a-number")
        alloc = _DefaultWorktreeAllocator()
        # Unparseable values fall back to "no cap".
        assert await alloc.allocate("a", tmp_path) is not None
        assert await alloc.allocate("b", tmp_path) is not None


class TestDiskSpaceGuard:
    """Allocation is refused when the filesystem is below *min_free_bytes*."""

    @pytest.mark.asyncio
    async def test_zero_threshold_never_blocks(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator(min_free_bytes=0)
        assert await alloc.allocate("a", tmp_path) is not None

    @pytest.mark.asyncio
    async def test_impossibly_high_threshold_blocks(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        # 10 PB — no developer machine has this much free space.
        alloc = _DefaultWorktreeAllocator(min_free_bytes=10 * 1024**5)
        assert await alloc.allocate("a", tmp_path) is None


class TestDiskOrphanReaper:
    """``reap_disk_orphans`` cleans up worktrees left behind by a prior run."""

    @pytest.mark.asyncio
    async def test_reaps_worktrees_not_in_active_set(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()

        keep = await alloc.allocate("keep", tmp_path)
        drop = await alloc.allocate("drop", tmp_path)
        assert keep is not None and drop is not None

        # Simulate a restart: build a fresh allocator that knows nothing
        # about the on-disk worktrees.
        restarted = _DefaultWorktreeAllocator()
        reaped = await restarted.reap_disk_orphans(tmp_path, {"keep"})

        assert reaped == 1
        assert not drop.path.exists()
        assert keep.path.exists()
        # Branch for the dropped worktree is gone too.
        delete_check = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{drop.branch}"],
            cwd=tmp_path,
            check=False,
            capture_output=True,
        )
        assert delete_check.returncode != 0

    @pytest.mark.asyncio
    async def test_empty_active_set_reaps_everything(self, tmp_path: pathlib.Path) -> None:
        _init_repo(tmp_path)
        alloc = _DefaultWorktreeAllocator()
        await alloc.allocate("a", tmp_path)
        await alloc.allocate("b", tmp_path)

        restarted = _DefaultWorktreeAllocator()
        assert await restarted.reap_disk_orphans(tmp_path, set()) == 2

    @pytest.mark.asyncio
    async def test_non_git_base_path_returns_zero(self, tmp_path: pathlib.Path) -> None:
        alloc = _DefaultWorktreeAllocator()
        assert await alloc.reap_disk_orphans(tmp_path, set()) == 0

    @pytest.mark.asyncio
    async def test_ignores_worktrees_outside_cantrip_directory(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A user-created worktree elsewhere must not be reaped."""
        _init_repo(tmp_path)
        other = tmp_path.parent / "other-worktree"
        subprocess.run(
            ["git", "worktree", "add", "-b", "user-branch", str(other)],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        alloc = _DefaultWorktreeAllocator()
        reaped = await alloc.reap_disk_orphans(tmp_path, set())

        assert reaped == 0
        assert other.exists()
        # Clean up the manually-created worktree so the test doesn't leak it.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(other)],
            cwd=tmp_path,
            check=False,
            capture_output=True,
        )
