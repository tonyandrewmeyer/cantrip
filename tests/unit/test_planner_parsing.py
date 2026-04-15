"""Tests for planner task parsing, path qualification, and day-2 anchor."""

import pytest

from cantrip.agent.planner import (
    PlanningContext,
    _extract_json,
    _parse_single_task,
    _parse_task_list,
    find_day2_anchor,
    is_fast_path,
    is_one_shot_build,
    is_sprint,
    plan_one_shot_build,
)
from cantrip.agent.queue import AgentTask, TaskCategory


class TestExtractJson:
    """Tests for _extract_json markdown fence stripping."""

    def test_no_fences(self):
        raw = '[{"title": "Test"}]'
        assert _extract_json(raw) == raw

    def test_json_fences(self):
        raw = '```json\n[{"title": "Test"}]\n```'
        assert _extract_json(raw) == '[{"title": "Test"}]'

    def test_plain_fences(self):
        raw = '```\n[{"title": "Test"}]\n```'
        assert _extract_json(raw) == '[{"title": "Test"}]'

    def test_surrounding_text_stripped(self):
        raw = 'Here is the plan:\n```json\n[{"title": "x"}]\n```\nDone.'
        assert _extract_json(raw) == '[{"title": "x"}]'

    def test_whitespace_stripped(self):
        raw = "   [1, 2, 3]   "
        assert _extract_json(raw) == "[1, 2, 3]"


class TestParseTaskList:
    """Tests for _parse_task_list JSON parsing."""

    def test_valid_array(self):
        raw = '[{"id": "a", "title": "Do A", "category": "build", "dependencies": []}]'
        tasks = _parse_task_list(raw)
        assert len(tasks) == 1
        assert tasks[0].title == "Do A"
        assert tasks[0].category == TaskCategory.BUILD

    def test_wrapped_in_tasks_key(self):
        raw = '{"tasks": [{"id": "a", "title": "Do A"}]}'
        tasks = _parse_task_list(raw)
        assert len(tasks) == 1

    def test_markdown_fences(self):
        raw = '```json\n[{"id": "a", "title": "Do A"}]\n```'
        tasks = _parse_task_list(raw)
        assert len(tasks) == 1

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_task_list("not valid json {{{")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_task_list("")

    def test_dict_without_tasks_key_raises(self):
        with pytest.raises(ValueError, match="Expected"):
            _parse_task_list('{"foo": "bar"}')

    def test_non_list_raises(self):
        with pytest.raises(ValueError, match="Expected"):
            _parse_task_list('"just a string"')

    def test_multiple_tasks(self):
        raw = (
            '[{"id": "a", "title": "First", "category": "research"},'
            ' {"id": "b", "title": "Second", "category": "build", "dependencies": ["a"]}]'
        )
        tasks = _parse_task_list(raw)
        assert len(tasks) == 2
        assert tasks[1].dependencies == ["a"]


class TestParseSingleTask:
    """Tests for _parse_single_task validation."""

    def test_valid_task(self):
        item = {
            "id": "test",
            "title": "Test task",
            "category": "build",
            "description": "A test",
            "dependencies": ["dep1"],
        }
        task = _parse_single_task(item, 0)
        assert task.id == "test"
        assert task.title == "Test task"
        assert task.category == TaskCategory.BUILD
        assert task.dependencies == ["dep1"]

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="index 2"):
            _parse_single_task("not a dict", 2)  # type: ignore[arg-type]

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="missing a title"):
            _parse_single_task({"id": "x"}, 0)

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="missing a title"):
            _parse_single_task({"id": "x", "title": ""}, 0)

    def test_unknown_category_defaults_to_build(self):
        task = _parse_single_task({"title": "T", "category": "magic"}, 0)
        assert task.category == TaskCategory.BUILD

    def test_missing_category_defaults_to_build(self):
        task = _parse_single_task({"title": "T"}, 0)
        assert task.category == TaskCategory.BUILD

    def test_non_list_dependencies_default_to_empty(self):
        task = _parse_single_task({"title": "T", "dependencies": "not-a-list"}, 0)
        assert task.dependencies == []

    def test_dependencies_coerced_to_strings(self):
        task = _parse_single_task({"title": "T", "dependencies": [1, 2]}, 0)
        assert task.dependencies == ["1", "2"]

    def test_missing_id_generates_something(self):
        """A task without an explicit ID still gets an ID assigned."""
        task = _parse_single_task({"title": "T"}, 0)
        assert task.id  # Non-empty — a hash or slug is generated.

    def test_category_case_insensitive(self):
        task = _parse_single_task({"title": "T", "category": "RESEARCH"}, 0)
        assert task.category == TaskCategory.RESEARCH


