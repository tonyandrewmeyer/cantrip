"""Main Cantrip TUI application."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Input
from textual.worker import Worker, WorkerState

from cantrip import __version__
from cantrip.agent.core import CantripAgent
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.llm import create_provider
from cantrip.llm.base import ProviderRateLimitError
from cantrip.tui.screens.help import HelpScreen
from cantrip.tui.widgets.chat import ChatWidget, MessageStatus, MessageWidget
from cantrip.tui.widgets.status import JujuStatusWidget
from cantrip.tui.widgets.statusbar import StatusBar

# Map preflight statuses to chat progress statuses.
_STATUS_MAP = {
    CheckStatus.PENDING: MessageStatus.PENDING,
    CheckStatus.RUNNING: MessageStatus.IN_PROGRESS,
    CheckStatus.PASSED: MessageStatus.COMPLETE,
    CheckStatus.FAILED: MessageStatus.ERROR,
    CheckStatus.SKIPPED: MessageStatus.COMPLETE,
}

# Preflight check names shown during the eager prepare (full bootstrap).
_PREPARE_CHECKS = ["concierge", "prepare", "juju", "controller", "cos"]

# Preflight check names shown if a re-bootstrap is needed (different preset).
_BOOTSTRAP_CHECKS = ["bootstrap", "controller", "cos"]


class CantripApp(App):
    """Cantrip TUI application."""

    TITLE = f"Cantrip v{__version__}"
    CSS_PATH = "cantrip.tcss"

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "toggle_status", "Toggle Status"),
        Binding("f3", "logs", "Logs"),
        Binding("f4", "debug", "Debug"),
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
        self._thinking_widget: MessageWidget | None = None
        self._prepare_widget: MessageWidget | None = None
        self._bootstrap_widget: MessageWidget | None = None
        self._bootstrap_started = False

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()
        yield Horizontal(
            Vertical(
                ChatWidget(id="chat"),
                Input(placeholder="Type your message...", id="chat-input"),
                id="left-panel",
            ),
            Vertical(
                JujuStatusWidget(id="juju-status"),
                id="right-panel",
            ),
            id="main-container",
        )
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        """Handle app mount."""
        self.query_one("#chat-input", Input).focus()
        # Hide the status panel until there is something to show.
        self.query_one("#right-panel").display = False
        self._init_agent()
        self._start_prepare()
        self._update_header_subtitle()

    def _init_agent(self) -> None:
        """Initialise the LLM provider and agent."""
        try:
            llm_provider = create_provider(self.provider_name, self.model_name)
            self._agent = CantripAgent(provider=llm_provider, charm_path=self.charm_path)
        except ValueError as e:
            chat = self.query_one("#chat", ChatWidget)
            chat.add_system_message(f"Failed to initialise provider: {e}")

    def _update_header_subtitle(self) -> None:
        """Rebuild the header subtitle from agent state."""
        parts: list[str] = []
        if self._agent:
            state = self._agent.state
            if state.dev_model:
                substrate = "lxd" if state.charm_type == "machine" else "k8s"
                parts.append(f"[{state.dev_model}:{substrate}]")
            if state.cos_model:
                parts.append(f"[{state.cos_model}:k8s]")
        parts.append("[F1 Help]")
        self.sub_title = " ".join(parts)

    # -- Preflight integration ------------------------------------------------

    def _start_prepare(self) -> None:
        """Eagerly start a full environment preparation in a background worker.

        Uses the default preset (k8s) so the environment is ready by the
        time the user finishes describing their charm.
        """
        if not self._agent:
            return
        chat = self.query_one("#chat", ChatWidget)
        self._prepare_widget = chat.add_system_message(
            "Preparing environment...",
            progress_items=[
                "Concierge",
                "Environment",
                "Juju CLI",
                "Controller",
                "COS",
            ],
        )
        self.run_worker(
            self._agent.prepare(
                preset=DEFAULT_PRESET,
                callback=self._on_prepare_event,
            ),
            name="preflight_prepare",
            exclusive=False,
        )

    def _on_prepare_event(self, event: PreflightEvent) -> None:
        """Handle an eager-prepare preflight event — update progress items."""
        if self._prepare_widget is None:
            return
        if event.check_name in _PREPARE_CHECKS:
            idx = _PREPARE_CHECKS.index(event.check_name)
            self._prepare_widget.update_progress(idx, _STATUS_MAP[event.status])
        if event.check_name == "cos" and event.status == CheckStatus.PASSED:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.cos_health = "● COS healthy"
            self._update_header_subtitle()

    def _start_bootstrap(self) -> None:
        """Re-bootstrap if the user picked a different preset than the default.

        If the eager prepare already completed with the same preset (or the
        user hasn't specified a charm type yet), this is a no-op.
        """
        if not self._agent or self._bootstrap_started:
            return
        preset = self._agent.state.charm_type
        if not preset:
            return
        # Skip if the eager prepare already used the right preset.
        if preset == DEFAULT_PRESET and self._agent.preflight_result.fully_ready:
            self._bootstrap_started = True
            return
        self._bootstrap_started = True
        chat = self.query_one("#chat", ChatWidget)
        self._bootstrap_widget = chat.add_system_message(
            f"Re-bootstrapping environment ({preset})...",
            progress_items=["Controller", "Controller check", "COS"],
        )
        self.run_worker(
            self._agent.bootstrap_environment(
                preset=preset,
                callback=self._on_bootstrap_event,
            ),
            name="preflight_bootstrap",
            exclusive=False,
        )

    def _on_bootstrap_event(self, event: PreflightEvent) -> None:
        """Handle a re-bootstrap preflight event — update progress items."""
        if self._bootstrap_widget is None:
            return
        if event.check_name in _BOOTSTRAP_CHECKS:
            idx = _BOOTSTRAP_CHECKS.index(event.check_name)
            self._bootstrap_widget.update_progress(idx, _STATUS_MAP[event.status])

    # -- Chat -----------------------------------------------------------------

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

        # Disable input and show thinking indicator while processing.
        input_widget = self.query_one("#chat-input", Input)
        input_widget.disabled = True
        self._thinking_widget = chat.add_system_message("Thinking...")

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
        if event.worker.name == "agent_response":
            self._on_agent_response_done(event)
        # Preflight workers don't need special handling on completion.

    def _on_agent_response_done(self, event: Worker.StateChanged) -> None:
        """Handle agent response worker completion."""
        chat = self.query_one("#chat", ChatWidget)
        input_widget = self.query_one("#chat-input", Input)

        # Remove the thinking indicator.
        if self._thinking_widget is not None:
            chat.remove_message(self._thinking_widget)
            self._thinking_widget = None

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                chat.add_assistant_message(str(result))
            input_widget.disabled = False
            input_widget.focus()
            # Check whether charm_type was set during this exchange.
            self._start_bootstrap()
            self._update_header_subtitle()
            self._update_test_summary()

        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, ProviderRateLimitError):
                chat.add_system_message("Rate limited — please wait a moment and try again.")
            else:
                chat.add_system_message(f"Error: {error}")
            input_widget.disabled = False
            input_widget.focus()

    def _update_test_summary(self) -> None:
        """Update the status bar test summary from agent state."""
        if not self._agent or not self._agent.state.test_results:
            return
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.test_summary = self._agent.state.test_results.format_summary()

    def action_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())

    def action_debug(self) -> None:
        """Show debug mode (stub)."""
        self.notify("Debug mode not yet implemented", title="Debug")

    def on_juju_status_widget_status_available(self) -> None:
        """Show the status panel when status data first arrives."""
        self.query_one("#right-panel").display = True

    def action_toggle_status(self) -> None:
        """Toggle status panel visibility."""
        right_panel = self.query_one("#right-panel")
        right_panel.display = not right_panel.display

    def action_logs(self) -> None:
        """Show logs view."""
        self.notify("Logs view not yet implemented", title="Logs")

    def action_clear_chat(self) -> None:
        """Clear chat history."""
        chat = self.query_one("#chat", ChatWidget)
        chat.clear()
