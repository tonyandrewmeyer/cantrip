"""Log viewer modal screen for Cantrip TUI."""

import asyncio
import contextlib
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

# Log levels to cycle through with the 'l' key.
_LOG_LEVELS = ("WARNING", "INFO", "DEBUG", "ERROR")

# Maximum number of log lines to fetch per refresh (non-streaming).
_MAX_LINES = 200

# Timeout for the juju debug-log subprocess (seconds).
_SUBPROCESS_TIMEOUT = 15


class LogScreen(ModalScreen):
    """Modal screen showing ``juju debug-log`` output with level filtering.

    Supports two modes:

    - **Static** — fetches a fixed batch of lines (default, on open and refresh).
    - **Streaming** — tails live logs via ``juju debug-log --tail`` (press ``t``).
    """

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
        Binding("t", "toggle_stream", "Stream"),
    ]

    level: reactive[str] = reactive("WARNING")
    streaming: reactive[bool] = reactive(False)

    def __init__(self, model: str | None = None) -> None:
        """Initialise with the development model name."""
        super().__init__()
        self._model = model
        self._stream_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the log viewer layout."""
        with Center(), Vertical(id="log-container"):
            yield Static(
                "Juju Logs                                 [Esc Close]",
                id="log-title",
            )
            yield RichLog(id="log-output", wrap=True)
            yield Static(
                "[r] Refresh  [l] Level  [t] Stream  [Esc] Close",
                id="log-footer",
            )

    def on_mount(self) -> None:
        """Fetch logs on mount."""
        self._fetch_logs()

    def watch_level(self, _level: str) -> None:
        """Refresh logs when the level changes."""
        self._stop_stream()
        self._fetch_logs()

    def action_refresh(self) -> None:
        """Refresh the log output."""
        self._stop_stream()
        self._fetch_logs()

    def action_cycle_level(self) -> None:
        """Cycle through log levels."""
        current_idx = _LOG_LEVELS.index(self.level) if self.level in _LOG_LEVELS else 0
        self.level = _LOG_LEVELS[(current_idx + 1) % len(_LOG_LEVELS)]

    def action_toggle_stream(self) -> None:
        """Toggle live log streaming on/off."""
        if self.streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def action_dismiss(self) -> None:
        """Stop streaming and dismiss."""
        self._stop_stream()
        self.dismiss()

    # -- Static fetch --------------------------------------------------------

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

        self._update_title()

    # -- Live streaming ------------------------------------------------------

    def _start_stream(self) -> None:
        """Start tailing logs in the background."""
        if self.streaming or not self._model:
            return
        self.streaming = True
        log_widget = self.query_one("#log-output", RichLog)
        log_widget.clear()
        log_widget.write(f"[dim]Streaming logs at level {self.level}… (press t to stop)[/dim]")
        self._stream_task = asyncio.create_task(self._stream_loop())
        self._update_title()

    def _stop_stream(self) -> None:
        """Stop the streaming task if running."""
        if not self.streaming:
            return
        self.streaming = False
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None
        self._update_title()

    async def _stream_loop(self) -> None:
        """Background task that tails juju debug-log and appends lines."""
        from cantrip.juju.log_stream import stream_lines

        log_widget = self.query_one("#log-output", RichLog)
        try:
            async for line in stream_lines(
                self._model,  # type: ignore[arg-type]
                level=self.level,
                lines=50,
                max_lines=2000,
            ):
                if not self.streaming:
                    break
                log_widget.write(line)
        except asyncio.CancelledError:
            pass
        except (OSError, TimeoutError):
            pass
        finally:
            self.streaming = False
            self._update_title()

    # -- Helpers -------------------------------------------------------------

    def _update_title(self) -> None:
        """Update the title bar with current mode and level."""
        with contextlib.suppress(Exception):
            title = self.query_one("#log-title", Static)
            mode = "STREAMING" if self.streaming else self.level
            title.update(f"Juju Logs [{mode}]                      [Esc Close]")
