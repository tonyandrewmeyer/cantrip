"""Trace/debug viewer modal screen for Cantrip TUI."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Static

from cantrip.agent import cos_endpoints


class TraceScreen(ModalScreen):
    """Modal screen showing COS endpoint URLs and Grafana links."""

    DEFAULT_CSS = """
    TraceScreen {
        align: center middle;
    }

    #trace-container {
        width: 70;
        max-height: 60%;
        border: round $primary;
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

    .clickable:hover {
        background: $surface-darken-1;
        color: $text;
    }

    /* Phase 108.1: section headings replace the older
     * heading + ``─`` underline pattern. */
    .trace-section-header {
        text-style: bold;
        color: $primary;
        padding-top: 1;
    }

    .trace-link {
        padding: 0 2;
    }

    .trace-info {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "dismiss", "Close"),
    ]

    # Shown when we couldn't derive a real Grafana URL from the COS status
    # message.  The screen still renders placeholders so users have the
    # local port-forward fallback.
    _FALLBACK_GRAFANA = "http://localhost:3000"

    def __init__(
        self,
        cos_model: str | None = None,
        endpoints: cos_endpoints.CosEndpoints | None = None,
    ) -> None:
        """Initialise with the COS model name and optional derived endpoints.

        ``endpoints`` should come from
        :func:`cantrip.agent.cos_endpoints.derive_endpoints` applied to the
        watcher's latest COS status snapshot.  Passing ``None`` (the default)
        is equivalent to "no poll yet"; the screen renders an honest
        "Unknown" status rather than lying.
        """
        super().__init__()
        self._cos_model = cos_model
        self._endpoints = endpoints or cos_endpoints.CosEndpoints()

    def _status_line(self) -> str:
        """Human-readable status for the COS Model section."""
        if not self._cos_model:
            return "Not deployed"
        if not self._endpoints.known:
            return "Status: Unknown (no poll yet)"
        if not self._endpoints.has_grafana:
            return "Status: Grafana not deployed in COS model"
        if self._endpoints.grafana_active:
            return "Status: Reachable"
        return "Status: Not reachable"

    def _grafana_base(self) -> str:
        """Return the Grafana base URL for display — real URL or fallback."""
        return self._endpoints.grafana_url or self._FALLBACK_GRAFANA

    def on_click(self, event: Click) -> None:
        """Make the bracketed ``[ Esc Close ]`` label behave like a button."""
        if getattr(event.widget, "id", None) == "trace-close":
            self.dismiss()
            event.stop()

    def compose(self) -> ComposeResult:
        """Compose the trace/debug screen."""
        with Center(), Vertical(id="trace-container"):
            with Horizontal(id="trace-title"):
                yield Static("Observability", classes="title-text")
                yield Static(
                    "[ Esc Close ]", id="trace-close", classes="title-hint clickable", markup=False
                )
            # COS status.
            yield Static("COS Model", classes="trace-section-header")
            if self._cos_model:
                yield Static(f"Model: {self._cos_model}")
            yield Static(self._status_line(), classes="trace-info")

            # Grafana.
            grafana_base = self._grafana_base()
            yield Static("Grafana", classes="trace-section-header")
            yield Static(f"URL: {grafana_base}", classes="trace-link")
            if self._endpoints.grafana_url is None:
                yield Static(
                    "(Grafana workload status did not advertise a URL — "
                    "using the local port-forward fallback.)",
                    classes="trace-info",
                )
            yield Static(
                "Dashboards, metrics, and alerting.",
                classes="trace-info",
            )

            # Quick links.
            yield Static("Quick Links", classes="trace-section-header")
            explore = self._endpoints.grafana_explore_url or f"{grafana_base}/explore"
            tempo = self._endpoints.tempo_explore_url
            loki = self._endpoints.loki_explore_url
            tempo_line = (
                f"Tempo (traces):   {tempo}"
                if tempo is not None
                else "Tempo (traces):   not available (Tempo or Grafana URL missing)"
            )
            loki_line = (
                f"Loki (logs):      {loki}"
                if loki is not None
                else "Loki (logs):      not available (Loki or Grafana URL missing)"
            )
            yield Static(
                f"Grafana Explore:  {explore}\n{tempo_line}\n{loki_line}",
                classes="trace-link",
            )

            # Instructions.
            yield Static("Access", classes="trace-section-header")
            yield Static(
                "If Grafana is not accessible at the URL above,\n"
                "set up port forwarding:\n"
                "  juju ssh --model cos grafana/0 -L 3000:localhost:3000",
                classes="trace-info",
            )
