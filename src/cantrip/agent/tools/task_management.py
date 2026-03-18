"""Task management tool — lets the conversation LLM steer autonomous work."""

import logging
from typing import Any

from cantrip.agent.queue import AgentTask, TaskStatus, WorkQueue
from cantrip.agent.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class ManageTasksTool(Tool):
    """Inspect and modify the autonomous work queue.

    The conversation LLM calls this tool when the user wants to steer the
    autonomous work loop — cancelling tasks, reprioritising them, or
    checking progress.
    """

    def __init__(self, queue: WorkQueue) -> None:
        self._queue = queue

    @property
    def name(self) -> str:
        return "manage_tasks"

    @property
    def description(self) -> str:
        return (
            "Inspect and modify the autonomous task queue. Use 'list' to see "
            "all tasks, 'cancel' to remove a task, 'reprioritise' to move a "
            "task to the front, or 'detail' to see a task's full result."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "cancel", "reprioritise", "detail", "approve"],
                    "description": (
                        "'list' — show all tasks and their statuses; "
                        "'cancel' — remove a pending/blocked task; "
                        "'reprioritise' — move a pending task to the front; "
                        "'detail' — show full result/description of a task; "
                        "'approve' — approve a blocked CONFIRM task, unblocking it"
                    ),
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required for cancel, reprioritise, detail, approve)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task_id: str | None = None,
        **_kwargs: Any,
    ) -> ToolResult:
        """Execute the requested task management action."""
        if action == "list":
            return self._list_tasks()
        if action == "cancel":
            return self._cancel_task(task_id)
        if action == "reprioritise":
            return self._reprioritise_task(task_id)
        if action == "detail":
            return self._task_detail(task_id)
        if action == "approve":
            return self._approve_task(task_id)
        return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    def _list_tasks(self) -> ToolResult:
        """Return a formatted summary of all tasks."""
        tasks = self._queue.all_tasks()
        if not tasks:
            return ToolResult(success=True, output="No tasks in the queue.")

        lines = [f"**Tasks** ({len(tasks)} total):\n"]
        for task in tasks:
            indicator = _status_indicator(task.status)
            line = f"{indicator} [{task.category.value}] **{task.title}** (id: {task.id})"
            if task.blocked_reason:
                line += f" — blocked: {task.blocked_reason}"
            lines.append(line)

        counts = _status_counts(tasks)
        lines.append(f"\n{counts}")
        return ToolResult(success=True, output="\n".join(lines))

    def _cancel_task(self, task_id: str | None) -> ToolResult:
        """Cancel a pending or blocked task."""
        if not task_id:
            return ToolResult(success=False, output="", error="task_id is required for cancel.")
        task = self._queue.get_task(task_id)
        if task is None:
            return ToolResult(success=False, output="", error=f"Task {task_id} not found.")
        if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Cannot cancel task {task_id} — status is {task.status.value}. "
                    "Only pending or blocked tasks can be cancelled."
                ),
            )
        self._queue.cancel(task_id)
        return ToolResult(success=True, output=f"Cancelled task: {task.title}")

    def _reprioritise_task(self, task_id: str | None) -> ToolResult:
        """Move a pending task to the front of the queue."""
        if not task_id:
            return ToolResult(
                success=False, output="", error="task_id is required for reprioritise."
            )
        task = self._queue.get_task(task_id)
        if task is None:
            return ToolResult(success=False, output="", error=f"Task {task_id} not found.")
        if task.status != TaskStatus.PENDING:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Cannot reprioritise task {task_id} — status is {task.status.value}. "
                    "Only pending tasks can be reprioritised."
                ),
            )
        self._queue.move_to_front(task_id)
        return ToolResult(success=True, output=f"Moved to front: {task.title}")

    def _approve_task(self, task_id: str | None) -> ToolResult:
        """Approve a CONFIRM task, marking it as done.

        Accepts both blocked and pending CONFIRM tasks.  The task may
        still be pending if the conversation LLM short-circuited the
        research phase and the executor hasn't picked it up yet.
        """
        if not task_id:
            return ToolResult(success=False, output="", error="task_id is required for approve.")
        task = self._queue.get_task(task_id)
        if task is None:
            return ToolResult(success=False, output="", error=f"Task {task_id} not found.")
        if task.status not in (TaskStatus.BLOCKED, TaskStatus.PENDING):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Cannot approve task {task_id} — status is {task.status.value}. "
                    "Only pending or blocked tasks can be approved."
                ),
            )
        self._queue.set_done(task_id, "Approved by user")
        return ToolResult(success=True, output=f"Approved: {task.title}")

    def _task_detail(self, task_id: str | None) -> ToolResult:
        """Return detailed information about a single task."""
        if not task_id:
            return ToolResult(success=False, output="", error="task_id is required for detail.")
        task = self._queue.get_task(task_id)
        if task is None:
            return ToolResult(success=False, output="", error=f"Task {task_id} not found.")

        lines = [
            f"**{task.title}** (id: {task.id})",
            f"- Status: {task.status.value}",
            f"- Category: {task.category.value}",
        ]
        if task.description:
            lines.append(f"- Description: {task.description}")
        if task.dependencies:
            lines.append(f"- Dependencies: {', '.join(task.dependencies)}")
        if task.blocked_reason:
            lines.append(f"- Blocked: {task.blocked_reason}")
        if task.result:
            lines.append(f"- Result: {task.result}")
        return ToolResult(success=True, output="\n".join(lines))


def _status_indicator(status: TaskStatus) -> str:
    """Return a text indicator for a task status."""
    return {
        TaskStatus.PENDING: "\u25cb",  # ○
        TaskStatus.ACTIVE: "\u27f3",  # ⟳
        TaskStatus.DONE: "\u2713",  # ✓
        TaskStatus.FAILED: "\u2717",  # ✗
        TaskStatus.BLOCKED: "\u25cc",  # ◌
    }.get(status, "?")


def _status_counts(tasks: list[AgentTask]) -> str:
    """Return a summary line of status counts."""
    counts: dict[str, int] = {}
    for task in tasks:
        label = task.status.value
        counts[label] = counts.get(label, 0) + 1
    return "Summary: " + ", ".join(f"{v} {k}" for k, v in counts.items())
