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
    """Tests for TaskPlanner.plan() with FakeProvider."""

    @pytest.mark.asyncio
    async def test_plan_returns_tasks(self) -> None:
        provider = FakeProvider(responses=[Response(content=VALID_TASKS_JSON)])
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build a charm for Redis")

        tasks = await planner.plan(context)

        assert len(tasks) == 2
        assert tasks[0].title == "Research the workload"

    @pytest.mark.asyncio
    async def test_plan_raises_on_bad_response(self) -> None:
        provider = FakeProvider(responses=[Response(content="I cannot do that.")])
        planner = TaskPlanner(provider)
        context = PlanningContext(intent="Build a charm for Redis")

        with pytest.raises(ValueError):
            await planner.plan(context)

    @pytest.mark.asyncio
    async def test_plan_uses_low_temperature(self) -> None:
        """Verify the planner passes temperature=0.3 to the provider."""
        recorded_temp: list[float] = []

        class RecordingProvider(FakeProvider):
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                recorded_temp.append(temperature)
                return Response(content="[]")

        provider = RecordingProvider()
        planner = TaskPlanner(provider)
        await planner.plan(PlanningContext(intent="test"))

        assert recorded_temp == [0.3]


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
        provider = FakeProvider(responses=[Response(content=VALID_TASKS_JSON)])
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert result.success
        assert queue.pending_count == 2
        assert result.data["task_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_formatted_summary(self) -> None:
        provider = FakeProvider(responses=[Response(content=VALID_TASKS_JSON)])
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build a charm for Redis")

        assert "Task plan" in result.output
        assert "Research the workload" in result.output
        assert "Scaffold the charm" in result.output
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
    async def test_handles_planning_failure(self) -> None:
        provider = FakeProvider(responses=[Response(content="not json")])
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build something")

        assert not result.success
        assert result.error is not None and "Failed" in result.error

    @pytest.mark.asyncio
    async def test_uses_state_context(self) -> None:
        provider = FakeProvider(responses=[Response(content="[]")])
        state = AgentState(
            charm_name="my-charm",
            charm_type="k8s",
            framework="flask",
        )
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        result = await tool.execute(intent="Build the charm")

        assert result.success

    @pytest.mark.asyncio
    async def test_replans_when_tasks_exist(self) -> None:
        """When the queue already has tasks, the tool should replan."""
        first_json = json.dumps(
            [
                {"id": "old", "title": "Old task", "category": "research"},
            ]
        )
        second_json = json.dumps(
            [
                {"id": "new", "title": "New task", "category": "build"},
            ]
        )
        provider = FakeProvider(
            responses=[
                Response(content=first_json),
                Response(content=second_json),
            ]
        )
        state = AgentState()
        queue = WorkQueue()
        tool = PlanTasksTool(provider=provider, state=state, queue=queue)

        # First plan.
        await tool.execute(intent="Build a charm for Redis")
        assert queue.pending_count == 1

        # Second plan (replanning) — old pending task dropped, new one added.
        result = await tool.execute(intent="Actually, target machine")
        assert result.success


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
