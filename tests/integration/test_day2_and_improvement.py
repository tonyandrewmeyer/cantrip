"""Integration tests: Day-2 and improvement confirmation flows.

Exercises the day-2 operations pipeline and the improvement (audit-based)
pipeline through CantripAgent, verifying task generation and executor
pickup.
"""

import json
import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import (
    MultiRoleProvider,
    wait_for_queue_state,
)

# -- Canned planner outputs ---------------------------------------------------

# ``complete_structured`` validates planner replies against the
# ``PLANNER_BRIEFING`` schema (Phase 73.3) — a top-level
# ``{"tasks": [...]}`` object, not a bare array.
DAY2_IMPL_PLAN_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "add-backup-action",
                "title": "Add backup action",
                "category": "build",
                "description": "Implement backup action for the charm.",
                "dependencies": [],
            },
            {
                "id": "add-ha-support",
                "title": "Add high-availability support",
                "category": "build",
                "description": "Implement HA with sentinel-based failover.",
                "dependencies": ["add-backup-action"],
            },
        ]
    }
)

DAY2_SYNTHESIS_RESULT = """\
# Day-2 Operations Plan for redis-k8s

## Backup and restore
- Add backup action using RDB snapshots
- Add restore action from snapshot

## High availability
- Implement Redis Sentinel for automatic failover
- Add peer relation for leader election
"""


