"""Trace/debug viewer modal screen for Cantrip TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class TraceScreen(ModalScreen):
    """Modal screen showing COS endpoint URLs and Grafana links."""

    DEFAULT_CSS = """
    TraceScreen {
        align: center middle;
    }

    #trace-container {
        width: 70;
        max-height: 60%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #trace-title {
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

    .trace-section-header {
        text-style: bold;
        padding-top: 1;
    }

    .trace-separator {
        color: $text-muted;
    }

    .trace-link {
        padding: 0 2;
    }

    .trace-info {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, cos_model: str | None = None) -> None:
        """Initialise with the COS model name."""
        super().__init__()
        self._cos_model = cos_model

    def compose(self) -> ComposeResult:
        """Compose the trace/debug screen."""
        with Center(), Vertical(id="trace-container"):
            with Horizontal(id="trace-title"):
                yield Static("Observability", classes="title-text")
                yield Static("[Esc Close]", classes="title-hint")
            yield Static("─" * 66, classes="trace-separator")

            # COS status.
            yield Static("COS Model", classes="trace-section-header")
            yield Static("─────────", classes="trace-separator")
            if self._cos_model:
                yield Static(f"Model: {self._cos_model}")
                yield Static("Status: Connected", classes="trace-info")
            else:
                yield Static("Not deployed", classes="trace-info")

            # Grafana.
            yield Static("Grafana", classes="trace-section-header")
            yield Static("───────", classes="trace-separator")
            yield Static(
                "URL: http://localhost:3000",
                classes="trace-link",
            )
            yield Static(
                "Dashboards, metrics, and alerting.",
                classes="trace-info",
            )

            # Quick links.
            yield Static("Quick Links", classes="trace-section-header")
            yield Static("───────────", classes="trace-separator")
            yield Static(
                "Grafana Explore:  http://localhost:3000/explore\n"
                "Tempo (traces):   http://localhost:3000/explore?orgId=1&left=...\n"
                "Loki (logs):      http://localhost:3000/explore?orgId=1&left=...",
                classes="trace-link",
            )

            # Instructions.
            yield Static("Access", classes="trace-section-header")
            yield Static("──────", classes="trace-separator")
            yield Static(
                "If Grafana is not accessible at localhost:3000,\n"
                "set up port forwarding:\n"
                "  juju ssh --model cos grafana/0 -L 3000:localhost:3000",
                classes="trace-info",
            )
