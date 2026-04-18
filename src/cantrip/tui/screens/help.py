"""Help screen modal for Cantrip TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical
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
        border: thick $primary;
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

    #help-scroll {
        height: 1fr;
    }

    .help-section-header {
        text-style: bold;
        padding-top: 1;
    }

    .help-separator {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the help screen layout."""
        with Center(), Vertical(id="help-container"):
            with Horizontal(id="help-title"):
                yield Static("Cantrip Help", classes="title-text")
                yield Static("[Esc Close]", classes="title-hint")
            with ScrollableContainer(id="help-scroll"):
                yield Static("─" * 66, classes="help-separator")

                yield Static("Quick Start", classes="help-section-header")
                yield Static("───────────", classes="help-separator")
                yield Static(
                    "Just describe what you want to charm:\n"
                    "  > build a charm for my flask app\n"
                    "  > add postgresql integration\n"
                    "  > add a backup action"
                )

                yield Static("Keyboard Shortcuts", classes="help-section-header")
                yield Static("──────────────────", classes="help-separator")
                yield Static(
                    "F1        This help\n"
                    "F2        Toggle status panel\n"
                    "F3        View logs\n"
                    "F4        Debug mode\n"
                    "F5        Watcher\n"
                    "F6        Files\n"
                    "F7        Model info\n"
                    "F8        Integration graph\n"
                    "F9        Transcript\n"
                    "/         Search chat (empty input only)\n"
                    "Ctrl+F    Search chat\n"
                    "Ctrl+L    Clear chat\n"
                    "Ctrl+C    Cancel operation\n"
                    "q         Quit"
                )

                yield Static("Slash commands", classes="help-section-header")
                yield Static("──────────────", classes="help-separator")
                yield Static(
                    "/feelings                Convene the inner parliament\n"
                    "                         (default: joy + fear)\n"
                    "/feelings joy fear       Run only the named emotions\n"
                    "                         (joy | fear | anger | disgust |\n"
                    "                         sadness)"
                )

                yield Static("Links", classes="help-section-header")
                yield Static("─────", classes="help-separator")
                yield Static("Grafana:  http://localhost:3000\nDocs:     https://juju.is/docs")
