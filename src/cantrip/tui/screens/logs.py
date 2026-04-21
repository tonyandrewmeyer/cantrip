"""Log viewer modal screen for Cantrip TUI."""

import asyncio
import contextlib
import functools
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static
from textual.worker import Worker, WorkerState

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
        Binding("m", "cycle_model", "Model"),
        Binding("t", "toggle_stream", "Stream"),
    ]

    level: reactive[str] = reactive("WARNING")
    streaming: reactive[bool] = reactive(False)

    def __init__(
        self,
        model: str | None = None,
        *,
        dev_model: str | None = None,
        cos_model: str | None = None,
    ) -> None:
        """Initialise with the model(s) to tail.

        Callers may pass ``dev_model`` and ``cos_model`` separately; the
        ``m`` binding cycles between whichever are set.  The legacy
        positional ``model`` argument is equivalent to ``dev_model``.
        """
        super().__init__()
        if model is not None and dev_model is None:
            dev_model = model
        self._dev_model = dev_model
        self._cos_model = cos_model
        # Start with dev if available, otherwise fall back to cos.  The
        # active model is held on the instance rather than as a reactive
        # so we can re-fetch imperatively without fighting Textual's
        # watcher lifecycle (watchers fire before ``compose`` wires up
        # the ``#log-output`` widget).
        self._model = dev_model or cos_model
        self._stream_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the log viewer layout."""
        with Vertical(id="log-container"):
            with Horizontal(id="log-title"):
                yield Static("Juju Logs", classes="title-text")
                yield Static("[Esc Close]", classes="title-hint")
            yield RichLog(id="log-output", wrap=True)
            yield Static(
                "[r] Refresh  [l] Level  [m] Model  [t] Stream  [Esc] Close",
                id="log-footer",
            )

    def on_mount(self) -> None:
        """Fetch logs on mount."""
        self._update_title()
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

    def action_cycle_model(self) -> None:
        """Switch between dev and COS log sources.

        No-op when only one (or neither) model is configured — users
        running without COS should see the key do nothing rather than
        swap into a broken "None" state.
        """
        if not self._dev_model or not self._cos_model:
            return
        self._model = self._cos_model if self._model == self._dev_model else self._dev_model
        self._stop_stream()
        self._fetch_logs()

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
        """Kick off a background worker to fetch log lines."""
        log_widget = self.query_one("#log-output", RichLog)
        log_widget.clear()

        if not self._model:
            log_widget.write("No development model connected.")
            return

        log_widget.write("[dim]Fetching logs…[/dim]")
        self.run_worker(
            functools.partial(self._fetch_logs_blocking, self._model, self.level),
            name="fetch_logs",
            exclusive=True,
            thread=True,
        )

    @staticmethod
    def _fetch_logs_blocking(model: str, level: str) -> str:
        """Run ``juju debug-log`` in a thread (called via ``run_worker``)."""
        cmd = [
            "juju",
            "debug-log",
            "--model",
            model,
            "-n",
            str(_MAX_LINES),
            "--level",
            level,
            "--no-tail",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except FileNotFoundError:
            return "ERROR:juju CLI not found. Is it installed?"
        except subprocess.TimeoutExpired:
            return "ERROR:Timed out fetching logs."

        if result.returncode != 0:
            return f"ERROR:{result.stderr or 'unknown error'}"

        output = result.stdout.strip()
        if not output:
            return f"EMPTY:{level}"

        return output

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle the fetch_logs worker completing."""
        if event.worker.name != "fetch_logs":
            return
        if event.worker.state != WorkerState.SUCCESS:
            return

        result = event.worker.result
        log_widget = self.query_one("#log-output", RichLog)
        log_widget.clear()

        if result.startswith("ERROR:"):
            log_widget.write(result.removeprefix("ERROR:"))
        elif result.startswith("EMPTY:"):
            level = result.removeprefix("EMPTY:")
            log_widget.write(f"No log entries at level {level}.")
        else:
            for line in result.split("\n"):
                log_widget.write(line)

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
                self._model,
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
        """Update the title bar with current mode, level, and model.

        Wraps the final string in :class:`Content` so Textual treats it
        as literal text — the model name is arbitrary (and may contain
        stray ``[`` / ``<`` / ``=`` characters in test doubles).
        """
        with contextlib.suppress(LookupError):
            title = self.query_one("#log-title .title-text", Static)
            mode = "STREAMING" if self.streaming else self.level
            model_label = str(self._model) if self._model else "no-model"
            title.update(Content(f"Juju Logs [{model_label}] [{mode}]"))
