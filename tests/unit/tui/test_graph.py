"""Tests for the F8 integration graph screen (Phase 90.3 rework)."""

from __future__ import annotations

import pytest
from jubilant import statustypes
from rich.panel import Panel
from textual.widgets import OptionList

from cantrip.agent.runtime import presets
from cantrip.tui import topology
from cantrip.tui.screens.graph import (
    GraphScreen,
    _app_panel,
    _edge_endpoints,
    _edge_label,
    _endpoint_for,
    _has_catalogue_relation,
    build_graph_items,
)

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(apps_data: dict | None = None, *, model_name: str = "dev") -> statustypes.Status:
    return statustypes.Status._from_dict(
        {
            "model": {
                "name": model_name,
                "type": "caas",
                "cloud": "k8s",
                "region": "",
                "version": "3.5.0",
                "controller": "k8s",
                "model-status": {"current": "available"},
            },
            "machines": {},
            "applications": apps_data or {},
        }
    )


def _app_data(
    *,
    charm: str = "test-charm",
    status: str = "active",
    message: str = "",
    units: dict | None = None,
    relations: dict | None = None,
) -> dict:
    return {
        "charm": charm,
        "charm-origin": "charmhub",
        "charm-name": charm,
        "charm-rev": 1,
        "exposed": False,
        "application-status": {"current": status, "message": message},
        "units": units or {},
        "relations": relations or {},
    }


def _unit_data(status: str = "active") -> dict:
    return {
        "workload-status": {"current": status},
        "juju-status": {"current": "idle"},
        "address": "10.0.0.1",
        "open-ports": [],
    }


def _rel(related_app: str, interface: str = "iface") -> list[dict]:
    return [{"related-application": related_app, "interface": interface, "scope": "global"}]


def _two_app_status() -> statustypes.Status:
    """A web app related to PostgreSQL over ``postgresql_client``."""
    return _make_status(
        {
            "web": _app_data(relations={"db": _rel("postgresql", "postgresql_client")}),
            "postgresql": _app_data(relations={"database": _rel("web", "postgresql_client")}),
        }
    )


def _cos_lite_status() -> statustypes.Status:
    """A model whose apps match the ``cos-lite`` preset by charm name."""
    return _make_status(
        {
            "traefik": _app_data(
                charm="traefik-k8s",
                relations={"ingress": _rel("prometheus", "ingress")},
            ),
            "prometheus": _app_data(
                charm="prometheus-k8s",
                relations={
                    "ingress": _rel("traefik", "ingress"),
                    "alertmanager": _rel("alertmanager", "alertmanager_dispatch"),
                },
            ),
            "alertmanager": _app_data(
                charm="alertmanager-k8s",
                relations={"alerting": _rel("prometheus", "alertmanager_dispatch")},
            ),
            "grafana": _app_data(charm="grafana-k8s"),
            "loki": _app_data(charm="loki-k8s"),
        }
    )


def _kinds(items) -> list[str]:
    return [it.kind for it in items]


def _render_text(renderable) -> str:
    """Render a Rich renderable to plain text (for asserting on contents)."""
    from rich.console import Console

    console = Console(width=60, no_color=True)
    with console.capture() as cap:
        console.print(renderable)
    return cap.get()


class _FakeSelected:
    """Minimal stand-in for ``OptionList.OptionSelected`` carrying an id."""

    def __init__(self, option_id: str | None) -> None:
        self.option = type("_Opt", (), {"id": option_id})()


# ---------------------------------------------------------------------------
# build_graph_items
# ---------------------------------------------------------------------------


