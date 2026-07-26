"""Integration graph modal screen for Cantrip TUI.

The F8 graph is built around the *edges*: a relation is a clickable
object that opens an inline detail strip (interface, the endpoint names
on both ends, and — when the model matches a known preset — the
provider/requirer roles and a one-line description from the preset
catalogue).  Selecting an *app* focuses it: unconnected apps and edges
that don't touch it fade out; Escape, or re-selecting the same app,
clears the focus.  When the model matches a preset the app panels are
grouped under that preset's semantic layers; otherwise they fall back
to a flat alphabetical list — no layer is ever invented.
"""

from __future__ import annotations

import contextlib
import dataclasses
from typing import TYPE_CHECKING, ClassVar

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from cantrip.agent import presets
from cantrip.tui import topology

if TYPE_CHECKING:
    from jubilant import statustypes
    from textual.app import ComposeResult
    from textual.events import Click

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

# Border colour per status (Rich colour names — the RichLog-style
# panels render Rich renderables, not Textual markup).
_BORDER_COLOUR = topology.STATUS_RICH_COLOUR

_DIM_BORDER = "grey42"


def _status_indicator(status: str) -> Text:
    """Return a coloured ``● status`` indicator."""
    char = topology.status_glyph(status)
    return Text.assemble((f"{char} {status}", topology.status_rich_colour(status)))


def _has_catalogue_relation(app: statustypes.AppStatus) -> bool:
    """Return true iff the app has registered itself with COS Catalogue.

    Surfaced as a ``[cat]`` badge so users can spot at a glance which
    apps appear on the COS landing page.
    """
    for related_list in app.relations.values():
        for rel in related_list:
            if rel.interface == "catalogue":
                return True
    return False


def _app_panel(
    name: str,
    app: statustypes.AppStatus,
    *,
    highlight: bool = False,
    dim: bool = False,
) -> Panel:
    """Build a Rich Panel for a single application.

    ``highlight`` marks the app under construction with a ``★``.  ``dim``
    fades the panel when another app is focused and this one isn't a
    neighbour.
    """
    status = app.app_status.current
    unit_count = len(app.units)
    message = app.app_status.message or ""
    if len(message) > 40:
        message = message[:37] + "..."

    lines: list[Text | str] = [_status_indicator(status)]
    if message:
        lines.append(Text(f"  {message}", style="dim"))
    lines.append(f"{unit_count} unit{'s' if unit_count != 1 else ''}")
    if unit_count > 1:
        for unit_name, unit in app.units.items():
            u_status = unit.workload_status.current
            short = unit_name.split("/")[-1]
            lines.append(
                Text.assemble(
                    ("  ", ""),
                    (topology.status_glyph(u_status), topology.status_rich_colour(u_status)),
                    f" /{short}",
                )
            )

    title = f"★ {name}" if highlight else name
    if _has_catalogue_relation(app):
        title = f"{title} [cat]"
    border = _DIM_BORDER if dim else _BORDER_COLOUR.get(status, "white")
    return Panel(
        Group(*lines),
        title=title,
        title_align="left",
        border_style=border,
        width=32,
        expand=False,
        style="dim" if dim else "",
    )


def _endpoint_for(
    status: statustypes.Status, app_name: str, other: str, interface: str
) -> str | None:
    """Return the local endpoint name on *app_name*'s side of its relation to *other*."""
    app = status.apps.get(app_name)
    if app is None:
        return None
    for ep_name, rels in app.relations.items():
        for rel in rels:
            if rel.related_app == other and rel.interface == interface:
                return ep_name
    return None


def _edge_endpoints(status: statustypes.Status, edge: topology.Edge) -> tuple[str, str]:
    """``("a:ep", "b:ep")`` for an edge, falling back to the bare app name."""
    ep_a = _endpoint_for(status, edge.a, edge.b, edge.interface)
    ep_b = _endpoint_for(status, edge.b, edge.a, edge.interface)
    return (
        f"{edge.a}:{ep_a}" if ep_a else edge.a,
        f"{edge.b}:{ep_b}" if ep_b else edge.b,
    )


