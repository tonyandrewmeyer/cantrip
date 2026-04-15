"""Integration tests: Plan -> Execute -> Complete.

Exercises the full autonomous work loop: TaskPlanner produces tasks,
BackgroundExecutor picks them up via subagents, and results are
recorded on the work queue (and optionally persisted).
"""

import asyncio
from pathlib import Path

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.planner import PlanningContext, TaskPlanner
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import (
    RESEARCH_PLAN_JSON,
    MultiRoleProvider,
    make_stub_tool,
    wait_for_queue_state,
)


@pytest.mark.integration
class TestPlanAndExecute:
    """Plan tasks via TaskPlanner, then run them through BackgroundExecutor."""

    @pytest.mark.asyncio
    async def test_research_plan_executes_to_completion(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """Planner produces research tasks; executor runs them to DONE.

        The CONFIRM task should be blocked (not executed by a subagent).
        """
        provider = MultiRoleProvider(
            planner_responses=[Response(content=RESEARCH_PLAN_JSON)],
            subagent_responses=[
                Response(content="Source analysis complete."),
                Response(content="Web research complete."),
                Response(content="Design proposal synthesised."),
            ],
        )
        tools = [make_stub_tool("read_file"), make_stub_tool("web_fetch")]
        queue = WorkQueue()
        state = AgentState(charm_name="test-charm")

        # Plan.
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build a charm for redis")
        tasks = await planner.plan(context)
        queue.add_tasks(tasks)

        assert len(tasks) == 4
        assert queue.pending_count == 4

        # Execute.
        executor = BackgroundExecutor(
            queue=queue,
            tools=tools,
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=3)
            # Give the executor one more poll cycle to pick up and block the
            # confirm task (it becomes ready after operational-discovery is done).
            await asyncio.sleep(0.2)
        finally:
            await executor.stop()

        # Three research tasks should be done.
        done_tasks = [t for t in queue.all_tasks() if t.status == TaskStatus.DONE]
        assert len(done_tasks) == 3

        # The confirm task should be blocked (handled by conversation loop).
        confirm = queue.get_task("confirm-design")
        assert confirm is not None
        assert confirm.status == TaskStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_dependency_chain_respected(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """Three chained tasks (A -> B -> C) execute in order."""
        execution_order: list[str] = []

        class OrderTrackingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,  # noqa: ARG002
                temperature=0.7,  # noqa: ARG002
                max_tokens=None,  # noqa: ARG002
            ):
                # Extract the task title from the system prompt to track order.
                for msg in messages:
                    if msg.role.value == "system":
                        for line in msg.content.split("\n"):
                            if "**Title:**" in line:
                                title = line.split("**Title:**")[1].strip()
                                execution_order.append(title)
                                break
                        break
                return Response(content="Done.")

        provider = OrderTrackingProvider()
        queue = WorkQueue()
        state = AgentState()

        task_a = AgentTask(id="a", title="Task A", category=TaskCategory.BUILD)
        task_b = AgentTask(id="b", title="Task B", category=TaskCategory.BUILD, dependencies=["a"])
        task_c = AgentTask(id="c", title="Task C", category=TaskCategory.BUILD, dependencies=["b"])
        queue.add_tasks([task_a, task_b, task_c])

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=3)
        finally:
            await executor.stop()

        assert execution_order == ["Task A", "Task B", "Task C"]

    @pytest.mark.asyncio
    async def test_parallel_independent_tasks_both_complete(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """Two tasks with no dependencies both reach DONE."""
        provider = FakeProvider(
            responses=[
                Response(content="Task 1 done."),
                Response(content="Task 2 done."),
            ]
        )
        queue = WorkQueue()
        state = AgentState()

        task_1 = AgentTask(id="t1", title="Task 1", category=TaskCategory.RESEARCH)
        task_2 = AgentTask(id="t2", title="Task 2", category=TaskCategory.RESEARCH)
        queue.add_tasks([task_1, task_2])

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=2)
        finally:
            await executor.stop()

        assert all(t.status == TaskStatus.DONE for t in queue.all_tasks())

    @pytest.mark.asyncio
    async def test_failed_task_does_not_block_independent_tasks(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """Task A fails; independent Task B still completes."""

        class FailFirstProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,  # noqa: ARG002
                temperature=0.7,  # noqa: ARG002
                max_tokens=None,  # noqa: ARG002
            ):
                self._call_count += 1
                for msg in messages:
                    if msg.role.value == "system" and "Fail me" in msg.content:
                        raise RuntimeError("Deliberate failure")
                return Response(content="Success.")

        provider = FailFirstProvider()
        queue = WorkQueue()
        state = AgentState()

        task_a = AgentTask(id="fail", title="Fail me", category=TaskCategory.BUILD)
        task_b = AgentTask(id="pass", title="Pass me", category=TaskCategory.BUILD)
        queue.add_tasks([task_a, task_b])

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1, failed_count=1)
        finally:
            await executor.stop()

        assert queue.get_task("fail").status == TaskStatus.FAILED
        assert queue.get_task("pass").status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_task_results_persisted_to_store(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """Completed tasks are persisted via SessionStore."""
        provider = FakeProvider(responses=[Response(content="Research done.")])
        queue = WorkQueue()
        state = AgentState()
        store = SessionStore(tmp_path / ".cantrip")

        task = AgentTask(id="persist-me", title="Persist me", category=TaskCategory.RESEARCH)
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
            store=store,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1)
        finally:
            await executor.stop()

        # Verify persistence.
        loaded = store.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].id == "persist-me"
        assert loaded[0].status == TaskStatus.DONE
        assert loaded[0].result == "Research done."