class TestBuildGraphItems:
    def test_empty_model(self) -> None:
        items = build_graph_items(_make_status())
        assert _kinds(items) == ["empty"]
        assert "No applications deployed" in str(items[0].renderable)

    def test_single_app_no_relations(self) -> None:
        items = build_graph_items(_make_status({"web": _app_data()}))
        assert _kinds(items) == ["app"]
        assert items[0].app_name == "web"
        assert isinstance(items[0].renderable, Panel)
        assert items[0].option_id == "app::web"

    def test_apps_alphabetical_when_no_preset(self) -> None:
        items = build_graph_items(
            _make_status({"zeta": _app_data(), "alpha": _app_data(), "mu": _app_data()})
        )
        assert [it.app_name for it in items if it.kind == "app"] == ["alpha", "mu", "zeta"]

    def test_edges_section_with_interface_labels(self) -> None:
        items = build_graph_items(_two_app_status(), model="dev")
        kinds = _kinds(items)
        assert kinds == ["app", "app", "edges-header", "edge"]
        edge_item = items[-1]
        assert edge_item.edge == topology.Edge("postgresql", "web", "postgresql_client")
        assert edge_item.option_id == "edge:dev:0"
        rendered = str(edge_item.renderable)
        assert "postgresql_client" in rendered
        # Endpoint names are surfaced on both ends.
        assert "postgresql:database" in rendered
        assert "web:db" in rendered

    def test_status_filter_hides_apps_and_dangling_edges(self) -> None:
        status = _make_status(
            {
                "web": _app_data(status="active", relations={"db": _rel("postgresql", "pgsql")}),
                "postgresql": _app_data(
                    status="blocked", relations={"database": _rel("web", "pgsql")}
                ),
            }
        )
        items = build_graph_items(status, status_filter=frozenset({"blocked"}))
        assert [it.app_name for it in items if it.kind == "app"] == ["postgresql"]
        # The web–postgresql edge is gone (one end filtered out).
        assert not [it for it in items if it.kind == "edge"]

    def test_filter_with_no_matches_returns_notice(self) -> None:
        items = build_graph_items(
            _make_status({"web": _app_data()}), status_filter=frozenset({"error"})
        )
        assert _kinds(items) == ["empty"]
        assert "matching filter" in str(items[0].renderable)

    def test_current_app_highlighted(self) -> None:
        items = build_graph_items(_make_status({"web": _app_data()}), current_app="web")
        panel = items[0].renderable
        assert isinstance(panel, Panel)
        assert "★" in str(panel.title)

    def test_preset_match_groups_apps_by_layer(self) -> None:
        status = _cos_lite_status()
        match = presets.match_preset(status)
        assert match is not None and match.bundle.name == "cos-lite"
        items = build_graph_items(status, model="dev", preset_match=match)
        # Layer headers appear in the preset's declared order, then the
        # apps that fell into that layer.
        layered = [
            (it.kind, str(it.renderable) if it.kind == "layer" else it.app_name) for it in items
        ]
        assert ("layer", "▸ Routing") in layered
        assert ("layer", "▸ Telemetry") in layered
        # Routing layer (traefik) precedes Telemetry (prometheus/loki).
        routing_i = layered.index(("layer", "▸ Routing"))
        telemetry_i = layered.index(("layer", "▸ Telemetry"))
        assert routing_i < telemetry_i

    def test_focus_dims_unconnected_apps_and_edges(self) -> None:
        # web—postgresql; an unrelated "monitor" app.
        status = _make_status(
            {
                "web": _app_data(relations={"db": _rel("postgresql", "pgsql")}),
                "postgresql": _app_data(relations={"database": _rel("web", "pgsql")}),
                "monitor": _app_data(),
            }
        )
        items = build_graph_items(status, model="dev", focus_app="web")
        panels = {it.app_name: it.renderable for it in items if it.kind == "app"}
        # web (focus) and postgresql (neighbour) are not dimmed; monitor is.
        assert panels["monitor"].style == "dim"
        assert panels["web"].style != "dim"
        assert panels["postgresql"].style != "dim"

    def test_no_focus_dims_nothing(self) -> None:
        status = _make_status({"web": _app_data(), "db": _app_data()})
        items = build_graph_items(status, model="dev", focus_app=None)
        assert all(it.renderable.style != "dim" for it in items if it.kind == "app")

    def test_focus_on_filtered_out_app_is_a_noop(self) -> None:
        status = _make_status({"web": _app_data(), "db": _app_data()})
        # focus an app that doesn't exist → no dimming.
        items = build_graph_items(status, focus_app="ghost")
        assert all(it.renderable.style != "dim" for it in items if it.kind == "app")


# ---------------------------------------------------------------------------
# Panel + endpoint helpers
# ---------------------------------------------------------------------------


