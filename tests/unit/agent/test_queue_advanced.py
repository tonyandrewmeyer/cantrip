"""Advanced tests for WorkQueue: transitions, ordering, callbacks, and merge logic."""

import pytest

from cantrip.agent.planner import _merge_tasks
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue


class TestWorkQueueTransitions:
    """Test status transitions and state tracking."""

    def test_set_active(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active("t1")
        assert queue.get_task("t1").status == TaskStatus.ACTIVE

    def test_set_done_with_result(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_done("t1", result="All done")
        t = queue.get_task("t1")
        assert t.status == TaskStatus.DONE
        assert t.result == "All done"

    def test_set_failed_with_error(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_failed("t1", error="Boom")
        t = queue.get_task("t1")
        assert t.status == TaskStatus.FAILED
        assert t.result == "Boom"

    def test_set_blocked_with_reason(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_blocked("t1", reason="Needs user input")
        t = queue.get_task("t1")
        assert t.status == TaskStatus.BLOCKED
        assert t.blocked_reason == "Needs user input"

    def test_unblock(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_blocked("t1", reason="blocked")
        queue.unblock("t1")
        t = queue.get_task("t1")
        assert t.status == TaskStatus.PENDING
        assert t.blocked_reason is None

    def test_set_pending_resets_status(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active("t1")
        queue.set_pending("t1")
        assert queue.get_task("t1").status == TaskStatus.PENDING

    def test_cancel_removes_task(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Test", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.cancel("t1")
        assert queue.get_task("t1") is None
        assert len(queue.all_tasks()) == 0

    def test_get_or_raise_on_missing(self):
        queue = WorkQueue()
        with pytest.raises(KeyError):
            queue.set_active("nonexistent")

    def test_get_task_returns_none_for_missing(self):
        queue = WorkQueue()
        assert queue.get_task("nonexistent") is None


class TestWorkQueueOrdering:
    """Test task ordering and readiness."""

    def test_all_ready_returns_queue_order(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
                AgentTask(id="c", title="C", category=TaskCategory.BUILD),
            ]
        )
        ready = queue.all_ready()
        assert [t.id for t in ready] == ["a", "b", "c"]

    def test_all_ready_with_limit(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
            ]
        )
        ready = queue.all_ready(limit=1)
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_move_to_front(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
                AgentTask(id="c", title="C", category=TaskCategory.BUILD),
            ]
        )
        queue.move_to_front("c")
        ready = queue.all_ready()
        assert ready[0].id == "c"

    def test_move_to_front_non_pending_raises(self):
        queue = WorkQueue()
        task = AgentTask(id="t1", title="T", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active("t1")
        with pytest.raises(ValueError, match="Cannot reprioritise"):
            queue.move_to_front("t1")

    def test_next_ready_skips_active(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
            ]
        )
        queue.set_active("a")
        t = queue.next_ready()
        assert t.id == "b"

    def test_next_ready_returns_none_when_empty(self):
        queue = WorkQueue()
        assert queue.next_ready() is None

    def test_cancelled_dep_unblocks_downstream(self):
        """Cancelling a dependency unblocks tasks that depended on it."""
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD, dependencies=["a"]),
            ]
        )
        queue.cancel("a")
        # b's dependency is now missing from the queue → treated as satisfied.
        t = queue.next_ready()
        assert t.id == "b"


class TestWorkQueueCounts:
    """Test count properties."""

    def test_counts(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
                AgentTask(id="c", title="C", category=TaskCategory.BUILD),
            ]
        )
        queue.set_active("a")
        queue.set_done("b")

        assert queue.pending_count == 1
        assert queue.active_count == 1
        assert queue.done_count == 1

    def test_clear(self):
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="a", title="A", category=TaskCategory.BUILD),
                AgentTask(id="b", title="B", category=TaskCategory.BUILD),
            ]
        )
        queue.clear()
        assert len(queue.all_tasks()) == 0


class TestWorkQueueCallback:
    """Test mutation callbacks."""

    def test_callback_fired_on_add(self):
        events: list[str] = []
        queue = WorkQueue(on_task_changed=lambda t: events.append(t.id))
        queue.add_task(AgentTask(id="t1", title="T", category=TaskCategory.BUILD))
        assert "t1" in events

    def test_callback_fired_on_status_change(self):
        events: list[tuple[str, str]] = []
        queue = WorkQueue(
            on_task_changed=lambda t: events.append((t.id, t.status.value)),
        )
        queue.add_task(AgentTask(id="t1", title="T", category=TaskCategory.BUILD))
        queue.set_active("t1")
        queue.set_done("t1")
        assert ("t1", "active") in events
        assert ("t1", "done") in events


