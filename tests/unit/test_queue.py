"""Tests for the work queue and agent task model."""

import asyncio
import datetime
from collections.abc import Iterator
from pathlib import Path

import pytest

from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.store import SessionStore

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / ".cantrip"


@pytest.fixture
def store(db_path: Path) -> Iterator[SessionStore]:
    """Return an open SessionStore backed by a temporary file."""
    s = SessionStore(db_path)
    s.open()
    yield s
    s.close()


def _task(
    title: str = "Do something",
    category: TaskCategory = TaskCategory.BUILD,
    **kwargs: object,
) -> AgentTask:
    """Shorthand factory for test tasks."""
    return AgentTask(title=title, category=category, **kwargs)  # type: ignore[arg-type]


# -- AgentTask dataclass ----------------------------------------------------


class TestAgentTask:
    """Tests for AgentTask construction and defaults."""

    def test_default_id_generated(self) -> None:
        """An ID is auto-generated when not provided."""
        task = _task()
        assert task.id
        assert len(task.id) == 12

    def test_explicit_id(self) -> None:
        """A provided ID is preserved."""
        task = _task(id="custom-id")
        assert task.id == "custom-id"

    def test_default_status_is_pending(self) -> None:
        """New tasks default to pending status."""
        task = _task()
        assert task.status == TaskStatus.PENDING

    def test_default_dependencies_empty(self) -> None:
        """Dependencies default to an empty list."""
        task = _task()
        assert task.dependencies == []

    def test_default_created_at(self) -> None:
        """created_at is auto-set to approximately now."""
        before = datetime.datetime.now()
        task = _task()
        after = datetime.datetime.now()
        assert before <= task.created_at <= after


# -- WorkQueue core operations ----------------------------------------------


