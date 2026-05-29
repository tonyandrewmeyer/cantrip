"""Protocol interfaces for executor service injection.

Defines the contracts the ``BackgroundExecutor`` depends on, so the
real implementations can be swapped for fakes in tests without touching
the executor code.
"""

from __future__ import annotations

import pathlib
from typing import Any, Protocol, runtime_checkable

from cantrip.agent.git.worktree import WorktreeHandle
from cantrip.agent.queue import AgentTask
from cantrip.agent.subagent import SubagentContext, SubagentResult

# ---------------------------------------------------------------------------
# SubagentRunner — runs a subagent for a given task
# ---------------------------------------------------------------------------


@runtime_checkable
class SubagentRunner(Protocol):
    """Runs a subagent and returns the result."""

    async def run(
        self,
        context: SubagentContext,
        tools: list[Any],
    ) -> SubagentResult:
        """Execute a subagent for the given context and return the result."""
        ...


# ---------------------------------------------------------------------------
# GitService — git snapshot, revert, fingerprint, uncommitted check
# ---------------------------------------------------------------------------


@runtime_checkable
class GitService(Protocol):
    """Git operations needed by the executor for snapshot/revert."""

    def fingerprint(self, charm_path: str | pathlib.Path | None) -> str:
        """Return a lightweight fingerprint of the working tree."""
        ...

    def snapshot_head(self, charm_path: str | pathlib.Path | None) -> str | None:
        """Return the current HEAD commit hash, or None."""
        ...

    def revert_to_clean(
        self, charm_path: str | pathlib.Path, task: AgentTask, snapshot: str
    ) -> None:
        """Revert tracked and untracked files after a failed task, preserving diff."""
        ...

    def has_uncommitted_changes(self, charm_path: str | pathlib.Path) -> bool:
        """Return True if the charm directory has uncommitted changes."""
        ...


# ---------------------------------------------------------------------------
# StateService — read/write persistent state
# ---------------------------------------------------------------------------


@runtime_checkable
class StateService(Protocol):
    """Session store operations used by the executor."""

    def record_event(self, event_type: str, detail: dict[str, str]) -> None:
        """Record an event in the audit log."""
        ...

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        category: str | None = None,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Record token usage from an LLM response."""
        ...

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        """Persist the current task list."""
        ...


# ---------------------------------------------------------------------------
# EnvironmentChecker — pre-task environment validation
# ---------------------------------------------------------------------------


@runtime_checkable
class EnvironmentChecker(Protocol):
    """Validates the environment before launching a subagent."""

    def check(self, task: AgentTask) -> str | None:
        """Return an error message if the environment is not ready, else None."""
        ...


# ---------------------------------------------------------------------------
# FollowupPlanner — creates follow-up tasks after completion
# ---------------------------------------------------------------------------


@runtime_checkable
class FollowupPlanner(Protocol):
    """Creates follow-up tasks for completed or failed tasks."""

    def followup_tasks(self, task: AgentTask) -> list[AgentTask]:
        """Return any follow-up tasks that should be created."""
        ...


# ---------------------------------------------------------------------------
# WorktreeAllocator — per-subagent git worktree isolation
# ---------------------------------------------------------------------------


@runtime_checkable
class WorktreeAllocator(Protocol):
    """Creates, tracks, and tears down per-subagent git worktrees."""

    async def allocate(self, task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle | None:
        """Create a worktree for *task_id* off the current HEAD of *base_path*.

        Returns ``None`` when the base path is not a git repository or the
        worktree could not be created.
        """
        ...

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        """Remove the worktree for *task_id*.

        With ``keep_branch=True`` the ephemeral branch is preserved so the
        caller can merge it before deletion.
        """
        ...

    def get(self, task_id: str) -> WorktreeHandle | None:
        """Return the handle for *task_id* if one is allocated."""
        ...

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        """Return a snapshot of every active ``task_id → handle`` mapping."""
        ...

    async def reap_orphans(self, active_task_ids: set[str]) -> int:
        """Remove any worktrees not represented in *active_task_ids*."""
        ...