class TestAgentTaskPostInit:
    """Test AgentTask auto-ID generation."""

    def test_auto_id_generated(self):
        task = AgentTask(title="Test", category=TaskCategory.BUILD)
        assert task.id
        assert len(task.id) == 12

    def test_explicit_id_preserved(self):
        task = AgentTask(id="custom-id", title="Test", category=TaskCategory.BUILD)
        assert task.id == "custom-id"

    def test_noop_count_defaults_to_zero(self):
        task = AgentTask(title="Test", category=TaskCategory.BUILD)
        assert task.noop_count == 0

    def test_noop_count_increments(self):
        task = AgentTask(title="Test", category=TaskCategory.BUILD)
        task.noop_count += 1
        task.noop_count += 1
        assert task.noop_count == 2


class TestMergeTasks:
    """Tests for _merge_tasks replanning logic."""

    def test_empty_lists(self):
        assert _merge_tasks([], []) == []

    def test_new_tasks_appended(self):
        new = [AgentTask(id="a", title="A", category=TaskCategory.BUILD)]
        result = _merge_tasks([], new)
        assert len(result) == 1
        assert result[0].id == "a"

    def test_completed_tasks_preserved(self):
        existing = [
            AgentTask(id="a", title="A", category=TaskCategory.BUILD, status=TaskStatus.DONE),
        ]
        new = [AgentTask(id="b", title="B", category=TaskCategory.BUILD)]
        result = _merge_tasks(existing, new)
        assert len(result) == 2
        assert result[0].id == "a"  # Preserved first.
        assert result[1].id == "b"

    def test_active_tasks_preserved(self):
        existing = [
            AgentTask(id="a", title="A", category=TaskCategory.BUILD, status=TaskStatus.ACTIVE),
        ]
        new = [AgentTask(id="b", title="B", category=TaskCategory.BUILD)]
        result = _merge_tasks(existing, new)
        assert result[0].id == "a"

    def test_pending_tasks_dropped(self):
        existing = [
            AgentTask(id="a", title="A", category=TaskCategory.BUILD, status=TaskStatus.PENDING),
        ]
        new = [AgentTask(id="b", title="B", category=TaskCategory.BUILD)]
        result = _merge_tasks(existing, new)
        assert len(result) == 1
        assert result[0].id == "b"

    def test_colliding_id_preserved_task_wins(self):
        """If a new task has the same ID as a completed task, the completed one wins."""
        existing = [
            AgentTask(id="a", title="Old A", category=TaskCategory.BUILD, status=TaskStatus.DONE),
        ]
        new = [
            AgentTask(id="a", title="New A", category=TaskCategory.BUILD),
            AgentTask(id="b", title="B", category=TaskCategory.BUILD),
        ]
        result = _merge_tasks(existing, new)
        assert len(result) == 2
        assert result[0].title == "Old A"  # Preserved.
        assert result[1].id == "b"

    def test_blocked_and_failed_tasks_dropped(self):
        """Blocked and failed tasks are not preserved (only done/active)."""
        existing = [
            AgentTask(id="a", title="A", category=TaskCategory.BUILD, status=TaskStatus.BLOCKED),
            AgentTask(id="b", title="B", category=TaskCategory.BUILD, status=TaskStatus.FAILED),
        ]
        new = [AgentTask(id="c", title="C", category=TaskCategory.BUILD)]
        result = _merge_tasks(existing, new)
        assert len(result) == 1
        assert result[0].id == "c"

    def test_mixed_scenario(self):
        existing = [
            AgentTask(
                id="done1", title="Done", category=TaskCategory.RESEARCH, status=TaskStatus.DONE
            ),
            AgentTask(
                id="active1", title="Active", category=TaskCategory.BUILD, status=TaskStatus.ACTIVE
            ),
            AgentTask(
                id="pending1",
                title="Pending",
                category=TaskCategory.BUILD,
                status=TaskStatus.PENDING,
            ),
            AgentTask(
                id="failed1", title="Failed", category=TaskCategory.BUILD, status=TaskStatus.FAILED
            ),
        ]
        new = [
            AgentTask(id="new1", title="New 1", category=TaskCategory.BUILD),
            AgentTask(id="done1", title="Collision", category=TaskCategory.BUILD),
        ]
        result = _merge_tasks(existing, new)
        ids = [t.id for t in result]
        assert ids == ["done1", "active1", "new1"]
