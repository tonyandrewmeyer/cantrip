"""Chat widget for the TUI."""

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, LoadingIndicator, Static


class MessageRole(StrEnum):
    """Role of a chat message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(StrEnum):
    """Status of a message or action."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class ProgressItem:
    """A progress item within a message."""

    text: str
    status: MessageStatus = MessageStatus.PENDING


@dataclass
class ChatMessage:
    """A chat message."""

    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    progress_items: list[ProgressItem] = field(default_factory=list)


class MessageWidget(Static):
    """Widget for a single chat message."""

    DEFAULT_CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 1 0;
    }

    MessageWidget.user {
        background: $surface;
        border-left: thick $primary;
    }

    MessageWidget.assistant {
        border-left: thick $secondary;
    }

    MessageWidget.system {
        color: $text-muted;
        text-style: italic;
        border-left: thick $surface;
    }

    MessageWidget .message-header {
        color: $text-muted;
        text-style: dim;
    }

    MessageWidget .message-content {
        margin-top: 1;
    }

    MessageWidget .progress-item {
        margin-left: 2;
    }

    MessageWidget .progress-pending {
        color: $text-muted;
    }

    MessageWidget .progress-in-progress {
        color: $primary;
    }

    MessageWidget .progress-complete {
        color: $success;
    }

    MessageWidget .progress-error {
        color: $error;
    }
    """

    def __init__(self, message: ChatMessage) -> None:
        """Initialise with a message."""
        super().__init__()
        self.message = message
        self.add_class(message.role.value)
        # Search highlighting state: query and which local match (0-indexed)
        # should be styled as the "active" match.  ``None`` means no search.
        self._search_query: str | None = None
        self._active_local_idx: int | None = None

    def compose(self) -> ComposeResult:
        """Compose the message widget."""
        yield Static(self._render_body(), id="message-body")

    def _render_body(self) -> str:
        """Build the Rich-markup body string for this message."""
        role_display = {
            MessageRole.USER: "> ",
            MessageRole.ASSISTANT: "",
            MessageRole.SYSTEM: "[system] ",
        }
        header = role_display.get(self.message.role, "")
        timestamp = self.message.timestamp.strftime("%H:%M")
        header = f"[dim][{timestamp}][/dim] {header}"

        content = self._highlighted_content() if self._search_query else self.message.content
        content_lines = [content]

        for item in self.message.progress_items:
            status_char = self._status_char(item.status)
            status_class = f"progress-{item.status.value.replace('_', '-')}"
            content_lines.append(f"[{status_class}]{status_char}[/{status_class}] {item.text}")

        return header + "\n".join(content_lines)

    def _highlighted_content(self) -> str:
        """Return message content with search matches wrapped in Rich tags.

        Escapes existing markup in ``message.content`` to avoid collisions
        with user/assistant text that happens to contain square brackets;
        this is acceptable because highlighting is active only while the
        search bar is open.
        """
        query = self._search_query or ""
        text = self.message.content
        if not query:
            return rich_escape(text)

        lower_text = text.lower()
        lower_query = query.lower()
        parts: list[str] = []
        cursor = 0
        local_idx = 0
        while True:
            pos = lower_text.find(lower_query, cursor)
            if pos < 0:
                parts.append(rich_escape(text[cursor:]))
                break
            parts.append(rich_escape(text[cursor:pos]))
            end = pos + len(query)
            # Active match uses a brighter style so the user can see which
            # occurrence is currently focused.
            style = "black on yellow" if local_idx == self._active_local_idx else "yellow reverse"
            parts.append(f"[{style}]{rich_escape(text[pos:end])}[/{style}]")
            cursor = end
            local_idx += 1
        return "".join(parts)

    def _rerender(self) -> None:
        """Re-render the message body.

        If the widget has been mounted but not yet composed (e.g. streaming
        chunks arrive on the same tick the message was added), the body
        Static won't exist yet; skip silently — the next ``compose()`` call
        will read the current ``message.content`` and render correctly.
        """
        try:
            body = self.query_one("#message-body", Static)
        except NoMatches:
            return
        body.update(self._render_body())

    def count_matches(self, query: str) -> int:
        """Return the number of case-insensitive occurrences of *query*."""
        if not query:
            return 0
        return self.message.content.lower().count(query.lower())

    def apply_highlight(self, query: str | None, active_local_idx: int | None) -> None:
        """Configure search highlighting and re-render."""
        self._search_query = query or None
        self._active_local_idx = active_local_idx
        self._rerender()

    def _status_char(self, status: MessageStatus) -> str:
        """Get status indicator character."""
        return {
            MessageStatus.PENDING: "○",
            MessageStatus.IN_PROGRESS: "⟳",
            MessageStatus.COMPLETE: "✓",
            MessageStatus.ERROR: "✗",
        }.get(status, "○")

    def update_progress(self, index: int, status: MessageStatus) -> None:
        """Update progress item status."""
        if 0 <= index < len(self.message.progress_items):
            self.message.progress_items[index].status = status
            self._rerender()

    def append_content(self, chunk: str) -> None:
        """Append a text chunk to the message content and re-render.

        Used by streaming responses to grow an in-progress message
        without creating a new widget per chunk.
        """
        if not chunk:
            return
        self.message.content += chunk
        self._rerender()


class ChatInput(Input):
    """The chat input — subclassed so a leading ``/`` opens search.

    Pressing ``/`` when the input is empty posts a ``SearchRequested`` message
    (which the app converts into an ``open search`` action).  If the input
    already has text, ``/`` is inserted at the cursor as normal, so users can
    still type paths like ``/etc/hosts`` mid-message.
    """

    class SearchRequested(Message):
        """Posted when the user presses ``/`` in an empty chat input."""

    async def _on_key(self, event) -> None:
        """Intercept ``/`` (only) when the field is empty, otherwise defer.

        ``Input`` consumes printable characters directly in ``_on_key`` —
        which means the normal ``BINDINGS`` mechanism cannot see them — so
        the interception has to happen here, before ``super()._on_key``
        inserts the character.
        """
        if event.key == "slash" and not self.value:
            event.stop()
            event.prevent_default()
            self.post_message(self.SearchRequested())
            return
        await super()._on_key(event)


class SearchBar(Widget):
    """Search bar shown above the chat scroll area when searching is active.

    Holds its own ``Input`` and a status label showing match position.  Emits
    ``Changed`` whenever the query changes and ``Dismissed`` when the user
    presses Escape or Enter-with-empty-value.  Next/previous navigation is
    driven by the containing widget.
    """

    DEFAULT_CSS = """
    SearchBar {
        height: 1;
        display: none;
    }

    SearchBar.-visible {
        display: block;
    }

    SearchBar #search-row {
        height: 1;
    }

    SearchBar #search-input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $boost;
    }

    SearchBar #search-status {
        width: auto;
        min-width: 14;
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $boost;
    }
    """

    class Changed(Message):
        """Posted when the query text changes."""

        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class Dismissed(Message):
        """Posted when the user dismisses the search bar."""

    class Navigate(Message):
        """Posted when the user requests the next/previous match."""

        def __init__(self, *, forward: bool) -> None:
            super().__init__()
            self.forward = forward

    def compose(self) -> ComposeResult:
        """Compose the search bar."""
        with Horizontal(id="search-row"):
            yield Input(placeholder="Search chat... (Enter: next, Esc: close)", id="search-input")
            yield Static("", id="search-status")

    def show(self) -> None:
        """Reveal and focus the search bar."""
        self.add_class("-visible")
        input_widget = self.query_one("#search-input", Input)
        input_widget.focus()

    def hide(self) -> None:
        """Hide the search bar and clear its query."""
        self.remove_class("-visible")
        self.query_one("#search-input", Input).value = ""
        self.set_status("")

    @property
    def is_open(self) -> bool:
        """Whether the search bar is currently shown."""
        return self.has_class("-visible")

    @property
    def query_text(self) -> str:
        """The current search text."""
        try:
            return self.query_one("#search-input", Input).value
        except NoMatches:
            return ""

    def set_status(self, text: str) -> None:
        """Update the match counter label."""
        with contextlib.suppress(NoMatches):
            self.query_one("#search-status", Static).update(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Propagate changes so the host can re-run the search."""
        if event.input.id == "search-input":
            event.stop()
            self.post_message(self.Changed(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter inside the search field jumps to the next match."""
        if event.input.id == "search-input":
            event.stop()
            self.post_message(self.Navigate(forward=True))

    def on_key(self, event) -> None:
        """Escape closes the search bar."""
        if not self.is_open:
            return
        if event.key == "escape":
            event.stop()
            self.post_message(self.Dismissed())


class ChatWidget(Widget):
    """Widget for chat history and input."""

    class SearchClosed(Message):
        """Posted when the user dismisses the search bar."""

    DEFAULT_CSS = """
    ChatWidget {
        height: 100%;
    }

    ChatWidget #chat-history {
        height: 1fr;
        border: solid $primary;
        padding: 1;
    }

    ChatWidget #chat-scroll {
        height: 1fr;
    }

    ChatWidget .welcome-message {
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        """Initialise the chat widget."""
        super().__init__(**kwargs)
        self._messages: list[ChatMessage] = []
        # Flattened list of (message_widget, local_match_index) pairs for the
        # current search query, rebuilt on every query change.
        self._match_index: list[tuple[MessageWidget, int]] = []
        self._active_match: int = 0

    def compose(self) -> ComposeResult:
        """Compose the chat widget."""
        with Vertical(id="chat-history"):
            yield SearchBar(id="search-bar")
            yield ScrollableContainer(id="chat-scroll")

    def on_mount(self) -> None:
        """Handle mount."""
        self._show_welcome()

    def _show_welcome(self) -> None:
        """Show welcome message."""
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.mount(
            Static(
                "Welcome to Cantrip!\n\n"
                "Describe what you want to charm:\n"
                '  "build a charm for my Flask app"\n'
                '  "charm a PostgreSQL deployment"\n\n'
                "I'll help you create a production-ready "
                "Juju charm in minutes.",
                classes="welcome-message",
            )
        )

    def add_message(self, message: ChatMessage) -> MessageWidget:
        """Add a message to the chat."""
        self._messages.append(message)

        scroll = self.query_one("#chat-scroll", ScrollableContainer)

        # Clear welcome message on first real message
        if len(self._messages) == 1:
            scroll.remove_children()

        widget = MessageWidget(message)
        scroll.mount(widget)
        scroll.scroll_end(animate=False)

        return widget

    def add_user_message(self, content: str) -> MessageWidget:
        """Add a user message."""
        return self.add_message(ChatMessage(role=MessageRole.USER, content=content))

    def add_assistant_message(
        self,
        content: str,
        progress_items: list[str] | None = None,
    ) -> MessageWidget:
        """Add an assistant message with optional progress items."""
        items = [ProgressItem(text=item) for item in (progress_items or [])]
        return self.add_message(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=content,
                progress_items=items,
            )
        )

    def add_system_message(
        self,
        content: str,
        progress_items: list[str] | None = None,
    ) -> MessageWidget:
        """Add a system message with optional progress items."""
        items = [ProgressItem(text=item) for item in (progress_items or [])]
        return self.add_message(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=content,
                progress_items=items,
            )
        )

    def append_streaming_chunk(self, widget: MessageWidget, chunk: str) -> None:
        """Append *chunk* to *widget* and keep the scroll pinned to the bottom.

        The caller typically obtains *widget* from ``add_assistant_message("")``
        before streaming begins, then pumps chunks in via this method as they
        arrive from ``process_message_streaming``.
        """
        widget.append_content(chunk)
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.scroll_end(animate=False)

    def remove_message(self, widget: MessageWidget) -> None:
        """Remove a message widget from the chat."""
        if widget.message in self._messages:
            self._messages.remove(widget.message)
        widget.remove()

    def show_thinking(self) -> None:
        """Show an animated thinking indicator in the chat area."""
        self.hide_thinking()
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.mount(LoadingIndicator(id="thinking-indicator"))
        scroll.scroll_end(animate=False)

    def hide_thinking(self) -> None:
        """Remove the thinking indicator if present."""
        for widget in self.query("#thinking-indicator"):
            widget.remove()

    def clear(self) -> None:
        """Clear chat history."""
        self._messages.clear()
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.remove_children()
        self._show_welcome()
        # Any in-flight search is no longer meaningful.
        self._match_index.clear()
        self._active_match = 0
        with contextlib.suppress(NoMatches):
            self.query_one(SearchBar).hide()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def open_search(self) -> None:
        """Reveal the search bar and focus its input."""
        try:
            bar = self.query_one(SearchBar)
        except NoMatches:
            return
        bar.show()

    def close_search(self) -> None:
        """Clear highlights and hide the search bar."""
        self._clear_highlights()
        with contextlib.suppress(NoMatches):
            self.query_one(SearchBar).hide()
        self.post_message(self.SearchClosed())

    @property
    def search_active(self) -> bool:
        """Whether the search bar is currently visible."""
        try:
            return self.query_one(SearchBar).is_open
        except NoMatches:
            return False

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        """Re-run the search each time the query text changes."""
        event.stop()
        self._run_search(event.query)

    def on_search_bar_dismissed(self, event: SearchBar.Dismissed) -> None:
        """Handle Esc inside the search bar."""
        event.stop()
        self.close_search()

    def on_search_bar_navigate(self, event: SearchBar.Navigate) -> None:
        """Handle next/previous requests from the search bar."""
        event.stop()
        self.navigate_match(forward=event.forward)

    def navigate_match(self, *, forward: bool = True) -> None:
        """Move to the next (or previous) match and scroll it into view."""
        if not self._match_index:
            return
        delta = 1 if forward else -1
        self._active_match = (self._active_match + delta) % len(self._match_index)
        self._apply_highlights()
        self._scroll_to_active()
        self._update_status_label()

    def _run_search(self, query: str) -> None:
        """Rebuild the match list for *query* and highlight all matches."""
        query = query.strip()
        self._clear_highlights()
        if not query:
            self._update_status_label()
            return

        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        matches: list[tuple[MessageWidget, int]] = []
        for widget in scroll.query(MessageWidget):
            count = widget.count_matches(query)
            matches.extend((widget, local) for local in range(count))
        self._match_index = matches
        self._active_match = 0
        self._apply_highlights()
        if matches:
            self._scroll_to_active()
        self._update_status_label()

    def _apply_highlights(self) -> None:
        """Push the current query / active-match state into every widget."""
        if not self._match_index:
            return
        query = self.query_one(SearchBar).query_text
        # Group match positions by widget so we can set the active local idx
        # only on the widget that owns the active global match.
        active_widget, active_local = self._match_index[self._active_match]
        seen: set[int] = set()
        for widget, _ in self._match_index:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            local_idx = active_local if widget is active_widget else None
            widget.apply_highlight(query, local_idx)

    def _clear_highlights(self) -> None:
        """Remove highlights from any widget that was previously highlighted."""
        seen: set[int] = set()
        for widget, _ in self._match_index:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            widget.apply_highlight(None, None)
        self._match_index.clear()
        self._active_match = 0

    def _scroll_to_active(self) -> None:
        """Scroll the chat area so the active match is visible."""
        if not self._match_index:
            return
        widget, _ = self._match_index[self._active_match]
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.scroll_to_widget(widget, animate=False)

    def _update_status_label(self) -> None:
        """Refresh the match-count text shown next to the search input."""
        try:
            bar = self.query_one(SearchBar)
        except NoMatches:
            return
        if not bar.query_text.strip():
            bar.set_status("")
        elif not self._match_index:
            bar.set_status("no matches")
        else:
            bar.set_status(f"{self._active_match + 1}/{len(self._match_index)}")
