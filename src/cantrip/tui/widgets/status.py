"""Juju status widget for the TUI."""

import collections

from jubilant import statustypes
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Click, Resize
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static

from cantrip.tui import topology

# Status values ranked by "worth surfacing first" when a model has a mix —
# error before blocked before waiting before active keeps the problem
# states visible even when the summary line is short.
_STATUS_ORDER = ("error", "blocked", "waiting", "maintenance", "active", "unknown")

# Below this content width (in cells) the expanded-model body falls back
# to the verbose ``AppBox`` + ``RelationLine`` list — there isn't room
# for the topology sketch's interface sub-headers and indented edge
# lines without wrapping.  At the right-panel ``min-width: 30`` (≈ 26
# content cells once the panel's and the widget's padding come off) we
# are below the threshold; a typical ≥ 88-column terminal clears it.
_SKETCH_MIN_WIDTH = 28


def _relation_pair_count(status: statustypes.Status) -> int:
    """Return number of distinct app-pairs related in *status* (interface-agnostic)."""
    pairs: set[tuple[str, str]] = set()
    for app_name, app in status.apps.items():
        for related_list in app.relations.values():
            for rel in related_list:
                pairs.add(tuple(sorted((app_name, rel.related_app))))
    return len(pairs)


def _cos_collapsed_summary(status: statustypes.Status) -> str:
    """Render the one-line summary shown when the COS section is collapsed.

    Looks like ``6 apps · 10 relations · 3 active, 2 waiting · 4 offers
    (click to expand)`` — every number is labelled, the relation count
    gives a sense of how wired-up the model is without expanding it,
    non-active status buckets are listed explicitly, and offers show how
    many integration points the dev charm could consume.
    """
    counts = collections.Counter(app.app_status.current for app in status.apps.values())
    total = sum(counts.values())
    if total == 0:
        return "no apps  (click to expand)"

    rel_count = _relation_pair_count(status)
    offers_count = len(getattr(status, "offers", None) or {})

    if len(counts) == 1 and "active" in counts:
        health = "all active"
    else:
        parts = [f"{counts[name]} {name}" for name in _STATUS_ORDER if counts.get(name)]
        # Tack on any exotic statuses we didn't pre-rank, so nothing
        # silently vanishes when Juju grows a new state.
        for name, n in counts.items():
            if name not in _STATUS_ORDER and n:
                parts.append(f"{n} {name}")
        health = ", ".join(parts)

    bits = [f"{total} app{'s' if total != 1 else ''}"]
    if rel_count:
        bits.append(f"{rel_count} relation{'s' if rel_count != 1 else ''}")
    bits.append(health)
    if offers_count:
        bits.append(f"{offers_count} offers")
    return " · ".join(bits) + "  (click to expand)"


class AppBox(Static):
    """Widget representing a single application — compact two-line form.

    Renders as ``● app-name · active: message`` followed by indented
    unit / subordinate lines.  No border (the per-status colour at
    the line head makes the app boundary clear without a frame), no
    explicit "N units" line (the indented unit list itself shows
    the count), unit indicators carry their own status colour so a
    blocked unit jumps out under an otherwise-active app.
    """

    DEFAULT_CSS = """
    AppBox {
        height: auto;
        margin: 0 0 1 0;
    }

    AppBox .status-active {
        color: $success;
    }

    AppBox .status-waiting {
        color: $warning;
    }

    AppBox .status-blocked {
        color: $error;
    }

    AppBox .status-error {
        color: $error;
    }

    AppBox .status-maintenance {
        color: $accent;
    }

    AppBox .status-unknown {
        color: $text-muted;
    }
    """

    def __init__(self, app_name: str, app: statustypes.AppStatus, highlight: bool = False) -> None:
        """Initialise with app status."""
        super().__init__()
        self.app_name = app_name
        self.app_data = app
        self.highlight = highlight

    def compose(self) -> ComposeResult:
        """Compose the compact app rendering."""
        status = self.app_data.app_status.current
        status_char = self._status_char(status)
        status_class = f"status-{status}"

        # ``● flask-app · active: ready`` — colour on indicator + status.
        head = (
            f"[{status_class}]{status_char}[/{status_class}] "
            f"[bold]{self.app_name}[/bold] · "
            f"[{status_class}]{status}[/{status_class}]"
        )
        if self.highlight:
            head += " ← you are here"
        message = self.app_data.app_status.message
        if message:
            head += f": {message[:30]}"

        unit_lines: list[str] = []
        for unit_name, unit in sorted(self.app_data.units.items()):
            u_status = unit.workload_status.current
            u_char = self._status_char(u_status)
            u_class = f"status-{u_status}"
            u_msg = unit.workload_status.message
            line = f"  [{u_class}]{u_char}[/{u_class}] {unit_name}"
            if u_msg:
                line += f": {u_msg[:25]}"
            unit_lines.append(line)
            for sub_name, sub in sorted(unit.subordinates.items()):
                s_status = sub.workload_status.current
                s_char = self._status_char(s_status)
                s_class = f"status-{s_status}"
                s_msg = sub.workload_status.message
                sub_line = f"    └ [{s_class}]{s_char}[/{s_class}] {sub_name}"
                if s_msg:
                    sub_line += f": {s_msg[:20]}"
                unit_lines.append(sub_line)

        body = head
        if unit_lines:
            body += "\n" + "\n".join(unit_lines)

        yield Static(body)

    def _status_char(self, status: str) -> str:
        """Get status indicator character."""
        return topology.status_glyph(status)


