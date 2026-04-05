"""Tests for the task planner and PlanTasksTool."""

import json
from pathlib import Path

import pytest

from cantrip.agent.planner import (
    DAY2_RESEARCH_PREFIX,
    OPERABILITY_PREFIX,
    SPRINT_BUILD_PREFIX,
    SPRINT_DEPLOY_PREFIX,
    PlanningContext,
    TaskPlanner,
    _build_day2_to_build_prompt,
    _build_design_to_build_prompt,
    _build_planning_prompt,
    _build_replanning_prompt,
    _extract_json,
    _merge_tasks,
    _parse_task_list,
    find_day2_anchor,
    is_fast_path,
    is_improvement,
    is_one_shot_build,
    is_sprint,
    plan_day2_ops_phase,
    plan_fast_path,
    plan_improvement_fixes,
    plan_improvement_phase,
    plan_one_shot_build,
    plan_operability_assessment,
    plan_operability_fixes,
    plan_research_phase,
    plan_sprint_deploy,
)
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools.planning import PlanTasksTool
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Sample JSON payloads
# ---------------------------------------------------------------------------

VALID_TASKS_JSON = json.dumps(
    [
        {
            "id": "research",
            "title": "Research the workload",
            "category": "research",
            "description": "Clone and analyse the source.",
            "dependencies": [],
        },
        {
            "id": "scaffold",
            "title": "Scaffold the charm",
            "category": "build",
            "description": "Run charmcraft init and write charm code.",
            "dependencies": ["research"],
        },
    ]
)

WRAPPED_TASKS_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "deploy",
                "title": "Deploy the charm",
                "category": "deploy",
                "description": "Pack and deploy.",
                "dependencies": [],
            },
        ]
    }
)


# ===================================================================
# TestExtractJson
# ===================================================================


class TestExtractJson:
    """Tests for _extract_json — stripping code fences."""

    def test_plain_json(self) -> None:
        assert _extract_json('[{"id": "a"}]') == '[{"id": "a"}]'

    def test_json_code_fence(self) -> None:
        raw = '```json\n[{"id": "a"}]\n```'
        assert _extract_json(raw) == '[{"id": "a"}]'

    def test_bare_code_fence(self) -> None:
        raw = '```\n[{"id": "a"}]\n```'
        assert _extract_json(raw) == '[{"id": "a"}]'

    def test_surrounding_text_stripped(self) -> None:
        raw = 'Here is the plan:\n```json\n[{"id": "a"}]\n```\nDone.'
        assert _extract_json(raw) == '[{"id": "a"}]'


# ===================================================================
# TestParseTaskList
# ===================================================================


