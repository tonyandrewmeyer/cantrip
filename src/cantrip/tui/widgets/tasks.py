"""Task checklist widget for the TUI."""

import threading
from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from cantrip.agent.preflight import CheckStatus
from cantrip.agent.queue import AgentTask, TaskStatus

# Status indicator characters and CSS classes per task status.
_STATUS_DISPLAY: dict[TaskStatus, tuple[str, str]] = {
    TaskStatus.PENDING: ("\u25cb", "task-pending"),  # ○
    TaskStatus.ACTIVE: ("\u27f3", "task-active"),  # ⟳
    TaskStatus.DONE: ("\u2713", "task-done"),  # ✓
    TaskStatus.FAILED: ("\u2717", "task-failed"),  # ✗
    TaskStatus.BLOCKED: ("\u25cc", "task-blocked"),  # ◌
}

# Reuse the same visual indicators for preflight checks.
_CHECK_STATUS_DISPLAY: dict[CheckStatus, tuple[str, str]] = {
    CheckStatus.PENDING: ("\u25cb", "task-pending"),  # ○
    CheckStatus.RUNNING: ("\u27f3", "task-active"),  # ⟳
    CheckStatus.PASSED: ("\u2713", "task-done"),  # ✓
    CheckStatus.FAILED: ("\u2717", "task-failed"),  # ✗
    CheckStatus.SKIPPED: ("\u2713", "task-done"),  # ✓
}


@dataclass
class _PreflightGroup:
    """A group of preflight environment checks."""

    title: str
    items: list[tuple[str, CheckStatus]] = field(default_factory=list)


def _status_display(status: TaskStatus) -> tuple[str, str]:
    """Return ``(indicator_char, css_class)`` for a task status."""
    return _STATUS_DISPLAY.get(status, ("\u25cb", "task-pending"))


def _format_detail(task: AgentTask) -> str:
    """Build the detail text shown when a task row is expanded."""
    lines: list[str] = []
    lines.append(f"  Category: {task.category.value}")
    lines.append(f"  Status: {task.status.value}")
    if task.blocked_reason:
        lines.append(f"  Blocked: {task.blocked_reason}")
    if task.result:
        # Truncate very long results for the panel.
        result = task.result
        if len(result) > 200:
            result = result[:197] + "..."
        lines.append(f"  Result: {result}")
    if task.description:
        desc = task.description
        if len(desc) > 200:
            desc = desc[:197] + "..."
        lines.append(f"  Info: {desc}")
    return "\n".join(lines)


class _TaskRow(Static):
    """A clickable task row that toggles detail expansion."""

    def __init__(self, task_id: str, content: str, **kwargs: object) -> None:
        super().__init__(content, **kwargs)
        self.task_id = task_id


