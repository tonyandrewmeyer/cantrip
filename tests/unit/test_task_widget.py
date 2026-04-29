"""Tests for the TaskChecklistWidget."""

from datetime import datetime

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.tui.widgets.tasks import (
    _CATEGORY_ORDER,
    TaskChecklistWidget,
    _format_detail,
    _status_display,
)

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Pure logic tests
# ---------------------------------------------------------------------------


class TestStatusDisplay:
    """Test the _status_display helper for all five statuses."""

    def test_pending(self):
        char, css = _status_display(TaskStatus.PENDING)
        assert char == "\u25cb"
        assert css == "task-pending"

    def test_active(self):
        char, css = _status_display(TaskStatus.ACTIVE)
        assert char == "\u27f3"
        assert css == "task-active"

    def test_done(self):
        char, css = _status_display(TaskStatus.DONE)
        assert char == "\u2713"
        assert css == "task-done"

    def test_failed(self):
        char, css = _status_display(TaskStatus.FAILED)
        assert char == "\u2717"
        assert css == "task-failed"

    def test_blocked(self):
        char, css = _status_display(TaskStatus.BLOCKED)
        assert char == "\u25cc"
        assert css == "task-blocked"


# ---------------------------------------------------------------------------
# Headless Textual tests
# ---------------------------------------------------------------------------


def _make_task(
    title: str = "Test task",
    status: TaskStatus = TaskStatus.PENDING,
    category: TaskCategory = TaskCategory.BUILD,
    result: str | None = None,
    description: str = "",
    task_id: str = "",
    subagent_phase: str = "",
    subagent_started_at: datetime | None = None,
) -> AgentTask:
    """Create a minimal AgentTask for testing."""
    task = AgentTask(
        id=task_id,
        title=title,
        category=category,
        status=status,
        description=description,
        created_at=datetime(2025, 1, 1),
    )
    task.result = result
    task.subagent_phase = subagent_phase
    task.subagent_started_at = subagent_started_at
    return task


# ---------------------------------------------------------------------------
# Pure format_detail tests
# ---------------------------------------------------------------------------


class TestFormatDetail:
    """Tests for the _format_detail helper."""

    def test_includes_category(self):
        task = _make_task(category=TaskCategory.RESEARCH)
        detail = _format_detail(task)
        assert "research" in detail

    def test_includes_status(self):
        task = _make_task(status=TaskStatus.DONE)
        detail = _format_detail(task)
        assert "done" in detail

    def test_includes_result(self):
        task = _make_task(result="Charm built successfully")
        detail = _format_detail(task)
        assert "Charm built successfully" in detail

    def test_includes_description(self):
        task = _make_task(description="Scaffold the charm")
        detail = _format_detail(task)
        assert "Scaffold the charm" in detail

    def test_truncates_long_result(self):
        task = _make_task(result="x" * 300)
        detail = _format_detail(task)
        assert "..." in detail
        assert len(detail) < 350

    def test_includes_blocked_reason(self):
        task = _make_task(status=TaskStatus.BLOCKED)
        task.blocked_reason = "Waiting for user"
        detail = _format_detail(task)
        assert "Waiting for user" in detail

    def test_includes_worktree_path_when_set(self):
        task = _make_task()
        task.worktree_path = "/tmp/charm/.cantrip-worktrees/t1"
        detail = _format_detail(task)
        assert "Worktree:" in detail
        assert "/tmp/charm/.cantrip-worktrees/t1" in detail

    def test_omits_worktree_row_when_not_set(self):
        task = _make_task()
        detail = _format_detail(task)
        assert "Worktree" not in detail


class _ChecklistApp:
    """Tiny Textual app that hosts a single TaskChecklistWidget."""

    @staticmethod
    def build():
        from textual.app import App, ComposeResult

        class _App(App):
            def compose(self) -> ComposeResult:
                yield TaskChecklistWidget(id="task-checklist")

        return _App()


