"""Integration tests: BUILD -> DEPLOY -> Verify -> DEBUG chain.

Exercises the automatic follow-up logic: a BUILD task completes,
triggering a DEPLOY follow-up, then verification, and on failure
a DEBUG task.
"""

from pathlib import Path

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import (
    CallbackProvider,
    wait_for_queue_state,
)


@pytest.mark.integration
class TestAutoDeployChain:
    """Test the build -> deploy -> verify -> debug follow-up chain."""

    @pytest.mark.asyncio
    async def test_build_triggers_deploy_followup(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A completed BUILD task auto-creates a DEPLOY follow-up."""
        provider = FakeProvider(
            responses=[
                Response(content="Build complete."),
                Response(content="Deploy complete."),
                Response(content="Verification complete."),
            ]
        )
        queue = WorkQueue()
        state = AgentState(dev_model="test-model")

        task = AgentTask(id="build-1", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            # Wait for build + deploy follow-up + verify follow-up.
            await wait_for_queue_state(queue, done_count=3)
        finally:
            await executor.stop()

        # Verify the chain: BUILD -> DEPLOY -> Verify.
        all_tasks = queue.all_tasks()
        categories = [t.category for t in all_tasks]
        assert TaskCategory.BUILD in categories
        assert TaskCategory.DEPLOY in categories

        # The deploy task should depend on the build task.
        deploy_tasks = [t for t in all_tasks if t.category == TaskCategory.DEPLOY]
        assert any("build-1" in t.dependencies for t in deploy_tasks)

    @pytest.mark.asyncio
    async def test_failed_verify_triggers_debug(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A failed verification task auto-creates a DEBUG follow-up.

        Note: the DEBUG task depends on the failed verify task.  Since
        ``next_ready()`` only resolves DONE dependencies, the debug task
        remains pending — but it IS created, which is what we verify.
        """

        def respond(messages, tools):  # noqa: ARG001
            # Find the task title in the system prompt.
            system_text = ""
            for msg in messages:
                if msg.role.value == "system":
                    system_text = msg.content
                    break
            if "Verify deployment:" in system_text:
                raise RuntimeError("Verification failed")
            return Response(content="Task done.")

        provider = CallbackProvider(respond)
        queue = WorkQueue()
        state = AgentState(dev_model="test-model")

        task = AgentTask(id="build-v", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            # BUILD succeeds -> DEPLOY succeeds -> Verify fails -> DEBUG created.
            await wait_for_queue_state(queue, done_count=2, failed_count=1)
        finally:
            await executor.stop()

        all_tasks = queue.all_tasks()
        debug_tasks = [t for t in all_tasks if t.category == TaskCategory.DEBUG]
        assert len(debug_tasks) >= 1
        assert any("Diagnose" in t.title for t in debug_tasks)
        # The debug task depends on the failed verify task.
        assert debug_tasks[0].status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_full_chain_build_deploy_verify_success(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """When all stages succeed, no DEBUG task is created."""
        provider = FakeProvider(
            responses=[
                Response(content="Build done."),
                Response(content="Deploy done."),
                Response(content="Verify passed."),
            ]
        )
        queue = WorkQueue()
        state = AgentState(dev_model="test-model")

        task = AgentTask(id="build-ok", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

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

        all_tasks = queue.all_tasks()
        debug_tasks = [t for t in all_tasks if t.category == TaskCategory.DEBUG]
        assert len(debug_tasks) == 0
        assert all(t.status == TaskStatus.DONE for t in all_tasks)

    @pytest.mark.asyncio
    async def test_no_followups_without_dev_model(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """When dev_model is None, no follow-up tasks are created after BUILD."""
        provider = FakeProvider(responses=[Response(content="Build done.")])
        queue = WorkQueue()
        state = AgentState(dev_model=None)

        task = AgentTask(id="build-no-dm", title="Build charm", category=TaskCategory.BUILD)
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=provider,
            state=state,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1)
        finally:
            await executor.stop()

        # Only the original BUILD task should exist — no follow-ups.
        assert len(queue.all_tasks()) == 1
        assert queue.all_tasks()[0].id == "build-no-dm"

    @pytest.mark.asyncio
    async def test_chain_persisted_to_store(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """The full chain is persisted to the SessionStore at each step."""
        provider = FakeProvider(
            responses=[
                Response(content="Build done."),
                Response(content="Deploy done."),
                Response(content="Verify done."),
            ]
        )
        queue = WorkQueue()
        state = AgentState(dev_model="test-model")
        store = SessionStore(tmp_path / ".cantrip")

        task = AgentTask(id="build-p", title="Build charm", category=TaskCategory.BUILD)
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
            await wait_for_queue_state(queue, done_count=3)
        finally:
            await executor.stop()

        loaded = store.load_tasks()
        assert len(loaded) == 3
        assert all(t.status == TaskStatus.DONE for t in loaded)

        # Verify categories are correct.
        categories = {t.category for t in loaded}
        assert TaskCategory.BUILD in categories
        assert TaskCategory.DEPLOY in categories
