"""Planner tests: parsing.

The Phase 73.3 migration moved planner replies onto :func:`cantrip.llm.
structured.complete_structured` against :data:`~cantrip.llm.schemas.
PLANNER_BRIEFING`.  Schema enforcement covers JSON parsing, fence
stripping, the top-level ``{"tasks": [...]}`` shape, and per-item
required keys / category enum — those used to live in
``_extract_json`` / ``_parse_task_list`` / ``_parse_single_task`` and
no longer need module-level coverage here.

What this file does cover is everything the schema does **not**:
the conversion from a validated briefing dict into ``AgentTask``
objects, dependency sanitisation (cycle detection, dropping
references to unknown ids), and ``_merge_tasks``.
"""

from cantrip.agent.planner import (
    _briefing_to_tasks,
    _merge_tasks,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

# ===================================================================
# TestBriefingToTasks
# ===================================================================


class TestBriefingToTasks:
    """Tests for ``_briefing_to_tasks`` — briefing-dict → AgentTask list."""

    def test_valid_briefing(self) -> None:
        briefing = {
            "tasks": [
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
                    "description": "Run charmcraft init.",
                    "dependencies": ["research"],
                },
            ]
        }
        tasks = _briefing_to_tasks(briefing)
        assert len(tasks) == 2
        assert tasks[0].title == "Research the workload"
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[0].dependencies == []
        assert tasks[1].dependencies == ["research"]
        assert tasks[1].category == TaskCategory.BUILD

    def test_empty_tasks_array(self) -> None:
        """A schema-valid briefing with no tasks returns an empty list."""
        assert _briefing_to_tasks({"tasks": []}) == []

    def test_missing_optional_fields(self) -> None:
        """``id``, ``description``, and ``dependencies`` default sensibly."""
        briefing = {"tasks": [{"title": "Just a title", "category": "build"}]}
        tasks = _briefing_to_tasks(briefing)
        assert len(tasks) == 1
        # ``AgentTask.__post_init__`` fills in a uuid hex when no id is provided.
        assert tasks[0].id
        assert tasks[0].title == "Just a title"
        assert tasks[0].description == ""
        assert tasks[0].dependencies == []

    def test_dependencies_coerced_to_strings(self) -> None:
        """Numeric dependencies (rare, but seen in the wild) are stringified."""
        briefing = {
            "tasks": [
                {"id": "a", "title": "A", "category": "build", "dependencies": [1, 2]},
            ]
        }
        tasks = _briefing_to_tasks(briefing)
        # The numeric deps reference unknown task ids and are stripped by
        # `_validate_dependencies` after coercion to strings.
        assert tasks[0].dependencies == []

    def test_unknown_dependency_stripped(self) -> None:
        """Dependencies referencing missing task ids are dropped with a warning."""
        briefing = {
            "tasks": [
                {
                    "id": "a",
                    "title": "First",
                    "category": "build",
                    "dependencies": ["nonexistent"],
                },
            ]
        }
        tasks = _briefing_to_tasks(briefing)
        assert tasks[0].dependencies == []

    def test_dependency_cycle_broken(self) -> None:
        """A cycle is detected and broken rather than raising."""
        briefing = {
            "tasks": [
                {"id": "a", "title": "A", "category": "build", "dependencies": ["b"]},
                {"id": "b", "title": "B", "category": "build", "dependencies": ["a"]},
            ]
        }
        tasks = _briefing_to_tasks(briefing)
        assert len(tasks) == 2
        # All cycle members shed their cyclic dependencies.
        assert tasks[0].dependencies == []
        assert tasks[1].dependencies == []


# ===================================================================
# TestMergeTasks
# ===================================================================


class TestMergeTasks:
    """Tests for ``_merge_tasks`` — combining existing and new tasks."""

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