@pytest.mark.integration
class TestDay2Confirmation:
    """Test the day-2 operations confirmation flow."""

    @pytest.mark.asyncio
    async def test_day2_confirmation_creates_impl_tasks(self, tmp_path: pathlib.Path):
        """Day-2 synthesis DONE + confirm BLOCKED -> implementation tasks added."""
        provider = FakeProvider(
            responses=[Response(content=DAY2_IMPL_PLAN_JSON)],
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        # Simulate completed day-2 research chain.
        research = AgentTask(
            id="day2-research",
            title="Research day-2 operations",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result="Research findings here.",
        )
        synthesis = AgentTask(
            id="day2-synthesis",
            title="Synthesise day-2 plan",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=DAY2_SYNTHESIS_RESULT,
        )
        confirm = AgentTask(
            id="confirm-day2",
            title="Confirm day-2 operations",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["day2-synthesis"],
        )
        agent.work_queue.add_tasks([research, synthesis, confirm])

        impl_tasks = await agent.handle_day2_confirmation("confirm-day2")

        assert len(impl_tasks) == 2
        titles = [t.title for t in impl_tasks]
        assert "Add backup action" in titles
        assert "Add high-availability support" in titles

    @pytest.mark.asyncio
    async def test_day2_confirmation_missing_synthesis(self, tmp_path: pathlib.Path):
        """Confirm task with no synthesis result returns empty list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        synthesis = AgentTask(
            id="day2-synthesis",
            title="Synthesise day-2 plan",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=None,
        )
        confirm = AgentTask(
            id="confirm-day2",
            title="Confirm day-2 operations",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["day2-synthesis"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        impl_tasks = await agent.handle_day2_confirmation("confirm-day2")
        assert impl_tasks == []

    @pytest.mark.asyncio
    async def test_day2_confirmation_missing_task_id(self, tmp_path: pathlib.Path):
        """Nonexistent confirm task ID returns empty list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        impl_tasks = await agent.handle_day2_confirmation("nonexistent")
        assert impl_tasks == []

    @pytest.mark.asyncio
    async def test_day2_confirmation_with_overrides(self, tmp_path: pathlib.Path):
        """Overrides string is passed through to the planner."""
        received_messages: list[str] = []

        class CapturingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
                response_schema=None,  # noqa: ARG002
            ):
                for msg in messages:
                    if msg.role.value == "user":
                        received_messages.append(msg.content)
                return Response(content=DAY2_IMPL_PLAN_JSON)

        provider = CapturingProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        synthesis = AgentTask(
            id="day2-synthesis",
            title="Synthesise day-2 plan",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=DAY2_SYNTHESIS_RESULT,
        )
        confirm = AgentTask(
            id="confirm-day2",
            title="Confirm day-2 operations",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["day2-synthesis"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        await agent.handle_day2_confirmation(
            "confirm-day2", overrides="Skip HA, focus on backup only"
        )

        assert any("Skip HA" in msg for msg in received_messages)

    @pytest.mark.asyncio
    async def test_day2_then_executor(self, tmp_path: pathlib.Path, fast_executor):  # noqa: ARG002
        """Day-2 impl tasks are picked up and completed by the executor."""
        provider = MultiRoleProvider(
            planner_responses=[Response(content=DAY2_IMPL_PLAN_JSON)],
            subagent_responses=[
                Response(content="Backup action added."),
                Response(content="HA support added."),
            ],
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        synthesis = AgentTask(
            id="day2-synthesis",
            title="Synthesise day-2 plan",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=DAY2_SYNTHESIS_RESULT,
        )
        confirm = AgentTask(
            id="confirm-day2",
            title="Confirm day-2 operations",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["day2-synthesis"],
        )
        agent.work_queue.add_tasks([synthesis, confirm])

        impl_tasks = await agent.handle_day2_confirmation("confirm-day2")
        assert len(impl_tasks) == 2

        executor = BackgroundExecutor(
            queue=agent.work_queue,
            tools=[],
            provider=provider,
            state=agent.state,
        )
        executor.start()
        try:
            # synthesis (DONE) + 2 impl tasks.
            await wait_for_queue_state(agent.work_queue, done_count=3)
        finally:
            await executor.stop()

        build_statuses = [
            t.status for t in agent.work_queue.all_tasks() if t.category == TaskCategory.BUILD
        ]
        assert all(s == TaskStatus.DONE for s in build_statuses)


@pytest.mark.integration
class TestImprovementConfirmation:
    """Test the improvement (audit-based) confirmation flow."""

    @pytest.mark.asyncio
    async def test_improvement_creates_fix_tasks(self, tmp_path: pathlib.Path):
        """Audit report with gaps triggers fix task generation."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        # An audit that flags tracing and unit tests as missing.
        audit_text = (
            "## Audit Results\n\n"
            "- Tracing is missing from the charm.\n"
            "- No unit tests found. Unit test coverage is missing.\n"
            "- All other checks passed.\n"
        )

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit the charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=audit_text,
        )
        confirm = AgentTask(
            id="confirm-improvements",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")

        assert len(fix_tasks) > 0
        ids = [t.id for t in fix_tasks]
        assert any(i.startswith("fill-observability-") for i in ids)
        assert any(i.startswith("fill-tests-") for i in ids)

    @pytest.mark.asyncio
    async def test_improvement_stores_audit_report(self, tmp_path: pathlib.Path):
        """After confirmation, the audit report is stored on agent state."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        audit_text = "No tracing. Tracing is missing."
        audit_task = AgentTask(
            id="audit-charm",
            title="Audit the charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=audit_text,
        )
        confirm = AgentTask(
            id="confirm-improvements",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm])

        await agent.handle_improvement_confirmation("confirm-improvements")

        assert agent.state.audit_report == audit_text

    @pytest.mark.asyncio
    async def test_improvement_missing_audit(self, tmp_path: pathlib.Path):
        """No audit result returns empty list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit the charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=None,
        )
        confirm = AgentTask(
            id="confirm-improvements",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")
        assert fix_tasks == []

    @pytest.mark.asyncio
    async def test_clean_audit_produces_no_fixes(self, tmp_path: pathlib.Path):
        """A clean audit report (no gaps) produces no fix tasks."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        audit_text = "All checks passed. The charm is well structured."
        audit_task = AgentTask(
            id="audit-charm",
            title="Audit the charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            result=audit_text,
        )
        confirm = AgentTask(
            id="confirm-improvements",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")
        assert fix_tasks == []


@pytest.mark.integration
class TestBuildResumeSummary:
    """Test the session resume summary generation."""

    @pytest.mark.asyncio
    async def test_empty_state_returns_none(self, tmp_path: pathlib.Path):
        """An empty state produces no summary."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        summary = agent.build_resume_summary()
        assert summary is None

    @pytest.mark.asyncio
    async def test_summary_includes_charm_name(self, tmp_path: pathlib.Path):
        """Summary mentions the charm name."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"
        agent.state.charm_type = "kubernetes"

        summary = agent.build_resume_summary()

        assert summary is not None
        assert "redis-k8s" in summary
        assert "kubernetes" in summary

    @pytest.mark.asyncio
    async def test_summary_includes_decisions(self, tmp_path: pathlib.Path):
        """Summary lists recorded decisions."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"
        agent.state.add_decision("substrate", "Kubernetes")
        agent.state.add_decision("charm_path", "Custom")

        summary = agent.build_resume_summary()

        assert "substrate" in summary
        assert "Kubernetes" in summary
        assert "charm_path" in summary

    @pytest.mark.asyncio
    async def test_summary_includes_task_progress(self, tmp_path: pathlib.Path):
        """Summary reports task completion counts."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        agent.work_queue.add_tasks(
            [
                AgentTask(
                    id="t1",
                    title="Research workload",
                    category=TaskCategory.RESEARCH,
                    status=TaskStatus.DONE,
                ),
                AgentTask(
                    id="t2",
                    title="Write charm code",
                    category=TaskCategory.BUILD,
                    status=TaskStatus.PENDING,
                ),
            ]
        )

        summary = agent.build_resume_summary()

        assert "1 done" in summary
        assert "1 pending" in summary
        assert "Research workload" in summary

    @pytest.mark.asyncio
    async def test_summary_includes_framework(self, tmp_path: pathlib.Path):
        """Summary mentions the framework when set."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "myapp"
        agent.state.framework = "Flask"

        summary = agent.build_resume_summary()

        assert "Flask" in summary

    @pytest.mark.asyncio
    async def test_summary_includes_models(self, tmp_path: pathlib.Path):
        """Summary mentions dev and cos models."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "myapp"
        agent.state.dev_model = "dev-model"
        agent.state.cos_model = "cos-model"

        summary = agent.build_resume_summary()

        assert "dev-model" in summary
        assert "cos-model" in summary

    @pytest.mark.asyncio
    async def test_summary_injected_into_messages(self, tmp_path: pathlib.Path):
        """build_resume_summary appends the summary as a SYSTEM message.

        Phase 31.11 switched from USER to SYSTEM to avoid breaking the
        alternating user/assistant pattern that some providers require.
        """
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "redis-k8s"

        initial_count = len(agent.state.messages)
        agent.build_resume_summary()

        assert len(agent.state.messages) == initial_count + 1
        assert agent.state.messages[-1].role.value == "system"
        assert "Session resumed" in agent.state.messages[-1].content
