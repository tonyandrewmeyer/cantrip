"""Git worktree allocation, merge, and orphan-reaping for the executor.

``WorktreeMixin`` isolates the per-task worktree lifecycle —
allocate-on-pick, merge-the-winner-back, reap-orphans-on-startup — that
:class:`~cantrip.agent.executor.core.BackgroundExecutor` mixes in.
"""

import asyncio
import logging
import pathlib
import subprocess

from cantrip.agent.git.worktree import WorktreeHandle
from cantrip.agent.queue import AgentTask, TaskStatus
from cantrip.agent.tools.git import _gpg_sign_enabled

log = logging.getLogger(__name__)


async def _run_git_async(
    args: list[str],
    *,
    cwd: str | pathlib.Path,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand off the event loop without blocking other tasks."""

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return await asyncio.to_thread(_run)


class WorktreeMixin:
    """Worktree lifecycle helpers mixed into ``BackgroundExecutor``.

    Reads ``_state``, ``_queue``, ``_worktrees`` and ``_merge_lock`` from
    the executor instance via ``self``.
    """

    async def _reap_worktree_orphans(self) -> None:
        """Drop worktrees left over from a previous session on startup.

        Tasks in terminal states (``DONE``, ``FAILED``, ``BLOCKED``) no longer
        need a worktree either — only tasks that might still run get to keep
        theirs across a restart.
        """
        if self._state.charm_path is None:
            return
        active = {
            t.id
            for t in self._queue.all_tasks()
            if t.status in (TaskStatus.PENDING, TaskStatus.ACTIVE)
        }
        reaper = getattr(self._worktrees, "reap_disk_orphans", None)
        if reaper is None:
            return
        try:
            reaped = await reaper(self._state.charm_path, active)
        except (OSError, RuntimeError) as exc:
            log.warning("Worktree orphan reap failed: %s", exc)
            return
        if reaped:
            log.info("Startup: reaped %d orphan worktree(s)", reaped)

    async def _try_allocate_worktree(self, task: AgentTask) -> WorktreeHandle | None:
        """Attempt to allocate a worktree for *task*, returning None on failure.

        The allocator itself handles the "not a git repo" fallback.  This
        wrapper additionally suppresses unexpected ``ValueError`` (duplicate
        task id) and ``OSError`` so a broken allocator never blocks the
        executor — the worst-case behaviour is running in the main tree.
        """
        if self._state.charm_path is None:
            return None
        try:
            return await self._worktrees.allocate(task.id, self._state.charm_path)
        except (ValueError, OSError, RuntimeError) as exc:
            log.warning("Worktree allocation failed for '%s': %s", task.title, exc)
            return None

    async def _merge_worktree(self, handle: WorktreeHandle, task: AgentTask) -> str | None:
        """Merge the worktree branch back into the main charm branch.

        Returns ``None`` on clean merge, or an error message describing why
        the merge could not complete (main tree dirty, or merge conflict).
        When an error is returned the ephemeral branch is preserved so the
        user can resolve it manually.
        """
        main = self._state.charm_path
        if main is None:
            return None

        async with self._merge_lock:
            # 1. Auto-commit any uncommitted changes in the worktree so the
            #    subsequent ``git merge`` sees them.  Subagents that call
            #    ``GitCommitTool`` already committed on ``handle.branch``;
            #    this catches the common case of bare file writes.
            add_result = await _run_git_async(["add", "-A"], cwd=handle.path)
            if add_result.returncode == 0:
                staged = await _run_git_async(["diff", "--cached", "--quiet"], cwd=handle.path)
                # ``--quiet`` exits with 1 when there are staged changes.
                if staged.returncode == 1:
                    commit_args = ["commit", "-m", f"cantrip: {task.title[:72]}"]
                    if not _gpg_sign_enabled():
                        commit_args.append("--no-gpg-sign")
                    await _run_git_async(commit_args, cwd=handle.path)

            # 2. Skip the merge if main has uncommitted work — overwriting it
            #    would silently lose the user's state.
            status = await _run_git_async(["status", "--porcelain"], cwd=main)
            if status.returncode == 0 and status.stdout.strip():
                return (
                    f"Main tree has uncommitted changes; worktree branch "
                    f"{handle.branch!r} kept for manual merge"
                )

            # 3. ``--no-ff`` preserves the subagent's commits on the main
            #    branch as a merge commit rather than collapsing them.
            merge_args = ["merge", "--no-ff", "--no-edit", handle.branch]
            if not _gpg_sign_enabled():
                merge_args.append("--no-gpg-sign")
            merge = await _run_git_async(merge_args, cwd=main)
            if merge.returncode != 0:
                # Return the main tree to its pre-merge state so the next
                # task starts from a clean slate.
                await _run_git_async(["merge", "--abort"], cwd=main)
                return (
                    f"Merge conflict with worktree branch {handle.branch!r}; "
                    "main tree reset and branch preserved for manual merge"
                )

            return None