class TestParseTaskList:
    """Tests for _parse_task_list — JSON-to-AgentTask conversion."""

    def test_valid_array(self) -> None:
        tasks = _parse_task_list(VALID_TASKS_JSON)
        assert len(tasks) == 2
        assert tasks[0].title == "Research the workload"
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[0].dependencies == []
        assert tasks[1].dependencies == ["research"]

    def test_code_fenced_json(self) -> None:
        raw = f"```json\n{VALID_TASKS_JSON}\n```"
        tasks = _parse_task_list(raw)
        assert len(tasks) == 2

    def test_wrapped_object(self) -> None:
        tasks = _parse_task_list(WRAPPED_TASKS_JSON)
        assert len(tasks) == 1
        assert tasks[0].title == "Deploy the charm"

    def test_non_array_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON array"):
            _parse_task_list('"just a string"')

    def test_invalid_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON array"):
            _parse_task_list('{"foo": "bar"}')

    def test_missing_title_raises(self) -> None:
        raw = json.dumps([{"id": "x", "category": "build"}])
        with pytest.raises(ValueError, match="missing a title"):
            _parse_task_list(raw)

    def test_unknown_category_defaults_to_build(self) -> None:
        raw = json.dumps([{"id": "x", "title": "Do stuff", "category": "banana"}])
        tasks = _parse_task_list(raw)
        assert tasks[0].category == TaskCategory.BUILD

    def test_missing_category_defaults_to_build(self) -> None:
        raw = json.dumps([{"id": "x", "title": "Do stuff"}])
        tasks = _parse_task_list(raw)
        assert tasks[0].category == TaskCategory.BUILD

    def test_dependencies_preserved(self) -> None:
        raw = json.dumps(
            [
                {"id": "a", "title": "First", "dependencies": []},
                {"id": "b", "title": "Second", "dependencies": ["a"]},
            ]
        )
        tasks = _parse_task_list(raw)
        assert tasks[1].dependencies == ["a"]

    def test_invalid_dependencies_defaults_to_empty(self) -> None:
        raw = json.dumps([{"id": "a", "title": "First", "dependencies": "not-a-list"}])
        tasks = _parse_task_list(raw)
        assert tasks[0].dependencies == []

    def test_empty_array_valid(self) -> None:
        tasks = _parse_task_list("[]")
        assert tasks == []

    def test_unparseable_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_task_list("this is not json at all")


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
        assert tasks[0].id == "web-research"
        assert tasks[1].id == "charmhub-survey"
        assert tasks[2].id == "operational-discovery"
        assert tasks[3].id == "confirm-design"

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
        assert tasks[0].id == "source-analysis"

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
        assert tasks[0].id == "sprint-build"
        assert tasks[1].id == "sprint-deploy"
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
        assert tasks[0].id == "source-analysis"


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
        assert tasks[1].dependencies == ["fast-design"]

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
        assert tasks[0].id == "sprint-build"
        assert tasks[0].title.startswith(SPRINT_BUILD_PREFIX)
        assert tasks[0].category == TaskCategory.BUILD
        assert tasks[1].id == "sprint-deploy"
        assert tasks[1].title.startswith(SPRINT_DEPLOY_PREFIX)
        assert tasks[1].category == TaskCategory.DEPLOY
        assert tasks[1].dependencies == ["sprint-build"]
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
        assert tasks[0].id == "one-shot-build"
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
            [
                {"id": "new-task", "title": "New work", "category": "build"},
            ]
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
            [
                {"id": "active-task", "title": "Replaced?", "category": "build"},
                {"id": "new-one", "title": "New", "category": "test"},
            ]
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
# TestMergeTasks
# ===================================================================


class TestMergeTasks:
    """Tests for _merge_tasks — combining existing and new tasks."""

    def test_completed_first(self) -> None:
        existing = [
            AgentTask(
                id="a", title="Done", category=TaskCategory.RESEARCH, status=TaskStatus.DONE
            ),
            AgentTask(
                id="b", title="Pending", category=TaskCategory.BUILD, status=TaskStatus.PENDING
            ),
        ]
        new = [
            AgentTask(id="c", title="New", category=TaskCategory.TEST),
        ]
        merged = _merge_tasks(existing, new)
        assert [t.id for t in merged] == ["a", "c"]

    def test_new_tasks_appended_after_preserved(self) -> None:
        existing = [
            AgentTask(
                id="a", title="Active", category=TaskCategory.BUILD, status=TaskStatus.ACTIVE
            ),
        ]
        new = [
            AgentTask(id="b", title="New1", category=TaskCategory.DEPLOY),
            AgentTask(id="c", title="New2", category=TaskCategory.TEST),
        ]
        merged = _merge_tasks(existing, new)
        assert [t.id for t in merged] == ["a", "b", "c"]

    def test_duplicate_id_completed_wins(self) -> None:
        existing = [
            AgentTask(
                id="x", title="Done", category=TaskCategory.RESEARCH, status=TaskStatus.DONE
            ),
        ]
        new = [
            AgentTask(id="x", title="Replacement", category=TaskCategory.BUILD),
            AgentTask(id="y", title="Other", category=TaskCategory.TEST),
        ]
        merged = _merge_tasks(existing, new)
        assert len(merged) == 2
        assert merged[0].id == "x"
        assert merged[0].title == "Done"
        assert merged[1].id == "y"

    def test_empty_existing(self) -> None:
        new = [AgentTask(id="a", title="New", category=TaskCategory.BUILD)]
        merged = _merge_tasks([], new)
        assert len(merged) == 1

    def test_empty_new(self) -> None:
        existing = [
            AgentTask(id="a", title="Done", category=TaskCategory.BUILD, status=TaskStatus.DONE),
        ]
        merged = _merge_tasks(existing, [])
        assert len(merged) == 1


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
        assert "audit-charm" in task_ids
        assert "confirm-improvements" in task_ids
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