class TestAppPanel:
    def test_catalogue_badge(self) -> None:
        app = _make_status(
            {"grafana": _app_data(relations={"catalogue": _rel("catalogue", "catalogue")})}
        ).apps["grafana"]
        assert _has_catalogue_relation(app)
        assert "[cat]" in str(_app_panel("grafana", app).title)

    def test_no_catalogue_badge(self) -> None:
        app = _make_status({"web": _app_data()}).apps["web"]
        assert not _has_catalogue_relation(app)
        assert "[cat]" not in str(_app_panel("web", app).title)

    def test_unit_breakdown_when_scaled(self) -> None:
        app = _make_status(
            {"web": _app_data(units={"web/0": _unit_data(), "web/1": _unit_data("blocked")})}
        ).apps["web"]
        text = _render_text(_app_panel("web", app))
        assert "2 units" in text
        assert "/0" in text and "/1" in text

    def test_dim_panel(self) -> None:
        app = _make_status({"web": _app_data()}).apps["web"]
        assert _app_panel("web", app, dim=True).style == "dim"
        assert _app_panel("web", app, dim=False).style == ""


class TestEndpointHelpers:
    def test_endpoint_for(self) -> None:
        status = _two_app_status()
        assert _endpoint_for(status, "web", "postgresql", "postgresql_client") == "db"
        assert _endpoint_for(status, "postgresql", "web", "postgresql_client") == "database"
        assert _endpoint_for(status, "web", "nope", "postgresql_client") is None
        assert _endpoint_for(status, "ghost", "web", "x") is None

    def test_edge_endpoints(self) -> None:
        status = _two_app_status()
        edge = topology.Edge("postgresql", "web", "postgresql_client")
        assert _edge_endpoints(status, edge) == ("postgresql:database", "web:db")

    def test_edge_label_dim_vs_normal(self) -> None:
        status = _two_app_status()
        edge = topology.Edge("postgresql", "web", "postgresql_client")
        assert "postgresql_client" in str(_edge_label(status, edge))
        assert "postgresql_client" in str(_edge_label(status, edge, dim=True))


# ---------------------------------------------------------------------------
# GraphScreen — construction
# ---------------------------------------------------------------------------


class TestGraphScreenConstruction:
    def test_no_status(self) -> None:
        screen = GraphScreen()
        assert screen._status is None and screen._cos_status is None

    def test_with_status_and_focus(self) -> None:
        status = _two_app_status()
        screen = GraphScreen(status=status, current_app="web", focus_app="web")
        assert screen._status is status
        assert screen._current_app == "web"
        assert screen._focus_app == "web"

    def test_filter_cycle_index(self) -> None:
        screen = GraphScreen()
        assert screen.filter_index == 0
        screen.action_cycle_filter()
        assert screen.filter_index == 1
        screen.filter_index = 3
        screen.action_cycle_filter()
        assert screen.filter_index == 0


# ---------------------------------------------------------------------------
# GraphScreen — rendered behaviour
# ---------------------------------------------------------------------------


def _push_graph(**kwargs):
    """Build a tiny host app that pushes a GraphScreen on mount."""
    from textual.app import App

    class _Host(App):
        def on_mount(self) -> None:
            self.push_screen(GraphScreen(**kwargs))

    return _Host()


