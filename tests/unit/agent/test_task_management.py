"""Tests for the manage_tasks tool."""

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.tools.task_management import ManageTasksTool


def _make_queue(*tasks: AgentTask) -> WorkQueue:
    """Build a WorkQueue pre-loaded with the given tasks."""
    queue = WorkQueue()
    for task in tasks:
        queue.add_task(task)
    return queue


def _make_task(
    title: str = "Test task",
    category: TaskCategory = TaskCategory.BUILD,
    status: TaskStatus = TaskStatus.PENDING,
    task_id: str = "",
    result: str | None = None,
    description: str = "",
) -> AgentTask:
    """Create a minimal AgentTask for testing."""
    task = AgentTask(id=task_id, title=title, category=category, description=description)
    task.status = status
    task.result = result
    return task


# ===================================================================
# TestListAction
# ===================================================================


class TestListAction:
    """Tests for the 'list' action."""

    @pytest.mark.asyncio
    async def test_list_empty_queue(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="list")
        assert result.success
        assert "No tasks" in result.output

    @pytest.mark.asyncio
    async def test_list_shows_all_tasks(self) -> None:
        queue = _make_queue(
            _make_task("Research Redis", task_id="r1"),
            _make_task("Build charm", task_id="b1"),
        )
        tool = ManageTasksTool(queue=queue)
        result = await tool.execute(action="list")

        assert result.success
        assert "Research Redis" in result.output
        assert "Build charm" in result.output
        assert "r1" in result.output
        assert "b1" in result.output

    @pytest.mark.asyncio
    async def test_list_shows_blocked_reason(self) -> None:
        task = _make_task("Stuck", task_id="s1")
        queue = _make_queue(task)
        queue.set_blocked("s1", "Goal budget exceeded")
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="list")

        assert result.success
        assert "blocked: Goal budget exceeded" in result.output

    @pytest.mark.asyncio
    async def test_list_shows_status_counts(self) -> None:
        queue = _make_queue(
            _make_task("Done", status=TaskStatus.DONE),
            _make_task("Pending", status=TaskStatus.PENDING),
        )
        tool = ManageTasksTool(queue=queue)
        result = await tool.execute(action="list")

        assert "Summary:" in result.output


# ===================================================================
# TestCancelAction
# ===================================================================


class TestCancelAction:
    """Tests for the 'cancel' action."""

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self) -> None:
        task = _make_task("Build charm", task_id="b1")
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="cancel", task_id="b1")

        assert result.success
        assert "Cancelled" in result.output
        assert queue.get_task("b1") is None

    @pytest.mark.asyncio
    async def test_cancel_blocked_task(self) -> None:
        task = _make_task("Confirm", task_id="c1", status=TaskStatus.BLOCKED)
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="cancel", task_id="c1")

        assert result.success

    @pytest.mark.asyncio
    async def test_cancel_active_task_fails(self) -> None:
        task = _make_task("Building", task_id="b1", status=TaskStatus.ACTIVE)
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="cancel", task_id="b1")

        assert not result.success
        assert result.error is not None and "active" in result.error

    @pytest.mark.asyncio
    async def test_cancel_done_task_fails(self) -> None:
        task = _make_task("Done", task_id="d1", status=TaskStatus.DONE)
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="cancel", task_id="d1")

        assert not result.success

    @pytest.mark.asyncio
    async def test_cancel_missing_task_fails(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="cancel", task_id="nope")

        assert not result.success
        assert result.error is not None and "not found" in result.error

    @pytest.mark.asyncio
    async def test_cancel_requires_task_id(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="cancel")

        assert not result.success
        assert result.error is not None and "required" in result.error


# ===================================================================
# TestReprioritiseAction
# ===================================================================