# ===================================================================
# TestPlanningPrompt
# ===================================================================


class TestPlanningPrompt:
    """Tests for prompt construction helpers."""

    def test_includes_charm_name(self) -> None:
        context = PlanningContext(intent="test", charm_name="redis-k8s")
        prompt = _build_planning_prompt(context)
        assert "redis-k8s" in prompt

    def test_includes_environment_not_ready(self) -> None:
        context = PlanningContext(intent="test", environment_ready=False)
        prompt = _build_planning_prompt(context)
        assert "not yet provisioned" in prompt

    def test_includes_environment_ready(self) -> None:
        context = PlanningContext(intent="test", environment_ready=True)
        prompt = _build_planning_prompt(context)
        assert "ready" in prompt.lower()

    def test_replanning_prompt_includes_existing(self) -> None:
        existing = [
            AgentTask(
                id="done-task",
                title="Already done",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
            ),
        ]
        context = PlanningContext(
            intent="test",
            existing_tasks=existing,
        )
        prompt = _build_replanning_prompt(context)
        assert "done-task" in prompt
        assert "Already done" in prompt
        assert "Existing tasks" in prompt

    def test_includes_all_categories(self) -> None:
        context = PlanningContext(intent="test")
        prompt = _build_planning_prompt(context)
        for cat in ("research", "build", "deploy", "test", "debug", "infra", "confirm"):
            assert cat in prompt

    def test_includes_research_decomposition_guide(self) -> None:
        """Verify the research-first decomposition guidance is present."""
        context = PlanningContext(intent="test")
        prompt = _build_planning_prompt(context)
        assert "source-analysis" in prompt
        assert "web-research" in prompt
        assert "charmhub-survey" in prompt
        assert "operational-discovery" in prompt
        assert "confirm-design" in prompt

    def test_includes_source_url(self) -> None:
        context = PlanningContext(
            intent="test",
            source_url="https://github.com/example/repo",
        )
        prompt = _build_planning_prompt(context)
        assert "https://github.com/example/repo" in prompt


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
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
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
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
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


# ===================================================================
# TestDesignToBuildPrompt
# ===================================================================


