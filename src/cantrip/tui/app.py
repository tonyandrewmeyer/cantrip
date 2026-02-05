"""Main Cantrip TUI application."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from cantrip import __version__


class JujuStatusWidget(Static):
    """Widget displaying Juju status."""

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        yield Static(
            "Juju Status\n"
            "───────────\n\n"
            "No model connected.\n\n"
            "Start by describing what\n"
            "you want to charm.",
            id="status-content",
        )


class ChatWidget(Static):
    """Widget for chat history."""

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        yield Static(
            "Welcome to Cantrip!\n\n"
            "Describe what you want to charm:\n"
            '  "build a charm for my Flask app"\n'
            '  "charm a PostgreSQL deployment"\n\n'
            "I'll help you create a production-ready\n"
            "Juju charm in minutes.",
            id="chat-history",
        )


class CantripApp(App):
    """Cantrip TUI application."""

    TITLE = f"Cantrip v{__version__}"
    CSS_PATH = "cantrip.tcss"

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "toggle_status", "Toggle Status"),
        Binding("f3", "logs", "Logs"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
    ]

    def __init__(
        self,
        provider: str = "gemini",
        model: str | None = None,
        charm_path: Path | None = None,
    ):
        """Initialise the app."""
        super().__init__()
        self.provider = provider
        self.model_name = model
        self.charm_path = charm_path or Path.cwd()

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield Horizontal(
            Vertical(
                JujuStatusWidget(id="juju-status"),
                id="left-panel",
            ),
            Vertical(
                ChatWidget(id="chat"),
                Input(placeholder="Type your message...", id="chat-input"),
                id="right-panel",
            ),
            id="main-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Handle app mount."""
        self.query_one("#chat-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        message = event.value.strip()
        if not message:
            return

        # Clear input
        event.input.value = ""

        # TODO: Send to agent and handle response
        chat = self.query_one("#chat-history", Static)
        current = str(chat.renderable)
        chat.update(f"{current}\n\n> {message}\n\nProcessing...")

    def action_help(self) -> None:
        """Show help screen."""
        # TODO: Implement help screen
        self.notify("Help screen not yet implemented", title="Help")

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        left_panel = self.query_one("#left-panel")
        left_panel.display = not left_panel.display

    def action_logs(self) -> None:
        """Show logs view."""
        # TODO: Implement logs view
        self.notify("Logs view not yet implemented", title="Logs")

    def action_clear_chat(self) -> None:
        """Clear chat history."""
        chat = self.query_one("#chat-history", Static)
        chat.update("Chat cleared.\n\nWhat would you like to do?")
