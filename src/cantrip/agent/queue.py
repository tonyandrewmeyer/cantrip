"""Work queue for autonomous agent task scheduling."""

import enum
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime


class TaskStatus(enum.StrEnum):
    """Lifecycle status of an agent task."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskCategory(enum.StrEnum):
    """Category of work a task represents."""

    RESEARCH = "research"
    BUILD = "build"
    DEPLOY = "deploy"
    TEST = "test"
    DEBUG = "debug"
    INFRA = "infra"
    CONFIRM = "confirm"


class ModelHint(enum.StrEnum):
    """Hint for which model a task should use, overriding category defaults."""

    PRIMARY = "primary"
    LIGHT = "light"


@dataclass
class AgentTask:
    """A discrete unit of work for the autonomous agent."""

    title: str
    category: TaskCategory
    id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    result: str | None = None
    blocked_reason: str | None = None
    model_hint: ModelHint | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """Generate a unique ID if not provided."""
        if not self.id:
            self.id = uuid.uuid4().hex[:12]


class WorkQueue:
    """Central task queue for the autonomous work loop.

    Holds ``AgentTask`` objects and provides status transitions, dependency
    checking, and an optional callback fired on every task mutation.
    """

    def __init__(
        self,
        on_task_changed: Callable[[AgentTask], None] | None = None,
    ) -> None:
        self._tasks: list[AgentTask] = []
        self._on_task_changed = on_task_changed

    # -- Mutation helpers ----------------------------------------------------

    def _notify(self, task: AgentTask) -> None:
        """Fire the callback if one is registered."""
        if self._on_task_changed is not None:
            self._on_task_changed(task)

    def _get_or_raise(self, task_id: str) -> AgentTask:
        """Return the task with *task_id* or raise ``KeyError``."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    # -- Adding tasks -------------------------------------------------------

    def add_task(self, task: AgentTask) -> None:
        """Append a single task and fire the callback."""
        self._tasks.append(task)
        self._notify(task)

    def add_tasks(self, tasks: list[AgentTask]) -> None:
        """Bulk-add tasks (for planner output)."""
        for task in tasks:
            self._tasks.append(task)
            self._notify(task)

    # -- Scheduling ---------------------------------------------------------

    def next_ready(self) -> AgentTask | None:
        """Return the first pending task whose dependencies are all done."""
        ready = self.all_ready(limit=1)
        return ready[0] if ready else None

    def all_ready(self, limit: int = 0) -> list[AgentTask]:
        """Return all pending tasks whose dependencies are all done.

        When *limit* is positive, return at most that many tasks.
        Tasks are returned in queue order.

        A dependency is considered satisfied if the task is done *or* if
        it has been cancelled (removed from the queue).  This prevents
        downstream tasks from being stuck forever when the conversation
        LLM short-circuits earlier tasks.
        """
        done_ids = {t.id for t in self._tasks if t.status == TaskStatus.DONE}
        all_ids = {t.id for t in self._tasks}
        ready: list[AgentTask] = []
        for task in self._tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in done_ids or dep not in all_ids for dep in task.dependencies):
                ready.append(task)
                if limit and len(ready) >= limit:
                    break
        return ready

    # -- Status transitions -------------------------------------------------

    def set_active(self, task_id: str) -> None:
        """Mark a task as actively being worked on."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.ACTIVE
        self._notify(task)

    def set_done(self, task_id: str, result: str | None = None) -> None:
        """Mark a task as successfully completed."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.DONE
        task.result = result
        self._notify(task)

    def set_failed(self, task_id: str, error: str | None = None) -> None:
        """Mark a task as failed."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.FAILED
        task.result = error
        self._notify(task)

    def set_blocked(self, task_id: str, reason: str) -> None:
        """Mark a task as blocked with a reason."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.BLOCKED
        task.blocked_reason = reason
        self._notify(task)

    def unblock(self, task_id: str) -> None:
        """Return a blocked task to pending status."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.PENDING
        task.blocked_reason = None
        self._notify(task)

    def cancel(self, task_id: str) -> None:
        """Remove a task from the queue entirely."""
        task = self._get_or_raise(task_id)
        self._tasks.remove(task)
        self._notify(task)

    def move_to_front(self, task_id: str) -> None:
        """Move a pending task to the front of the queue.

        Only pending tasks can be moved.  The task is repositioned so that
        ``next_ready()`` picks it up as soon as its dependencies are met.
        """
        task = self._get_or_raise(task_id)
        if task.status != TaskStatus.PENDING:
            raise ValueError(f"Cannot reprioritise task in {task.status.value} status")
        self._tasks.remove(task)
        # Insert after any non-pending tasks (active/done/failed/blocked)
        # so it becomes the first pending task.
        insert_idx = 0
        for i, t in enumerate(self._tasks):
            if t.status == TaskStatus.PENDING:
                insert_idx = i
                break
        else:
            insert_idx = len(self._tasks)
        self._tasks.insert(insert_idx, task)
        self._notify(task)

    # -- Lookup -------------------------------------------------------------

    def get_task(self, task_id: str) -> AgentTask | None:
        """Look up a task by ID, returning ``None`` if not found."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def all_tasks(self) -> list[AgentTask]:
        """Return a shallow copy of the task list."""
        return list(self._tasks)

    # -- Introspection ------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Number of tasks in pending status."""
        return sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)

    @property
    def active_count(self) -> int:
        """Number of tasks in active status."""
        return sum(1 for t in self._tasks if t.status == TaskStatus.ACTIVE)

    @property
    def done_count(self) -> int:
        """Number of tasks in done status."""
        return sum(1 for t in self._tasks if t.status == TaskStatus.DONE)

    # -- Bulk operations ----------------------------------------------------

    def clear(self) -> None:
        """Remove all tasks from the queue."""
        self._tasks.clear()
