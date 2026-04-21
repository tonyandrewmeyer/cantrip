"""Transcript viewer modal screen for Cantrip TUI."""

import contextlib
import pathlib

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, RichLog, Static

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
        width: 100%;
        height: 1;
        padding-bottom: 1;
    }

    .title-text {
        text-style: bold;
        width: 1fr;
    }

    .title-hint {
        color: $text-muted;
        width: auto;
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

    #transcript-search {
        height: 1;
        display: none;
    }

    #transcript-search.-visible {
        display: block;
    }

    #transcript-search #search-row {
        height: 1;
    }

    #transcript-search #search-input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $boost;
    }

    #transcript-search #search-status {
        width: auto;
        min-width: 14;
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $boost;
    }
    """

    BINDINGS = [
        Binding("escape", "close_or_dismiss", "Close"),
        Binding("v", "cycle_view", "View"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "search", "Search"),
        Binding("ctrl+f", "search", "Search"),
    ]

    view: reactive[str] = reactive("conversation")

    def __init__(self, db_path: pathlib.Path | None = None) -> None:
        """Initialise with the path to the .cantrip database."""
        super().__init__()
        self._db_path = db_path
        # Cached raw lines (Rich markup) from the last render, so the search
        # bar can re-render with highlights without re-reading the database.
        self._last_lines: list[str] = []
        self._search_query: str = ""
        self._match_line_indices: list[int] = []
        self._active_match: int = 0

    def compose(self) -> ComposeResult:
        """Compose the transcript viewer layout."""
        with Vertical(id="transcript-container"):
            with Horizontal(id="transcript-title"):
                yield Static("Session Transcript", classes="title-text")
                yield Static("[Esc Close]", classes="title-hint")
            with Vertical(id="transcript-search"), Horizontal(id="search-row"):
                yield Input(
                    placeholder="Search transcript... (Enter: next, Esc: close)",
                    id="search-input",
                )
                yield Static("", id="search-status")
            yield RichLog(id="transcript-output", wrap=True, markup=True)
            yield Static(
                "[/ Search]  [v] View  [r] Refresh  [Esc] Close",
                id="transcript-footer",
                markup=False,
            )

    def on_mount(self) -> None:
        """Load transcript data on mount."""
        self._render_view()
        # Keep the (hidden) search input out of the focus chain so typing
        # a leading ``/`` triggers the screen-level binding instead of
        # being captured as text.
        self.query_one("#search-input", Input).can_focus = False
        self.query_one("#transcript-output", RichLog).focus()

    def watch_view(self, _view: str) -> None:
        """Re-render when the view changes."""
        # Switching views invalidates the current search result set.
        self._search_query = ""
        self._match_line_indices.clear()
        self._active_match = 0
        self._hide_search_bar()
        self._render_view()

    def action_cycle_view(self) -> None:
        """Cycle through transcript views."""
        idx = _VIEWS.index(self.view) if self.view in _VIEWS else 0
        self.view = _VIEWS[(idx + 1) % len(_VIEWS)]

    def action_refresh(self) -> None:
        """Refresh the current view."""
        self._render_view()

    def action_search(self) -> None:
        """Open the search bar and focus its input."""
        bar = self.query_one("#transcript-search")
        bar.add_class("-visible")
        input_widget = self.query_one("#search-input", Input)
        input_widget.can_focus = True
        input_widget.focus()

    def action_close_or_dismiss(self) -> None:
        """Esc closes the search bar if open, otherwise dismisses the screen."""
        try:
            bar = self.query_one("#transcript-search")
        except NoMatches:
            self.dismiss()
            return
        if bar.has_class("-visible"):
            self._hide_search_bar()
            return
        self.dismiss()

    def _hide_search_bar(self) -> None:
        """Hide the search bar, clear its query, and drop highlights."""
        try:
            bar = self.query_one("#transcript-search")
        except NoMatches:
            return
        bar.remove_class("-visible")
        with contextlib.suppress(NoMatches):
            input_widget = self.query_one("#search-input", Input)
            input_widget.value = ""
            input_widget.can_focus = False
        self._search_query = ""
        self._match_line_indices.clear()
        self._active_match = 0
        self._redraw_output()
        # Return focus to the transcript so further bindings (e.g. another
        # `/`) fire instead of going into the now-hidden input.
        with contextlib.suppress(NoMatches):
            self.query_one("#transcript-output", RichLog).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Re-search as the user types."""
        if event.input.id != "search-input":
            return
        event.stop()
        self._search_query = event.value
        self._recompute_matches()
        self._redraw_output()
        self._update_status_label()
        if self._match_line_indices:
            self._scroll_to_active_match()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter inside the search field jumps to the next match."""
        if event.input.id != "search-input":
            return
        event.stop()
        if not self._match_line_indices:
            return
        self._active_match = (self._active_match + 1) % len(self._match_line_indices)
        self._redraw_output()
        self._update_status_label()
        self._scroll_to_active_match()

    def _recompute_matches(self) -> None:
        """Find lines containing the query and reset the active match."""
        query = self._search_query.lower()
        self._match_line_indices.clear()
        self._active_match = 0
        if not query.strip():
            return
        for i, line in enumerate(self._last_lines):
            if query in self._strip_markup(line).lower():
                self._match_line_indices.append(i)

    def _redraw_output(self) -> None:
        """Rewrite the RichLog from cached lines, applying match highlights."""
        try:
            log_widget = self.query_one("#transcript-output", RichLog)
        except NoMatches:
            return
        log_widget.clear()
        query = self._search_query
        active_line_idx = (
            self._match_line_indices[self._active_match] if self._match_line_indices else -1
        )
        for i, line in enumerate(self._last_lines):
            if query and i in self._match_line_indices:
                log_widget.write(self._apply_line_highlight(line, query, i == active_line_idx))
            else:
                log_widget.write(line)

    def _scroll_to_active_match(self) -> None:
        """Scroll the RichLog so the active match is near the top."""
        if not self._match_line_indices:
            return
        try:
            log_widget = self.query_one("#transcript-output", RichLog)
        except NoMatches:
            return
        target = self._match_line_indices[self._active_match]
        log_widget.scroll_to(y=target, animate=False)

    def _update_status_label(self) -> None:
        """Refresh the match-count label."""
        try:
            status = self.query_one("#search-status", Static)
        except NoMatches:
            return
        if not self._search_query.strip():
            status.update("")
        elif not self._match_line_indices:
            status.update("no matches")
        else:
            status.update(f"{self._active_match + 1}/{len(self._match_line_indices)}")

    @staticmethod
    def _apply_line_highlight(line: str, query: str, is_active: bool) -> str:
        """Wrap all case-insensitive ``query`` occurrences in highlight markup.

        Works on the *plain-text projection* of the line (markup stripped), so
        the returned string replaces any Rich styling the caller added —
        acceptable because highlight is transient (search-only).
        """
        plain = TranscriptScreen._strip_markup(line)
        lower_plain = plain.lower()
        lower_query = query.lower()
        if lower_query not in lower_plain:
            return line
        style = "black on yellow" if is_active else "yellow reverse"
        parts: list[str] = []
        cursor = 0
        while True:
            pos = lower_plain.find(lower_query, cursor)
            if pos < 0:
                parts.append(rich_escape(plain[cursor:]))
                break
            parts.append(rich_escape(plain[cursor:pos]))
            end = pos + len(query)
            parts.append(f"[{style}]{rich_escape(plain[pos:end])}[/{style}]")
            cursor = end
        return "".join(parts)

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Strip Rich ``[tag]...[/tag]`` markup from *text* for matching.

        A light-weight stripper: Rich markup tokens are always ``[...]`` with
        no nested brackets in the tag itself, so a greedy regex is fine for
        our rendered lines (which contain no user-supplied raw brackets).
        """
        import re

        return re.sub(r"\[/?[^\[\]]*?\]", "", text)

    def _render_view(self) -> None:
        """Render the current view into the RichLog widget."""
        log_widget = self.query_one("#transcript-output", RichLog)
        log_widget.clear()
        self._last_lines = []

        title = self.query_one("#transcript-title .title-text", Static)

        if not self._db_path or not self._db_path.exists():
            self._last_lines = ["No .cantrip session file found."]
            log_widget.write(self._last_lines[0])
            return

        from cantrip.transcript.export import load_transcript

        data = load_transcript(self._db_path)

        if self.view == "conversation":
            title.update(f"Conversation ({len(data.messages)} messages)")
            self._last_lines = self._conversation_lines(data)
        elif self.view == "tasks":
            title.update(f"Tasks ({len(data.tasks)} tasks)")
            self._last_lines = self._task_lines(data)
        elif self.view == "events":
            title.update(f"Events ({len(data.events)} events)")
            self._last_lines = self._event_lines(data)

        # Re-run any in-flight search against the new content.
        self._recompute_matches()
        self._redraw_output()
        self._update_status_label()

    @staticmethod
    def _conversation_lines(data: object) -> list[str]:
        """Return the rendered conversation as a list of markup lines."""
        messages = getattr(data, "messages", [])
        if not messages:
            return ["No conversation messages recorded."]

        lines: list[str] = []
        for msg in messages[-_MAX_DISPLAY:]:
            role = msg.get("role", "unknown")
            ts = msg.get("timestamp", "")
            content = msg.get("content", "") or ""

            role_style = {
                "user": "[bold blue]USER[/bold blue]",
                "assistant": "[bold green]ASSISTANT[/bold green]",
                "system": "[bold yellow]SYSTEM[/bold yellow]",
                "tool": "[bold dim]TOOL[/bold dim]",
            }.get(role, f"[bold]{role.upper()}[/bold]")

            lines.append(f"{role_style}  [dim]{ts}[/dim]")

            if content:
                preview = content[:500]
                if len(content) > 500:
                    preview += "..."
                lines.append(f"  {preview}")

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    name = tc.get("name", "?") if isinstance(tc, dict) else "?"
                    lines.append(f"  [dim]→ tool call: {name}[/dim]")

            lines.append("")
        return lines

    @staticmethod
    def _task_lines(data: object) -> list[str]:
        """Return the rendered task list as a list of markup lines."""
        tasks = getattr(data, "tasks", [])
        subagent_messages = getattr(data, "subagent_messages", {})
        if not tasks:
            return ["No tasks recorded."]

        status_icons = {
            "done": "[green]✓[/green]",
            "failed": "[red]✗[/red]",
            "active": "[blue]⟳[/blue]",
            "pending": "[dim]○[/dim]",
            "blocked": "[yellow]◌[/yellow]",
        }

        lines: list[str] = []
        for task in tasks:
            icon = status_icons.get(task.get("status", ""), "?")
            title = task.get("title", "Untitled")
            category = task.get("category", "")
            status = task.get("status", "")

            lines.append(f"{icon} [bold]{title}[/bold]  [{category}] {status}")

            result = task.get("result", "")
            if result:
                preview = result[:300]
                if len(result) > 300:
                    preview += "..."
                lines.append(f"  [dim]{preview}[/dim]")

            task_id = task.get("id", "")
            sub_msgs = subagent_messages.get(task_id, [])
            if sub_msgs:
                tool_count = sum(1 for m in sub_msgs if m.get("tool_calls"))
                lines.append(
                    f"  [dim]↳ {len(sub_msgs)} subagent messages, {tool_count} tool calls[/dim]"
                )

            lines.append("")
        return lines

    @staticmethod
    def _event_lines(data: object) -> list[str]:
        """Return the rendered event log as a list of markup lines."""
        events = getattr(data, "events", [])
        if not events:
            return ["No events recorded."]

        lines: list[str] = []
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

            lines.append(f"{type_style}{event_type}[/]  [dim]{ts}[/dim]")

            if isinstance(detail, dict):
                for k, v in detail.items():
                    lines.append(f"  [dim]{k}: {v}[/dim]")

            lines.append("")
        return lines
