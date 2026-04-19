"""Planner tests: paths."""

import pytest

from cantrip.agent.planner import (
    SPRINT_BUILD_PREFIX,
    SPRINT_DEPLOY_PREFIX,
    PlanningContext,
    TaskPlanner,
    is_fast_path,
    is_improvement,
    is_one_shot_build,
    is_sprint,
    plan_fast_path,
    plan_improvement_phase,
    plan_one_shot_build,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.queue import ModelHint, TaskCategory
from tests.conftest import FakeProvider

# ===================================================================
# TestFastPath
# ===================================================================


class TestFastPath:
    """Tests for the fast-path logic for known 12-factor frameworks."""

    def test_is_fast_path_flask(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask")
        assert is_fast_path(ctx)

    def test_is_fast_path_django(self) -> None:
        ctx = PlanningContext(intent="build", framework="django")
        assert is_fast_path(ctx)

    def test_is_fast_path_fastapi(self) -> None:
        ctx = PlanningContext(intent="build", framework="fastapi")
        assert is_fast_path(ctx)

    def test_is_fast_path_go(self) -> None:
        ctx = PlanningContext(intent="build", framework="go")
        assert is_fast_path(ctx)

    def test_is_fast_path_express(self) -> None:
        ctx = PlanningContext(intent="build", framework="express")
        assert is_fast_path(ctx)

    def test_is_fast_path_spring_boot(self) -> None:
        ctx = PlanningContext(intent="build", framework="spring-boot")
        assert is_fast_path(ctx)

    def test_not_fast_path_unknown_framework(self) -> None:
        ctx = PlanningContext(intent="build", framework="redis")
        assert not is_fast_path(ctx)

    def test_not_fast_path_no_framework(self) -> None:
        ctx = PlanningContext(intent="build")
        assert not is_fast_path(ctx)

    def test_not_fast_path_with_source_url(self) -> None:
        ctx = PlanningContext(
            intent="build",
            framework="flask",
            source_url="https://github.com/user/app",
        )
        assert not is_fast_path(ctx)

    def test_fast_path_case_insensitive(self) -> None:
        ctx = PlanningContext(intent="build", framework="Flask")
        assert is_fast_path(ctx)

    def test_plan_fast_path_produces_two_tasks(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_fast_path(ctx)
        assert len(tasks) == 2
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].category == TaskCategory.CONFIRM
        assert len(tasks[1].dependencies) == 1
        assert tasks[1].dependencies[0].startswith("fast-design-")

    def test_plan_research_phase_produces_four_tasks(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="redis")
        tasks = plan_research_phase(ctx)
        assert len(tasks) == 4


# ===================================================================
# TestSprint
# ===================================================================


class TestSprint:
    """Tests for the sprint (instant deploy) path."""

    def test_is_sprint_flask(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask")
        assert is_sprint(ctx)

    def test_is_sprint_with_explicit_charm_type(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="hello", charm_type="machine")
        assert is_sprint(ctx)

    def test_not_sprint_without_name_and_type(self) -> None:
        ctx = PlanningContext(intent="build", charm_type="k8s")
        assert not is_sprint(ctx)

    def test_not_sprint_with_source_url(self) -> None:
        ctx = PlanningContext(
            intent="build",
            framework="flask",
            source_url="https://github.com/user/app",
        )
        assert not is_sprint(ctx)

    def test_plan_sprint_deploy_paas(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_sprint_deploy(ctx)
        assert len(tasks) == 2
        assert tasks[0].id.startswith("sprint-build-")
        assert tasks[0].title.startswith(SPRINT_BUILD_PREFIX)
        assert tasks[0].category == TaskCategory.BUILD
        assert tasks[1].id.startswith("sprint-deploy-")
        assert tasks[1].title.startswith(SPRINT_DEPLOY_PREFIX)
        assert tasks[1].category == TaskCategory.DEPLOY
        assert tasks[1].dependencies == [tasks[0].id]
        assert "flask-framework" in tasks[0].description

    def test_plan_sprint_deploy_machine(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="hello", charm_type="machine")
        tasks = plan_sprint_deploy(ctx)
        assert len(tasks) == 2
        assert "machine" in tasks[0].description
        assert tasks[0].title.startswith(SPRINT_BUILD_PREFIX)

    def test_plan_sprint_deploy_k8s(self) -> None:
        ctx = PlanningContext(intent="build", charm_name="myapp", charm_type="k8s")
        tasks = plan_sprint_deploy(ctx)
        assert "kubernetes" in tasks[0].description

    def test_sprint_build_says_no_tests(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_sprint_deploy(ctx)
        desc = tasks[0].description.lower()
        assert "do not write tests" in desc
        assert "do not run charm_validate" in desc


# ===================================================================
# TestOneShotBuild
# ===================================================================


class TestOneShotBuild:
    """Tests for one-shot build mode — collapse scaffold+write+pack into one task."""

    def test_is_one_shot_build_flask(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask")
        assert is_one_shot_build(ctx)

    def test_is_one_shot_build_django(self) -> None:
        ctx = PlanningContext(intent="build", framework="django")
        assert is_one_shot_build(ctx)

    def test_not_one_shot_build_unknown_framework(self) -> None:
        ctx = PlanningContext(intent="build", framework="redis")
        assert not is_one_shot_build(ctx)

    def test_not_one_shot_build_no_framework(self) -> None:
        ctx = PlanningContext(intent="build")
        assert not is_one_shot_build(ctx)

    def test_one_shot_build_with_source_url(self) -> None:
        """One-shot build is allowed even with a source URL (unlike fast path)."""
        ctx = PlanningContext(
            intent="build",
            framework="flask",
            source_url="https://github.com/user/app",
        )
        assert is_one_shot_build(ctx)

    def test_one_shot_build_case_insensitive(self) -> None:
        ctx = PlanningContext(intent="build", framework="FastAPI")
        assert is_one_shot_build(ctx)

    def test_plan_one_shot_build_produces_single_task(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "## Design\nA flask charm.")
        assert len(tasks) == 1
        assert tasks[0].id.startswith("one-shot-build-")
        assert tasks[0].category == TaskCategory.BUILD
        assert tasks[0].dependencies == []

    def test_plan_one_shot_build_uses_primary_model(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "design")
        assert tasks[0].model_hint == ModelHint.PRIMARY

    def test_plan_one_shot_build_includes_design_in_description(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        design = "## Approved\nFlask PaaS charm with ingress and PostgreSQL."
        tasks = plan_one_shot_build(ctx, design)
        assert "Approved" in tasks[0].description
        assert "PostgreSQL" in tasks[0].description

    def test_plan_one_shot_build_includes_framework_in_title(self) -> None:
        ctx = PlanningContext(intent="build", framework="django", charm_name="my-site")
        tasks = plan_one_shot_build(ctx, "design")
        assert "django" in tasks[0].title

    def test_plan_one_shot_build_mentions_companion_charms(self) -> None:
        ctx = PlanningContext(intent="build", framework="flask", charm_name="my-app")
        tasks = plan_one_shot_build(ctx, "design")
        assert "companion" in tasks[0].description.lower()


# ===================================================================
# TestImprovementPath
# ===================================================================


class TestImprovementPath:
    """Tests for the improvement (existing charm audit) planning path."""

    def test_is_improvement_with_path(self) -> None:
        ctx = PlanningContext(intent="improve", existing_charm_path="/tmp/charm")
        assert is_improvement(ctx)

    def test_is_not_improvement_without_path(self) -> None:
        ctx = PlanningContext(intent="build")
        assert not is_improvement(ctx)

    def test_plan_improvement_phase_produces_two_tasks(self) -> None:
        ctx = PlanningContext(
            intent="improve",
            charm_name="my-charm",
            existing_charm_path="/tmp/charm",
        )
        tasks = plan_improvement_phase(ctx)

        assert len(tasks) == 2
        assert tasks[0].id.startswith("audit-charm-")
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].id.startswith("confirm-improvements-")
        assert tasks[1].category == TaskCategory.CONFIRM

    def test_plan_improvement_phase_has_correct_dependencies(self) -> None:
        ctx = PlanningContext(
            intent="improve",
            existing_charm_path="/tmp/charm",
        )
        tasks = plan_improvement_phase(ctx)

        assert tasks[0].dependencies == []
        assert tasks[1].dependencies == [tasks[0].id]

    def test_plan_improvement_phase_includes_charm_path(self) -> None:
        ctx = PlanningContext(
            intent="improve",
            existing_charm_path="/home/user/my-charm",
        )
        tasks = plan_improvement_phase(ctx)

        assert "/home/user/my-charm" in tasks[0].description

    @pytest.mark.asyncio
    async def test_planner_routes_to_improvement(self) -> None:
        """TaskPlanner.plan() routes to improvement when existing_charm_path is set."""
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        ctx = PlanningContext(
            intent="improve this charm",
            existing_charm_path="/tmp/charm",
            charm_name="test",
        )

        tasks = await planner.plan(ctx)

        assert tasks[0].id.startswith("audit-charm-")
        # No LLM call for deterministic templates.
        assert provider._call_count == 0
