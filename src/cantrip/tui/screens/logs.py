"""Log viewer modal screen for Cantrip TUI."""

import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

# Log levels to cycle through with the 'l' key.
_LOG_LEVELS = ("WARNING", "INFO", "DEBUG", "ERROR")

# Maximum number of log lines to fetch per refresh.
_MAX_LINES = 200

# Timeout for the juju debug-log subprocess (seconds).
_SUBPROCESS_TIMEOUT = 15


class LogScreen(ModalScreen):
    """Modal screen showing ``juju debug-log`` output with level filtering."""

    DEFAULT_CSS = """
    LogScreen {
        align: center middle;
    }

    #log-container {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #log-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }

    #log-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #log-output {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "cycle_level", "Level"),
    ]

    level: reactive[str] = reactive("WARNING")

    def __init__(self, model: str | None = None) -> None:
        """Initialise with the development model name."""
        super().__init__()
        self._model = model

    def compose(self) -> ComposeResult:
        """Compose the log viewer layout."""
        with Center(), Vertical(id="log-container"):
            yield Static(
                "Juju Logs                                 [Esc Close]",
                id="log-title",
            )
            yield RichLog(id="log-output", wrap=True)
            yield Static(
                "[r] Refresh  [l] Level  [Esc] Close",
                id="log-footer",
            )

    def on_mount(self) -> None:
        """Fetch logs on mount."""
        self._fetch_logs()

    def watch_level(self, _level: str) -> None:
        """Refresh logs when the level changes."""
        self._fetch_logs()

    def action_refresh(self) -> None:
        """Refresh the log output."""
        self._fetch_logs()

    def action_cycle_level(self) -> None:
        """Cycle through log levels."""
        current_idx = _LOG_LEVELS.index(self.level) if self.level in _LOG_LEVELS else 0
        self.level = _LOG_LEVELS[(current_idx + 1) % len(_LOG_LEVELS)]

    def _fetch_logs(self) -> None:
        """Fetch log lines from ``juju debug-log`` and populate the RichLog."""
        log_widget = self.query_one("#log-output", RichLog)
        log_widget.clear()

        if not self._model:
            log_widget.write("No development model connected.")
            return

        cmd = [
            "juju",
            "debug-log",
            "--model",
            self._model,
            "-n",
            str(_MAX_LINES),
            "--level",
            self.level,
            "--no-tail",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )

            if result.returncode != 0:
                log_widget.write(f"Error fetching logs: {result.stderr or 'unknown error'}")
                return

            output = result.stdout.strip()
            if not output:
                log_widget.write(f"No log entries at level {self.level}.")
                return

            for line in output.split("\n"):
                log_widget.write(line)

        except FileNotFoundError:
            log_widget.write("juju CLI not found. Is it installed?")
        except subprocess.TimeoutExpired:
            log_widget.write("Timed out fetching logs.")

        # Update the title with the current level.
        title = self.query_one("#log-title", Static)
        title.update(f"Juju Logs [{self.level}]                      [Esc Close]")
