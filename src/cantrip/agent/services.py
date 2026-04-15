"""Protocol interfaces for executor service injection.

Defines the contracts the ``BackgroundExecutor`` depends on, so the
real implementations can be swapped for fakes in tests without touching
the executor code.
"""

from __future__ import annotations

import pathlib
from typing import Any, Protocol, runtime_checkable

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