class TestDesignToBuildPrompt:
    """Tests for the design-to-build prompt builder."""

    def test_includes_categories(self) -> None:
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        for cat in ("build", "deploy", "test"):
            assert cat in prompt

    def test_includes_context(self) -> None:
        context = PlanningContext(
            intent="test",
            charm_name="redis-k8s",
            dev_model="dev",
        )
        prompt = _build_design_to_build_prompt(context)
        assert "redis-k8s" in prompt
        assert "dev" in prompt

    def test_mentions_companion_charms(self) -> None:
        """The design-to-build prompt instructs the LLM to handle companion charms."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        assert "companion" in prompt.lower()
        assert "Companion charms" in prompt


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
        assert tasks[0].id == "audit-charm"
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].id == "confirm-improvements"
        assert tasks[1].category == TaskCategory.CONFIRM

    def test_plan_improvement_phase_has_correct_dependencies(self) -> None:
        ctx = PlanningContext(
            intent="improve",
            existing_charm_path="/tmp/charm",
        )
        tasks = plan_improvement_phase(ctx)

        assert tasks[0].dependencies == []
        assert tasks[1].dependencies == ["audit-charm"]

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

        assert tasks[0].id == "audit-charm"
        # No LLM call for deterministic templates.
        assert provider._call_count == 0


# ===================================================================
# TestPlanImprovementFixes
# ===================================================================


class TestPlanImprovementFixes:
    """Tests for plan_improvement_fixes — conditional fix task generation."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="improve",
            existing_charm_path="/tmp/charm",
            charm_name="my-charm",
        )

    def test_no_gaps_produces_no_tasks(self) -> None:
        gaps: dict[str, bool] = {}
        tasks = plan_improvement_fixes(self._ctx(), gaps)
        assert tasks == []

    def test_cos_gaps_produce_observability_task(self) -> None:
        gaps = {"cos_tracing": True, "cos_metrics": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        obs_tasks = [t for t in tasks if t.id == "fill-observability"]
        assert len(obs_tasks) == 1
        assert obs_tasks[0].category == TaskCategory.BUILD

    def test_test_gaps_produce_test_task(self) -> None:
        gaps = {"unit_tests": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        test_tasks = [t for t in tasks if t.id == "fill-tests"]
        assert len(test_tasks) == 1

    def test_deprecated_apis_produce_modernise_task(self) -> None:
        gaps = {"deprecated_apis": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        mod_tasks = [t for t in tasks if t.id == "modernise-code"]
        assert len(mod_tasks) == 1

    def test_listing_gaps_produce_listing_task(self) -> None:
        gaps = {"readme": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        listing_tasks = [t for t in tasks if t.id == "listing-readiness"]
        assert len(listing_tasks) == 1

    def test_icon_gap_produces_listing_task(self) -> None:
        gaps = {"icon": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        listing_tasks = [t for t in tasks if t.id == "listing-readiness"]
        assert len(listing_tasks) == 1
        assert "generate_icon" in listing_tasks[0].description

    def test_validation_task_depends_on_all_fixes(self) -> None:
        gaps = {"cos_tracing": True, "unit_tests": True, "deprecated_apis": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        validate = [t for t in tasks if t.id == "validate-improvements"]
        assert len(validate) == 1
        assert "fill-observability" in validate[0].dependencies
        assert "fill-tests" in validate[0].dependencies
        assert "modernise-code" in validate[0].dependencies

    def test_fix_tasks_depend_on_confirm(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        obs = [t for t in tasks if t.id == "fill-observability"][0]
        assert "confirm-improvements" in obs.dependencies

    def test_all_fix_tasks_use_primary_model(self) -> None:
        gaps = {
            "cos_tracing": True,
            "unit_tests": True,
            "deprecated_apis": True,
            "readme": True,
        }
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        build_tasks = [t for t in tasks if t.category == TaskCategory.BUILD]
        assert all(t.model_hint == ModelHint.PRIMARY for t in build_tasks)

    def test_deploy_verify_task_after_validation(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        deploy = [t for t in tasks if t.id == "deploy-verify-improvements"]
        assert len(deploy) == 1
        assert deploy[0].category == TaskCategory.DEPLOY
        assert "validate-improvements" in deploy[0].dependencies

    def test_diff_review_task_at_end(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        review = [t for t in tasks if t.id == "diff-review"]
        assert len(review) == 1
        assert review[0].category == TaskCategory.RESEARCH
        assert "deploy-verify-improvements" in review[0].dependencies

    def test_no_deploy_or_review_without_fixes(self) -> None:
        gaps: dict[str, bool] = {}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assert not any(t.id == "deploy-verify-improvements" for t in tasks)
        assert not any(t.id == "diff-review" for t in tasks)

    def test_observability_description_mentions_dashboards(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        obs = [t for t in tasks if t.id == "fill-observability"][0]
        assert "Grafana dashboard" in obs.description
        assert "alert rules" in obs.description

    def test_test_fill_description_mentions_jubilant(self) -> None:
        gaps = {"integration_tests": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        test_task = [t for t in tasks if t.id == "fill-tests"][0]
        assert "Jubilant" in test_task.description
        assert "run_charm_tests" in test_task.description

    def test_full_pipeline_task_count(self) -> None:
        """With all gaps, the pipeline has: 4 fixes + validate + deploy + review = 7."""
        gaps = {
            "cos_tracing": True,
            "unit_tests": True,
            "deprecated_apis": True,
            "readme": True,
        }
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assert len(tasks) == 7
        ids = [t.id for t in tasks]
        assert "fill-observability" in ids
        assert "fill-tests" in ids
        assert "modernise-code" in ids
        assert "listing-readiness" in ids
        assert "validate-improvements" in ids
        assert "deploy-verify-improvements" in ids
        assert "diff-review" in ids


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
        ids = [t.id for t in tasks]
        assert ids == ["day2-research", "day2-synthesis", "confirm-day2"]

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
        assert tasks[1].dependencies == ["day2-research"]
        assert tasks[2].dependencies == ["day2-synthesis"]

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
# TestDay2ToBuildPrompt
# ===================================================================


class TestDay2ToBuildPrompt:
    """Tests for the day-2 to build prompt builder."""

    def test_includes_categories(self) -> None:
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        for cat in ("build", "test"):
            assert cat in prompt

    def test_includes_context(self) -> None:
        ctx = PlanningContext(intent="test", charm_name="redis-k8s", dev_model="dev")
        prompt = _build_day2_to_build_prompt(ctx)
        assert "redis-k8s" in prompt
        assert "dev" in prompt

    def test_mentions_operational_areas(self) -> None:
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        prompt_lower = prompt.lower()
        assert "backup" in prompt_lower
        assert "scaling" in prompt_lower
        assert "security" in prompt_lower
        assert "upgrade" in prompt_lower

    def test_mentions_edit_not_rewrite(self) -> None:
        """Day-2 tasks should modify existing charm, not rewrite from scratch."""
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        assert "edit_file" in prompt
        assert "NOT rewrite" in prompt


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
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
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
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
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


# ===================================================================
# TestPlanOperabilityAssessment
# ===================================================================


class TestPlanOperabilityAssessment:
    """Tests for plan_operability_assessment."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="Assess operational readiness",
            charm_name="my-charm",
            existing_charm_path="/charms/my-charm",
        )

    def test_creates_assessment_and_confirm_tasks(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert len(tasks) == 2
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].category == TaskCategory.CONFIRM

    def test_assessment_title_has_prefix(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[0].title.startswith(OPERABILITY_PREFIX)

    def test_confirm_depends_on_assessment(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[1].dependencies == ["assess-operational-readiness"]

    def test_depends_on_parameter(self) -> None:
        tasks = plan_operability_assessment(self._ctx(), depends_on="acceptance-1")
        assert tasks[0].dependencies == ["acceptance-1"]

    def test_no_depends_on(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[0].dependencies == []

    def test_description_mentions_tool(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert "operational_readiness" in tasks[0].description


# ===================================================================
# TestPlanOperabilityFixes
# ===================================================================


class TestPlanOperabilityFixes:
    """Tests for plan_operability_fixes."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="Fix operability gaps",
            charm_name="my-charm",
            existing_charm_path="/charms/my-charm",
        )

    def test_generates_status_task(self) -> None:
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("status" in t.lower() for t in titles)

    def test_generates_action_task(self) -> None:
        findings = {
            "must_fix": ["[Reliability] Health validation mechanism exists"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("action" in t.lower() for t in titles)

    def test_generates_backup_task(self) -> None:
        findings = {"must_fix": [], "should_fix": ["[Reliability] Backup action exists"]}
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("backup" in t.lower() for t in titles)

    def test_generates_security_task(self) -> None:
        findings = {
            "must_fix": ["[Security] Data encryption in transit (TLS)"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("security" in t.lower() for t in titles)

    def test_generates_reassessment_task(self) -> None:
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        assert any("re-assess" in t.title.lower() for t in tasks)

    def test_reassessment_depends_on_all_fixes(self) -> None:
        findings = {
            "must_fix": [
                "[Best Practices] Sets status for missing config",
                "[Reliability] Health validation mechanism exists",
            ],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        reassess = [t for t in tasks if "re-assess" in t.title.lower()]
        assert len(reassess) == 1
        # Should depend on all fix task IDs.
        fix_ids = [t.id for t in tasks if t.id != reassess[0].id]
        assert set(reassess[0].dependencies) == set(fix_ids)

    def test_no_tasks_for_empty_findings(self) -> None:
        findings = {"must_fix": [], "should_fix": []}
        tasks = plan_operability_fixes(self._ctx(), findings)
        assert tasks == []

    def test_fix_tasks_depend_on_confirm(self) -> None:
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        fix_tasks = [t for t in tasks if "re-assess" not in t.title.lower()]
        for t in fix_tasks:
            assert "confirm-operability" in t.dependencies

    def test_all_fix_tasks_use_primary_model(self) -> None:
        findings = {
            "must_fix": [
                "[Best Practices] Sets status for missing config",
                "[Reliability] Backup action exists",
            ],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        for t in tasks:
            assert t.model_hint == ModelHint.PRIMARY
