"""Main Cantrip TUI application."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input
from textual.worker import Worker, WorkerState

from cantrip import __version__
from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider
from cantrip.tui.widgets.chat import ChatWidget
from cantrip.tui.widgets.status import JujuStatusWidget


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
        self.provider_name = provider
        self.model_name = model
        self.charm_path = charm_path or Path.cwd()
        self._agent: CantripAgent | None = None

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
        self._init_agent()

    def _init_agent(self) -> None:
        """Initialise the LLM provider and agent."""
        try:
            llm_provider = create_provider(self.provider_name, self.model_name)
            self._agent = CantripAgent(provider=llm_provider, charm_path=self.charm_path)
        except ValueError as e:
            chat = self.query_one("#chat", ChatWidget)
            chat.add_system_message(f"Failed to initialise provider: {e}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle chat input submission."""
        message = event.value.strip()
        if not message:
            return

        event.input.value = ""

        chat = self.query_one("#chat", ChatWidget)
        chat.add_user_message(message)

        if not self._agent:
            chat.add_system_message("No LLM provider configured. Check your API key.")
            return

        # Disable input while processing.
        input_widget = self.query_one("#chat-input", Input)
        input_widget.disabled = True

        # Run agent processing in a background worker.
        self.run_worker(
            self._process_agent_message(message),
            name="agent_response",
            exclusive=True,
        )

    async def _process_agent_message(self, message: str) -> str:
        """Process a message through the agent. Runs in a worker."""
        return await self._agent.process_message(message)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes to update the UI."""
        if event.worker.name != "agent_response":
            return

        chat = self.query_one("#chat", ChatWidget)
        input_widget = self.query_one("#chat-input", Input)

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                chat.add_assistant_message(str(result))
            input_widget.disabled = False
            input_widget.focus()

        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            chat.add_system_message(f"Error: {error}")
            input_widget.disabled = False
            input_widget.focus()

    def action_help(self) -> None:
        """Show help screen."""
        self.notify("Help screen not yet implemented", title="Help")

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        left_panel = self.query_one("#left-panel")
        left_panel.display = not left_panel.display

    def action_logs(self) -> None:
        """Show logs view."""
        self.notify("Logs view not yet implemented", title="Logs")

    def action_clear_chat(self) -> None:
        """Clear chat history."""
        chat = self.query_one("#chat", ChatWidget)
        chat.clear()
