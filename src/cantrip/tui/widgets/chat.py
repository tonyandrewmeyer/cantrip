"""Chat widget for the TUI."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static


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

    def compose(self) -> ComposeResult:
        """Compose the message widget."""
        # Header with role indicator
        role_display = {
            MessageRole.USER: "> ",
            MessageRole.ASSISTANT: "",
            MessageRole.SYSTEM: "[system] ",
        }
        header = role_display.get(self.message.role, "")

        content_lines = [self.message.content]

        # Add progress items if any
        for item in self.message.progress_items:
            status_char = self._status_char(item.status)
            status_class = f"progress-{item.status.value.replace('_', '-')}"
            content_lines.append(f"[{status_class}]{status_char}[/{status_class}] {item.text}")

        yield Static(header + "\n".join(content_lines))

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
            self.refresh()


class ChatWidget(Widget):
    """Widget for chat history and input."""

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
        height: 100%;
    }

    ChatWidget .welcome-message {
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        """Initialise the chat widget."""
        super().__init__(**kwargs)
        self._messages: list[ChatMessage] = []

    def compose(self) -> ComposeResult:
        """Compose the chat widget."""
        with Vertical(id="chat-history"):
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
