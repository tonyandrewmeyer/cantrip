"""Planner tests: planner."""

import json

import pytest

from cantrip.agent.planner import (
    PlanningContext,
    TaskPlanner,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ===================================================================
# TestTaskPlannerPlan
# ===================================================================


class TestTaskPlannerPlan:
    """Tests for TaskPlanner.plan() — deterministic research-phase templates."""

    @pytest.mark.asyncio
    async def test_plan_returns_research_phase(self) -> None:
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build a charm for Redis", charm_name="redis-k8s")

        tasks = await planner.plan(context)

        # 4 tasks: web-research, charmhub-survey, operational-discovery, confirm-design.
        assert len(tasks) == 4
        assert tasks[0].id.startswith("web-research-")
        assert tasks[1].id.startswith("charmhub-survey-")
        assert tasks[2].id.startswith("operational-discovery-")
        assert tasks[3].id.startswith("confirm-design-")

    @pytest.mark.asyncio
    async def test_plan_includes_source_analysis_when_url_given(self) -> None:
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Build a charm for Redis",
            source_url="https://github.com/redis/redis",
        )

        tasks = await planner.plan(context)

        # 5 tasks: source-analysis, web-research, charmhub-survey, operational-discovery, confirm.
        assert len(tasks) == 5
        assert tasks[0].id.startswith("source-analysis-")

    @pytest.mark.asyncio
    async def test_plan_no_llm_call(self) -> None:
        """Deterministic planning should not call the LLM."""
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        await planner.plan(PlanningContext(intent="test"))

        assert provider._call_count == 0

    @pytest.mark.asyncio
    async def test_sprint_path_for_known_framework(self) -> None:
        """Known 12-factor frameworks use sprint path: build + deploy, no research."""
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Build a charm for my Flask app",
            charm_name="my-flask-app",
            framework="flask",
        )

        tasks = await planner.plan(context)

        assert len(tasks) == 2
        assert tasks[0].id.startswith("sprint-build-")
        assert tasks[1].id.startswith("sprint-deploy-")
        assert "flask" in tasks[0].description.lower()
        # No LLM call needed — sprint is deterministic.
        assert provider._call_count == 0

    @pytest.mark.asyncio
    async def test_fast_path_not_used_with_source_url(self) -> None:
        """Even for known frameworks, source URLs trigger full research."""
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Build a charm",
            framework="flask",
            source_url="https://github.com/user/app",
        )

        tasks = await planner.plan(context)

        # Full research phase, not fast path.
        assert len(tasks) == 5
        assert tasks[0].id.startswith("source-analysis-")


# ===================================================================
# TestTaskPlannerReplan
# ===================================================================


class TestTaskPlannerReplan:
    """Tests for TaskPlanner.replan()."""

    @pytest.mark.asyncio
    async def test_done_tasks_preserved(self) -> None:
        existing = [
            AgentTask(
                id="done-task",
                title="Already done",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
            ),
            AgentTask(
                id="pending-task",
                title="Not started",
                category=TaskCategory.BUILD,
                status=TaskStatus.PENDING,
            ),
        ]
        new_json = json.dumps(
            {
                "tasks": [
                    {"id": "new-task", "title": "New work", "category": "build"},
                ]
            }
        )
        provider = FakeProvider(responses=[Response(content=new_json)])
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Build a charm for Redis",
            existing_tasks=existing,
            new_context="Actually, target machine instead of K8s",
        )

        tasks = await planner.replan(context)

        ids = [t.id for t in tasks]
        assert "done-task" in ids
        assert "pending-task" not in ids
        assert "new-task" in ids

    @pytest.mark.asyncio
    async def test_active_tasks_preserved(self) -> None:
        existing = [
            AgentTask(
                id="active-task",
                title="In progress",
                category=TaskCategory.BUILD,
                status=TaskStatus.ACTIVE,
            ),
        ]
        new_json = json.dumps(
            {
                "tasks": [
                    {"id": "active-task", "title": "Replaced?", "category": "build"},
                    {"id": "new-one", "title": "New", "category": "test"},
                ]
            }
        )
        provider = FakeProvider(responses=[Response(content=new_json)])
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Replan",
            existing_tasks=existing,
            new_context="Changed scope",
        )

        tasks = await planner.replan(context)

        # Active task preserved, duplicate discarded, new one added.
        assert tasks[0].id == "active-task"
        assert tasks[0].title == "In progress"
        assert any(t.id == "new-one" for t in tasks)
        assert len(tasks) == 2


# ===================================================================
# TestUniqueTaskIDs
# ===================================================================


class TestUniqueTaskIDs:
    """Verify that planner functions produce unique (suffixed) task IDs."""

    def test_sprint_ids_have_suffix(self) -> None:
        """Sprint task IDs must not be bare strings — they include a random suffix."""
        ctx = PlanningContext(intent="build", framework="flask", charm_name="app")
        tasks = plan_sprint_deploy(ctx)
        for task in tasks:
            # The suffix adds a dash and 8 hex characters after the base name.
            assert len(task.id) > len("sprint-build")
            assert "-" in task.id[len("sprint-") :]

    def test_two_plans_produce_different_ids(self) -> None:
        """Running the same planner function twice yields distinct IDs."""
        ctx = PlanningContext(intent="build", framework="flask", charm_name="app")
        first = plan_sprint_deploy(ctx)
        second = plan_sprint_deploy(ctx)
        first_ids = {t.id for t in first}
        second_ids = {t.id for t in second}
        assert first_ids.isdisjoint(second_ids)

    def test_research_ids_have_suffix(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis")
        tasks = plan_research_phase(ctx)
        for task in tasks:
            # The last 8 characters (after the final dash) are a hex suffix.
            suffix = task.id.rsplit("-", 1)[-1]
            assert len(suffix) == 8
            int(suffix, 16)  # Validates it is hex.


# ===================================================================
# TestPlanningContextNewFields
# ===================================================================


class TestPlanningContextNewFields:
    """Tests for the new source_url field on PlanningContext."""

    def test_source_url_defaults_to_none(self) -> None:
        ctx = PlanningContext(intent="test")
        assert ctx.source_url is None

    def test_source_url_set(self) -> None:
        ctx = PlanningContext(
            intent="test",
            source_url="https://github.com/example/repo",
        )
        assert ctx.source_url == "https://github.com/example/repo"