class TestGraphScreenRendered:
    @pytest.mark.asyncio
    async def test_renders_app_and_edge_options(self) -> None:
        async with _push_graph(status=_two_app_status()).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, GraphScreen)
            opts = screen.query_one("#graph-options", OptionList)
            assert opts.option_count > 0
            assert "app:dev:web" in screen._items_by_id
            assert "app:dev:postgresql" in screen._items_by_id
            assert "edge:dev:0" in screen._items_by_id
            # The "── Dev model ──" header and "Relations" header are
            # present as (disabled) options.
            prompts = " ".join(
                str(opts.get_option_at_index(i).prompt) for i in range(opts.option_count)
            )
            assert "Dev model" in prompts
            assert "Relations" in prompts

    @pytest.mark.asyncio
    async def test_selecting_edge_populates_detail_strip(self) -> None:
        async with _push_graph(status=_two_app_status()).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.on_option_list_option_selected(_FakeSelected("edge:dev:0"))
            await pilot.pause()
            detail = str(screen.query_one("#graph-detail").render())
            assert "postgresql_client" in detail
            assert "web" in detail and "postgresql" in detail

    @pytest.mark.asyncio
    async def test_selecting_edge_uses_preset_prose_when_matched(self) -> None:
        # COS-Lite charm names → cos-lite preset → the prometheus↔alertmanager
        # edge picks up the catalogue's role + description.
        async with _push_graph(status=_cos_lite_status()).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            # Find the alertmanager_dispatch edge id.
            edge_id = next(
                oid
                for oid, item in screen._items_by_id.items()
                if item.edge is not None and item.edge.interface == "alertmanager_dispatch"
            )
            screen.on_option_list_option_selected(_FakeSelected(edge_id))
            await pilot.pause()
            detail = str(screen.query_one("#graph-detail").render())
            assert "provides" in detail and "requires" in detail
            # The cos-lite catalogue's prose for this edge.
            assert "Alertmanager" in detail

    @pytest.mark.asyncio
    async def test_selecting_app_focuses_then_clears(self) -> None:
        async with _push_graph(status=_two_app_status()).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.on_option_list_option_selected(_FakeSelected("app:dev:web"))
            await pilot.pause()
            assert screen._focus_app == "web"
            assert "focus: web" in str(screen.query_one("#graph-title .title-text").render())
            # Pick web again → toggles the focus off.
            screen.on_option_list_option_selected(_FakeSelected("app:dev:web"))
            await pilot.pause()
            assert screen._focus_app is None

    @pytest.mark.asyncio
    async def test_selecting_disabled_or_unknown_option_is_a_noop(self) -> None:
        async with _push_graph(status=_two_app_status()).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.on_option_list_option_selected(_FakeSelected(None))
            screen.on_option_list_option_selected(_FakeSelected("edge:dev:999"))
            await pilot.pause()
            assert screen._focus_app is None

    @pytest.mark.asyncio
    async def test_escape_clears_focus_before_closing(self) -> None:
        async with _push_graph(status=_two_app_status(), focus_app="web").run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert screen._focus_app == "web"
            await pilot.press("escape")
            await pilot.pause()
            # Still on the graph screen, focus cleared.
            assert isinstance(pilot.app.screen, GraphScreen)
            assert pilot.app.screen._focus_app is None
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, GraphScreen)

    @pytest.mark.asyncio
    async def test_clear_focus_action(self) -> None:
        async with _push_graph(status=_two_app_status(), focus_app="web").run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            screen.action_clear_focus()
            await pilot.pause()
            assert screen._focus_app is None

    @pytest.mark.asyncio
    async def test_both_models_render_with_headers(self) -> None:
        dev = _make_status({"web": _app_data()}, model_name="dev")
        cos = _make_status({"grafana": _app_data(charm="grafana-k8s")}, model_name="cos")
        async with _push_graph(status=dev, cos_status=cos).run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            opts = screen.query_one("#graph-options", OptionList)
            rendered = " ".join(
                str(opts.get_option_at_index(i).prompt) for i in range(opts.option_count)
            )
            assert "Dev model" in rendered
            assert "COS model" in rendered

    @pytest.mark.asyncio
    async def test_dev_only_omits_cos_header(self) -> None:
        async with _push_graph(status=_make_status({"web": _app_data()})).run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            opts = screen.query_one("#graph-options", OptionList)
            rendered = " ".join(
                str(opts.get_option_at_index(i).prompt) for i in range(opts.option_count)
            )
            assert "COS model" not in rendered

    @pytest.mark.asyncio
    async def test_no_model_connected(self) -> None:
        async with _push_graph().run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            opts = screen.query_one("#graph-options", OptionList)
            rendered = " ".join(
                str(opts.get_option_at_index(i).prompt) for i in range(opts.option_count)
            )
            assert "No model connected" in rendered


class TestGraphScreenFooter:
    @pytest.mark.asyncio
    async def test_clicking_filter_button_cycles(self) -> None:
        async with _push_graph(status=_make_status({"web": _app_data()})).run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert screen.filter_index == 0
            await pilot.click("#graph-filter-btn")
            await pilot.pause()
            assert screen.filter_index == 1

    @pytest.mark.asyncio
    async def test_clicking_close_button_dismisses(self) -> None:
        async with _push_graph(status=_make_status({"web": _app_data()})).run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            assert isinstance(pilot.app.screen, GraphScreen)
            await pilot.click("#graph-close-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, GraphScreen)

    @pytest.mark.asyncio
    async def test_clicking_clear_focus_button(self) -> None:
        async with _push_graph(status=_two_app_status(), focus_app="web").run_test(
            size=(120, 40)
        ) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert screen._focus_app == "web"
            await pilot.click("#graph-clearfocus-btn")
            await pilot.pause()
            assert screen._focus_app is None
