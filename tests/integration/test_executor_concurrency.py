"""Integration tests: Executor pause/resume and light model routing.

Exercises executor lifecycle (pause during ``process_message()``, resume
afterwards) and the light-vs-primary model routing for different task
categories.
"""

from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import wait_for_queue_state


@pytest.mark.integration
class TestExecutorPauseResume:
    """Test that the executor pauses during conversation and resumes after."""

    @pytest.mark.asyncio
    async def test_process_message_pauses_executor(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """During process_message(), the executor is paused."""
        paused_during_call = False

        class PauseCheckingProvider(FakeProvider):
            def __init__(self, agent_ref):
                super().__init__(responses=[Response(content="Reply.")])
                self._agent_ref = agent_ref

            async def complete(
                self,
                messages,  # noqa: ARG002
                tools=None,  # noqa: ARG002
                temperature=0.7,  # noqa: ARG002
                max_tokens=None,  # noqa: ARG002
            ):
                nonlocal paused_during_call
                # Check if executor is paused when the LLM is called.
                if self._agent_ref._executor:
                    paused_during_call = self._agent_ref._executor.paused
                return Response(content="Reply.")

        # Create agent, then set its provider to the pause-checking one.
        provider = FakeProvider(responses=[Response(content="Reply.")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        checking_provider = PauseCheckingProvider(agent)
        agent.provider = checking_provider

        # Start executor with a pending task.
        task = AgentTask(id="bg-task", title="Background work", category=TaskCategory.RESEARCH)
        agent.work_queue.add_task(task)
        agent.start_executor()

        # Process a message — should pause the executor.
        await agent.process_message("Hello")

        assert paused_during_call is True

        await agent.stop_executor()

    @pytest.mark.asyncio
    async def test_executor_resumes_after_conversation(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """After process_message() completes, pending tasks get picked up."""
        provider = FakeProvider(
            responses=[
                # First call: conversation reply.
                Response(content="I see."),
                # Second call: subagent for the background task.
                Response(content="Background task done."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        task = AgentTask(id="resume-task", title="Resume me", category=TaskCategory.RESEARCH)
        agent.work_queue.add_task(task)
        agent.start_executor()

        # Process a message (pauses executor, then resumes).
        await agent.process_message("Hello")

        # After process_message, the executor should resume and pick up the task.
        try:
            await wait_for_queue_state(agent.work_queue, done_count=1)
        finally:
            await agent.stop_executor()

        assert agent.work_queue.get_task("resume-task").status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_executor_started_via_agent(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """CantripAgent.start_executor() creates and starts the executor."""
        provider = FakeProvider(responses=[Response(content="Done.")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        assert not agent.executor_running

        task = AgentTask(id="start-test", title="Test start", category=TaskCategory.RESEARCH)
        agent.work_queue.add_task(task)
        agent.start_executor()

        assert agent.executor_running

        try:
            await wait_for_queue_state(agent.work_queue, done_count=1)
        finally:
            await agent.stop_executor()

        assert not agent.executor_running
        assert agent.work_queue.get_task("start-test").status == TaskStatus.DONE


@pytest.mark.integration
class TestLightModelRouting:
    """Test that task categories route to the correct provider."""

    @pytest.mark.asyncio
    async def test_research_task_uses_light_provider(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """RESEARCH tasks are routed to the light provider."""
        primary = FakeProvider(responses=[Response(content="primary response")])
        light = FakeProvider(responses=[Response(content="light response")])

        queue = WorkQueue()
        state = AgentState()

        task = AgentTask(
            id="research-light",
            title="Web research",
            category=TaskCategory.RESEARCH,
        )
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=primary,
            state=state,
            light_provider=light,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1)
        finally:
            await executor.stop()

        # Light provider should have been called, not primary.
        assert light._call_count == 1
        assert primary._call_count == 0
        assert queue.get_task("research-light").result == "light response"

    @pytest.mark.asyncio
    async def test_build_task_uses_primary_provider(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """BUILD tasks are routed to the primary provider."""
        primary = FakeProvider(responses=[Response(content="primary built")])
        light = FakeProvider(responses=[Response(content="light built")])

        queue = WorkQueue()
        state = AgentState()

        task = AgentTask(
            id="build-primary",
            title="Write charm code",
            category=TaskCategory.BUILD,
        )
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=primary,
            state=state,
            light_provider=light,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1)
        finally:
            await executor.stop()

        assert primary._call_count == 1
        assert light._call_count == 0
        assert queue.get_task("build-primary").result == "primary built"

    @pytest.mark.asyncio
    async def test_operational_discovery_uses_primary(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """RESEARCH tasks with 'operational-discovery' use the primary provider."""
        primary = FakeProvider(responses=[Response(content="synthesis done")])
        light = FakeProvider(responses=[Response(content="light synthesis")])

        queue = WorkQueue()
        state = AgentState()

        task = AgentTask(
            id="op-disc",
            title="operational-discovery: synthesise design",
            category=TaskCategory.RESEARCH,
        )
        queue.add_task(task)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[],
            provider=primary,
            state=state,
            light_provider=light,
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1)
        finally:
            await executor.stop()

        # Operational-discovery is special: uses primary despite being RESEARCH.
        assert primary._call_count == 1
        assert light._call_count == 0
        assert queue.get_task("op-disc").result == "synthesis done"
