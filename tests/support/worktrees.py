"""In-memory :class:`WorktreeAllocator` fake shared by executor tests.

Three test modules used to define their own ``FakeAllocator`` /
``_FakeAllocator`` because nothing centralised the protocol stand-in.
The shared :class:`FakeAllocator` here covers every variant: it
records every allocate/release call, hands out handles via a
configurable factory (default: real-on-disk paths under a chosen
``root``), and supports per-task allocation failure and
release-raise injection so tests can exercise the recovery paths.
"""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Callable

from cantrip.agent.worktree import WorktreeHandle

HandleFactory = Callable[[str, pathlib.Path], WorktreeHandle | None]


@dataclasses.dataclass
class AllocCall:
    """Record of one :meth:`FakeAllocator.allocate` invocation."""

    task_id: str
    base_path: pathlib.Path


@dataclasses.dataclass
class ReleaseCall:
    """Record of one :meth:`FakeAllocator.release` invocation."""

    task_id: str
    keep_branch: bool


def make_disk_handle_factory(
    root: pathlib.Path,
    *,
    mkdir: bool = True,
    base_sha: str = "0" * 40,
) -> HandleFactory:
    """Return a factory that builds a real on-disk worktree handle.

    Each handle's ``path`` is ``<root>/<task_id>``.  When *mkdir* is
    true the directory is created on first allocation so callers can
    chdir into it.
    """

    def _factory(task_id: str, base_path: pathlib.Path) -> WorktreeHandle:
        del base_path
        path = root / task_id
        if mkdir:
            path.mkdir(parents=True, exist_ok=True)
        return WorktreeHandle(
            task_id=task_id,
            path=path,
            branch=f"cantrip/wt/{task_id}",
            base_sha=base_sha,
        )

    return _factory


class FakeAllocator:
    """In-memory ``WorktreeAllocator`` covering executor + race tests.

    Each :meth:`allocate` call appends an :class:`AllocCall`; each
    :meth:`release` call appends a :class:`ReleaseCall`.  The
    allocator can be configured several ways:

    * Pass *handle_factory* for full control of the returned handle
      (e.g. to return ``None`` and exercise the non-git fallback).
    * Pass *root* to use the default factory which builds handles
      under ``<root>/<task_id>`` and (by default) creates that
      directory on disk so subsequent code can ``cd`` into it.
    * Add task ids to :attr:`allocate_fail_for` to make those calls
      return ``None`` even when the factory would otherwise hand back
      a handle.
    * Set :attr:`release_raise` to ``True`` to make every release raise
      ``RuntimeError`` — useful for exercising error-path code in the
      coordinator.
    """

    def __init__(
        self,
        *,
        root: pathlib.Path | None = None,
        handle_factory: HandleFactory | None = None,
        mkdir_on_allocate: bool = True,
    ) -> None:
        if handle_factory is not None:
            self._factory: HandleFactory = handle_factory
        elif root is not None:
            self._factory = make_disk_handle_factory(root, mkdir=mkdir_on_allocate)
        else:
            self._factory = lambda *_a: None
        self._handles: dict[str, WorktreeHandle] = {}
        self.alloc_calls: list[AllocCall] = []
        self.release_calls: list[ReleaseCall] = []
        self.allocate_fail_for: set[str] = set()
        self.release_raise: bool = False

    async def allocate(
        self,
        task_id: str,
        base_path: pathlib.Path | str,
    ) -> WorktreeHandle | None:
        self.alloc_calls.append(AllocCall(task_id, pathlib.Path(base_path)))
        if task_id in self.allocate_fail_for:
            return None
        handle = self._factory(task_id, pathlib.Path(base_path))
        if handle is not None:
            self._handles[task_id] = handle
        return handle

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        if self.release_raise:
            raise RuntimeError("simulated release failure")
        self.release_calls.append(ReleaseCall(task_id, keep_branch))
        self._handles.pop(task_id, None)

    def get(self, task_id: str) -> WorktreeHandle | None:
        return self._handles.get(task_id)

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        return dict(self._handles)

    async def reap_orphans(self, active_task_ids: set[str]) -> int:
        stale = [tid for tid in list(self._handles) if tid not in active_task_ids]
        for tid in stale:
            await self.release(tid)
        return len(stale)