class TestPathQualification:
    """Tests for is_fast_path, is_sprint, is_one_shot_build."""

    def test_fast_path_flask(self):
        ctx = PlanningContext(intent="build", framework="Flask")
        assert is_fast_path(ctx) is True

    def test_fast_path_django(self):
        ctx = PlanningContext(intent="build", framework="Django")
        assert is_fast_path(ctx) is True

    def test_fast_path_with_source_url_false(self):
        ctx = PlanningContext(intent="build", framework="Flask", source_url="https://x.com")
        assert is_fast_path(ctx) is False

    def test_fast_path_unknown_framework(self):
        ctx = PlanningContext(intent="build", framework="obscure-lang")
        assert is_fast_path(ctx) is False

    def test_fast_path_no_framework(self):
        ctx = PlanningContext(intent="build")
        assert is_fast_path(ctx) is False

    def test_sprint_flask(self):
        ctx = PlanningContext(intent="build", framework="flask")
        assert is_sprint(ctx) is True

    def test_sprint_explicit_type_and_name(self):
        ctx = PlanningContext(intent="build", charm_type="kubernetes", charm_name="myapp")
        assert is_sprint(ctx) is True

    def test_sprint_with_source_url_false(self):
        ctx = PlanningContext(
            intent="build",
            charm_type="kubernetes",
            charm_name="myapp",
            source_url="https://x.com",
        )
        assert is_sprint(ctx) is False

    def test_sprint_no_framework_no_type(self):
        ctx = PlanningContext(intent="build")
        assert is_sprint(ctx) is False

    def test_one_shot_build_flask(self):
        ctx = PlanningContext(intent="build", framework="flask")
        assert is_one_shot_build(ctx) is True

    def test_one_shot_build_with_source_url_still_true(self):
        """one_shot_build doesn't check source_url (unlike fast_path)."""
        ctx = PlanningContext(intent="build", framework="flask", source_url="https://x.com")
        assert is_one_shot_build(ctx) is True

    def test_one_shot_build_no_framework(self):
        ctx = PlanningContext(intent="build")
        assert is_one_shot_build(ctx) is False


class TestPlanOneShotBuild:
    """Tests for plan_one_shot_build."""

    def test_produces_single_task(self):
        ctx = PlanningContext(intent="build", framework="Flask", charm_name="myapp")
        tasks = plan_one_shot_build(ctx, "design doc here")
        assert len(tasks) == 1
        assert tasks[0].id.startswith("one-shot-build-")
        assert tasks[0].category == TaskCategory.BUILD
        assert "Flask" in tasks[0].description
        assert "design doc here" in tasks[0].description

    def test_uses_charm_name_in_title(self):
        ctx = PlanningContext(intent="build", framework="fastapi", charm_name="api-svc")
        tasks = plan_one_shot_build(ctx, "")
        assert "api-svc" in tasks[0].title

    def test_no_dependencies(self):
        ctx = PlanningContext(intent="build", framework="flask")
        tasks = plan_one_shot_build(ctx, "")
        assert tasks[0].dependencies == []


class TestFindDay2Anchor:
    """Tests for find_day2_anchor."""

    def test_empty_list_returns_none(self):
        assert find_day2_anchor([]) is None

    def test_last_deploy_task(self):
        tasks = [
            AgentTask(id="build", title="Build", category=TaskCategory.BUILD),
            AgentTask(id="deploy", title="Deploy", category=TaskCategory.DEPLOY),
            AgentTask(id="test", title="Test", category=TaskCategory.TEST),
        ]
        assert find_day2_anchor(tasks) == "test"

    def test_deploy_before_test(self):
        tasks = [
            AgentTask(id="build", title="Build", category=TaskCategory.BUILD),
            AgentTask(id="test", title="Test", category=TaskCategory.TEST),
            AgentTask(id="deploy", title="Deploy", category=TaskCategory.DEPLOY),
        ]
        assert find_day2_anchor(tasks) == "deploy"

    def test_no_deploy_or_test_falls_back_to_last(self):
        tasks = [
            AgentTask(id="build1", title="Build 1", category=TaskCategory.BUILD),
            AgentTask(id="build2", title="Build 2", category=TaskCategory.BUILD),
        ]
        assert find_day2_anchor(tasks) == "build2"

    def test_single_deploy_task(self):
        tasks = [
            AgentTask(id="deploy", title="Deploy", category=TaskCategory.DEPLOY),
        ]
        assert find_day2_anchor(tasks) == "deploy"

    def test_single_build_task(self):
        tasks = [
            AgentTask(id="build", title="Build", category=TaskCategory.BUILD),
        ]
        assert find_day2_anchor(tasks) == "build"
