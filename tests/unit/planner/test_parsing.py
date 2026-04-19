"""Planner tests: parsing."""

import json

import pytest

from cantrip.agent.planner import (
    _extract_json,
    _merge_tasks,
    _parse_task_list,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

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

    def test_missing_title_skipped(self) -> None:
        """A single untitled item is skipped; the whole plan then has no tasks."""
        raw = json.dumps([{"id": "x", "category": "build"}])
        with pytest.raises(ValueError, match="No valid tasks"):
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
