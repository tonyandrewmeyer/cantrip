"""Help screen modal for Cantrip TUI."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpScreen(ModalScreen):
    """Modal help screen showing quick start, shortcuts, and links."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-container {
        width: 80%;
        max-width: 80;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #help-title {
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

    .clickable:hover {
        background: $surface-darken-1;
        color: $text;
    }

    #help-scroll {
        height: 1fr;
    }

    /* Phase 108.1: section headings carry weight via colour + bold,
     * not via a hand-drawn underline row. */
    .help-section-header {
        text-style: bold;
        color: $primary;
        padding-top: 1;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "dismiss", "Close"),
    ]

    def on_click(self, event: Click) -> None:
        """Make the bracketed ``[ Esc Close ]`` label behave like a button."""
        if getattr(event.widget, "id", None) == "help-close":
            self.dismiss()
            event.stop()

    def compose(self) -> ComposeResult:
        """Compose the help screen layout."""
        with Center(), Vertical(id="help-container"):
            with Horizontal(id="help-title"):
                yield Static("Cantrip Help", classes="title-text")
                yield Static(
                    "[ Esc Close ]", id="help-close", classes="title-hint clickable", markup=False
                )
            with ScrollableContainer(id="help-scroll"):
                yield Static("Quick Start", classes="help-section-header")
                yield Static(
                    "Just describe what you want to charm:\n"
                    "  > build a charm for my flask app\n"
                    "  > charm overleaf, the collaborative LaTeX editor\n"
                    "  > improve the charm in ./my-charm\n"
                    "  > add a backup action"
                )

                yield Static("Keyboard Shortcuts", classes="help-section-header")
                yield Static(
                    "F1        This help\n"
                    "F2        Toggle status panel\n"
                    "F3        View logs\n"
                    "F4        Debug mode\n"
                    "F5        Watcher (pause/resume auto-reactions)\n"
                    "F6        Files\n"
                    "F7        Model info\n"
                    "F8        Integration graph\n"
                    "F9        Transcript\n"
                    "Ctrl+F    Search chat\n"
                    "Ctrl+L    Clear chat\n"
                    "Ctrl+X    Toggle shell mode (Enter runs the command\n"
                    "          as a subprocess; bypasses the agent so no\n"
                    "          tokens are spent — prefix with `$$` to\n"
                    "          also keep the row out of any future\n"
                    "          agent context)\n"
                    "Ctrl+C    Cancel operation (also: Esc)\n"
                    "q         Quit"
                )

                yield Static("Slash commands", classes="help-section-header")
                yield Static(
                    "/feelings                Convene the inner parliament\n"
                    "                         (default: joy + fear)\n"
                    "/feelings joy fear       Run only the named emotions\n"
                    "                         (joy | fear | anger | disgust |\n"
                    "                         sadness)"
                )

                yield Static("Links", classes="help-section-header")
                yield Static("Grafana:  http://localhost:3000\nDocs:     https://juju.is/docs")
