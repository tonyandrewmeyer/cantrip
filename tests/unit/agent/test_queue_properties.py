"""Property-based tests for :class:`WorkQueue` and :class:`AgentTask`.

The example-based tests in ``test_queue.py`` and ``test_queue_advanced.py``
cover the named-scenario cases.  These property tests cover the space in
between: random sequences of add/transition/cancel against random task
graphs, asserting the invariants that should hold for *every* legal
state of the queue.

Invariants under test, restated once here so they don't have to be
re-read from each test body:

* *Count consistency.*  ``pending_count + active_count + done_count + (failed) +
  (blocked) == len(all_tasks())`` for any sequence of mutations.
* *Status counters track status.*  ``pending_count`` equals the count of tasks
  whose ``status == PENDING``; same for ``active_count`` and ``done_count``.
* *all_tasks() is a deep copy.*  Mutating the returned list — or any task in
  it — never affects the live queue.
* *Auto-assigned IDs are unique.*  ``AgentTask`` instances built with the
  default ID are statistically unique (uuid4 hex first 12 chars).
* *add_tasks is atomic on collision.*  A batch containing any duplicate ID
  (against the existing queue or within the same batch) rejects the entire
  batch and leaves the queue untouched.
* *all_ready respects PENDING-only.*  Every task returned by ``all_ready()`` has
  ``status == PENDING``.
* *all_ready respects dependencies.*  A pending task whose dependency list
  contains an ID of a still-PENDING (or still-ACTIVE) in-queue task is *not*
  returned; once every such dep transitions to DONE / FAILED / BLOCKED or is
  cancelled, the task becomes ready.
* *all_ready preserves queue order.*  Ready tasks come back in insertion order.
* *Cancel removes.*  After ``cancel(id)`` the task is gone from ``all_tasks()``
  and ``get_task(id)`` returns ``None``.
* *Clear empties.*  After ``clear()`` every counter is zero and ``all_tasks()``
  is empty.
* *move_to_front beats non-target PENDING tasks.*  After ``move_to_front(id)``,
  the moved task appears before any other PENDING task in queue order.
* *unblock returns BLOCKED → PENDING.*  After ``unblock(id)`` the task's
  status is PENDING and ``blocked_reason`` is cleared.
* *Workflow-phase mapping is total and deterministic.*  Every
  :class:`TaskCategory` maps to exactly one :class:`WorkflowPhase`, and
  ``WorkflowPhase.from_category(None)`` returns :attr:`BUILD`.
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.queue import (
    AgentTask,
    TaskCategory,
    TaskStatus,
    WorkflowPhase,
    WorkQueue,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _task_id_strategy() -> st.SearchStrategy[str]:
    """Short alphanumeric IDs.

    Real IDs are uuid4 hex; the property tests want short labels so
    Hypothesis can shrink to minimal failing examples without the
    identifiers fighting readability.
    """
    return st.text(alphabet="abcdefghijklmnop", min_size=1, max_size=4)


def _unique_ids(min_size: int = 1, max_size: int = 8) -> st.SearchStrategy[list[str]]:
    """A list of *min_size*..*max_size* distinct task IDs."""
    return st.lists(_task_id_strategy(), min_size=min_size, max_size=max_size, unique=True)


def _category() -> st.SearchStrategy[TaskCategory]:
    """Any of the eight task categories."""
    return st.sampled_from(list(TaskCategory))


def _terminal_status() -> st.SearchStrategy[TaskStatus]:
    """A status that resolves dependencies — DONE, FAILED, or BLOCKED."""
    return st.sampled_from([TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED])


@st.composite
def _dag_tasks(draw: st.DrawFn) -> list[AgentTask]:
    """Build an acyclic task graph in topological order.

    Each task is assigned an index; a task at index *i* may depend only
    on tasks at lower indices.  That keeps the graph a DAG by
    construction regardless of which subset of earlier IDs Hypothesis
    samples.
    """
    ids = draw(_unique_ids(min_size=1, max_size=6))
    tasks: list[AgentTask] = []
    for i, tid in enumerate(ids):
        earlier = ids[:i]
        deps = (
            draw(st.lists(st.sampled_from(earlier), max_size=len(earlier), unique=True))
            if earlier
            else []
        )
        tasks.append(
            AgentTask(
                id=tid,
                title=f"task-{tid}",
                category=draw(_category()),
                dependencies=deps,
            )
        )
    return tasks


def _load_queue(tasks: list[AgentTask]) -> WorkQueue:
    """Build a queue containing copies of *tasks* (fresh PENDING state)."""
    queue = WorkQueue()
    for task in tasks:
        queue.add_task(copy.deepcopy(task))
    return queue


# ---------------------------------------------------------------------------
# AgentTask invariants
# ---------------------------------------------------------------------------


class TestAgentTaskAutoID:
    """``AgentTask.__post_init__`` always produces an ID."""

    @given(
        title=st.text(min_size=0, max_size=64),
        category=_category(),
    )
    def test_default_id_is_nonempty_hex(self, title: str, category: TaskCategory) -> None:
        task = AgentTask(title=title, category=category)
        assert task.id, "Default ID must be non-empty."
        assert len(task.id) == 12, "Default ID is uuid4().hex[:12]."
        assert all(c in "0123456789abcdef" for c in task.id), "Default ID is lowercase hex."

    @given(n=st.integers(min_value=2, max_value=64))
    def test_default_ids_are_unique_across_instances(self, n: int) -> None:
        tasks = [AgentTask(title=f"t{i}", category=TaskCategory.BUILD) for i in range(n)]
        ids = {t.id for t in tasks}
        assert len(ids) == n, "uuid4 hex collisions in 64 draws are astronomically unlikely."

    @given(
        explicit_id=st.text(alphabet="abcdef0123456789", min_size=1, max_size=20),
        title=st.text(min_size=0, max_size=32),
        category=_category(),
    )
    def test_explicit_id_is_preserved(
        self, explicit_id: str, title: str, category: TaskCategory
    ) -> None:
        task = AgentTask(id=explicit_id, title=title, category=category)
        assert task.id == explicit_id, "An explicit ID must not be overwritten."


# ---------------------------------------------------------------------------
# Add / lookup invariants
# ---------------------------------------------------------------------------


class TestAddTaskInvariants:
    """``add_task`` / ``add_tasks`` preserve the in-queue task set."""

    @given(tasks=_dag_tasks())
    def test_add_task_preserves_count_and_ids(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        retrieved = queue.all_tasks()
        assert len(retrieved) == len(tasks)
        assert {t.id for t in retrieved} == {t.id for t in tasks}

    @given(tasks=_dag_tasks())
    def test_add_task_rejects_duplicate_id_atomically(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        before = queue.all_tasks()
        # Try to add a task whose ID collides with the first existing task.
        duplicate = AgentTask(
            id=tasks[0].id,
            title="dup",
            category=tasks[0].category,
        )
        with pytest.raises(ValueError, match="Duplicate task ID"):
            queue.add_task(duplicate)
        after = queue.all_tasks()
        assert [t.id for t in after] == [t.id for t in before], (
            "A duplicate-ID add must leave the queue exactly as it was."
        )

    @given(tasks=_dag_tasks())
    def test_add_tasks_batch_is_atomic_on_collision(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        before = queue.all_tasks()
        # Build a batch where the *last* task collides; everything earlier is fine.
        clean = AgentTask(id="zzz-clean", title="clean", category=TaskCategory.BUILD)
        colliding = AgentTask(
            id=tasks[0].id,
            title="collide",
            category=TaskCategory.BUILD,
        )
        with pytest.raises(ValueError, match="Duplicate task ID"):
            queue.add_tasks([clean, colliding])
        after = queue.all_tasks()
        assert [t.id for t in after] == [t.id for t in before], (
            "A colliding batch must not partially apply — neither task should land."
        )

    @given(tasks=_dag_tasks())
    def test_add_tasks_rejects_intra_batch_duplicate(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        before = queue.all_tasks()
        # Two tasks with the same ID inside one batch.
        twin_a = AgentTask(id="twin", title="A", category=TaskCategory.BUILD)
        twin_b = AgentTask(id="twin", title="B", category=TaskCategory.BUILD)
        with pytest.raises(ValueError, match="Duplicate task ID"):
            queue.add_tasks([twin_a, twin_b])
        after = queue.all_tasks()
        assert [t.id for t in after] == [t.id for t in before], (
            "An intra-batch duplicate must leave the queue untouched."
        )

    @given(tasks=_dag_tasks())
    def test_all_tasks_returns_deep_copies(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        snapshot = queue.all_tasks()
        # Mutate the snapshot in every way callers might.
        for task in snapshot:
            task.status = TaskStatus.DONE
            task.title = "tampered"
            task.dependencies.append("phantom")
        # Live state is untouched.
        live = queue.all_tasks()
        for task in live:
            assert task.status == TaskStatus.PENDING
            assert task.title != "tampered"
            assert "phantom" not in task.dependencies


# ---------------------------------------------------------------------------
# Counter consistency
# ---------------------------------------------------------------------------


class TestCounterConsistency:
    """The three status counters always agree with the underlying tasks."""

    @given(tasks=_dag_tasks())
    def test_initial_state_is_all_pending(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        assert queue.pending_count == len(tasks)
        assert queue.active_count == 0
        assert queue.done_count == 0

    @given(tasks=_dag_tasks(), data=st.data())
    def test_counters_match_status_after_random_transitions(
        self, tasks: list[AgentTask], data: st.DataObject
    ) -> None:
        queue = _load_queue(tasks)
        # Apply a random transition to each task.
        for task in tasks:
            target = data.draw(
                st.sampled_from(
                    [
                        TaskStatus.PENDING,
                        TaskStatus.ACTIVE,
                        TaskStatus.DONE,
                        TaskStatus.FAILED,
                        TaskStatus.BLOCKED,
                    ]
                )
            )
            if target == TaskStatus.PENDING:
                queue.set_pending(task.id)
            elif target == TaskStatus.ACTIVE:
                queue.set_active(task.id)
            elif target == TaskStatus.DONE:
                queue.set_done(task.id, "ok")
            elif target == TaskStatus.FAILED:
                queue.set_failed(task.id, "boom")
            else:
                queue.set_blocked(task.id, "stuck")

        live = queue.all_tasks()
        pending = sum(1 for t in live if t.status == TaskStatus.PENDING)
        active = sum(1 for t in live if t.status == TaskStatus.ACTIVE)
        done = sum(1 for t in live if t.status == TaskStatus.DONE)
        assert queue.pending_count == pending
        assert queue.active_count == active
        assert queue.done_count == done
        # The five known statuses partition every task.
        assert sum(1 for t in live if t.status in TaskStatus) == len(live), (
            "Every task carries a TaskStatus value."
        )


# ---------------------------------------------------------------------------
# Status transition shape
# ---------------------------------------------------------------------------


class TestStatusTransitionsRecordPayload:
    """Each ``set_*`` method writes the documented fields."""

    @given(tasks=_dag_tasks(), result=st.text(min_size=0, max_size=64))
    def test_set_done_writes_result(self, tasks: list[AgentTask], result: str) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.set_done(target, result)
        task = queue.get_task(target)
        assert task is not None
        assert task.status == TaskStatus.DONE
        assert task.result == result

    @given(tasks=_dag_tasks(), error=st.text(min_size=0, max_size=64))
    def test_set_failed_writes_error(self, tasks: list[AgentTask], error: str) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.set_failed(target, error)
        task = queue.get_task(target)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.result == error

    @given(tasks=_dag_tasks(), reason=st.text(min_size=1, max_size=64))
    def test_set_blocked_writes_reason(self, tasks: list[AgentTask], reason: str) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.set_blocked(target, reason)
        task = queue.get_task(target)
        assert task is not None
        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == reason

    @given(tasks=_dag_tasks(), reason=st.text(min_size=1, max_size=32))
    def test_unblock_returns_to_pending_and_clears_reason(
        self, tasks: list[AgentTask], reason: str
    ) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.set_blocked(target, reason)
        queue.unblock(target)
        task = queue.get_task(target)
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.blocked_reason is None


# ---------------------------------------------------------------------------
# Dependency / readiness invariants
# ---------------------------------------------------------------------------


class TestDependencyGating:
    """``all_ready`` and ``next_ready`` respect status + dependencies."""

    @given(tasks=_dag_tasks())
    def test_all_ready_only_returns_pending(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        for task in queue.all_ready():
            assert task.status == TaskStatus.PENDING

    @given(tasks=_dag_tasks(), data=st.data())
    def test_unmet_pending_or_active_dep_blocks_ready(
        self, tasks: list[AgentTask], data: st.DataObject
    ) -> None:
        # Randomly transition some tasks to ACTIVE; ACTIVE tasks do *not*
        # resolve a dependency (only DONE / FAILED / BLOCKED do).
        queue = _load_queue(tasks)
        for task in tasks:
            if data.draw(st.booleans()):
                queue.set_active(task.id)

        live = queue.all_tasks()
        ready_ids = {t.id for t in queue.all_ready()}
        unresolved_ids = {
            t.id for t in live if t.status in (TaskStatus.PENDING, TaskStatus.ACTIVE)
        }
        for task in live:
            if task.status != TaskStatus.PENDING:
                continue
            if any(dep in unresolved_ids for dep in task.dependencies):
                assert task.id not in ready_ids, (
                    f"Task {task.id!r} has an unresolved dependency; "
                    f"it must not appear in all_ready()."
                )

    @given(tasks=_dag_tasks())
    def test_terminal_dep_unblocks_dependents(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        # Find a task that has at least one dependency on another in-queue task.
        candidates = [t for t in tasks if t.dependencies]
        if not candidates:
            return
        dependent = candidates[0]
        # Walk each dep and resolve it.  Once every dep is terminal, the
        # dependent must show up in all_ready().
        for dep_id in dependent.dependencies:
            queue.set_done(dep_id, "ok")
        ready_ids = {t.id for t in queue.all_ready()}
        assert dependent.id in ready_ids, (
            "After every dependency has reached DONE, the dependent must be ready."
        )

    @given(tasks=_dag_tasks())
    def test_cancelled_dep_unblocks_dependents(self, tasks: list[AgentTask]) -> None:
        # Cancelling a dep removes it from the queue.  ``all_ready`` treats a
        # missing dep as resolved (the cancelled prerequisite can't block us
        # because it no longer exists).
        queue = _load_queue(tasks)
        candidates = [t for t in tasks if t.dependencies]
        if not candidates:
            return
        dependent = candidates[0]
        for dep_id in dependent.dependencies:
            queue.cancel(dep_id)
        ready_ids = {t.id for t in queue.all_ready()}
        assert dependent.id in ready_ids

    @given(tasks=_dag_tasks())
    def test_all_ready_preserves_queue_order(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        # No dependencies → every pending task is ready, and order should match
        # insertion order.  Filter to tasks whose deps are all empty so the
        # ordering check is unambiguous.
        independent_in_order = [t.id for t in tasks if not t.dependencies]
        ready_ids_in_order = [t.id for t in queue.all_ready() if not t.dependencies]
        assert ready_ids_in_order == independent_in_order

    @given(tasks=_dag_tasks())
    def test_next_ready_matches_first_all_ready(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        ready = queue.all_ready()
        nxt = queue.next_ready()
        if not ready:
            assert nxt is None
        else:
            assert nxt is not None
            assert nxt.id == ready[0].id

    @given(tasks=_dag_tasks(), limit=st.integers(min_value=1, max_value=8))
    def test_all_ready_limit_truncates(self, tasks: list[AgentTask], limit: int) -> None:
        queue = _load_queue(tasks)
        unlimited = queue.all_ready()
        limited = queue.all_ready(limit=limit)
        assert len(limited) <= limit
        assert [t.id for t in limited] == [t.id for t in unlimited[:limit]]


# ---------------------------------------------------------------------------
# Cancel / clear / move_to_front
# ---------------------------------------------------------------------------


class TestCancelClearMove:
    """Structural mutations leave the queue in a predictable shape."""

    @given(tasks=_dag_tasks())
    def test_cancel_removes_task(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.cancel(target)
        assert queue.get_task(target) is None
        assert target not in {t.id for t in queue.all_tasks()}
        assert len(queue.all_tasks()) == len(tasks) - 1

    @given(tasks=_dag_tasks())
    def test_clear_empties_queue(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        queue.clear()
        assert queue.all_tasks() == []
        assert queue.pending_count == 0
        assert queue.active_count == 0
        assert queue.done_count == 0

    @given(tasks=_dag_tasks())
    def test_move_to_front_places_before_other_pending(self, tasks: list[AgentTask]) -> None:
        if len(tasks) < 2:
            return
        queue = _load_queue(tasks)
        target = tasks[-1].id  # Last-inserted task.
        queue.move_to_front(target)
        live = queue.all_tasks()
        target_idx = next(i for i, t in enumerate(live) if t.id == target)
        # Every PENDING task that isn't the target must come *after* it.
        for i, task in enumerate(live):
            if task.id == target:
                continue
            if task.status != TaskStatus.PENDING:
                continue
            assert i > target_idx, (
                f"Task {task.id!r} (PENDING) appears before the moved task; "
                f"move_to_front must promote the target above all other pending tasks."
            )

    @given(tasks=_dag_tasks())
    def test_move_to_front_rejects_non_pending(self, tasks: list[AgentTask]) -> None:
        queue = _load_queue(tasks)
        target = tasks[0].id
        queue.set_active(target)
        with pytest.raises(ValueError, match="Cannot reprioritise"):
            queue.move_to_front(target)


# ---------------------------------------------------------------------------
# WorkflowPhase mapping
# ---------------------------------------------------------------------------


class TestWorkflowPhaseMapping:
    """``WorkflowPhase.from_category`` is total, deterministic, and idempotent."""

    @given(category=_category())
    def test_every_category_maps_to_a_phase(self, category: TaskCategory) -> None:
        phase = WorkflowPhase.from_category(category)
        assert isinstance(phase, WorkflowPhase)

    @given(category=_category())
    def test_mapping_is_deterministic(self, category: TaskCategory) -> None:
        first = WorkflowPhase.from_category(category)
        second = WorkflowPhase.from_category(category)
        assert first == second

    def test_none_category_defaults_to_build(self) -> None:
        assert WorkflowPhase.from_category(None) == WorkflowPhase.BUILD

    @given(category=_category())
    def test_returned_phase_is_a_member(self, category: TaskCategory) -> None:
        phase = WorkflowPhase.from_category(category)
        assert phase in set(WorkflowPhase)