class AppNode(Static):
    """A single app in the compact topology sketch — ``● app-name``.

    Glyph and name both carry the app's status colour, so a blocked app
    jumps out of an otherwise-green list.  Clicking (or pressing Enter)
    opens the F8 integration graph focused on this app — the sketch is
    the *entry point* to the full view, not a competing detail surface.
    """

    DEFAULT_CSS = """
    AppNode {
        height: 1;
        padding: 0 1;
    }

    AppNode:hover {
        background: $surface-darken-1;
    }
    """

    class Selected(Message):
        """Posted when the user picks an app node in the sketch."""

        def __init__(self, app_name: str) -> None:
            super().__init__()
            self.app_name = app_name

    def __init__(self, app_name: str, status: str, *, highlight: bool = False) -> None:
        super().__init__()
        self.app_name = app_name
        self.app_status = status
        self.highlight = highlight

    def compose(self) -> ComposeResult:
        """Render ``<glyph> <name>`` in the status colour."""
        glyph = topology.status_glyph(self.app_status)
        colour = topology.status_colour(self.app_status)
        line = f"[{colour}]{glyph} {self.app_name}[/{colour}]"
        if self.highlight:
            line += " [dim]← you are here[/dim]"
        yield Static(line)

    def on_click(self) -> None:
        """Open the F8 graph focused on this app."""
        self.post_message(self.Selected(self.app_name))


class RelationLine(Static):
    """Widget showing a relation between apps.

    Click or press Enter to open a detail panel showing the full
    relation databag contents.
    """

    DEFAULT_CSS = """
    RelationLine {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    RelationLine:hover {
        background: $surface-darken-1;
    }
    """

    class Selected(Message):
        """Posted when the user selects a relation line."""

        def __init__(self, unit_name: str, endpoint: str, related_app: str) -> None:
            super().__init__()
            self.unit_name = unit_name
            self.endpoint = endpoint
            self.related_app = related_app

    def __init__(
        self,
        relation_name: str,
        endpoint: str = "",
        related_app: str = "",
        unit_name: str = "",
    ) -> None:
        """Initialise with relation name and metadata for detail lookup."""
        super().__init__()
        self.relation_name = relation_name
        self.endpoint = endpoint
        self.related_app = related_app
        self.unit_name = unit_name

    def compose(self) -> ComposeResult:
        """Compose the relation line."""
        yield Static(f"│ {self.relation_name}")

    def on_click(self) -> None:
        """Open the relation detail panel on click."""
        if self.endpoint:
            self.post_message(self.Selected(self.unit_name, self.endpoint, self.related_app))


class OfferLine(Static):
    """Widget showing a single cross-model offer.

    Offers are exposed by apps in this model for consumption by apps in
    *other* models via ``juju consume``.  Showing them alongside the
    app list makes the "what can my dev charm integrate with?" question
    answerable at a glance — in a COS model, offers typically include
    prometheus/loki/grafana endpoints the dev charm can consume.
    """

    DEFAULT_CSS = """
    OfferLine {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """


