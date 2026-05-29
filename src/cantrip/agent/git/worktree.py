"""Per-subagent git worktrees for parallel isolation.

Today the background executor runs up to three subagents concurrently in the
same working tree, which makes overlapping BUILD/TEST/DOC work racy.  The
``WorktreeAllocator`` gives each subagent its own ``git worktree`` under
``.cantrip-worktrees/<task-id>/`` so writes in one subagent cannot collide
with another's.

Design notes:

- Worktrees live beside the ``.cantrip`` SQLite file (which is itself a
  file, not a directory — hence ``.cantrip-worktrees`` rather than
  ``.cantrip/worktrees``).
- Each worktree is checked out on an ephemeral branch named
  ``cantrip/wt/<task-id>``.  The branch is created from the current HEAD so
  the subagent starts from a consistent baseline.
- Non-git charm paths (or any path where ``git worktree add`` fails) fall
  back to returning ``None``; the executor then runs the subagent in the
  original path, preserving today's behaviour.
- The allocator is the source of truth for ``task_id → worktree_path``.  Git
  itself tracks the list of worktrees, which ``reap_orphans`` uses to recover
  after a crash.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import pathlib
import shutil
import subprocess
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

_WORKTREES_DIRNAME = ".cantrip-worktrees"
_BRANCH_PREFIX = "cantrip/wt/"
_GIT_TIMEOUT = 30.0

# Environment override for the per-allocator worktree cap.  Setting this to
# ``0`` disables worktree allocation entirely (useful as an escape hatch if
# a user hits a broken git install).
_MAX_WORKTREES_ENV = "CANTRIP_MAX_WORKTREES"

# Refuse to allocate a new worktree when the filesystem containing the base
# path has less than this many free bytes.  Matches roughly "one charm build
# with rocks" — a defensive floor, not a tuned value.
_DEFAULT_MIN_FREE_BYTES = 200 * 1024 * 1024  # 200 MB


@dataclasses.dataclass(frozen=True)
class WorktreeHandle:
    """Bookkeeping for a single allocated worktree."""

    task_id: str
    path: pathlib.Path
    branch: str
    base_sha: str


@runtime_checkable
class WorktreeAllocator(Protocol):
    """Creates, tracks, and tears down per-subagent git worktrees."""

    async def allocate(self, task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle | None:
        """Create a worktree for *task_id* off the current HEAD of *base_path*.

        Returns ``None`` when the base path is not a git repository or the
        worktree could not be created; callers should fall back to running
        the subagent in the base path.
        """
        ...

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        """Remove the worktree for *task_id*.

        With ``keep_branch=True`` the ephemeral branch is preserved (e.g. so
        the caller can merge it); otherwise the branch is deleted.
        """
        ...

    def get(self, task_id: str) -> WorktreeHandle | None:
        """Return the handle for *task_id* if one is allocated, else ``None``."""
        ...

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        """Return a snapshot of every active ``task_id → handle`` mapping."""
        ...

    async def reap_orphans(self, active_task_ids: set[str]) -> int:
        """Remove any worktrees not represented in *active_task_ids*.

        Returns the number of orphans removed.  Intended for startup cleanup
        after an unclean shutdown.
        """
        ...


def _branch_name(task_id: str) -> str:
    """Return the ephemeral branch name used for *task_id*'s worktree."""
    # Keep ``task_id`` verbatim — work-queue ids are already filesystem-safe.
    return f"{_BRANCH_PREFIX}{task_id}"