class TestReprioritiseAction:
    """Tests for the 'reprioritise' action."""

    @pytest.mark.asyncio
    async def test_reprioritise_moves_to_front(self) -> None:
        t1 = _make_task("First", task_id="t1")
        t2 = _make_task("Second", task_id="t2")
        t3 = _make_task("Third", task_id="t3")
        queue = _make_queue(t1, t2, t3)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="reprioritise", task_id="t3")

        assert result.success
        # t3 should now be the first pending task.
        first_pending = queue.next_ready()
        assert first_pending is not None
        assert first_pending.id == "t3"

    @pytest.mark.asyncio
    async def test_reprioritise_active_task_fails(self) -> None:
        task = _make_task("Active", task_id="a1", status=TaskStatus.ACTIVE)
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="reprioritise", task_id="a1")

        assert not result.success

    @pytest.mark.asyncio
    async def test_reprioritise_requires_task_id(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="reprioritise")

        assert not result.success
        assert result.error is not None and "required" in result.error

    @pytest.mark.asyncio
    async def test_reprioritise_missing_task_fails(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="reprioritise", task_id="ghost")
        assert not result.success
        assert result.error is not None and "not found" in result.error


# ===================================================================
# TestApproveAction
# ===================================================================


class TestApproveAction:
    """Tests for the 'approve' action — pending or blocked CONFIRM tasks."""

    @pytest.mark.asyncio
    async def test_approve_blocked_task_marks_done(self) -> None:
        task = _make_task("Confirm plan", task_id="c1", category=TaskCategory.CONFIRM)
        queue = _make_queue(task)
        queue.set_blocked("c1", "Waiting for user confirmation")
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="approve", task_id="c1")

        assert result.success
        assert "Approved" in result.output
        assert queue.get_task("c1").status is TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_approve_pending_task_marks_done(self) -> None:
        task = _make_task("Confirm plan", task_id="c2", category=TaskCategory.CONFIRM)
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="approve", task_id="c2")

        assert result.success
        assert queue.get_task("c2").status is TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_approve_active_task_fails(self) -> None:
        task = _make_task("Working", task_id="a1", status=TaskStatus.ACTIVE)
        tool = ManageTasksTool(queue=_make_queue(task))
        result = await tool.execute(action="approve", task_id="a1")
        assert not result.success
        assert result.error is not None and "Cannot approve" in result.error

    @pytest.mark.asyncio
    async def test_approve_missing_task_fails(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="approve", task_id="ghost")
        assert not result.success
        assert result.error is not None and "not found" in result.error

    @pytest.mark.asyncio
    async def test_approve_requires_task_id(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="approve")
        assert not result.success
        assert result.error is not None and "required" in result.error


# ===================================================================
# TestDetailAction
# ===================================================================


class TestDetailAction:
    """Tests for the 'detail' action."""

    @pytest.mark.asyncio
    async def test_detail_shows_task_info(self) -> None:
        task = _make_task(
            "Build charm",
            task_id="b1",
            category=TaskCategory.BUILD,
            description="Scaffold the charm",
            result="Charm built successfully",
            status=TaskStatus.DONE,
        )
        queue = _make_queue(task)
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="detail", task_id="b1")

        assert result.success
        assert "Build charm" in result.output
        assert "build" in result.output
        assert "done" in result.output
        assert "Scaffold the charm" in result.output
        assert "Charm built successfully" in result.output

    @pytest.mark.asyncio
    async def test_detail_shows_dependencies_and_blocked_reason(self) -> None:
        task = AgentTask(
            id="d1",
            title="Dependent task",
            category=TaskCategory.BUILD,
            dependencies=["upstream-a", "upstream-b"],
        )
        queue = _make_queue(task)
        queue.set_blocked("d1", "Upstream not done")
        tool = ManageTasksTool(queue=queue)

        result = await tool.execute(action="detail", task_id="d1")

        assert result.success
        assert "Dependencies: upstream-a, upstream-b" in result.output
        assert "Blocked: Upstream not done" in result.output

    @pytest.mark.asyncio
    async def test_detail_missing_task(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="detail", task_id="nope")

        assert not result.success

    @pytest.mark.asyncio
    async def test_detail_requires_task_id(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="detail")

        assert not result.success


# ===================================================================
# TestUnknownAction
# ===================================================================


class TestUnknownAction:
    """Tests for unknown actions."""

    @pytest.mark.asyncio
    async def test_unknown_action_fails(self) -> None:
        tool = ManageTasksTool(queue=WorkQueue())
        result = await tool.execute(action="explode")

        assert not result.success
        assert result.error is not None and "Unknown action" in result.error
