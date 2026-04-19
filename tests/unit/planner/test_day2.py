"""Planner tests: day2."""

import json

import pytest

from cantrip.agent.planner import (
    DAY2_RESEARCH_PREFIX,
    PlanningContext,
    TaskPlanner,
    find_day2_anchor,
    plan_day2_ops_phase,
)
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ===================================================================
# TestDay2OpsPhase
# ===================================================================


class TestDay2OpsPhase:
    """Tests for the day-2 operations research phase planning."""

    def test_produces_three_tasks(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy-charm")
        assert len(tasks) == 3

    def test_task_ids(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy-charm")
        assert tasks[0].id.startswith("day2-research-")
        assert tasks[1].id.startswith("day2-synthesis-")
        assert tasks[2].id.startswith("confirm-day2-")

    def test_categories(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy-charm")
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].category == TaskCategory.RESEARCH
        assert tasks[2].category == TaskCategory.CONFIRM

    def test_depends_on_wired(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="my-deploy-task")
        assert tasks[0].dependencies == ["my-deploy-task"]

    def test_dependency_chain(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        assert tasks[1].dependencies == [tasks[0].id]
        assert tasks[2].dependencies == [tasks[1].id]

    def test_workload_in_titles(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="postgresql-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        assert "postgresql-k8s" in tasks[0].title
        assert "postgresql-k8s" in tasks[1].title

    def test_title_prefix(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        assert tasks[0].title.startswith(DAY2_RESEARCH_PREFIX)
        assert tasks[1].title.startswith(DAY2_RESEARCH_PREFIX)

    def test_uses_primary_model(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        assert tasks[0].model_hint == ModelHint.PRIMARY
        assert tasks[1].model_hint == ModelHint.PRIMARY

    def test_research_description_mentions_key_areas(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis-k8s")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        desc = tasks[0].description.lower()
        assert "backup" in desc
        assert "scaling" in desc
        assert "high availability" in desc
        assert "security" in desc

    def test_fallback_workload_name(self) -> None:
        ctx = PlanningContext(intent="build")
        tasks = plan_day2_ops_phase(ctx, depends_on="deploy")
        assert "the workload" in tasks[0].title


# ===================================================================
# TestFindDay2Anchor
# ===================================================================


class TestFindDay2Anchor:
    """Tests for find_day2_anchor — locating the dependency anchor."""

    def test_finds_deploy_task(self) -> None:
        tasks = [
            AgentTask(id="build", title="Build", category=TaskCategory.BUILD),
            AgentTask(id="deploy", title="Deploy", category=TaskCategory.DEPLOY),
            AgentTask(id="test", title="Test", category=TaskCategory.TEST),
        ]
        assert find_day2_anchor(tasks) == "test"

    def test_prefers_last_deploy_or_test(self) -> None:
        tasks = [
            AgentTask(id="deploy", title="Deploy", category=TaskCategory.DEPLOY),
            AgentTask(id="build2", title="Build", category=TaskCategory.BUILD),
        ]
        assert find_day2_anchor(tasks) == "deploy"

    def test_fallback_to_last_task(self) -> None:
        tasks = [
            AgentTask(id="build1", title="Build", category=TaskCategory.BUILD),
            AgentTask(id="build2", title="Build", category=TaskCategory.BUILD),
        ]
        assert find_day2_anchor(tasks) == "build2"

    def test_empty_list_returns_none(self) -> None:
        assert find_day2_anchor([]) is None


# ===================================================================
# TestPlanFromDay2Findings
# ===================================================================


class TestPlanFromDay2Findings:
    """Tests for TaskPlanner.plan_from_day2_findings()."""

    @pytest.mark.asyncio
    async def test_generates_tasks(self) -> None:
        impl_json = json.dumps(
            [
                {
                    "id": "add-backup",
                    "title": "Add backup action",
                    "category": "build",
                    "description": "Add backup and restore actions.",
                    "dependencies": [],
                },
            ]
        )
        provider = FakeProvider(responses=[Response(content=impl_json)])
        planner = TaskPlanner(provider)
        ctx = PlanningContext(intent="Implement day-2", charm_name="redis-k8s")

        tasks = await planner.plan_from_day2_findings(
            findings="## Backup\nRedis uses RDB and AOF.",
            context=ctx,
        )

        assert len(tasks) == 1
        assert tasks[0].id == "add-backup"
        assert tasks[0].category == TaskCategory.BUILD

    @pytest.mark.asyncio
    async def test_includes_overrides(self) -> None:
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
        ctx = PlanningContext(intent="Implement day-2")

        await planner.plan_from_day2_findings(
            findings="## Backup\nSome findings.",
            context=ctx,
            overrides="Skip HA, focus on backup only",
        )

        user_msg = recorded_messages[-1].content
        assert "User overrides" in user_msg
        assert "Skip HA" in user_msg

    @pytest.mark.asyncio
    async def test_no_overrides_omits_section(self) -> None:
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
        ctx = PlanningContext(intent="Implement day-2")

        await planner.plan_from_day2_findings(
            findings="## Backup",
            context=ctx,
            overrides=None,
        )

        user_msg = recorded_messages[-1].content
        assert "User overrides" not in user_msg
