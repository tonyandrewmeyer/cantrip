"""Tool-failure detail modal screen for Cantrip TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static


class ToolErrorScreen(ModalScreen):
    """Modal showing the full output of a failed tool call.

    The chat surfaces only render a one-line caption for a tool
    failure; clicking that block opens this screen, which surfaces the
    captured ``error`` summary and ``output`` (stderr, test logs,
    tracebacks) so the user can see what actually went wrong without
    opening the transcript viewer.
    """

    DEFAULT_CSS = """
    ToolErrorScreen {
        align: center middle;
    }

    #tool-error-container {
        width: 90%;
        height: 80%;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }

    #tool-error-title {
        width: 100%;
        height: 1;
        padding-bottom: 1;
    }

    .title-text {
        text-style: bold;
        color: $error;
        width: 1fr;
    }

    .title-hint {
        color: $text-muted;
        width: auto;
    }

    .clickable:hover {
        background: $surface-darken-1;
        color: $text;
    }

    #tool-error-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #tool-error-output {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, caption: str, detail: str) -> None:
        """Initialise with the failed tool's caption and full detail text."""
        super().__init__()
        self._caption = caption.strip() or "Tool failed"
        self._detail = detail

    def compose(self) -> ComposeResult:
        """Compose the tool-error detail layout."""
        with Vertical(id="tool-error-container"):
            with Horizontal(id="tool-error-title"):
                yield Static(self._caption, classes="title-text")
                yield Static(
                    "[ Esc Close ]",
                    id="tool-error-close",
                    classes="title-hint clickable",
                    markup=False,
                )
            yield RichLog(
                id="tool-error-output",
                wrap=True,
                markup=False,
                highlight=False,
            )
            yield Static(
                "[ Esc Close ]", id="tool-error-footer", classes="clickable", markup=False
            )

    def on_click(self, event: Click) -> None:
        """Make the bracketed ``[ Esc Close ]`` labels behave like buttons."""
        if getattr(event.widget, "id", None) in ("tool-error-close", "tool-error-footer"):
            self.dismiss()
            event.stop()

    def on_mount(self) -> None:
        """Populate the log with the captured failure detail."""
        output = self.query_one("#tool-error-output", RichLog)
        text = self._detail.strip() or "(no further detail was captured)"
        for line in text.splitlines() or [text]:
            output.write(line)