class TestWorkQueue:
    """Tests for core WorkQueue operations."""

    def test_add_task(self) -> None:
        """A single task can be added and retrieved."""
        q = WorkQueue()
        task = _task()
        q.add_task(task)
        assert q.all_tasks() == [task]

    def test_add_tasks_bulk(self) -> None:
        """Multiple tasks can be added in bulk."""
        q = WorkQueue()
        tasks = [_task(title="A"), _task(title="B")]
        q.add_tasks(tasks)
        assert len(q.all_tasks()) == 2

    def test_add_task_rejects_duplicate_id(self) -> None:
        """Adding a task whose ID already exists raises ValueError."""
        q = WorkQueue()
        q.add_task(_task(id="dup-id"))
        with pytest.raises(ValueError, match="Duplicate task ID"):
            q.add_task(_task(id="dup-id", title="Another"))

    def test_add_tasks_rejects_duplicate_in_batch(self) -> None:
        """Bulk-add rejects a duplicate that collides within the batch."""
        q = WorkQueue()
        with pytest.raises(ValueError, match="Duplicate task ID"):
            q.add_tasks([_task(id="same"), _task(id="same", title="Dupe")])

    def test_next_ready_returns_first_pending(self) -> None:
        """next_ready returns the first pending task."""
        q = WorkQueue()
        t1 = _task(title="First")
        t2 = _task(title="Second")
        q.add_tasks([t1, t2])
        assert q.next_ready() is t1

    def test_next_ready_skips_blocked(self) -> None:
        """Blocked tasks are skipped by next_ready."""
        q = WorkQueue()
        t1 = _task(title="Blocked")
        t2 = _task(title="Ready")
        q.add_tasks([t1, t2])
        q.set_blocked(t1.id, "waiting")
        assert q.next_ready() is t2

    def test_next_ready_skips_active(self) -> None:
        """Active tasks are skipped by next_ready."""
        q = WorkQueue()
        t1 = _task(title="Active")
        t2 = _task(title="Ready")
        q.add_tasks([t1, t2])
        q.set_active(t1.id)
        assert q.next_ready() is t2

    def test_next_ready_respects_dependencies(self) -> None:
        """A task is not ready until its dependencies are done."""
        q = WorkQueue()
        t1 = _task(title="Prerequisite", id="prereq")
        t2 = _task(title="Dependent", dependencies=["prereq"])
        q.add_tasks([t1, t2])

        # t2 depends on t1 which is still pending — only t1 is ready.
        assert q.next_ready() is t1

        q.set_active(t1.id)
        q.set_done(t1.id)

        # Now t2 should be ready.
        assert q.next_ready() is t2

    def test_next_ready_returns_none_when_empty(self) -> None:
        """An empty queue returns None."""
        q = WorkQueue()
        assert q.next_ready() is None

    def test_next_ready_returns_none_when_all_done(self) -> None:
        """Returns None when every task is already done."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_done(t.id)
        assert q.next_ready() is None

    def test_all_ready_returns_multiple(self) -> None:
        """all_ready returns all pending tasks whose dependencies are met."""
        q = WorkQueue()
        t1 = _task(title="A", id="a")
        t2 = _task(title="B", id="b")
        t3 = _task(title="C", id="c", dependencies=["a"])
        q.add_tasks([t1, t2, t3])

        ready = q.all_ready()
        assert ready == [t1, t2]

    def test_all_ready_with_limit(self) -> None:
        """all_ready respects the limit parameter."""
        q = WorkQueue()
        t1 = _task(title="A")
        t2 = _task(title="B")
        t3 = _task(title="C")
        q.add_tasks([t1, t2, t3])

        ready = q.all_ready(limit=2)
        assert len(ready) == 2
        assert ready == [t1, t2]

    def test_all_ready_empty_queue(self) -> None:
        """all_ready returns empty list when no tasks are ready."""
        q = WorkQueue()
        assert q.all_ready() == []

    def test_all_ready_unblocks_after_failed_dependency(self) -> None:
        """all_ready considers a failed dependency as resolved."""
        q = WorkQueue()
        t1 = _task(title="Build", id="build-1")
        t2 = _task(title="Deploy", id="deploy-1", dependencies=["build-1"])
        q.add_tasks([t1, t2])

        # t2 is blocked by t1.
        assert q.all_ready() == [t1]

        # t1 fails.
        q.set_active(t1.id)
        q.set_failed(t1.id, "build error")

        # t2 should now be ready (not stuck forever).
        assert q.all_ready() == [t2]

    def test_all_ready_skips_active(self) -> None:
        """all_ready skips tasks that are already active."""
        q = WorkQueue()
        t1 = _task(title="Active")
        t2 = _task(title="Pending")
        q.add_tasks([t1, t2])
        q.set_active(t1.id)

        ready = q.all_ready()
        assert ready == [t2]

    def test_set_active(self) -> None:
        """set_active transitions a task to active status."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_active(t.id)
        assert t.status == TaskStatus.ACTIVE

    def test_set_done(self) -> None:
        """set_done transitions a task to done status."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_done(t.id)
        assert t.status == TaskStatus.DONE

    def test_set_done_with_result(self) -> None:
        """set_done stores an optional result string."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_done(t.id, result="Charm deployed")
        assert t.status == TaskStatus.DONE
        assert t.result == "Charm deployed"

    def test_set_failed(self) -> None:
        """set_failed transitions a task to failed status and stores error."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_failed(t.id, error="Build error")
        assert t.status == TaskStatus.FAILED
        assert t.result == "Build error"

    def test_set_blocked_and_unblock(self) -> None:
        """set_blocked and unblock round-trip correctly."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)

        q.set_blocked(t.id, "Waiting for model")
        assert t.status == TaskStatus.BLOCKED
        assert t.blocked_reason == "Waiting for model"

        q.unblock(t.id)
        assert t.status == TaskStatus.PENDING
        assert t.blocked_reason is None

    def test_cancel_removes_task(self) -> None:
        """cancel removes the task from the queue."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.cancel(t.id)
        assert q.all_tasks() == []

    def test_cancelled_dependency_unblocks_downstream(self) -> None:
        """A cancelled dependency should not block downstream tasks."""
        q = WorkQueue()
        dep = _task(title="Research", id="dep-1")
        downstream = _task(title="Confirm", id="confirm-1", dependencies=["dep-1"])
        q.add_task(dep)
        q.add_task(downstream)

        # Initially downstream is not ready (dependency pending).
        assert q.all_ready() == [dep]

        # Cancel the dependency — downstream should now be ready.
        q.cancel("dep-1")
        ready = q.all_ready()
        assert len(ready) == 1
        assert ready[0].id == "confirm-1"

    def test_get_task(self) -> None:
        """get_task returns the task by ID."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        assert q.get_task(t.id) is t

    def test_get_task_unknown_returns_none(self) -> None:
        """get_task returns None for an unknown ID."""
        q = WorkQueue()
        assert q.get_task("nonexistent") is None

    def test_all_tasks_returns_copy(self) -> None:
        """all_tasks returns a copy, not the internal list."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        result = q.all_tasks()
        result.clear()
        assert len(q.all_tasks()) == 1

    def test_lock_attribute_is_asyncio_lock(self) -> None:
        """WorkQueue exposes an asyncio.Lock for callers that need atomicity."""
        q = WorkQueue()
        assert isinstance(q._lock, asyncio.Lock)

    def test_all_tasks_returns_deep_copies(self) -> None:
        """Mutating returned task objects does not affect the queue."""
        q = WorkQueue()
        t = _task(title="Original")
        q.add_task(t)

        returned = q.all_tasks()
        returned[0].title = "Mutated"
        returned[0].status = TaskStatus.DONE

        # The live queue should be unaffected.
        live = q.all_tasks()
        assert live[0].title == "Original"
        assert live[0].status == TaskStatus.PENDING

    def test_count_properties(self) -> None:
        """Count properties reflect current task statuses."""
        q = WorkQueue()
        q.add_tasks([_task(title="A"), _task(title="B"), _task(title="C")])
        tasks = q.all_tasks()

        q.set_active(tasks[0].id)
        q.set_done(tasks[1].id)

        assert q.pending_count == 1
        assert q.active_count == 1
        assert q.done_count == 1

    def test_clear(self) -> None:
        """clear removes all tasks."""
        q = WorkQueue()
        q.add_tasks([_task(), _task()])
        q.clear()
        assert q.all_tasks() == []

    def test_move_to_front(self) -> None:
        """move_to_front makes a task the first picked by next_ready."""
        q = WorkQueue()
        t1 = _task(title="First", id="t1")
        t2 = _task(title="Second", id="t2")
        t3 = _task(title="Third", id="t3")
        q.add_tasks([t1, t2, t3])

        q.move_to_front(t3.id)

        assert q.next_ready() is t3

    def test_move_to_front_with_non_pending_prefix(self) -> None:
        """move_to_front places the task after done/active tasks."""
        q = WorkQueue()
        t1 = _task(title="Done", id="t1")
        t2 = _task(title="Pending1", id="t2")
        t3 = _task(title="Pending2", id="t3")
        q.add_tasks([t1, t2, t3])
        q.set_done(t1.id)

        q.move_to_front(t3.id)

        # t3 should be the first pending (next_ready).
        assert q.next_ready() is t3

    def test_move_to_front_raises_for_non_pending(self) -> None:
        """Cannot move a non-pending task."""
        q = WorkQueue()
        t = _task()
        q.add_task(t)
        q.set_active(t.id)

        with pytest.raises(ValueError, match="active"):
            q.move_to_front(t.id)

    def test_move_to_front_fires_callback(self) -> None:
        """Callback fires when a task is reprioritised."""
        received: list[AgentTask] = []
        q = WorkQueue(on_task_changed=received.append)
        t1 = _task(title="First", id="t1")
        t2 = _task(title="Second", id="t2")
        q.add_tasks([t1, t2])
        received.clear()

        q.move_to_front(t2.id)

        assert len(received) == 1
        assert received[0] is t2


# -- Callbacks --------------------------------------------------------------


class TestWorkQueueCallbacks:
    """Tests for callback firing on task mutations."""

    def test_callback_on_add(self) -> None:
        """Callback fires when a task is added."""
        received: list[AgentTask] = []
        q = WorkQueue(on_task_changed=received.append)
        t = _task()
        q.add_task(t)
        assert received == [t]

    def test_callback_on_status_change(self) -> None:
        """Callback fires on status transitions."""
        received: list[AgentTask] = []
        q = WorkQueue(on_task_changed=received.append)
        t = _task()
        q.add_task(t)
        q.set_active(t.id)
        q.set_done(t.id, result="ok")
        # add + active + done = 3 callbacks.
        assert len(received) == 3

    def test_no_callback_when_none(self) -> None:
        """No error when callback is None."""
        q = WorkQueue(on_task_changed=None)
        t = _task()
        q.add_task(t)
        q.set_done(t.id)


# -- SQLite persistence round-trip ------------------------------------------


class TestWorkQueuePersistence:
    """Tests for saving and loading tasks via SessionStore."""

    def test_save_and_load_tasks(self, store: SessionStore) -> None:
        """Tasks survive a save/load round-trip."""
        t1 = _task(title="Research workload", category=TaskCategory.RESEARCH)
        t2 = _task(title="Write charm", category=TaskCategory.BUILD, description="Build it")
        store.save_tasks([t1, t2])

        loaded = store.load_tasks()
        assert len(loaded) == 2
        assert loaded[0].title == "Research workload"
        assert loaded[0].category == TaskCategory.RESEARCH
        assert loaded[1].title == "Write charm"
        assert loaded[1].description == "Build it"

    def test_save_replaces_tasks(self, store: SessionStore) -> None:
        """Saving twice replaces rather than duplicating."""
        store.save_tasks([_task(title="First")])
        store.save_tasks([_task(title="Second")])

        loaded = store.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].title == "Second"

    def test_load_empty_returns_empty_list(self, store: SessionStore) -> None:
        """Loading from an empty table returns an empty list."""
        assert store.load_tasks() == []

    def test_dependencies_round_trip(self, store: SessionStore) -> None:
        """Dependency lists survive JSON serialisation."""
        t = _task(title="Deploy", dependencies=["task-a", "task-b"])
        store.save_tasks([t])

        loaded = store.load_tasks()
        assert loaded[0].dependencies == ["task-a", "task-b"]

    def test_model_hint_round_trip(self, store: SessionStore) -> None:
        """Model hint survives a save/load round-trip."""
        t = _task(title="Research")
        t.model_hint = ModelHint.PRIMARY
        store.save_tasks([t])

        loaded = store.load_tasks()
        assert loaded[0].model_hint == ModelHint.PRIMARY

    def test_model_hint_none_round_trip(self, store: SessionStore) -> None:
        """None model hint survives a save/load round-trip."""
        t = _task(title="Build")
        store.save_tasks([t])

        loaded = store.load_tasks()
        assert loaded[0].model_hint is None
