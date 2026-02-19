"""Tests for the TaskChecklistWidget."""

from datetime import datetime

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.tui.widgets.tasks import TaskChecklistWidget, _format_detail, _status_display

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
    async def test_long_titles_truncated(self):
        """Titles longer than 40 characters are truncated with an ellipsis."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            long_title = "A" * 60
            checklist.notify_changed([_make_task(long_title)])
            await pilot.pause(delay=0.7)

            container = checklist.query_one("#task-container")
            statics = container.query("Static")
            combined = " ".join(str(s.render()) for s in statics)
            # The full 60-char title should not appear.
            assert long_title not in combined
            # The truncated version (39 chars + ellipsis) should be present.
            assert "\u2026" in combined

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
