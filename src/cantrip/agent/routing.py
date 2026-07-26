"""Pure state machine for work queue routing.

Extracts the "what happens next" decision from the executor into a pure
function over a data snapshot, following orc's ``route(WorldState) → action``
pattern.  No I/O, no side effects — the entire routing decision is
deterministic and testable.
"""

from __future__ import annotations

import dataclasses
import enum


class RouteAction(enum.StrEnum):
    """Action the executor should take next."""

    SPAWN_TASK = "spawn_task"
    WAIT_FOR_CONFIRMATION = "wait_for_confirmation"
    WAIT_FOR_IN_FLIGHT = "wait_for_in_flight"
    IDLE = "idle"


@dataclasses.dataclass(frozen=True)
class RoutingDecision:
    """The result of a routing decision.

    *action* is what to do; *task_id* identifies the specific task when
    the action is ``SPAWN_TASK`` or ``WAIT_FOR_CONFIRMATION``.
    """

    action: RouteAction
    task_id: str | None = None


class TaskSnapshot(enum.StrEnum):
    """Simplified status for a task in the queue snapshot."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclasses.dataclass(frozen=True)
class TaskInfo:
    """Lightweight snapshot of a single task for routing decisions."""

    id: str
    category: str
    status: TaskSnapshot
    dependencies: tuple[str, ...]
    noop_count: int = 0


@dataclasses.dataclass(frozen=True)
class WorkQueueState:
    """Frozen snapshot of everything that influences the next-task decision.

    Built from the live ``WorkQueue`` and executor state.  All fields are
    immutable so the snapshot can be hashed, compared, and used as a dict
    key in BFS verification.
    """

    tasks: tuple[TaskInfo, ...]
    active_subagent_count: int
    max_concurrency: int
    paused: bool
    draining: bool
    has_charm_path: bool
    has_dev_model: bool

    # -- Derived counts (convenience) ----------------------------------------

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskSnapshot.PENDING)

    @property
    def active_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskSnapshot.ACTIVE)

    @property
    def blocked_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskSnapshot.BLOCKED)

    @property
    def done_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskSnapshot.DONE)

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskSnapshot.FAILED)

    @property
    def is_terminal(self) -> bool:
        """True when no further progress is possible without external input.

        Terminal states: no pending tasks, no active tasks, possibly some
        blocked/done/failed tasks remaining.
        """
        return self.pending_count == 0 and self.active_count == 0

    @property
    def free_slots(self) -> int:
        """Number of subagent slots available for new tasks."""
        return max(0, self.max_concurrency - self.active_subagent_count)


def _dependencies_satisfied(task: TaskInfo, state: WorkQueueState) -> bool:
    """Check whether all of a task's dependencies are satisfied.

    A dependency is satisfied if the task is done, failed, or has been
    removed from the queue (cancelled).
    """
    resolved = {t.id for t in state.tasks if t.status in (TaskSnapshot.DONE, TaskSnapshot.FAILED)}
    all_ids = {t.id for t in state.tasks}
    return all(dep in resolved or dep not in all_ids for dep in task.dependencies)


def _ready_tasks(state: WorkQueueState) -> list[TaskInfo]:
    """Return pending tasks whose dependencies are satisfied, in queue order."""
    return [
        t
        for t in state.tasks
        if t.status == TaskSnapshot.PENDING and _dependencies_satisfied(t, state)
    ]


def route(state: WorkQueueState) -> RoutingDecision:
    """Determine the next action for the executor.

    Pure function — no I/O, no side effects.  Maps the current queue
    snapshot to exactly one action.

    Decision priority:

    1. If paused or draining → wait for in-flight or idle.
    2. If no free slots → wait for in-flight tasks.
    3. Non-CONFIRM ready tasks are preferred — spawn the first one.
    4. If only CONFIRM tasks remain → ``WAIT_FOR_CONFIRMATION``.
    5. If tasks are in-flight but none are ready → ``WAIT_FOR_IN_FLIGHT``.
    6. Otherwise → ``IDLE`` (terminal or waiting for unblock).
    """
    if state.paused or state.draining:
        if state.active_subagent_count > 0:
            return RoutingDecision(action=RouteAction.WAIT_FOR_IN_FLIGHT)
        return RoutingDecision(action=RouteAction.IDLE)

    if state.free_slots <= 0:
        return RoutingDecision(action=RouteAction.WAIT_FOR_IN_FLIGHT)

    ready = _ready_tasks(state)

    # Prefer non-CONFIRM tasks so confirmations don't block unrelated work.
    first_confirm: TaskInfo | None = None
    for task in ready:
        if task.category == "confirm":
            if first_confirm is None:
                first_confirm = task
            continue
        return RoutingDecision(
            action=RouteAction.SPAWN_TASK,
            task_id=task.id,
        )

    # Only CONFIRM tasks remain.
    if first_confirm is not None:
        return RoutingDecision(
            action=RouteAction.WAIT_FOR_CONFIRMATION,
            task_id=first_confirm.id,
        )

    # No ready tasks — either in-flight tasks will unblock something,
    # or we are truly idle (all done/failed/blocked).
    if state.active_subagent_count > 0:
        return RoutingDecision(action=RouteAction.WAIT_FOR_IN_FLIGHT)

    return RoutingDecision(action=RouteAction.IDLE)


def snapshot_from_queue(
    tasks: list[object],
    active_subagent_count: int,
    max_concurrency: int,
    *,
    paused: bool = False,
    draining: bool = False,
    has_charm_path: bool = False,
    has_dev_model: bool = False,
) -> WorkQueueState:
    """Build a ``WorkQueueState`` from live ``AgentTask`` objects.

    Accepts the raw task list (duck-typed — needs ``.id``, ``.category``,
    ``.status``, ``.dependencies``, ``.noop_count``) to avoid a hard import
    cycle with ``queue.py``.
    """
    infos: list[TaskInfo] = [
        TaskInfo(
            id=t.id,
            category=str(t.category),
            status=TaskSnapshot(str(t.status)),
            dependencies=tuple(t.dependencies),
            noop_count=t.noop_count,
        )
        for t in tasks
    ]
    return WorkQueueState(
        tasks=tuple(infos),
        active_subagent_count=active_subagent_count,
        max_concurrency=max_concurrency,
        paused=paused,
        draining=draining,
        has_charm_path=has_charm_path,
        has_dev_model=has_dev_model,
    )