class JujuStatusWidget(Widget):
    """Widget displaying full Juju model status.

    Press ``/`` to open an inline search filter.  The filter matches
    case-insensitively against app names, unit names, relation names,
    and status keywords.  Press ``Escape`` to clear the filter.
    """

    class StatusAvailable(Message):
        """Posted when status data first becomes available."""

    DEFAULT_CSS = """
    JujuStatusWidget {
        /* ``height: auto`` so the widget sizes to its contents (model
         * header + summary + AppBoxes + offers).  ``height: 100%``
         * here used to recurse into the surrounding ``.model-section``
         * (also ``height: auto``), which collapsed the inner content
         * to the first line — only ``Model: cos (k8s)`` would show
         * after a click-to-expand. */
        height: auto;
        padding: 1;
    }

    JujuStatusWidget .model-header {
        text-style: bold;
        margin-bottom: 1;
    }

    JujuStatusWidget .no-apps {
        color: $text-muted;
        text-style: italic;
    }

    JujuStatusWidget .model-summary {
        color: $text-muted;
        margin-bottom: 1;
    }

    JujuStatusWidget #status-container {
        /* Without an explicit ``height: auto`` the container picks up
         * the default Vertical sizing (``1fr``), which makes it
         * expand to fill the JujuStatusWidget regardless of how much
         * actual content it has — and that in turn makes the parent
         * widget claim space it doesn't need, hiding the next
         * section underneath. */
        height: auto;
    }

    JujuStatusWidget #status-filter {
        dock: top;
        height: 1;
        margin-bottom: 1;
        display: none;
    }

    JujuStatusWidget #status-filter.visible {
        display: block;
    }
    """

    status: reactive[statustypes.Status | None] = reactive(None)
    current_app: reactive[str | None] = reactive(None)
    filter_text: reactive[str] = reactive("")

    def __init__(
        self,
        status: statustypes.Status | None = None,
        current_app: str | None = None,
        role: str = "",
        **kwargs,
    ) -> None:
        """Initialise with optional status.

        ``role`` (e.g. ``"Dev"``, ``"COS"``) renders as a single
        combined header line ``"{role}: {model.name} ({cloud})"``,
        replacing the surrounding section-title that the
        :class:`MultiModelStatusWidget` would otherwise mount above
        the widget — saves two vertical lines per model.
        """
        super().__init__(**kwargs)
        self.status = status
        self.current_app = current_app
        self.role = role
        # Which body is currently mounted (sketch vs verbose list), or
        # ``None`` before the first render.  ``on_resize`` consults this
        # so it only re-renders when the width crosses the sketch
        # threshold — mounting children grows the widget's *height*,
        # which would otherwise bounce ``on_resize`` into a re-render
        # loop.
        self._rendered_sketch: bool | None = None

    def compose(self) -> ComposeResult:
        """Compose the status display."""
        yield Input(placeholder="Filter apps, units, relations…", id="status-filter")
        yield Vertical(id="status-container")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update filter text as the user types."""
        if event.input.id == "status-filter":
            self.filter_text = event.value

    def key_slash(self) -> None:
        """Show the filter input on ``/`` key."""
        filter_input = self.query_one("#status-filter", Input)
        filter_input.add_class("visible")
        filter_input.focus()

    def key_escape(self) -> None:
        """Clear the filter and hide the input on ``Escape``."""
        filter_input = self.query_one("#status-filter", Input)
        filter_input.value = ""
        filter_input.remove_class("visible")
        self.filter_text = ""

    def watch_status(self, old: statustypes.Status | None, new: statustypes.Status | None) -> None:
        """React to status changes."""
        if old is None and new is not None:
            self.post_message(self.StatusAvailable())
        self._refresh_display()

    def watch_current_app(self, _app: str | None) -> None:
        """React to current app changes."""
        self._refresh_display()

    def watch_filter_text(self, _text: str) -> None:
        """React to filter text changes."""
        self._refresh_display()

    def _app_matches_filter(self, app_name: str, app: statustypes.AppStatus) -> bool:
        """Return True if the app matches the current filter text."""
        if not self.filter_text:
            return True
        needle = self.filter_text.lower()
        # Match against app name.
        if needle in app_name.lower():
            return True
        # Match against app status.
        if needle in app.app_status.current.lower():
            return True
        if needle in (app.app_status.message or "").lower():
            return True
        # Match against unit names and statuses.
        for unit_name, unit in app.units.items():
            if needle in unit_name.lower():
                return True
            if needle in unit.workload_status.current.lower():
                return True
            if needle in (unit.workload_status.message or "").lower():
                return True
        # Match against relation names.
        for rel_name, related_apps in app.relations.items():
            if needle in rel_name.lower():
                return True
            for related in related_apps:
                if needle in related.related_app.lower():
                    return True
        return False

    def _sketch_mode(self) -> bool:
        """Return true when there is room for the compact topology sketch.

        Width 0 means the widget hasn't been laid out yet — treat that
        as "not enough room" so the first paint (driven by ``on_resize``
        once the real width lands) settles on the right body.
        """
        return self.size.width >= _SKETCH_MIN_WIDTH

    def on_resize(self, _event: Resize) -> None:
        """Re-render only when the width crosses the sketch threshold.

        Re-rendering on *every* resize would loop: mounting the body's
        children grows the widget height, which fires another resize.
        Gating on the sketch-mode flip means a height change is a no-op
        while a genuine terminal-width change still flips the body.
        """
        if self._rendered_sketch is not None and self._sketch_mode() == self._rendered_sketch:
            return
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the status display."""
        results = self.query("#status-container")
        if not results:
            # Watcher fired before compose() has run.
            return
        container = results.first(Vertical)
        container.remove_children()

        if not self.status:
            container.mount(
                Static(
                    "No model connected.\n\nStart by describing what\nyou want to charm.",
                    classes="no-apps",
                )
            )
            return

        # Model header — single line carrying role, model name, cloud,
        # and the app/unit counts that the old "model-summary" Static
        # used to render below.
        prefix = self.role if self.role else "Model"
        total_units = sum(len(app.units) for app in self.status.apps.values())
        n_apps = len(self.status.apps)
        if n_apps:
            counts = (
                f" · {n_apps} app{'s' if n_apps != 1 else ''},"
                f" {total_units} unit{'s' if total_units != 1 else ''}"
            )
        else:
            counts = ""
        container.mount(
            Static(
                f"{prefix}: {self.status.model.name} ({self.status.model.cloud}){counts}",
                classes="model-header",
            )
        )

        if not self.status.apps:
            container.mount(Static("No applications deployed.", classes="no-apps"))
            return

        visible = {
            name: app
            for name, app in self.status.apps.items()
            if self._app_matches_filter(name, app)
        }
        sketch = self._sketch_mode()
        self._rendered_sketch = sketch
        if not visible and self.filter_text:
            container.mount(Static(f"No matches for '{self.filter_text}'.", classes="no-apps"))
        elif sketch:
            self._render_sketch(container, visible)
        else:
            self._render_list(container, visible)

        self._render_offers(container)

    def _render_list(self, container: Vertical, visible: dict[str, statustypes.AppStatus]) -> None:
        """Return the verbose fallback — an ``AppBox`` + ``RelationLine`` per app."""
        for app_name, app in visible.items():
            container.mount(AppBox(app_name, app, highlight=app_name == self.current_app))
            # Pick the first unit for relation detail lookups.
            first_unit = next(iter(app.units), f"{app_name}/0")
            for rel_name, related_apps in app.relations.items():
                for related in related_apps:
                    container.mount(
                        RelationLine(
                            f"{rel_name} → {related.related_app}",
                            endpoint=rel_name,
                            related_app=related.related_app,
                            unit_name=first_unit,
                        )
                    )

    def _render_sketch(
        self, container: Vertical, visible: dict[str, statustypes.AppStatus]
    ) -> None:
        """Return the compact topology sketch — app nodes, then interface-grouped edges.

        App nodes carry their status colour and open the F8 graph when
        clicked; the unit-level breakdown is intentionally dropped (F8
        and ``juju status`` carry it).  Edges are one line per app-pair
        per interface, grouped under a ``[interface]`` sub-header so a
        model with three ``ingress`` relations reads as a cluster rather
        than three unrelated lines.
        """
        for app_name, app in visible.items():
            container.mount(
                AppNode(
                    app_name,
                    app.app_status.current,
                    highlight=app_name == self.current_app,
                )
            )

        edges = topology.dedup_edges(self.status, visible=set(visible))
        if not edges:
            return
        container.mount(Static("Relations", classes="model-header"))
        # Group by interface for the sub-headers; within an interface,
        # ``dedup_edges`` already sorted by (a, b).
        by_interface: dict[str, list[topology.Edge]] = {}
        for edge in edges:
            by_interface.setdefault(edge.interface, []).append(edge)
        for interface in sorted(by_interface):
            container.mount(Static(f"[dim]\\[{interface}][/dim]"))
            for edge in by_interface[interface]:
                container.mount(Static(f"[dim]  {edge.a} ─ {edge.b}[/dim]"))

    def _render_offers(self, container: Vertical) -> None:
        """Cross-model endpoints this model exposes via ``juju offer``.

        Empty when a model has no ``juju offer ...`` declarations; in a
        Cantrip-managed COS model the typical set is
        prometheus/loki/grafana/traefik-api, which is exactly what a dev
        charm would consume to wire up observability.
        """
        offers = getattr(self.status, "offers", None) or {}
        if not offers:
            return
        container.mount(Static("Offers", classes="model-header"))
        for offer_name, offer in offers.items():
            endpoints = ", ".join(
                f"{ep_name} ({ep.interface})" for ep_name, ep in offer.endpoints.items()
            )
            container.mount(OfferLine(f"│ {offer_name} ({offer.app}) — {endpoints}"))

    def update_status(self, status: statustypes.Status) -> None:
        """Update the displayed status."""
        self.status = status

    def set_current_app(self, app_name: str | None) -> None:
        """Set the currently active app (highlighted)."""
        self.current_app = app_name


