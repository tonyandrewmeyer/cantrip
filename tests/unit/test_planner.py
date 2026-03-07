"""Tests for the task planner and PlanTasksTool."""

import json

import pytest

from cantrip.agent.planner import (
    PlanningContext,
    TaskPlanner,
    _build_design_to_build_prompt,
    _build_planning_prompt,
    _build_replanning_prompt,
    _extract_json,
    _merge_tasks,
    _parse_task_list,
    is_fast_path,
    plan_fast_path,
    plan_research_phase,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
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
    async def test_fast_path_for_known_framework(self) -> None:
        """Known 12-factor frameworks skip research, producing only 2 tasks."""
        provider = FakeProvider()
        planner = TaskPlanner(provider)
        context = PlanningContext(
            intent="Build a charm for my Flask app",
            charm_name="my-flask-app",
            framework="flask",
        )

        tasks = await planner.plan(context)

        assert len(tasks) == 2
        assert tasks[0].id == "fast-design"
        assert tasks[1].id == "confirm-design"
        assert "flask" in tasks[0].description.lower()

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
