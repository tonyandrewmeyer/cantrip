"""Task checklist widget for the TUI."""

import dataclasses
import datetime
import threading

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from cantrip.agent.preflight import CheckStatus
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

# Display order and labels for category groups.
_CATEGORY_ORDER: list[tuple[TaskCategory, str]] = [
    (TaskCategory.RESEARCH, "Research"),
    (TaskCategory.LIBRARIAN, "Librarian"),
    (TaskCategory.BUILD, "Build"),
    (TaskCategory.DEPLOY, "Deploy"),
    (TaskCategory.TEST, "Test"),
    (TaskCategory.DEBUG, "Debug"),
    (TaskCategory.INFRA, "Infrastructure"),
    # ``CONFIRM`` is the enum's wire name; the display label is
    # what the user actually sees, and "Approve" reads as a
    # directive ("I need to approve this") instead of as a noun.
    (TaskCategory.CONFIRM, "Approve"),
]

# Statuses that are pinned to the top "In progress" section.  Keeping
# active work visible regardless of queue order is the main win here —
# otherwise a finished Research phase can push an ACTIVE build task
# off-screen.
_PINNED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.ACTIVE, TaskStatus.FAILED, TaskStatus.BLOCKED}
)

# Lookup from category to its display label.
_CATEGORY_LABELS: dict[TaskCategory, str] = dict(_CATEGORY_ORDER)

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


@dataclasses.dataclass
class _PreflightGroup:
    """A group of preflight environment checks."""

    title: str
    items: list[tuple[str, CheckStatus]] = dataclasses.field(default_factory=list)


def _status_display(status: TaskStatus) -> tuple[str, str]:
    """Return ``(indicator_char, css_class)`` for a task status."""
    return _STATUS_DISPLAY.get(status, ("\u25cb", "task-pending"))


def _elapsed_label(started: datetime.datetime | None) -> str:
    """Render a compact elapsed-duration label (e.g. "12s", "3m14s")."""
    if started is None:
        return ""
    delta = datetime.datetime.now() - started
    total = int(delta.total_seconds())
    if total < 0:
        return ""
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _subagent_line(task: AgentTask) -> str | None:
    """Build the subagent status line shown under an active task, or None."""
    phase = task.subagent_phase
    if not phase:
        return None
    elapsed = _elapsed_label(task.subagent_started_at)
    if elapsed:
        return f"  \u2514 {phase} \u00b7 {elapsed}"
    return f"  \u2514 {phase}"


def _format_detail(task: AgentTask) -> str:
    """Build the detail text shown when a task row is expanded.

    The ``.task-detail`` CSS class adds ``margin-left: 2``, so this
    helper produces lines without leading whitespace — otherwise the
    detail block is doubly-indented and stops aligning with anything
    else in the widget.
    """
    lines: list[str] = []
    lines.append(f"Category: {task.category.value}")
    lines.append(f"Status: {task.status.value}")
    if task.worktree_path:
        lines.append(f"Worktree: {task.worktree_path}")
    if task.blocked_reason:
        lines.append(f"Blocked: {task.blocked_reason}")
    if task.result:
        # Truncate very long results for the panel.
        result = task.result
        if len(result) > 200:
            result = result[:197] + "..."
        lines.append(f"Result: {result}")
    if task.description:
        desc = task.description
        if len(desc) > 200:
            desc = desc[:197] + "..."
        lines.append(f"Info: {desc}")
    return "\n".join(lines)


class _TaskRow(Static):
    """A clickable task row that toggles detail expansion."""

    def __init__(self, task_id: str, content: str, **kwargs: object) -> None:
        super().__init__(content, **kwargs)
        self.task_id = task_id


class _TaskDetail(Static):
    """The expanded-detail block under an expanded ``_TaskRow``.

    Subclassed so a click anywhere on the detail body collapses the
    task — the user expects "click the task" to toggle, regardless of
    whether the click landed on the row's title line or one of the
    detail lines below it.
    """

    def __init__(self, task_id: str, content: str, **kwargs: object) -> None:
        super().__init__(content, **kwargs)
        self.task_id = task_id


