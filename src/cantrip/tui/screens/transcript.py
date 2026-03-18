"""Transcript viewer modal screen for Cantrip TUI."""

import pathlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

# Views available via the 'v' key.
_VIEWS = ("conversation", "tasks", "events")

# Maximum messages to display per view to keep the UI responsive.
_MAX_DISPLAY = 500


class TranscriptScreen(ModalScreen):
    """Modal screen showing session transcript with conversation, tasks, and events."""

    DEFAULT_CSS = """
    TranscriptScreen {
        align: center middle;
    }

    #transcript-container {
        width: 95%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #transcript-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }

    #transcript-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #transcript-output {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("v", "cycle_view", "View"),
        Binding("r", "refresh", "Refresh"),
    ]

    view: reactive[str] = reactive("conversation")

    def __init__(self, db_path: pathlib.Path | None = None) -> None:
        """Initialise with the path to the .cantrip database."""
        super().__init__()
        self._db_path = db_path

    def compose(self) -> ComposeResult:
        """Compose the transcript viewer layout."""
        with Center(), Vertical(id="transcript-container"):
            yield Static(
                "Session Transcript                        [Esc Close]",
                id="transcript-title",
            )
            yield RichLog(id="transcript-output", wrap=True, markup=True)
            yield Static(
                "[v] View  [r] Refresh  [Esc] Close",
                id="transcript-footer",
            )

    def on_mount(self) -> None:
        """Load transcript data on mount."""
        self._render_view()

    def watch_view(self, _view: str) -> None:
        """Re-render when the view changes."""
        self._render_view()

    def action_cycle_view(self) -> None:
        """Cycle through transcript views."""
        idx = _VIEWS.index(self.view) if self.view in _VIEWS else 0
        self.view = _VIEWS[(idx + 1) % len(_VIEWS)]

    def action_refresh(self) -> None:
        """Refresh the current view."""
        self._render_view()

    def _render_view(self) -> None:
        """Render the current view into the RichLog widget."""
        log_widget = self.query_one("#transcript-output", RichLog)
        log_widget.clear()

        title = self.query_one("#transcript-title", Static)

        if not self._db_path or not self._db_path.exists():
            log_widget.write("No .cantrip session file found.")
            return

        from cantrip.transcript.export import load_transcript

        data = load_transcript(self._db_path)

        if self.view == "conversation":
            title.update(f"Conversation ({len(data.messages)} messages)              [Esc Close]")
            self._render_conversation(log_widget, data)
        elif self.view == "tasks":
            title.update(f"Tasks ({len(data.tasks)} tasks)                          [Esc Close]")
            self._render_tasks(log_widget, data)
        elif self.view == "events":
            title.update(f"Events ({len(data.events)} events)                        [Esc Close]")
            self._render_events(log_widget, data)

    @staticmethod
    def _render_conversation(log_widget: RichLog, data: object) -> None:
        """Render conversation messages."""
        messages = getattr(data, "messages", [])
        if not messages:
            log_widget.write("No conversation messages recorded.")
            return

        for msg in messages[-_MAX_DISPLAY:]:
            role = msg.get("role", "unknown")
            ts = msg.get("timestamp", "")
            content = msg.get("content", "") or ""

            # Role indicator.
            role_style = {
                "user": "[bold blue]USER[/bold blue]",
                "assistant": "[bold green]ASSISTANT[/bold green]",
                "system": "[bold yellow]SYSTEM[/bold yellow]",
                "tool": "[bold dim]TOOL[/bold dim]",
            }.get(role, f"[bold]{role.upper()}[/bold]")

            log_widget.write(f"{role_style}  [dim]{ts}[/dim]")

            # Show content (truncated for readability).
            if content:
                preview = content[:500]
                if len(content) > 500:
                    preview += "..."
                log_widget.write(f"  {preview}")

            # Show tool calls summary.
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    name = tc.get("name", "?") if isinstance(tc, dict) else "?"
                    log_widget.write(f"  [dim]→ tool call: {name}[/dim]")

            log_widget.write("")

    @staticmethod
    def _render_tasks(log_widget: RichLog, data: object) -> None:
        """Render task list with subagent conversation drill-down."""
        tasks = getattr(data, "tasks", [])
        subagent_messages = getattr(data, "subagent_messages", {})
        if not tasks:
            log_widget.write("No tasks recorded.")
            return

        status_icons = {
            "done": "[green]✓[/green]",
            "failed": "[red]✗[/red]",
            "active": "[blue]⟳[/blue]",
            "pending": "[dim]○[/dim]",
            "blocked": "[yellow]◌[/yellow]",
        }

        for task in tasks:
            icon = status_icons.get(task.get("status", ""), "?")
            title = task.get("title", "Untitled")
            category = task.get("category", "")
            status = task.get("status", "")

            log_widget.write(f"{icon} [bold]{title}[/bold]  [{category}] {status}")

            # Show result excerpt if present.
            result = task.get("result", "")
            if result:
                preview = result[:300]
                if len(result) > 300:
                    preview += "..."
                log_widget.write(f"  [dim]{preview}[/dim]")

            # Show subagent conversation summary.
            task_id = task.get("id", "")
            sub_msgs = subagent_messages.get(task_id, [])
            if sub_msgs:
                tool_count = sum(1 for m in sub_msgs if m.get("tool_calls"))
                log_widget.write(
                    f"  [dim]↳ {len(sub_msgs)} subagent messages, {tool_count} tool calls[/dim]"
                )

            log_widget.write("")

    @staticmethod
    def _render_events(log_widget: RichLog, data: object) -> None:
        """Render event log."""
        events = getattr(data, "events", [])
        if not events:
            log_widget.write("No events recorded.")
            return

        for event in events[-_MAX_DISPLAY:]:
            event_type = event.get("event_type", "unknown")
            ts = event.get("timestamp", "")
            detail = event.get("detail", {})

            type_style = {
                "session_start": "[bold green]",
                "session_resume": "[bold green]",
                "task_status_change": "[blue]",
                "error": "[bold red]",
            }.get(event_type, "[dim]")

            log_widget.write(f"{type_style}{event_type}[/]  [dim]{ts}[/dim]")

            if isinstance(detail, dict):
                for k, v in detail.items():
                    log_widget.write(f"  [dim]{k}: {v}[/dim]")

            log_widget.write("")
