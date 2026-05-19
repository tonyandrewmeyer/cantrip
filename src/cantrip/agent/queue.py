"""Work queue for autonomous agent task scheduling."""

import copy
import dataclasses
import datetime
import enum
import uuid
from collections.abc import Callable


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
    LIBRARIAN = "librarian"


class WorkflowPhase(enum.StrEnum):
    """Coarse workflow stage the agent is in, used to curate the tool slice.

    Distinct from :class:`TaskCategory` (which has eight values, several
    of them planner bookkeeping) — the phase is the *shape* of work the
    LLM is doing right now, and there are exactly five shapes worth a
    hand-curated tool set.  :meth:`from_category` collapses the queue
    categories onto these five.
    """

    RESEARCH = "research"
    BUILD = "build"
    DEBUG = "debug"
    DEPLOY = "deploy"
    DEMO = "demo"

    @classmethod
    def from_category(cls, category: "TaskCategory | None") -> "WorkflowPhase":
        """Map a queue task category onto a workflow phase.

        ``TEST`` is debug-shaped (run tests, read failures, lint); ``INFRA``
        is deploy-shaped (juju, concierge); ``CONFIRM`` / ``LIBRARIAN`` are
        short interactive turns that are happiest with the build set.  An
        unknown or missing category defaults to :attr:`BUILD` so the first
        interaction picks build-shaped tools.
        """
        return _CATEGORY_TO_PHASE.get(category, cls.BUILD) if category else cls.BUILD


_CATEGORY_TO_PHASE: dict[TaskCategory, WorkflowPhase] = {
    TaskCategory.RESEARCH: WorkflowPhase.RESEARCH,
    TaskCategory.BUILD: WorkflowPhase.BUILD,
    TaskCategory.DEPLOY: WorkflowPhase.DEPLOY,
    TaskCategory.TEST: WorkflowPhase.DEBUG,
    TaskCategory.DEBUG: WorkflowPhase.DEBUG,
    TaskCategory.INFRA: WorkflowPhase.DEPLOY,
    TaskCategory.CONFIRM: WorkflowPhase.BUILD,
    TaskCategory.LIBRARIAN: WorkflowPhase.RESEARCH,
}


class ModelHint(enum.StrEnum):
    """Hint for which model a task should use, overriding category defaults."""

    PRIMARY = "primary"
    LIGHT = "light"


@dataclasses.dataclass
class AgentTask:
    """A discrete unit of work for the autonomous agent."""

    title: str
    category: TaskCategory
    id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    description: str = ""
    dependencies: list[str] = dataclasses.field(default_factory=list)
    result: str | None = None
    blocked_reason: str | None = None
    model_hint: ModelHint | None = None
    created_at: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    noop_count: int = 0
    # Transient — set while a task owns a git worktree; cleared on release.
    # Not persisted to SQLite because worktrees don't survive sessions; they
    # are recreated on restart by whoever picks the task up next.
    worktree_path: str | None = None
    # Transient — set while a subagent is running this task.  ``subagent_phase``
    # is a short human-readable string like "thinking" or "running:
    # charmcraft_pack" and ``subagent_started_at`` is the wall-clock time the
    # subagent began.  Both cleared when the task transitions out of ACTIVE.
    subagent_phase: str = ""
    subagent_started_at: datetime.datetime | None = None
    # Tri-state signal for Best-of-N races that require a CONFIRM before
    # dispatching: ``None`` means the executor has not yet reached the
    # gate (or racing is disabled), ``"approved"`` means the user accepted
    # the estimated cost and the race should proceed, ``"declined"`` means
    # the user rejected it and the task should downgrade to a single
    # subagent run.  Transient — not persisted across restarts.
    race_decision: str | None = None

    def __post_init__(self) -> None:
        """Generate a unique ID if not provided."""
        if not self.id:
            self.id = uuid.uuid4().hex[:12]


class WorkQueue:
    """Central task queue for the autonomous work loop.

    Holds ``AgentTask`` objects and provides status transitions, dependency
    checking, and an optional callback fired on every task mutation.

    All mutation methods run synchronously within asyncio's single-threaded
    event loop, so they are atomic relative to one another — no caller
    needs to take an explicit lock.
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

    def notify_task(self, task: AgentTask) -> None:
        """Re-fire the change callback for *task*.

        Use this after mutating a task field directly (for example, setting
        ``worktree_path`` when a worktree is allocated) so subscribers see
        the update even though the change did not go through a queue method.
        """
        self._notify(task)

    def _get_or_raise(self, task_id: str) -> AgentTask:
        """Return the task with *task_id* or raise ``KeyError``."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    # -- Adding tasks -------------------------------------------------------

    def add_task(self, task: AgentTask) -> None:
        """Append a single task and fire the callback.

        Raises ``ValueError`` if a task with the same ID already exists.
        """
        if any(t.id == task.id for t in self._tasks):
            raise ValueError(f"Duplicate task ID {task.id!r} — IDs must be unique within a queue")
        self._tasks.append(task)
        self._notify(task)

    def add_tasks(self, tasks: list[AgentTask]) -> None:
        """Bulk-add tasks (for planner output).

        Raises ``ValueError`` if any task ID collides with an existing
        task or with another task in the same batch.  Atomic — a
        collision rejects the whole batch, leaving the queue untouched.
        """
        existing_ids = {t.id for t in self._tasks}
        seen_ids: set[str] = set()
        for task in tasks:
            if task.id in existing_ids:
                raise ValueError(
                    f"Duplicate task ID {task.id!r} — IDs must be unique within a queue"
                )
            if task.id in seen_ids:
                raise ValueError(f"Duplicate task ID {task.id!r} appears twice in the same batch")
            seen_ids.add(task.id)
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

        A dependency is considered satisfied if the task is done,
        failed, blocked, or has been cancelled (removed from the
        queue).  Treating ``BLOCKED`` as resolved (Phase 106.2) is
        load-bearing: without it a sprint-build task flipping to
        ``BLOCKED`` leaves every dependent stuck ``PENDING`` forever
        and the print-mode drain hangs the full 30-minute timeout
        polling for in-flight work that will never become ready.
        """
        resolved_ids = {
            t.id
            for t in self._tasks
            if t.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED)
        }
        all_ids = {t.id for t in self._tasks}
        ready: list[AgentTask] = []
        for task in self._tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in resolved_ids or dep not in all_ids for dep in task.dependencies):
                ready.append(task)
                if limit and len(ready) >= limit:
                    break
        return ready

    # -- Status transitions -------------------------------------------------

    def set_pending(self, task_id: str) -> None:
        """Reset a task back to pending (e.g. after a noop attempt)."""
        task = self._get_or_raise(task_id)
        task.status = TaskStatus.PENDING
        self._notify(task)

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
        # Insert at the first pending slot so the task becomes the
        # next-ready candidate; if no other tasks are pending, the
        # default sends us to the end of the queue.
        insert_idx = next(
            (i for i, t in enumerate(self._tasks) if t.status == TaskStatus.PENDING),
            len(self._tasks),
        )
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
        """Return a deep copy of the task list.

        Callers receive independent copies so they cannot accidentally mutate
        the live queue state.
        """
        return copy.deepcopy(self._tasks)

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