class MultiModelStatusWidget(Widget):
    """Widget showing status of multiple models (dev + cos)."""

    DEFAULT_CSS = """
    MultiModelStatusWidget {
        height: 100%;
    }

    MultiModelStatusWidget .model-section {
        border-bottom: solid $surface-darken-1;
        padding: 1;
        height: auto;
    }

    MultiModelStatusWidget .model-section:last-child {
        border-bottom: none;
    }

    MultiModelStatusWidget .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    MultiModelStatusWidget .collapsed-summary {
        color: $text-muted;
    }
    """

    dev_status: reactive[statustypes.Status | None] = reactive(None, init=False)
    cos_status: reactive[statustypes.Status | None] = reactive(None, init=False)
    cos_expanded: reactive[bool] = reactive(False, init=False)

    def compose(self) -> ComposeResult:
        """Compose the multi-model display.

        Wrap the two sections in a ``VerticalScroll`` so that when dev
        + expanded-COS together exceed the pane's allocated height, the
        user gets a real scrollbar instead of having content silently
        clipped at the bottom.
        """
        yield VerticalScroll(
            Vertical(
                Static("Dev Model", classes="section-title"),
                id="dev-section",
                classes="model-section",
            ),
            Vertical(
                Static("COS Model", classes="section-title"),
                id="cos-section",
                classes="model-section",
            ),
            id="multi-model-scroll",
        )

    def on_mount(self) -> None:
        """Start hidden — no pane real estate while no model is connected."""
        self._refresh_display()

    def watch_dev_status(self, _status: statustypes.Status | None) -> None:
        """React to dev status changes."""
        self._refresh_display()

    def watch_cos_status(self, _status: statustypes.Status | None) -> None:
        """React to COS status changes."""
        self._refresh_display()

    def watch_cos_expanded(self, _expanded: bool) -> None:
        """React to COS expand / collapse toggles.

        Without this watcher, setting ``cos_expanded`` outside
        :meth:`toggle_cos_expanded` (the click handler's only entry
        point) would not repaint — the reactive declaration alone
        doesn't drive a refresh.
        """
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the display.

        The pane hides itself entirely while neither model is connected
        — "Dev Model / Not connected / COS Model / Not deployed" used to
        claim half the right panel before any work began, which earned
        a bug report and the Phase 65 audit.  Each section also hides
        when its own model is disconnected, so a connected dev model
        without COS doesn't carry an empty COS section underneath.
        """
        if not self.dev_status and not self.cos_status:
            self.display = False
            return
        self.display = True

        dev_section = self.query_one("#dev-section", Vertical)
        dev_section.remove_children()
        if self.dev_status:
            dev_section.display = True
            dev_section.mount(JujuStatusWidget(status=self.dev_status, role="Dev"))
        else:
            dev_section.display = False

        cos_section = self.query_one("#cos-section", Vertical)
        cos_section.remove_children()
        if self.cos_status:
            cos_section.display = True
            if self.cos_expanded:
                cos_section.mount(JujuStatusWidget(status=self.cos_status, role="COS"))
            else:
                # Collapsed COS still needs a label to identify itself,
                # since the JujuStatusWidget (which would otherwise
                # carry the role) doesn't mount in this branch.
                cos_section.mount(Static("COS", classes="section-title"))
                cos_section.mount(
                    Static(
                        _cos_collapsed_summary(self.cos_status),
                        classes="collapsed-summary",
                    )
                )
        else:
            cos_section.display = False

    def on_click(self, event: Click) -> None:
        """Toggle COS expansion when the COS section is clicked."""
        cos_section = self.query_one("#cos-section", Vertical)
        # Walk up from the clicked widget to see if it's inside #cos-section.
        node = event.widget
        while node is not None:
            if node is cos_section:
                self.toggle_cos_expanded()
                event.stop()
                return
            if node is self:
                break
            node = node.parent

    def toggle_cos_expanded(self) -> None:
        """Toggle COS section expansion."""
        # Setting the reactive triggers ``watch_cos_expanded`` which
        # re-renders.  No explicit refresh needed here.
        self.cos_expanded = not self.cos_expanded