class TestTaskChecklistWidget:
    """Headless tests for TaskChecklistWidget."""

    @pytest.mark.asyncio
    async def test_empty_state_shows_placeholder(self):
        """With no tasks the widget shows 'No tasks yet.'."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            assert "No tasks yet." in combined

    @pytest.mark.asyncio
    async def test_notify_changed_triggers_refresh(self):
        """Calling notify_changed causes tasks to appear after the timer fires."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [_make_task("Research workload"), _make_task("Build charm")]
            checklist.notify_changed(tasks)
            # Allow the 0.5s timer to fire.
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            assert "Research workload" in combined
            assert "Build charm" in combined

    @pytest.mark.asyncio
    async def test_tasks_available_posted_on_first_task(self):
        """TasksAvailable message is posted when tasks first appear."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        messages_received: list[TaskChecklistWidget.TasksAvailable] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield TaskChecklistWidget(id="task-checklist")
                yield Static(id="sentinel")

            def on_task_checklist_widget_tasks_available(
                self, event: TaskChecklistWidget.TasksAvailable
            ) -> None:
                messages_received.append(event)

        app = _App()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.notify_changed([_make_task("First task")])
            await pilot.pause(delay=0.7)
            assert len(messages_received) == 1

    @pytest.mark.asyncio
    async def test_tasks_available_posted_only_once(self):
        """TasksAvailable is only fired on the first appearance of tasks."""
        from textual.app import App, ComposeResult
        from textual.widgets import Static

        messages_received: list[TaskChecklistWidget.TasksAvailable] = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield TaskChecklistWidget(id="task-checklist")
                yield Static(id="sentinel")

            def on_task_checklist_widget_tasks_available(
                self, event: TaskChecklistWidget.TasksAvailable
            ) -> None:
                messages_received.append(event)

        app = _App()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.notify_changed([_make_task("First")])
            await pilot.pause(delay=0.7)
            checklist.notify_changed([_make_task("First"), _make_task("Second")])
            await pilot.pause(delay=0.7)
            assert len(messages_received) == 1

    @pytest.mark.asyncio
    async def test_status_indicators_in_output(self):
        """Status indicator characters appear in the rendered output."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task("Pending task", status=TaskStatus.PENDING),
                _make_task("Active task", status=TaskStatus.ACTIVE),
                _make_task("Done task", status=TaskStatus.DONE),
                _make_task("Failed task", status=TaskStatus.FAILED),
                _make_task("Blocked task", status=TaskStatus.BLOCKED),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            # Check each indicator character is present.
            assert "\u25cb" in combined  # ○ pending
            assert "\u27f3" in combined  # ⟳ active
            assert "\u2713" in combined  # ✓ done
            assert "\u2717" in combined  # ✗ failed
            assert "\u25cc" in combined  # ◌ blocked

    @pytest.mark.asyncio
    async def test_long_titles_shown_in_full(self):
        """Long titles are shown without truncation."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            long_title = "A" * 60
            checklist.notify_changed([_make_task(long_title)])
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            assert long_title in combined

    @pytest.mark.asyncio
    async def test_toggle_detail_shows_result(self):
        """Toggling a task shows its detail including result text."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            task = _make_task(
                "Build charm",
                task_id="b1",
                result="Charm built ok",
                status=TaskStatus.DONE,
            )
            checklist.notify_changed([task])
            await pilot.pause(delay=0.7)

            # Expand by calling _toggle_detail directly.
            checklist._toggle_detail("b1")
            await pilot.pause(delay=0.1)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            assert "Charm built ok" in combined

    @pytest.mark.asyncio
    async def test_toggle_detail_collapses(self):
        """Toggling the same task twice collapses the detail."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            task = _make_task(
                "Build charm",
                task_id="b1",
                result="Charm built ok",
                status=TaskStatus.DONE,
            )
            checklist.notify_changed([task])
            await pilot.pause(delay=0.7)

            # Expand then collapse.
            checklist._toggle_detail("b1")
            await pilot.pause(delay=0.1)
            checklist._toggle_detail("b1")
            await pilot.pause(delay=0.1)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            assert "Charm built ok" not in combined

    @pytest.mark.asyncio
    async def test_clicking_detail_collapses_task(self):
        """A click anywhere on the expanded detail block collapses the task.

        The user expects the whole expanded block to act like the row —
        clicking ``Status: done`` (in the detail body, below the title
        line) should collapse the task, not be inert.
        """
        from cantrip.tui.widgets.tasks import _TaskDetail

        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            task = _make_task(
                "Build charm",
                task_id="b1",
                result="Charm built ok",
                status=TaskStatus.DONE,
            )
            checklist.notify_changed([task])
            await pilot.pause(delay=0.7)

            checklist._toggle_detail("b1")
            await pilot.pause(delay=0.1)
            assert checklist._expanded_id == "b1"

            # Click on the detail block, not the row.
            await pilot.click(_TaskDetail)
            await pilot.pause(delay=0.1)
            assert checklist._expanded_id is None

    @pytest.mark.asyncio
    async def test_tasks_grouped_by_category(self):
        """Tasks are grouped under category headers in display order."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task("Deploy app", category=TaskCategory.DEPLOY),
                _make_task("Analyse workload", category=TaskCategory.RESEARCH),
                _make_task("Scaffold charm", category=TaskCategory.BUILD),
                _make_task("Run unit tests", category=TaskCategory.TEST),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            texts = [str(s.render()) for s in statics]
            combined = " ".join(texts)

            # Category headers appear.
            assert "Research" in combined
            assert "Build" in combined
            assert "Deploy" in combined
            assert "Test" in combined

            # Research appears before Build, Build before Deploy, Deploy before Test.
            research_idx = next(i for i, t in enumerate(texts) if t == "Research")
            build_idx = next(i for i, t in enumerate(texts) if t == "Build")
            deploy_idx = next(i for i, t in enumerate(texts) if t == "Deploy")
            test_idx = next(i for i, t in enumerate(texts) if t == "Test")
            assert research_idx < build_idx < deploy_idx < test_idx

    @pytest.mark.asyncio
    async def test_empty_categories_omitted(self):
        """Categories with no tasks do not get a header."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [_make_task("Build it", category=TaskCategory.BUILD)]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)

            assert "Build" in combined
            # No other category headers should appear.
            for cat, label in _CATEGORY_ORDER:
                if cat != TaskCategory.BUILD:
                    assert label not in combined, f"Unexpected header: {label}"

    @pytest.mark.asyncio
    async def test_active_task_pinned_to_top(self):
        """ACTIVE tasks appear under 'In progress' ahead of category groups."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task(
                    "Research docs",
                    status=TaskStatus.PENDING,
                    category=TaskCategory.RESEARCH,
                ),
                _make_task(
                    "Scaffold charm",
                    status=TaskStatus.ACTIVE,
                    category=TaskCategory.BUILD,
                ),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            texts = [str(s.render()) for s in statics]
            combined = " ".join(texts)

            assert "In progress" in combined
            # "In progress" header must come before any category header.
            progress_idx = texts.index("In progress")
            research_idx = texts.index("Research")
            assert progress_idx < research_idx
            # The active task is tagged with its category for context.
            assert any("Build" in t and "Scaffold charm" in t for t in texts)
            # Pinned header carries its own emphasis class so it doesn't
            # blend into the category-header column below it.
            pinned_header = next(s for s in statics if str(s.render()) == "In progress")
            assert "task-pinned-header" in pinned_header.classes
            assert "task-header" not in pinned_header.classes

    @pytest.mark.asyncio
    async def test_active_task_not_duplicated_in_category(self):
        """An active task shown in 'In progress' does not also render in its category."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task(
                    "Scaffold charm",
                    status=TaskStatus.ACTIVE,
                    category=TaskCategory.BUILD,
                ),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            texts = [str(s.render()) for s in statics]
            # Only one row contains the task title (in the pinned section).
            matches = [t for t in texts if "Scaffold charm" in t]
            assert len(matches) == 1
            # And the Build category header is NOT rendered, since the only
            # task in it is pinned.
            assert "Build" not in texts

    @pytest.mark.asyncio
    async def test_fully_done_category_collapses(self):
        """A category whose tasks are all DONE collapses to a summary row."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task("Analyse", status=TaskStatus.DONE, category=TaskCategory.RESEARCH),
                _make_task("Survey", status=TaskStatus.DONE, category=TaskCategory.RESEARCH),
                _make_task(
                    "Scaffold",
                    status=TaskStatus.PENDING,
                    category=TaskCategory.BUILD,
                ),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            texts = [str(s.render()) for s in statics]
            combined = " ".join(texts)
            # Individual research titles are hidden behind the summary.
            assert "Analyse" not in combined
            assert "Survey" not in combined
            # The collapsed row is self-describing: "Research" appears in the
            # summary row text, *not* as a separate header above it.  And no
            # divider precedes it either.
            assert "✓ Research · 2 tasks done" in texts
            assert "Research" not in texts, "Collapsed category must not render a separate header"
            # The Research collapsed row should sit at the head of the list
            # — no header or divider in front of it.
            research_idx = texts.index("✓ Research · 2 tasks done")
            assert texts[research_idx - 1] != "─" * 20 if research_idx > 0 else True
            # Build is still rendered normally.
            assert "Scaffold" in combined
            assert "Build" in texts  # header still present for the open category

    @pytest.mark.asyncio
    async def test_mixed_category_renders_normally(self):
        """A category with DONE + PENDING tasks is NOT collapsed."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task("First done", status=TaskStatus.DONE, category=TaskCategory.BUILD),
                _make_task("Next up", status=TaskStatus.PENDING, category=TaskCategory.BUILD),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            # Both titles visible; no "done" summary row.
            assert "First done" in combined
            assert "Next up" in combined
            assert "tasks done (click to show)" not in combined

    @pytest.mark.asyncio
    async def test_subagent_phase_line_under_active_task(self):
        """An active task with a subagent phase shows a secondary status line."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            task = _make_task(
                "Scaffold charm",
                status=TaskStatus.ACTIVE,
                category=TaskCategory.BUILD,
                subagent_phase="running: charmcraft_init",
                subagent_started_at=datetime.now(),
            )
            checklist.notify_changed([task])
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "running: charmcraft_init" in combined
            # The phase line is under the pinned title row.
            assert "Scaffold charm" in combined

    @pytest.mark.asyncio
    async def test_subagent_phase_absent_when_empty(self):
        """A task without a subagent phase does not render the secondary line."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            task = _make_task(
                "Scaffold charm",
                status=TaskStatus.ACTIVE,
                category=TaskCategory.BUILD,
            )
            checklist.notify_changed([task])
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            # No " └ " phase-indent marker present.
            assert "\u2514" not in combined

    @pytest.mark.asyncio
    async def test_collapsed_group_expands_on_toggle(self):
        """Toggling a collapsed group reveals its tasks."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            tasks = [
                _make_task("Analyse", status=TaskStatus.DONE, category=TaskCategory.RESEARCH),
            ]
            checklist.notify_changed(tasks)
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "Analyse" not in combined

            checklist._toggle_group(TaskCategory.RESEARCH)
            await pilot.pause(delay=0.1)

            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "Analyse" in combined
