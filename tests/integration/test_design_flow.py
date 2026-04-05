"""Integration tests: Design confirmation flow.

Exercises the design confirmation pipeline: synthesis completes,
the confirm task blocks for user approval, ``handle_design_confirmation()``
generates build tasks from the approved design, and the executor picks
them up.
"""

from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import (
    BUILD_PLAN_JSON,
    SAMPLE_DESIGN_MD,
    MultiRoleProvider,
    wait_for_queue_state,
)


@pytest.mark.integration
class TestDesignConfirmation:
    """Test the design confirmation and build task generation flow."""

    @pytest.mark.asyncio
    async def test_handle_design_confirmation_creates_build_tasks(self, tmp_path: Path):
        """Synthesis DONE + confirm BLOCKED -> build tasks added to queue."""
        # The provider is called for plan_from_design inside handle_design_confirmation.
        provider = FakeProvider(
            responses=[
                # Response for the planner's plan_from_design call.
                Response(content=BUILD_PLAN_JSON),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        # Pre-populate queue with synthesis (DONE) and confirm (BLOCKED).
        synthesis = AgentTask(
            id="operational-discovery",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=SAMPLE_DESIGN_MD,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["operational-discovery"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        build_tasks = await agent.handle_design_confirmation("confirm-design")

        assert len(build_tasks) == 3
        titles = [t.title for t in build_tasks]
        assert "Scaffold the charm project" in titles
        assert "Write charm code" in titles
        assert "Write unit tests" in titles

        # Tasks should be in the queue.
        all_tasks = agent.work_queue.all_tasks()
        assert len(all_tasks) == 8  # synthesis + confirm + 3 build + 3 day-2

    @pytest.mark.asyncio
    async def test_design_confirmation_with_overrides(self, tmp_path: Path):
        """Passing overrides string reaches the planner."""
        received_messages: list[str] = []

        class CapturingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,  # noqa: ARG002
                temperature=0.7,  # noqa: ARG002
            ):
                for msg in messages:
                    if msg.role.value == "user":
                        received_messages.append(msg.content)
                return Response(content=BUILD_PLAN_JSON)

        provider = CapturingProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        synthesis = AgentTask(
            id="op-disc",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=SAMPLE_DESIGN_MD,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["op-disc"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        await agent.handle_design_confirmation(
            "confirm-design", overrides="Use machine substrate instead of k8s"
        )

        # The user message to the planner should contain the override.
        assert any("Use machine substrate instead of k8s" in msg for msg in received_messages)

    @pytest.mark.asyncio
    async def test_design_confirmation_missing_synthesis(self, tmp_path: Path):
        """Confirm task with no synthesis result returns empty list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        # Synthesis exists but has no result.
        synthesis = AgentTask(
            id="op-disc",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=None,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["op-disc"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        build_tasks = await agent.handle_design_confirmation("confirm-design")

        assert build_tasks == []

    @pytest.mark.asyncio
    async def test_confirmation_then_executor_runs_builds(
        self,
        tmp_path: Path,
        fast_executor,  # noqa: ARG002
    ):
        """Full flow: confirm -> build tasks -> executor completes them."""
        provider = MultiRoleProvider(
            planner_responses=[Response(content=BUILD_PLAN_JSON)],
            subagent_responses=[
                Response(content="Scaffold done."),
                Response(content="Code written."),
                Response(content="Tests written."),
            ],
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        synthesis = AgentTask(
            id="operational-discovery",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=SAMPLE_DESIGN_MD,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["operational-discovery"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        # Confirm the design — generates build tasks.
        build_tasks = await agent.handle_design_confirmation("confirm-design")
        assert len(build_tasks) == 3

        # Start the executor to run the build tasks.
        executor = BackgroundExecutor(
            queue=agent.work_queue,
            tools=[],
            provider=provider,
            state=agent.state,
        )
        executor.start()
        try:
            await wait_for_queue_state(agent.work_queue, done_count=4)  # synthesis + 3 builds
        finally:
            await executor.stop()

        build_statuses = [
            t.status for t in agent.work_queue.all_tasks() if t.category == TaskCategory.BUILD
        ]
        assert all(s == TaskStatus.DONE for s in build_statuses)

    @pytest.mark.asyncio
    async def test_design_proposal_parsed_into_state(self, tmp_path: Path):
        """state.design_proposal is populated with parsed design fields."""
        provider = FakeProvider(responses=[Response(content=BUILD_PLAN_JSON)])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        synthesis = AgentTask(
            id="op-disc",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=SAMPLE_DESIGN_MD,
        )
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm design with user",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["op-disc"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        await agent.handle_design_confirmation("confirm-design")

        proposal = agent.state.design_proposal
        assert proposal is not None
        assert proposal.workload_name == "Redis"
        assert "k8s" in proposal.substrate.lower() or "kubernetes" in proposal.substrate.lower()
        assert proposal.charm_path  # Should be populated
        assert len(proposal.integrations) > 0

        # Decisions should be recorded.
        decision_types = [d.type for d in agent.state.decisions]
        assert "substrate" in decision_types
        assert "charm_path" in decision_types