class TaskChecklistWidget(Widget):
    """Live checklist of autonomous agent tasks.

    Designed for placement in the right panel above ``JujuStatusWidget``.
    Uses an imperative refresh pattern: the ``notify_changed`` method is
    called from any thread (e.g. the executor callback) and sets a dirty
    flag; a 0.5 s timer polls the flag and rebuilds the display.

    Click a task row to expand/collapse its detail (result, category, etc.).
    """

    class TasksAvailable(Message):
        """Posted once when the first task appears (reveals the right panel)."""

    DEFAULT_CSS = """
    TaskChecklistWidget {
        height: auto;
        max-height: 50%;
        padding: 1;
    }

    TaskChecklistWidget .task-header {
        text-style: bold;
        margin-bottom: 1;
    }

    TaskChecklistWidget .task-divider {
        color: $primary;
        margin-bottom: 1;
    }

    TaskChecklistWidget .task-pending {
        color: $text-muted;
    }

    TaskChecklistWidget .task-active {
        color: $primary;
    }

    TaskChecklistWidget .task-done {
        color: $success;
    }

    TaskChecklistWidget .task-failed {
        color: $error;
    }

    TaskChecklistWidget .task-blocked {
        color: $warning;
    }

    TaskChecklistWidget .task-empty {
        color: $text-muted;
        text-style: italic;
    }

    TaskChecklistWidget .task-detail {
        color: $text-muted;
        margin-left: 2;
        margin-bottom: 1;
    }

    TaskChecklistWidget .task-row {
        height: auto;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        """Initialise the checklist widget."""
        super().__init__(**kwargs)
        self._tasks: list[AgentTask] = []
        self._preflight_groups: list[_PreflightGroup] = []
        self._dirty = False
        self._lock = threading.Lock()
        self._tasks_available_posted = False
        self._expanded_id: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the initial layout."""
        yield Vertical(id="task-container")

    def on_mount(self) -> None:
        """Start the refresh timer on mount."""
        self.set_interval(0.5, self._check_dirty)
        self._refresh_display()

    def add_preflight_group(self, title: str, items: list[str]) -> int:
        """Add a group of preflight checks and return its index.

        Call from the main thread (e.g. during ``on_mount``).
        """
        with self._lock:
            group = _PreflightGroup(
                title=title,
                items=[(label, CheckStatus.PENDING) for label in items],
            )
            self._preflight_groups.append(group)
            self._dirty = True
            return len(self._preflight_groups) - 1

    def update_preflight(self, group_idx: int, item_idx: int, status: CheckStatus) -> None:
        """Update the status of a preflight check item.

        Thread-safe — called from preflight worker callbacks.
        """
        with self._lock:
            group = self._preflight_groups[group_idx]
            label, _old = group.items[item_idx]
            group.items[item_idx] = (label, status)
            self._dirty = True

    def notify_changed(self, tasks: list[AgentTask]) -> None:
        """Thread-safe notification that tasks have changed.

        Called from the executor's ``on_task_changed`` callback, which may
        fire on any thread.
        """
        with self._lock:
            self._tasks = list(tasks)
            self._dirty = True

    def on_click(self, event: object) -> None:
        """Handle click events on task rows to toggle detail."""
        # Walk up the widget tree from the click target to find a _TaskRow.
        from textual.events import Click

        if not isinstance(event, Click):
            return
        widget = self.screen.get_widget_at(event.screen_x, event.screen_y)[0]
        # Walk up to find a _TaskRow ancestor (or the widget itself).
        node = widget
        while node is not None:
            if isinstance(node, _TaskRow):
                self._toggle_detail(node.task_id)
                return
            if node is self:
                break
            node = node.parent

    def _toggle_detail(self, task_id: str) -> None:
        """Toggle the expanded detail for a task."""
        if self._expanded_id == task_id:
            self._expanded_id = None
        else:
            self._expanded_id = task_id
        self._refresh_display()

    def _check_dirty(self) -> None:
        """Timer callback — refresh the display if the dirty flag is set."""
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False

        self._refresh_display()

    def _refresh_display(self) -> None:
        """Rebuild the widget contents from the current task list."""
        results = self.query("#task-container")
        if not results:
            return
        container = results.first(Vertical)
        container.remove_children()

        has_content = bool(self._preflight_groups) or bool(self._tasks)

        if not has_content:
            container.mount(Static("No tasks yet.", classes="task-empty"))
            return

        # Render preflight groups first.
        for group in self._preflight_groups:
            container.mount(Static(group.title, classes="task-header"))
            container.mount(Static("\u2500" * 20, classes="task-divider"))
            for label, status in group.items:
                char, css_class = _CHECK_STATUS_DISPLAY.get(status, ("\u25cb", "task-pending"))
                container.mount(Static(f"{char} {label}", classes=f"task-row {css_class}"))

        # Render work queue tasks.
        if self._tasks:
            # Post TasksAvailable once.
            if not self._tasks_available_posted:
                self._tasks_available_posted = True
                self.post_message(self.TasksAvailable())

            container.mount(Static("Tasks", classes="task-header"))
            container.mount(Static("\u2500" * 20, classes="task-divider"))

            for task in self._tasks:
                char, css_class = _status_display(task.status)
                row = _TaskRow(task.id, f"{char} {task.title}", classes=f"task-row {css_class}")
                container.mount(row)

                # Show detail panel if this task is expanded.
                if self._expanded_id == task.id:
                    detail_text = _format_detail(task)
                    container.mount(Static(detail_text, classes="task-detail"))