def _edge_label(status: statustypes.Status, edge: topology.Edge, *, dim: bool = False) -> Text:
    """Render an edge as ``a:ep ──[interface]── b:ep`` for the option list."""
    a_disp, b_disp = _edge_endpoints(status, edge)
    name_style = "dim" if dim else "bold"
    iface_style = "dim" if dim else "cyan italic"
    return Text.assemble(
        ("  ", ""),
        (a_disp, name_style),
        (" ──", "dim"),
        (f"[{edge.interface}]", iface_style),
        ("── ", "dim"),
        (b_disp, name_style),
    )


@dataclasses.dataclass(frozen=True)
class GraphItem:
    """One row in the rendered graph (an app panel, an edge, or a header)."""

    kind: str  # "model" | "layer" | "app" | "edges-header" | "edge" | "empty"
    renderable: RenderableType = ""
    model: str = ""  # "dev" / "cos" — which model this item belongs to
    app_name: str = ""
    edge: topology.Edge | None = None
    option_id: str | None = None  # set for selectable items (app:/edge:)

    @property
    def selectable(self) -> bool:
        return self.option_id is not None


def _focus_neighbours(
    focus_app: str | None, visible: set[str], edges: list[topology.Edge]
) -> set[str] | None:
    """Return the focus app plus its direct neighbours, or ``None`` if no focus."""
    if not focus_app or focus_app not in visible:
        return None
    out = {focus_app}
    for e in edges:
        if e.a == focus_app:
            out.add(e.b)
        elif e.b == focus_app:
            out.add(e.a)
    return out


def build_graph_items(
    status: statustypes.Status,
    *,
    model: str = "",
    current_app: str | None = None,
    status_filter: frozenset[str] | None = None,
    preset_match: presets.PresetMatch | None = None,
    focus_app: str | None = None,
) -> list[GraphItem]:
    r"""Build the ordered list of :class:`GraphItem`\\ s for one model.

    Apps come first — grouped under preset-layer headers when
    *preset_match* is given, otherwise alphabetically — followed by a
    ``Relations`` header and one edge item per deduplicated app-pair.
    When *focus_app* is set and present, app panels and edges that don't
    touch it render dimmed.
    """
    if not status.apps:
        return [
            GraphItem(
                kind="empty", renderable=Text("No applications deployed.", style="dim italic")
            )
        ]

    visible = {
        name: app
        for name, app in status.apps.items()
        if status_filter is None or app.app_status.current in status_filter
    }
    if not visible:
        label = ", ".join(sorted(status_filter)) if status_filter else "any"
        return [
            GraphItem(
                kind="empty",
                renderable=Text(f"No applications matching filter ({label}).", style="dim italic"),
            )
        ]

    edges = topology.dedup_edges(status, visible=set(visible))
    neighbours = _focus_neighbours(focus_app, set(visible), edges)

    def _app_item(name: str) -> GraphItem:
        dim = neighbours is not None and name not in neighbours
        return GraphItem(
            kind="app",
            model=model,
            app_name=name,
            renderable=_app_panel(name, visible[name], highlight=name == current_app, dim=dim),
            option_id=f"app:{model}:{name}",
        )

    items: list[GraphItem] = []
    if preset_match is not None and preset_match.app_layers:
        layer_order = [*preset_match.bundle.layers, "Other"]
        by_layer: dict[str, list[str]] = {}
        for name in visible:
            by_layer.setdefault(preset_match.app_layers.get(name, "Other"), []).append(name)
        for layer in layer_order:
            names = sorted(by_layer.get(layer, []))
            if not names:
                continue
            items.append(GraphItem(kind="layer", renderable=Text(f"▸ {layer}", style="bold")))
            items.extend(_app_item(n) for n in names)
    else:
        items.extend(_app_item(n) for n in sorted(visible))

    if edges:
        items.append(
            GraphItem(kind="edges-header", renderable=Text("Relations", style="bold underline"))
        )
        for i, edge in enumerate(edges):
            dim = neighbours is not None and focus_app not in (edge.a, edge.b)
            items.append(
                GraphItem(
                    kind="edge",
                    model=model,
                    edge=edge,
                    renderable=_edge_label(status, edge, dim=dim),
                    option_id=f"edge:{model}:{i}",
                )
            )
    return items


