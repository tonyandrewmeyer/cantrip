"""Planner tests: design."""

import json

import pytest

from cantrip.agent.planner import (
    PlanningContext,
    TaskPlanner,
    _build_design_to_build_prompt,
    plan_one_shot_build,
)
from cantrip.agent.queue import TaskCategory
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ===================================================================
# TestPlanFromDesign
# ===================================================================


class TestPlanFromDesign:
    """Tests for TaskPlanner.plan_from_design()."""

    @pytest.mark.asyncio
    async def test_generates_build_tasks(self) -> None:
        build_json = json.dumps(
            [
                {
                    "id": "scaffold",
                    "title": "Scaffold the charm",
                    "category": "build",
                    "description": "Run charmcraft init.",
                    "dependencies": [],
                },
                {
                    "id": "write-tests",
                    "title": "Write unit tests",
                    "category": "build",
                    "description": "Write Scenario tests.",
                    "dependencies": ["scaffold"],
                },
            ]
        )
        provider = FakeProvider(responses=[Response(content=build_json)])
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build a charm for Redis")

        tasks = await planner.plan_from_design(
            design_content="# Design: Redis\n## Substrate\nK8s",
            context=context,
        )

        assert len(tasks) == 2
        assert tasks[0].title == "Scaffold the charm"
        assert tasks[0].category == TaskCategory.BUILD
        assert tasks[1].dependencies == ["scaffold"]

    @pytest.mark.asyncio
    async def test_includes_overrides(self) -> None:
        """Verify overrides are passed in the user message."""
        recorded_messages: list = []

        class RecordingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                recorded_messages.extend(messages)
                return Response(content="[]")

        provider = RecordingProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build")

        await planner.plan_from_design(
            design_content="# Design",
            context=context,
            overrides="Use machine instead of K8s",
        )

        user_msg = recorded_messages[-1].content
        assert "User overrides" in user_msg
        assert "machine instead of K8s" in user_msg

    @pytest.mark.asyncio
    async def test_no_overrides_omits_section(self) -> None:
        """When overrides is None, the user message should not contain 'User overrides'."""
        recorded_messages: list = []

        class RecordingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                recorded_messages.extend(messages)
                return Response(content="[]")

        provider = RecordingProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build")

        await planner.plan_from_design(
            design_content="# Design",
            context=context,
            overrides=None,
        )

        user_msg = recorded_messages[-1].content
        assert "User overrides" not in user_msg

    @pytest.mark.asyncio
    async def test_passes_extended_thinking_budget(self) -> None:
        """Planner calls include a non-zero thinking_budget for structured decomposition."""
        recorded: dict = {}

        class RecordingProvider(FakeProvider):
            async def complete(
                self,
                messages,  # noqa: ARG002
                tools=None,  # noqa: ARG002
                temperature=0.7,  # noqa: ARG002
                max_tokens=None,  # noqa: ARG002
                thinking_budget=None,
            ):
                recorded["thinking_budget"] = thinking_budget
                return Response(content="[]")

        provider = RecordingProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build")

        await planner.plan_from_design(design_content="# Design", context=context)
        assert recorded["thinking_budget"] is not None
        assert recorded["thinking_budget"] > 0

        # Same for replan and plan_from_day2_findings.
        recorded.clear()
        context_with_new = PlanningContext(intent="Build", new_context="updated")
        await planner.replan(context_with_new)
        assert recorded["thinking_budget"] is not None
        assert recorded["thinking_budget"] > 0

        recorded.clear()
        await planner.plan_from_day2_findings(findings="# Findings", context=context)
        assert recorded["thinking_budget"] is not None
        assert recorded["thinking_budget"] > 0


# ===================================================================
# TestRedGreenBuildSequence
# ===================================================================


class TestRedGreenBuildSequence:
    """Tests for the red/green (integration-tests-first) build pipeline."""

    def test_design_to_build_prompt_mentions_red_green(self) -> None:
        """The design-to-build prompt includes the red/green approach."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        assert "red" in prompt.lower()
        assert "green" in prompt.lower()

    def test_design_to_build_prompt_integration_tests_before_charm_code(self) -> None:
        """Integration tests appear before charm code in the build sequence."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        integration_pos = prompt.find("integration tests")
        charm_code_pos = prompt.find("charm code")
        assert integration_pos < charm_code_pos

    def test_design_to_build_prompt_unit_tests_after_integration(self) -> None:
        """Unit tests are positioned after integration tests in the sequence."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        # In the numbered sequence, unit tests (step 6) come after integration (step 2).
        integration_pos = prompt.find("Write integration tests")
        unit_pos = prompt.find("Write unit tests")
        assert integration_pos < unit_pos

    def test_design_to_build_prompt_mentions_external_contract(self) -> None:
        """The prompt explains integration tests encode the external contract."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        assert "external contract" in prompt

    def test_one_shot_build_mentions_red_green(self) -> None:
        """One-shot build description includes the red/green approach."""
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "## Design\nA flask charm.")
        assert "red" in tasks[0].description.lower()

    def test_one_shot_build_integration_tests_before_charm_code(self) -> None:
        """One-shot build writes integration tests before src/charm.py."""
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "design")
        desc = tasks[0].description
        integration_pos = desc.find("integration tests")
        charm_pos = desc.find("src/charm.py")
        assert integration_pos < charm_pos

    def test_one_shot_build_unit_tests_for_edge_cases(self) -> None:
        """One-shot build positions unit tests for edge cases."""
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "design")
        assert "edge cases" in tasks[0].description
