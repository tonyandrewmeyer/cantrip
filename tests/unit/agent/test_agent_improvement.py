"""Tests for ``CantripAgent.handle_improvement_confirmation`` (audit → fix tasks)."""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from tests.conftest import FakeProvider


class TestHandleImprovementConfirmation:
    """Tests for CantripAgent.handle_improvement_confirmation."""

    @pytest.mark.asyncio
    async def test_generates_fix_tasks_from_audit(self, tmp_path: pathlib.Path) -> None:
        """Fix tasks are generated from an audit result with gaps."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.mode = "improve"
        agent.state.charm_name = "test-charm"

        # Simulate the audit → confirm flow.
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit existing charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
        )
        audit_task.result = (
            "## Must-fix\n- Missing tracing relation\n- No unit tests found\n- Missing README.md\n"
        )
        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm improvement plan",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.DONE,
            dependencies=["audit-charm"],
        )

        agent.work_queue.add_tasks([audit_task, confirm_task])
        agent.work_queue.set_done("audit-charm", audit_task.result)

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")

        assert len(fix_tasks) > 0
        task_ids = [t.id for t in fix_tasks]
        assert any(tid.startswith("fill-observability-") for tid in task_ids)
        assert any(tid.startswith("fill-tests-") for tid in task_ids)

    @pytest.mark.asyncio
    async def test_no_tasks_when_confirm_not_found(self) -> None:
        """Returns empty list when the confirm task does not exist."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        fix_tasks = await agent.handle_improvement_confirmation("nonexistent")

        assert fix_tasks == []

    @pytest.mark.asyncio
    async def test_no_tasks_when_no_audit_result(self) -> None:
        """Returns empty list when no audit result is found."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        from cantrip.agent.queue import AgentTask, TaskCategory

        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm",
            category=TaskCategory.CONFIRM,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([confirm_task])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")

        assert fix_tasks == []

    @pytest.mark.asyncio
    async def test_stores_audit_report_on_state(self, tmp_path: pathlib.Path) -> None:
        """The audit report is saved to agent state."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.mode = "improve"

        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
        )
        audit_text = "## Audit\nMissing tracing. Uses deprecated StoredState."
        audit_task.result = audit_text

        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm",
            category=TaskCategory.CONFIRM,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm_task])
        agent.work_queue.set_done("audit-charm", audit_text)

        await agent.handle_improvement_confirmation("confirm-improvements")

        assert agent.state.audit_report == audit_text
