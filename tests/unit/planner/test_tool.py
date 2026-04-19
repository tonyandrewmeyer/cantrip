"""Planner tests: tool."""

import json
from pathlib import Path

import pytest

from cantrip.agent.queue import WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools.planning import PlanTasksTool
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ===================================================================
# TestPlanTasksTool
# ===================================================================


class TestPlanTasksTool:
    """Tests for the PlanTasksTool conversation wrapper."""

    @pytest.mark.asyncio
    async def test_populates_work_queue(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert result.success
        # 4 deterministic tasks: web-research, charmhub-survey, operational-discovery, confirm.
        assert queue.pending_count == 4
        assert result.data["task_count"] == 4

    @pytest.mark.asyncio
    async def test_returns_formatted_summary(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert "Task plan" in result.output
        assert "research" in result.output.lower()
        assert "Shall I proceed" in result.output

    @pytest.mark.asyncio
    async def test_rejects_empty_intent(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="")

        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rejects_whitespace_intent(self) -> None:
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="   ")

        assert not result.success

    @pytest.mark.asyncio
    async def test_fresh_plan_always_succeeds(self) -> None:
        """Deterministic planning cannot fail (no LLM parsing involved)."""
        provider = FakeProvider()
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build something")

        assert result.success
        assert queue.pending_count > 0

    @pytest.mark.asyncio
    async def test_uses_state_context(self) -> None:
        provider = FakeProvider()
        state = AgentState(
            charm_name="my-charm",
            charm_type="k8s",
            framework="flask",
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build the charm")

        assert result.success
        # Charm name from state should appear in task titles.
        assert any("my-charm" in t.title for t in queue.all_tasks())

    @pytest.mark.asyncio
    async def test_improve_mode_routes_to_improvement(self) -> None:
        """When state.mode is 'improve', PlanTasksTool generates improvement tasks."""
        provider = FakeProvider()
        state = AgentState(
            mode="improve",
            charm_name="my-charm",
            charm_path=Path("/tmp/my-charm"),
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Improve this charm")

        assert result.success
        task_ids = [t.id for t in queue.all_tasks()]
        assert any(tid.startswith("audit-charm-") for tid in task_ids)
        assert any(tid.startswith("confirm-improvements-") for tid in task_ids)
        # No LLM call — improvement planning is deterministic.
        assert provider._call_count == 0

    @pytest.mark.asyncio
    async def test_replans_when_tasks_exist(self) -> None:
        """When the queue already has tasks, the tool should replan via the LLM."""
        replan_json = json.dumps(
            [
                {"id": "new", "title": "New task", "category": "build"},
            ]
        )
        provider = FakeProvider(
            responses=[Response(content=replan_json)],
        )
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        # First plan (deterministic).
        await tool.execute(intent="Build a charm for Redis")
        first_count = queue.pending_count
        assert first_count == 4

        # Second plan (replanning via LLM) — should call the provider.
        result = await tool.execute(intent="Actually, target machine")
        assert result.success
        assert provider._call_count == 1  # LLM called for replan