async def _run_git(
    args: list[str],
    cwd: pathlib.Path | str,
    *,
    timeout: float = _GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand off the main thread."""

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


async def _is_git_repo(path: pathlib.Path) -> bool:
    """Return True if *path* sits inside a git working tree."""
    try:
        result = await _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


async def _head_sha(path: pathlib.Path) -> str | None:
    """Return the HEAD commit SHA of *path*, or ``None`` if unavailable."""
    try:
        result = await _run_git(["rev-parse", "HEAD"], cwd=path)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _has_free_space(path: pathlib.Path, min_bytes: int) -> bool:
    """Return True if *path*'s filesystem has at least *min_bytes* free.

    Falls back to True when the filesystem can't be queried (for example, a
    path that doesn't exist yet) so we don't block allocation on transient
    conditions.
    """
    if min_bytes <= 0:
        return True
    target = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return True
    return usage.free >= min_bytes


async def _ensure_worktrees_excluded(base: pathlib.Path) -> None:
    """Add ``.cantrip-worktrees/`` to ``.git/info/exclude`` if not already there.

    Nested worktrees aren't automatically excluded by git, which means the
    main tree's ``git status`` would report the per-task worktree directory
    as untracked and block merge-back.  A single idempotent append to the
    repo-local exclude file keeps the main tree clean without polluting the
    user's tracked ``.gitignore``.
    """
    try:
        common = await _run_git(["rev-parse", "--git-common-dir"], cwd=base)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return
    if common.returncode != 0:
        return
    git_dir = pathlib.Path(common.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (base / git_dir).resolve()
    exclude_file = git_dir / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    entry = f"/{_WORKTREES_DIRNAME}/\n"
    if exclude_file.exists() and entry.strip() in exclude_file.read_text().splitlines():
        return
    with exclude_file.open("a", encoding="utf-8") as fh:
        fh.write(entry)


def _parse_max_worktrees(raw: str | None) -> int | None:
    """Read the ``CANTRIP_MAX_WORKTREES`` env var, returning ``None`` for unset.

    Zero is a valid value (disables allocation).  Garbage input is ignored.
    """
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        log.warning("Ignoring invalid %s=%r", _MAX_WORKTREES_ENV, raw)
        return None
    return max(0, value)


class _DefaultWorktreeAllocator:
    """Subprocess-driven worktree allocator backed by ``git worktree``.

    *max_worktrees* caps the number of concurrent worktrees; a ``None`` value
    means unlimited.  Defaults to the ``CANTRIP_MAX_WORKTREES`` environment
    variable when unset.

    *min_free_bytes* is the minimum free space on the base path's filesystem
    below which allocation is refused.  Defaults to 200 MB.
    """

    def __init__(
        self,
        *,
        max_worktrees: int | None = None,
        min_free_bytes: int = _DEFAULT_MIN_FREE_BYTES,
    ) -> None:
        self._handles: dict[str, WorktreeHandle] = {}
        self._lock = asyncio.Lock()
        self._max_worktrees = (
            max_worktrees
            if max_worktrees is not None
            else _parse_max_worktrees(os.environ.get(_MAX_WORKTREES_ENV))
        )
        self._min_free_bytes = max(0, min_free_bytes)

    # -- Public API ----------------------------------------------------------

    async def allocate(self, task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle | None:
        base = pathlib.Path(base_path)

        async with self._lock:
            existing = self._handles.get(task_id)
            if existing is not None:
                raise ValueError(
                    f"Worktree for task {task_id!r} already allocated at {existing.path}"
                )

            if self._max_worktrees is not None and len(self._handles) >= self._max_worktrees:
                log.warning(
                    "Worktree skipped: cap reached (%d/%s); falling back to main tree",
                    len(self._handles),
                    self._max_worktrees,
                )
                return None

            if not await _is_git_repo(base):
                log.debug("Worktree skipped: %s is not a git repository", base)
                return None

            head = await _head_sha(base)
            if head is None:
                log.debug("Worktree skipped: %s has no HEAD commit", base)
                return None

            if not _has_free_space(base, self._min_free_bytes):
                log.warning(
                    "Worktree skipped: %s has less than %d free bytes",
                    base,
                    self._min_free_bytes,
                )
                return None

            # Ensure the nested ``.cantrip-worktrees/`` directory is excluded
            # from the main tree's ``git status`` output; otherwise merge-back
            # would always see "uncommitted changes" and refuse to run.
            await _ensure_worktrees_excluded(base)

            worktree_path = base / _WORKTREES_DIRNAME / task_id
            branch = _branch_name(task_id)

            result = await _run_git(
                ["worktree", "add", "-B", branch, str(worktree_path), head],
                cwd=base,
            )
            if result.returncode != 0:
                log.warning(
                    "git worktree add failed for task %s: %s",
                    task_id,
                    result.stderr.strip() or result.stdout.strip() or "(no output)",
                )
                return None

            handle = WorktreeHandle(
                task_id=task_id,
                path=worktree_path,
                branch=branch,
                base_sha=head,
            )
            self._handles[task_id] = handle
            log.info(
                "Allocated worktree for task %s at %s (branch %s)",
                task_id,
                worktree_path,
                branch,
            )
            return handle

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        async with self._lock:
            handle = self._handles.pop(task_id, None)

        if handle is None:
            return

        # ``git worktree remove`` needs to run from inside the main repo, not
        # the worktree itself — derive the main path by walking up past the
        # ``.cantrip-worktrees/<task-id>`` prefix.
        main_repo = handle.path.parent.parent

        remove_result = await _run_git(
            ["worktree", "remove", "--force", str(handle.path)],
            cwd=main_repo,
        )
        if remove_result.returncode != 0:
            # Worktree removal can fail if the directory was already gone
            # (e.g. ``rm -rf`` from a prior session); prune to reconcile.
            await _run_git(["worktree", "prune"], cwd=main_repo)

        if not keep_branch:
            delete_result = await _run_git(
                ["branch", "-D", handle.branch],
                cwd=main_repo,
            )
            if delete_result.returncode != 0:
                log.debug(
                    "Could not delete branch %s after release: %s",
                    handle.branch,
                    delete_result.stderr.strip(),
                )

        log.info("Released worktree for task %s", task_id)

    def get(self, task_id: str) -> WorktreeHandle | None:
        return self._handles.get(task_id)

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        return dict(self._handles)

    async def reap_orphans(self, active_task_ids: set[str]) -> int:
        async with self._lock:
            stale = [tid for tid in self._handles if tid not in active_task_ids]

        reaped = 0
        for task_id in stale:
            await self.release(task_id)
            reaped += 1
        return reaped

    async def reap_disk_orphans(
        self,
        base_path: pathlib.Path | str,
        active_task_ids: set[str],
    ) -> int:
        """Reap worktrees left behind on disk from a prior session.

        ``reap_orphans`` only sees handles in the current process's memory,
        which is empty at startup.  ``reap_disk_orphans`` inspects
        ``git worktree list`` under *base_path* and removes any
        ``.cantrip-worktrees/<task-id>/`` whose ``task_id`` isn't in
        *active_task_ids*.  Returns the number of worktrees removed.
        """
        base = pathlib.Path(base_path)
        if not await _is_git_repo(base):
            return 0

        try:
            listing = await _run_git(["worktree", "list", "--porcelain"], cwd=base)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return 0
        if listing.returncode != 0:
            return 0

        reaped = 0
        prefix = base / _WORKTREES_DIRNAME
        for line in listing.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            path = pathlib.Path(line[len("worktree ") :])
            try:
                rel = path.relative_to(prefix)
            except ValueError:
                continue
            # ``rel`` is ``task_id/...`` — we want the first component.
            parts = rel.parts
            if not parts:
                continue
            task_id = parts[0]
            if task_id in active_task_ids:
                continue
            # Unknown to the live queue; drop it.
            branch = _branch_name(task_id)
            remove = await _run_git(["worktree", "remove", "--force", str(path)], cwd=base)
            if remove.returncode != 0:
                await _run_git(["worktree", "prune"], cwd=base)
            # Best-effort branch cleanup; the branch may not exist in every
            # failure mode and that's fine.
            await _run_git(["branch", "-D", branch], cwd=base)
            reaped += 1
        if reaped:
            log.info("Reaped %d orphan worktree(s) under %s", reaped, prefix)
        return reaped