class _CollapsedGroupRow(Static):
    """A clickable summary row for a fully-completed category."""

    def __init__(self, category: TaskCategory, content: str, **kwargs: object) -> None:
        super().__init__(content, **kwargs)
        self.category = category


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
    }

    TaskChecklistWidget .task-pinned-header {
        text-style: bold reverse;
        color: $accent;
    }

    TaskChecklistWidget .task-divider {
        color: $primary;
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

    TaskChecklistWidget .task-collapsed {
        text-style: italic;
    }

    TaskChecklistWidget .subagent-phase {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
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
        self._expanded_groups: set[TaskCategory] = set()
        self._agent_activity: str | None = None

    def set_agent_activity(self, label: str | None) -> None:
        """Show a transient agent-activity row (e.g. "Planning tasks…").

        Thread-safe — safe to call from any thread.  Pass ``None`` to
        clear the row.  The row is only rendered while the work queue
        is empty, so it quietly gives way once real tasks appear.
        """
        with self._lock:
            if self._agent_activity == label:
                return
            self._agent_activity = label
            self._dirty = True

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
            if group_idx >= len(self._preflight_groups):
                return
            group = self._preflight_groups[group_idx]
            if item_idx >= len(group.items):
                return
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
        """Handle click events on task and collapsed-group rows."""
        # Walk up the widget tree from the click target to find a row.
        from textual.events import Click

        if not isinstance(event, Click):
            return
        from textual.screen import NoWidget

        try:
            widget = self.screen.get_widget_at(event.screen_x, event.screen_y)[0]
        except NoWidget:
            return
        node = widget
        while node is not None:
            if isinstance(node, (_TaskRow, _TaskDetail)):
                self._toggle_detail(node.task_id)
                return
            if isinstance(node, _CollapsedGroupRow):
                self._toggle_group(node.category)
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

    def _toggle_group(self, category: TaskCategory) -> None:
        """Expand or collapse a fully-done category group."""
        if category in self._expanded_groups:
            self._expanded_groups.discard(category)
        else:
            self._expanded_groups.add(category)
        self._refresh_display()

    def _check_dirty(self) -> None:
        """Timer callback — refresh if dirty, or if a subagent is running.

        Subagent phase rows show an elapsed counter, so we have to redraw on
        every tick while one is active even without an explicit change event.
        """
        with self._lock:
            has_live_phase = any(
                t.subagent_phase and t.subagent_started_at is not None for t in self._tasks
            )
            if not self._dirty and not has_live_phase:
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

        has_content = (
            bool(self._preflight_groups) or bool(self._tasks) or bool(self._agent_activity)
        )

        if not has_content:
            container.mount(Static("No tasks yet.", classes="task-empty"))
            return

        # Render preflight groups first.  When a group is fully green,
        # collapse it to a single summary line so it stops monopolising
        # the task pane.
        _terminal_ok = {CheckStatus.PASSED, CheckStatus.SKIPPED}
        for group in self._preflight_groups:
            if group.items and all(status in _terminal_ok for _, status in group.items):
                container.mount(
                    Static(
                        f"\u2713 {group.title} \u00b7 ready",
                        classes="task-row task-done task-collapsed",
                    )
                )
                continue
            container.mount(Static(group.title, classes="task-header"))
            container.mount(Static("\u2500" * 20, classes="task-divider"))
            for label, status in group.items:
                char, css_class = _CHECK_STATUS_DISPLAY.get(status, ("\u25cb", "task-pending"))
                container.mount(Static(f"{char} {label}", classes=f"task-row {css_class}"))

        # Show the transient agent-activity row while the work queue is
        # still empty (e.g. "Planning tasks…" before plan_tasks runs).
        if self._agent_activity and not self._tasks:
            container.mount(
                Static(f"\u27f3 {self._agent_activity}", classes="task-row task-active")
            )

        # Render work queue tasks.
        if self._tasks:
            # Post TasksAvailable once.
            if not self._tasks_available_posted:
                self._tasks_available_posted = True
                self.post_message(self.TasksAvailable())

            # Pinned section — any ACTIVE, FAILED, or BLOCKED tasks rise to
            # the top so they aren't hidden by finished or queued work below.
            pinned = [t for t in self._tasks if t.status in _PINNED_STATUSES]
            if pinned:
                # The pinned header carries its own emphasis class so the
                # live block is visually distinct from the category sections
                # that follow; the underline divider would only add noise.
                container.mount(Static("In progress", classes="task-pinned-header"))
                for task in pinned:
                    char, css_class = _status_display(task.status)
                    cat_label = _CATEGORY_LABELS.get(task.category, task.category.value)
                    row = _TaskRow(
                        task.id,
                        f"{char} {cat_label} \u00b7 {task.title}",
                        classes=f"task-row {css_class}",
                    )
                    container.mount(row)
                    subagent_line = _subagent_line(task)
                    if subagent_line:
                        container.mount(Static(subagent_line, classes="subagent-phase"))
                    if self._expanded_id == task.id:
                        container.mount(
                            _TaskDetail(task.id, _format_detail(task), classes="task-detail")
                        )

            # Category sections — only tasks not already shown in the pinned
            # section (i.e. PENDING or DONE).  If every remaining task in a
            # category is DONE, collapse the whole group into a summary row.
            by_category: dict[TaskCategory, list[AgentTask]] = {}
            for task in self._tasks:
                if task.status in _PINNED_STATUSES:
                    continue
                by_category.setdefault(task.category, []).append(task)

            for category, label in _CATEGORY_ORDER:
                group = by_category.get(category)
                if not group:
                    continue

                has_unfinished = any(t.status != TaskStatus.DONE for t in group)
                # Auto-expand the group when the user has opened the detail
                # for a task inside it, so the detail actually shows up.
                has_opened_detail = self._expanded_id is not None and any(
                    t.id == self._expanded_id for t in group
                )
                collapsed = (
                    not has_unfinished
                    and category not in self._expanded_groups
                    and not has_opened_detail
                )

                # A fully-DONE category collapses to a single self-describing
                # row \u2014 header + divider + summary would be three lines for
                # one piece of information, and at end-of-session every
                # category is in this state at once.
                if collapsed:
                    count = len(group)
                    plural = "task" if count == 1 else "tasks"
                    summary = _CollapsedGroupRow(
                        category,
                        f"\u2713 {label} \u00b7 {count} {plural} done",
                        classes="task-row task-done task-collapsed",
                    )
                    container.mount(summary)
                    continue

                container.mount(Static(label, classes="task-header"))
                container.mount(Static("\u2500" * 20, classes="task-divider"))

                for task in group:
                    char, css_class = _status_display(task.status)
                    row = _TaskRow(
                        task.id, f"{char} {task.title}", classes=f"task-row {css_class}"
                    )
                    container.mount(row)

                    # Show detail panel if this task is expanded.
                    if self._expanded_id == task.id:
                        container.mount(
                            _TaskDetail(task.id, _format_detail(task), classes="task-detail")
                        )
