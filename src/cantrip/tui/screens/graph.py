"""Integration graph modal screen for Cantrip TUI."""

import contextlib

from jubilant import statustypes
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

# Cycle order for the ``f`` binding; ``None`` means show every app.
_FILTER_CYCLE: tuple[frozenset[str] | None, ...] = (
    None,
    frozenset({"blocked"}),
    frozenset({"waiting"}),
    frozenset({"blocked", "waiting"}),
)

# Short labels for the title bar.
_FILTER_LABELS: dict[frozenset[str] | None, str] = {
    None: "all",
    frozenset({"blocked"}): "blocked",
    frozenset({"waiting"}): "waiting",
    frozenset({"blocked", "waiting"}): "blocked+waiting",
}

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


def _has_catalogue_relation(app: statustypes.AppStatus) -> bool:
    """True iff the app has registered itself with COS Catalogue.

    Used to surface a badge on the integration graph so users can
    spot at a glance which apps appear on the COS landing page.
    """
    for related_list in app.relations.values():
        for rel in related_list:
            if rel.interface == "catalogue":
                return True
    return False


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
    if _has_catalogue_relation(app):
        title = f"{title} [cat]"

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
    status_filter: frozenset[str] | None = None,
) -> list[Text | Panel | str]:
    """Build a list of Rich renderables representing the integration graph.

    Returns a flat list of panels (apps) and text lines (relations) that
    can be rendered sequentially.  Apps are grouped first, followed by a
    relation section.

    When *status_filter* is set, only apps whose app-level status is in
    the set appear as panels, and relations are restricted to pairs
    where both ends pass the filter.  The relation section stays useful
    rather than turning into a noise of half-dangling edges.
    """
    if not status.apps:
        return [Text("No applications deployed.", style="dim italic")]

    visible_apps: dict[str, statustypes.AppStatus] = {
        name: app
        for name, app in status.apps.items()
        if status_filter is None or app.app_status.current in status_filter
    }

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

    if not visible_apps:
        label = ", ".join(sorted(status_filter)) if status_filter else "any"
        parts.append(Text(f"No applications matching filter ({label}).", style="dim italic"))
        return parts

    # App panels.
    for app_name, app in sorted(visible_apps.items()):
        highlight = app_name == current_app
        parts.append(_app_panel(app_name, app, highlight=highlight))

    # Relation section — only include edges where both ends are visible.
    seen: set[tuple[str, str, str]] = set()
    relation_lines: list[Text] = []
    for app_name, app in sorted(visible_apps.items()):
        for endpoint, related_list in sorted(app.relations.items()):
            for rel in related_list:
                if rel.related_app not in visible_apps:
                    continue
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
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #graph-title {
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

    #graph-body {
        height: 1fr;
    }

    #graph-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #graph-footer .clickable {
        margin-right: 2;
        width: auto;
    }

    .clickable:hover {
        background: $surface-darken-1;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
        Binding("f", "cycle_filter", "Filter"),
    ]

    def __init__(
        self,
        status: statustypes.Status | None = None,
        current_app: str | None = None,
        model: str | None = None,
        cos_status: statustypes.Status | None = None,
        cos_model: str | None = None,
    ) -> None:
        """Initialise with current Juju status.

        ``status`` / ``model`` carry the dev model (the primary work
        surface).  ``cos_status`` / ``cos_model`` carry the optional
        COS model so the graph can show both side by side — when the
        user hits F8 they expect to see *all* the integration shapes
        at once, not just the dev half.
        """
        super().__init__()
        self._status = status
        self._current_app = current_app
        self._model = model
        self._cos_status = cos_status
        self._cos_model = cos_model
        # Held as a plain int so tests can cycle the filter without a
        # mounted DOM; the binding re-renders explicitly in
        # :meth:`action_cycle_filter`.
        self.filter_index = 0

    def compose(self) -> ComposeResult:
        """Compose the graph layout."""
        with Vertical(id="graph-container"):
            with Horizontal(id="graph-title"):
                yield Static("Integration Graph", classes="title-text")
                yield Static(
                    "[ Esc Close ]",
                    id="graph-close",
                    classes="title-hint clickable",
                )
            yield RichLog(id="graph-body", wrap=True)
            with Horizontal(id="graph-footer"):
                yield Static("[ r Refresh ]", id="graph-refresh-btn", classes="clickable")
                yield Static("[ f Filter ]", id="graph-filter-btn", classes="clickable")
                yield Static("[ Esc Close ]", id="graph-close-btn", classes="clickable")

    def on_click(self, event: Click) -> None:
        """Make the text-shaped footer entries actually clickable.

        The keybindings still cover keyboard users; this routes mouse
        clicks on the visible labels to the matching action so the
        affordance the bracketed text suggests actually fires.
        """
        widget = event.widget
        if widget is None:
            return
        wid = getattr(widget, "id", None)
        if wid == "graph-refresh-btn":
            self.action_refresh()
            event.stop()
        elif wid == "graph-filter-btn":
            self.action_cycle_filter()
            event.stop()
        elif wid in ("graph-close-btn", "graph-close"):
            self.dismiss()
            event.stop()

    def on_mount(self) -> None:
        """Render the graph on mount."""
        self._render_graph()

    def action_refresh(self) -> None:
        """Fetch fresh Juju status and re-render the graph.

        Refreshes the dev model only — COS models are typically more
        stable than the dev surface, and pulling a fresh COS status
        on every press would slow the refresh markedly.  The cached
        ``self._cos_status`` continues to render alongside.
        """
        if self._model:
            self.run_worker(self._fetch_and_render, thread=True)
        else:
            self._render_graph()

    def action_cycle_filter(self) -> None:
        """Cycle the app-status filter: all → blocked → waiting → both."""
        self.filter_index = (self.filter_index + 1) % len(_FILTER_CYCLE)
        if self.is_mounted:
            self._render_graph()

    def _fetch_and_render(self) -> None:
        """Fetch current Juju status in a background thread and re-render."""
        import functools

        import jubilant

        try:
            juju = jubilant.Juju(model=self._model)
            self._status = functools.partial(juju.status)()
        except (jubilant.CLIError, OSError, TimeoutError):
            pass
        self.app.call_from_thread(self._render_graph)

    def update_status(self, status: statustypes.Status) -> None:
        """Update the status and re-render."""
        self._status = status
        self._render_graph()

    def _render_graph(self) -> None:
        """Build and display the integration graph for both models."""
        body = self.query_one("#graph-body", RichLog)
        body.clear()
        self._update_title()

        if not self._status and not self._cos_status:
            body.write("No model connected.")
            return

        status_filter = _FILTER_CYCLE[self.filter_index]

        if self._status is not None:
            body.write(Text("── Dev model ──", style="bold cyan"))
            for part in build_graph(self._status, self._current_app, status_filter):
                body.write(part)

        if self._cos_status is not None:
            if self._status is not None:
                body.write("")
            body.write(Text("── COS model ──", style="bold cyan"))
            for part in build_graph(self._cos_status, None, status_filter):
                body.write(part)

    def _update_title(self) -> None:
        """Reflect the active filter in the title bar."""
        with contextlib.suppress(LookupError):
            title = self.query_one("#graph-title .title-text", Static)
            label = _FILTER_LABELS[_FILTER_CYCLE[self.filter_index]]
            title.update(f"Integration Graph [{label}]")
