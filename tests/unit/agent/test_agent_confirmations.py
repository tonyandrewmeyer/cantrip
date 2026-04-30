"""Tests for ``CantripAgent`` design / day-2 confirmation handlers.

Targets the ~130 lines of core.py dedicated to turning an approved
confirmation task into a build / implementation plan.  The planner
and ``parse_design_from_result`` are mocked so these tests only
exercise the agent-side plumbing (dependency walking, state updates,
event logging, push-confirm append).
"""

import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.design import DesignProposal
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from tests.conftest import FakeProvider


def _agent(tmp_path: pathlib.Path | None = None) -> CantripAgent:
    return CantripAgent(provider=FakeProvider(), charm_path=tmp_path)


def _confirm_with_synthesis(
    agent: CantripAgent,
    confirm_id: str,
    synthesis_result: str,
) -> None:
    """Queue a synthesis task (done) and a CONFIRM that depends on it."""
    synth = AgentTask(
        id=f"{confirm_id}-synth",
        title="Synthesis",
        category=TaskCategory.RESEARCH,
        status=TaskStatus.DONE,
    )
    synth.result = synthesis_result
    confirm = AgentTask(
        id=confirm_id,
        title="Confirm",
        category=TaskCategory.CONFIRM,
        dependencies=[synth.id],
    )
    agent.work_queue.add_tasks([synth, confirm])


# ---------------------------------------------------------------------------
# handle_design_confirmation
# ---------------------------------------------------------------------------


class TestHandleDesignConfirmation:
    """Every early-exit and the happy path of ``handle_design_confirmation``."""

    @pytest.mark.asyncio
    async def test_missing_confirm_task_returns_empty(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        assert await agent.handle_design_confirmation("missing") == []

    @pytest.mark.asyncio
    async def test_no_synthesis_result_returns_empty(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        confirm = AgentTask(
            id="confirm-design",
            title="Confirm",
            category=TaskCategory.CONFIRM,
        )
        agent.work_queue.add_task(confirm)
        assert await agent.handle_design_confirmation("confirm-design") == []

    @pytest.mark.asyncio
    async def test_happy_path_records_decisions_and_plans(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        _confirm_with_synthesis(agent, "confirm-design", "## Design\n...")

        fake_proposal = DesignProposal(
            workload_name="widget",
            substrate="k8s",
            substrate_reasoning="best fit",
            charm_path="./charm",
            charm_path_reasoning="root",
            charmhub_recommendation="canonical/widget-k8s",
            raw_design_md="# Widget\n\nbody",
        )
        build_task = AgentTask(
            id="build-1",
            title="Build",
            category=TaskCategory.BUILD,
        )

        with (
            patch(
                "cantrip.agent.core.parse_design_from_result",
                return_value=fake_proposal,
            ),
            patch("cantrip.agent.core.is_one_shot_build", return_value=False),
            patch("cantrip.agent.core.TaskPlanner") as planner_cls,
            patch("cantrip.agent.core.find_day2_anchor", return_value=None),
        ):
            planner_cls.return_value.plan_from_design = AsyncMock(return_value=[build_task])
            tasks = await agent.handle_design_confirmation("confirm-design")

        assert tasks == [build_task]
        # State decisions captured.
        decision_types = {d.type for d in agent.state.decisions}
        assert {"substrate", "charm_path", "charmhub"} <= decision_types
        # Proposal attached to state.
        assert agent.state.design_proposal is fake_proposal

    @pytest.mark.asyncio
    async def test_one_shot_build_uses_deterministic_planner(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        _confirm_with_synthesis(agent, "confirm-design", "## Design")
        proposal = DesignProposal(workload_name="w", raw_design_md="md")
        one_shot_task = AgentTask(id="one", title="One shot", category=TaskCategory.BUILD)

        with (
            patch(
                "cantrip.agent.core.parse_design_from_result",
                return_value=proposal,
            ),
            patch("cantrip.agent.core.is_one_shot_build", return_value=True),
            patch(
                "cantrip.agent.core.plan_one_shot_build",
                return_value=[one_shot_task],
            ) as one_shot,
            patch("cantrip.agent.core.find_day2_anchor", return_value=None),
        ):
            tasks = await agent.handle_design_confirmation("confirm-design")

        one_shot.assert_called_once()
        assert tasks == [one_shot_task]

    @pytest.mark.asyncio
    async def test_day2_phase_appended_when_anchor_found(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        _confirm_with_synthesis(agent, "confirm-design", "## Design")
        proposal = DesignProposal(workload_name="w", raw_design_md="md")
        build_task = AgentTask(id="build-1", title="Build", category=TaskCategory.BUILD)
        day2_task = AgentTask(id="day2-1", title="Day2", category=TaskCategory.RESEARCH)

        with (
            patch(
                "cantrip.agent.core.parse_design_from_result",
                return_value=proposal,
            ),
            patch("cantrip.agent.core.is_one_shot_build", return_value=True),
            patch(
                "cantrip.agent.core.plan_one_shot_build",
                return_value=[build_task],
            ),
            patch("cantrip.agent.core.find_day2_anchor", return_value="build-1"),
            patch(
                "cantrip.agent.core.plan_day2_ops_phase",
                return_value=[day2_task],
            ),
        ):
            await agent.handle_design_confirmation("confirm-design")

        # Day-2 task added to the queue.
        assert agent.work_queue.get_task("day2-1") is not None


# ---------------------------------------------------------------------------
# handle_day2_confirmation
# ---------------------------------------------------------------------------


class TestHandleDay2Confirmation:
    """Every early-exit and the happy path of ``handle_day2_confirmation``."""

    @pytest.mark.asyncio
    async def test_missing_confirm_task_returns_empty(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        assert await agent.handle_day2_confirmation("missing") == []

    @pytest.mark.asyncio
    async def test_no_synthesis_result_returns_empty(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        confirm = AgentTask(id="confirm-day2", title="C", category=TaskCategory.CONFIRM)
        agent.work_queue.add_task(confirm)
        assert await agent.handle_day2_confirmation("confirm-day2") == []

    @pytest.mark.asyncio
    async def test_happy_path_plans_from_findings(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        _confirm_with_synthesis(agent, "confirm-day2", "## Findings\nstuff")

        impl = AgentTask(id="impl-1", title="Implement backup", category=TaskCategory.BUILD)
        with patch("cantrip.agent.core.TaskPlanner") as planner_cls:
            planner_cls.return_value.plan_from_day2_findings = AsyncMock(return_value=[impl])
            tasks = await agent.handle_day2_confirmation(
                "confirm-day2", overrides="keep it simple"
            )

        assert tasks == [impl]
        assert agent.work_queue.get_task("impl-1") is not None
