"""Integration graph modal screen for Cantrip TUI."""

from jubilant import statustypes
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

# Status indicator characters and Rich style names.
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "active": ("●", "green"),
    "waiting": ("○", "yellow"),
    "blocked": ("◌", "red"),
    "maintenance": ("◐", "blue"),
    "unknown": ("○", "yellow"),
    "error": ("✗", "red"),
}

# Border colour per status.
_BORDER_COLOUR: dict[str, str] = {
    "active": "green",
    "waiting": "yellow",
    "blocked": "red",
    "maintenance": "blue",
    "error": "red",
}


def _status_indicator(status: str) -> Text:
    """Return a coloured status indicator."""
    char, style = _STATUS_STYLE.get(status, ("○", "yellow"))
    return Text.assemble((f"{char} {status}", style))


def _app_panel(name: str, app: statustypes.AppStatus, highlight: bool = False) -> Panel:
    """Build a Rich Panel for a single application."""
    status = app.app_status.current
    unit_count = len(app.units)
    message = app.app_status.message or ""
    if len(message) > 40:
        message = message[:37] + "..."

    lines: list[Text | str] = []
    lines.append(_status_indicator(status))
    if message:
        lines.append(Text(f"  {message}", style="dim"))
    lines.append(f"{unit_count} unit{'s' if unit_count != 1 else ''}")

    # Show unit breakdown if multiple units.
    if unit_count > 1:
        for unit_name, unit in app.units.items():
            u_status = unit.workload_status.current
            u_char, u_style = _STATUS_STYLE.get(u_status, ("○", "yellow"))
            short = unit_name.split("/")[-1]
            lines.append(Text.assemble(("  ", ""), (f"{u_char}", u_style), f" /{short}"))

    border = _BORDER_COLOUR.get(status, "white")
    title = f"★ {name}" if highlight else name

    return Panel(
        Group(*lines),
        title=title,
        title_align="left",
        border_style=border,
        width=32,
        expand=False,
    )


def _relation_line(source: str, endpoint: str, target: str, interface: str) -> Text:
    """Render a single relation as a decorated line."""
    return Text.assemble(
        ("  ", ""),
        (source, "bold"),
        (":", ""),
        (endpoint, "cyan"),
        (" ── ", "dim"),
        (f"[{interface}]", "dim italic"),
        (" ──▸ ", "dim"),
        (target, "bold"),
    )


def build_graph(
    status: statustypes.Status,
    current_app: str | None = None,
) -> list[Text | Panel | str]:
    """Build a list of Rich renderables representing the integration graph.

    Returns a flat list of panels (apps) and text lines (relations) that
    can be rendered sequentially.  Apps are grouped first, followed by a
    relation section.
    """
    if not status.apps:
        return [Text("No applications deployed.", style="dim italic")]

    parts: list[Text | Panel | str] = []

    # Header.
    parts.append(
        Text.assemble(
            ("Model: ", "bold"),
            (status.model.name, ""),
            ("  ", ""),
            (f"({status.model.cloud})", "dim"),
        )
    )
    parts.append("")

    # App panels.
    for app_name, app in sorted(status.apps.items()):
        highlight = app_name == current_app
        parts.append(_app_panel(app_name, app, highlight=highlight))

    # Relation section.
    seen: set[tuple[str, str, str]] = set()
    relation_lines: list[Text] = []
    for app_name, app in sorted(status.apps.items()):
        for endpoint, related_list in sorted(app.relations.items()):
            for rel in related_list:
                # Deduplicate bidirectional relations.
                pair = tuple(sorted([app_name, rel.related_app]))
                key = (pair[0], pair[1], rel.interface)
                if key in seen:
                    continue
                seen.add(key)
                relation_lines.append(
                    _relation_line(app_name, endpoint, rel.related_app, rel.interface)
                )

    if relation_lines:
        parts.append("")
        parts.append(Text("Relations", style="bold underline"))
        parts.extend(relation_lines)

    return parts


class GraphScreen(ModalScreen):
    """Modal screen showing a visual integration graph of the Juju model."""

    DEFAULT_CSS = """
    GraphScreen {
        align: center middle;
    }

    #graph-container {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #graph-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }

    #graph-body {
        height: 1fr;
        overflow-y: auto;
    }

    #graph-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        status: statustypes.Status | None = None,
        current_app: str | None = None,
    ) -> None:
        """Initialise with current Juju status."""
        super().__init__()
        self._status = status
        self._current_app = current_app

    def compose(self) -> ComposeResult:
        """Compose the graph layout."""
        with Center(), Vertical(id="graph-container"):
            yield Static(
                "Integration Graph                         [Esc Close]",
                id="graph-title",
            )
            yield Static("", id="graph-body")
            yield Static(
                "[r] Refresh  [Esc] Close",
                id="graph-footer",
            )

    def on_mount(self) -> None:
        """Render the graph on mount."""
        self._render_graph()

    def action_refresh(self) -> None:
        """Re-render the graph (useful after external status change)."""
        self._render_graph()

    def update_status(self, status: statustypes.Status) -> None:
        """Update the status and re-render."""
        self._status = status
        self._render_graph()

    def _render_graph(self) -> None:
        """Build and display the integration graph."""
        body = self.query_one("#graph-body", Static)

        if not self._status:
            body.update("No model connected.")
            return

        parts = build_graph(self._status, self._current_app)
        body.update(Group(*parts))