class GraphScreen(ModalScreen):
    """Modal screen showing a visual integration graph of the Juju model."""

    DEFAULT_CSS = """
    GraphScreen {
        align: center middle;
    }

    #graph-container {
        width: 90%;
        height: 85%;
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

    #graph-options {
        height: 1fr;
    }

    #graph-detail {
        height: auto;
        max-height: 6;
        border-top: solid $surface-lighten-1;
        padding: 1 0 0 0;
        color: $text-muted;
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

    BINDINGS: ClassVar[list] = [
        Binding("escape", "back", "Close"),
        Binding("r", "refresh", "Refresh"),
        Binding("f", "cycle_filter", "Filter"),
        Binding("c", "clear_focus", "Clear focus"),
    ]

    def __init__(
        self,
        status: statustypes.Status | None = None,
        current_app: str | None = None,
        model: str | None = None,
        cos_status: statustypes.Status | None = None,
        cos_model: str | None = None,
        focus_app: str | None = None,
    ) -> None:
        """Initialise with current Juju status.

        ``status`` / ``model`` carry the dev model; ``cos_status`` /
        ``cos_model`` the optional COS model so F8 shows every
        integration shape at once.  ``current_app`` marks the app under
        construction with a ``★``; ``focus_app`` (set when the screen is
        opened from a click on the right-panel sketch) starts the view
        focused on that app.
        """
        super().__init__()
        self._status = status
        self._current_app = current_app
        self._model = model
        self._cos_status = cos_status
        self._cos_model = cos_model
        self._focus_app = focus_app
        # Held as a plain int so tests can cycle the filter without a
        # mounted DOM; the binding re-renders explicitly.
        self.filter_index = 0
        # Populated by :meth:`_render_graph` — maps a selectable
        # option's id to its :class:`GraphItem` so selection handlers
        # don't have to re-derive anything.
        self._items_by_id: dict[str, GraphItem] = {}

    def compose(self) -> ComposeResult:
        """Compose the graph layout."""
        with Vertical(id="graph-container"):
            with Horizontal(id="graph-title"):
                yield Static("Integration Graph", classes="title-text")
                yield Static("[ Esc Close ]", id="graph-close", classes="title-hint clickable")
            yield OptionList(id="graph-options")
            yield Static("", id="graph-detail")
            with Horizontal(id="graph-footer"):
                yield Static("[ r Refresh ]", id="graph-refresh-btn", classes="clickable")
                yield Static("[ f Filter ]", id="graph-filter-btn", classes="clickable")
                yield Static("[ c Clear focus ]", id="graph-clearfocus-btn", classes="clickable")
                yield Static("[ Esc Close ]", id="graph-close-btn", classes="clickable")

    def on_mount(self) -> None:
        """Render the graph on mount."""
        self._render_graph()

    # -- actions ------------------------------------------------------------

    def action_back(self) -> None:
        """Clear an active focus first; a second Escape closes the screen."""
        if self._focus_app is not None:
            self.action_clear_focus()
        else:
            self.dismiss()

    def action_clear_focus(self) -> None:
        """Drop the app focus and re-render."""
        if self._focus_app is None:
            return
        self._focus_app = None
        self._set_detail("")
        if self.is_mounted:
            self._render_graph()

    def action_refresh(self) -> None:
        """Fetch fresh Juju status (dev model only) and re-render."""
        if self._model:
            self.run_worker(self._fetch_and_render, thread=True)
        else:
            self._render_graph()

    def action_cycle_filter(self) -> None:
        """Cycle the app-status filter: all → blocked → waiting → both."""
        self.filter_index = (self.filter_index + 1) % len(_FILTER_CYCLE)
        if self.is_mounted:
            self._render_graph()

    # -- clicks / selection -------------------------------------------------

    def on_click(self, event: Click) -> None:
        """Route clicks on the bracketed footer labels to their actions."""
        wid = getattr(event.widget, "id", None)
        if wid == "graph-refresh-btn":
            self.action_refresh()
            event.stop()
        elif wid == "graph-filter-btn":
            self.action_cycle_filter()
            event.stop()
        elif wid == "graph-clearfocus-btn":
            self.action_clear_focus()
            event.stop()
        elif wid in ("graph-close-btn", "graph-close"):
            self.dismiss()
            event.stop()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle picking an app (focus toggle) or an edge (detail strip)."""
        option_id = event.option.id
        if option_id is None:
            return
        item = self._items_by_id.get(option_id)
        if item is None:
            return
        if item.kind == "app":
            # Toggle: re-selecting the focused app clears the focus.
            self._focus_app = None if self._focus_app == item.app_name else item.app_name
            self._set_detail("")
            self._render_graph()
        elif item.kind == "edge" and item.edge is not None:
            self._set_detail(self._edge_detail(item.model, item.edge))

    # -- rendering ----------------------------------------------------------

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
        """Update the dev status and re-render."""
        self._status = status
        if self.is_mounted:
            self._render_graph()

    def _model_status(self, model: str) -> statustypes.Status | None:
        return self._status if model == "dev" else self._cos_status

    def _render_graph(self) -> None:
        """Rebuild the option list from the current status / filter / focus."""
        opts = self.query_one("#graph-options", OptionList)
        opts.clear_options()
        self._items_by_id.clear()
        self._update_title()

        if not self._status and not self._cos_status:
            opts.add_option(Option("No model connected.", disabled=True))
            return

        status_filter = _FILTER_CYCLE[self.filter_index]
        options: list[Option] = []
        first = True
        for model, status in (("dev", self._status), ("cos", self._cos_status)):
            if status is None:
                continue
            if not first:
                options.append(Option(Text(""), disabled=True))
            first = False
            label = "Dev model" if model == "dev" else "COS model"
            options.append(Option(Text(f"── {label} ──", style="bold cyan"), disabled=True))
            preset_match = presets.match_preset(status)
            items = build_graph_items(
                status,
                model=model,
                current_app=self._current_app if model == "dev" else None,
                status_filter=status_filter,
                preset_match=preset_match,
                focus_app=self._focus_app,
            )
            for item in items:
                if item.selectable and item.option_id is not None:
                    self._items_by_id[item.option_id] = item
                    options.append(Option(item.renderable, id=item.option_id))
                else:
                    options.append(Option(item.renderable, disabled=True))
        opts.add_options(options)

    def _update_title(self) -> None:
        """Reflect the active filter (and any focus) in the title bar."""
        with contextlib.suppress(LookupError):
            title = self.query_one("#graph-title .title-text", Static)
            label = _FILTER_LABELS[_FILTER_CYCLE[self.filter_index]]
            suffix = f" ({label})"
            if self._focus_app:
                suffix += f" · focus: {self._focus_app}"
            title.update(f"Integration Graph{suffix}")

    def _set_detail(self, text: str) -> None:
        with contextlib.suppress(LookupError):
            self.query_one("#graph-detail", Static).update(text)

    def _edge_detail(self, model: str, edge: topology.Edge) -> str:
        """Compose the inline detail strip for a selected edge."""
        status = self._model_status(model)
        if status is None:
            return ""
        a_disp, b_disp = _edge_endpoints(status, edge)
        lines = [
            f"[bold]{a_disp}[/bold]  ──  [bold]{b_disp}[/bold]",
            f"interface: [bold cyan]{edge.interface}[/bold cyan]",
        ]
        preset_match = presets.match_preset(status)
        preset_edge = (
            preset_match.edge_for(edge.a, edge.b, edge.interface) if preset_match else None
        )
        if preset_edge is not None:
            lines.append(
                f"role: [bold]{preset_edge.provider}[/bold] provides → "
                f"[bold]{preset_edge.requirer}[/bold] requires"
            )
            lines.append(preset_edge.description)
        else:
            lines.append(
                "[dim]provider/requirer roles aren't derivable from juju status — "
                "open the relation in the status pane for databag contents.[/dim]"
            )
        return "\n".join(lines)
