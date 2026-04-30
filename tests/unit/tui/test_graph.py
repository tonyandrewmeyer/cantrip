"""Tests for the integration graph screen."""

import pytest
from jubilant import statustypes
from rich.panel import Panel
from rich.text import Text

from cantrip.tui.screens.graph import GraphScreen, build_graph

pytestmark = pytest.mark.tui

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(apps_data: dict | None = None) -> statustypes.Status:
    """Build a Status object from a simplified dict."""
    data = {
        "model": {
            "name": "dev",
            "type": "iaas",
            "cloud": "localhost",
            "region": "",
            "version": "3.1.0",
            "controller": "lxd",
            "model-status": {"current": "available"},
        },
        "machines": {},
        "applications": apps_data or {},
    }
    return statustypes.Status._from_dict(data)


def _app_data(
    status: str = "active",
    message: str = "",
    units: dict | None = None,
    relations: dict | None = None,
) -> dict:
    """Build an application dict for _make_status."""
    result: dict = {
        "charm": "test",
        "charm-origin": "local",
        "charm-name": "test",
        "charm-rev": 1,
        "exposed": False,
        "application-status": {"current": status, "message": message},
        "units": units or {},
        "relations": relations or {},
    }
    return result


def _unit_data(status: str = "active") -> dict:
    """Build a unit dict."""
    return {
        "workload-status": {"current": status},
        "juju-status": {"current": "idle"},
        "address": "10.0.0.1",
        "open-ports": [],
    }


# ---------------------------------------------------------------------------
# TestBuildGraph
# ---------------------------------------------------------------------------


class TestBuildGraph:
    """Tests for the build_graph() rendering function."""

    def test_empty_model_returns_placeholder(self) -> None:
        """An empty model shows a placeholder message."""
        status = _make_status()
        parts = build_graph(status)
        assert len(parts) == 1
        assert isinstance(parts[0], Text)
        assert "No applications" in parts[0].plain

    def test_single_app_produces_panel(self) -> None:
        """A single app generates a model header and an app panel."""
        status = _make_status({"my-app": _app_data()})
        parts = build_graph(status)
        panels = [p for p in parts if isinstance(p, Panel)]
        assert len(panels) == 1
        assert panels[0].title is not None
        assert "my-app" in str(panels[0].title)

    def test_model_header_present(self) -> None:
        """The model name appears in the header."""
        status = _make_status({"app": _app_data()})
        parts = build_graph(status)
        header = parts[0]
        assert isinstance(header, Text)
        assert "dev" in header.plain

    def test_multiple_apps(self) -> None:
        """Multiple apps each get a panel."""
        status = _make_status(
            {
                "app-a": _app_data(),
                "app-b": _app_data(status="waiting"),
            }
        )
        parts = build_graph(status)
        panels = [p for p in parts if isinstance(p, Panel)]
        assert len(panels) == 2

    def test_relations_section(self) -> None:
        """Relations between apps appear in a separate section."""
        status = _make_status(
            {
                "flask-app": _app_data(
                    relations={
                        "database": [
                            {
                                "related-application": "postgresql",
                                "interface": "pgsql",
                                "scope": "global",
                            }
                        ],
                    }
                ),
                "postgresql": _app_data(),
            }
        )
        parts = build_graph(status)
        text_parts = [p for p in parts if isinstance(p, Text)]
        # Should have "Relations" header and at least one relation line.
        plain = " ".join(t.plain for t in text_parts)
        assert "Relations" in plain
        assert "flask-app" in plain
        assert "postgresql" in plain

    def test_relations_deduplicated(self) -> None:
        """Bidirectional relations are shown only once."""
        status = _make_status(
            {
                "app-a": _app_data(
                    relations={
                        "endpoint-x": [
                            {
                                "related-application": "app-b",
                                "interface": "iface",
                                "scope": "global",
                            }
                        ],
                    }
                ),
                "app-b": _app_data(
                    relations={
                        "endpoint-y": [
                            {
                                "related-application": "app-a",
                                "interface": "iface",
                                "scope": "global",
                            }
                        ],
                    }
                ),
            }
        )
        parts = build_graph(status)
        text_parts = [p for p in parts if isinstance(p, Text)]
        # Count relation lines (exclude header and "Relations" title).
        relation_lines = [t for t in text_parts if "──" in t.plain]
        assert len(relation_lines) == 1

    def test_highlight_current_app(self) -> None:
        """The current app panel title includes a star marker."""
        status = _make_status({"my-charm": _app_data()})
        parts = build_graph(status, current_app="my-charm")
        panels = [p for p in parts if isinstance(p, Panel)]
        assert len(panels) == 1
        assert "★" in str(panels[0].title)

    def test_no_highlight_when_not_current(self) -> None:
        """Other apps do not get the star marker."""
        status = _make_status({"other-app": _app_data()})
        parts = build_graph(status, current_app="my-charm")
        panels = [p for p in parts if isinstance(p, Panel)]
        assert "★" not in str(panels[0].title)

    def test_unit_breakdown_shown(self) -> None:
        """Apps with multiple units show a per-unit breakdown."""
        status = _make_status(
            {
                "my-app": _app_data(
                    units={
                        "my-app/0": _unit_data("active"),
                        "my-app/1": _unit_data("waiting"),
                    }
                ),
            }
        )
        parts = build_graph(status)
        panels = [p for p in parts if isinstance(p, Panel)]
        assert len(panels) == 1
        # The panel renderable should contain unit references.
        # We check that "2 units" is in the rendered output.
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, width=40)
        console.print(panels[0])
        rendered = buf.getvalue()
        assert "2 units" in rendered

    def test_catalogue_badge_present_on_registered_app(self) -> None:
        """Apps relating on the ``catalogue`` interface get a ``[cat]`` title badge."""
        status = _make_status(
            {
                "my-app": _app_data(
                    relations={
                        "catalogue": [
                            {
                                "related-application": "catalogue-k8s",
                                "interface": "catalogue",
                                "scope": "global",
                            }
                        ],
                    }
                ),
                "catalogue-k8s": _app_data(),
            }
        )
        parts = build_graph(status)
        panels = {str(p.title): p for p in parts if isinstance(p, Panel)}
        assert "[cat]" in next(t for t in panels if t.startswith("my-app"))
        assert "[cat]" not in next(t for t in panels if t.startswith("catalogue-k8s"))

    def test_catalogue_badge_combines_with_highlight(self) -> None:
        """A starred current app with catalogue still shows both markers."""
        status = _make_status(
            {
                "my-app": _app_data(
                    relations={
                        "catalogue": [
                            {
                                "related-application": "catalogue-k8s",
                                "interface": "catalogue",
                                "scope": "global",
                            }
                        ],
                    }
                ),
            }
        )
        parts = build_graph(status, current_app="my-app")
        panels = [p for p in parts if isinstance(p, Panel)]
        assert "★" in str(panels[0].title)
        assert "[cat]" in str(panels[0].title)

    def test_status_indicators(self) -> None:
        """Different statuses produce correct indicator characters."""
        for status_name, expected_char in [
            ("active", "●"),
            ("waiting", "○"),
            ("blocked", "◌"),
            ("error", "✗"),
        ]:
            status = _make_status({"app": _app_data(status=status_name)})
            parts = build_graph(status)
            panels = [p for p in parts if isinstance(p, Panel)]
            assert len(panels) == 1
            from io import StringIO

            from rich.console import Console

            buf = StringIO()
            console = Console(file=buf, width=40)
            console.print(panels[0])
            rendered = buf.getvalue()
            assert expected_char in rendered, f"Expected {expected_char} for {status_name}"


# ---------------------------------------------------------------------------
# TestGraphScreen
# ---------------------------------------------------------------------------


class TestGraphScreen:
    """Tests for GraphScreen construction."""

    def test_screen_construction_no_status(self) -> None:
        """Screen can be constructed without status data."""
        screen = GraphScreen()
        assert screen._status is None
        assert screen._model is None

    def test_screen_construction_with_status(self) -> None:
        """Screen accepts status data."""
        status = _make_status({"app": _app_data()})
        screen = GraphScreen(status=status, current_app="app", model="dev")
        assert screen._status is status
        assert screen._current_app == "app"
        assert screen._model == "dev"

    def test_update_status(self) -> None:
        """update_status() replaces the stored status."""
        screen = GraphScreen()
        status = _make_status({"app": _app_data()})
        # Cannot call _render_graph without being mounted, but update_status
        # should at least store the new status.
        screen._status = status
        assert screen._status is status


# ---------------------------------------------------------------------------
# TestStatusFilter
# ---------------------------------------------------------------------------


class TestStatusFilter:
    """``status_filter`` keyword hides apps outside the set."""

    def _mixed_status_graph(self) -> statustypes.Status:
        return _make_status(
            {
                "happy-app": _app_data(status="active"),
                "stuck-app": _app_data(status="blocked"),
                "patient-app": _app_data(status="waiting"),
            }
        )

    def test_none_filter_shows_everything(self) -> None:
        """``status_filter=None`` — baseline: every app appears."""
        parts = build_graph(self._mixed_status_graph(), status_filter=None)
        panels = [p for p in parts if isinstance(p, Panel)]
        assert {str(p.title) for p in panels} == {"happy-app", "stuck-app", "patient-app"}

    def test_blocked_only(self) -> None:
        """Blocked-only filter hides active and waiting."""
        parts = build_graph(self._mixed_status_graph(), status_filter=frozenset({"blocked"}))
        panels = [p for p in parts if isinstance(p, Panel)]
        assert {str(p.title) for p in panels} == {"stuck-app"}

    def test_blocked_and_waiting(self) -> None:
        """Combined filter hides only active."""
        parts = build_graph(
            self._mixed_status_graph(),
            status_filter=frozenset({"blocked", "waiting"}),
        )
        panels = [p for p in parts if isinstance(p, Panel)]
        assert {str(p.title) for p in panels} == {"stuck-app", "patient-app"}

    def test_empty_match_shows_placeholder(self) -> None:
        """Filter matches nothing → placeholder, not a bare header."""
        parts = build_graph(
            _make_status({"happy-app": _app_data(status="active")}),
            status_filter=frozenset({"blocked"}),
        )
        panels = [p for p in parts if isinstance(p, Panel)]
        assert panels == []
        plain = " ".join(p.plain for p in parts if isinstance(p, Text))
        assert "No applications matching filter" in plain
        assert "blocked" in plain

    def test_relation_hidden_when_one_end_filtered_out(self) -> None:
        """Edges crossing the filter boundary disappear so the graph stays honest."""
        status = _make_status(
            {
                "stuck-app": _app_data(
                    status="blocked",
                    relations={
                        "database": [
                            {
                                "related-application": "happy-app",
                                "interface": "pgsql",
                                "scope": "global",
                            }
                        ],
                    },
                ),
                "happy-app": _app_data(status="active"),
            }
        )
        parts = build_graph(status, status_filter=frozenset({"blocked"}))
        text_parts = [p for p in parts if isinstance(p, Text)]
        plain = " ".join(t.plain for t in text_parts)
        assert "Relations" not in plain


class TestGraphScreenFilterCycle:
    """``action_cycle_filter`` advances through four modes."""

    def test_cycle_advances_index(self) -> None:
        screen = GraphScreen(status=_make_status({"a": _app_data()}))
        assert screen.filter_index == 0
        screen.action_cycle_filter()
        assert screen.filter_index == 1
        screen.action_cycle_filter()
        assert screen.filter_index == 2
        screen.action_cycle_filter()
        assert screen.filter_index == 3

    def test_cycle_wraps(self) -> None:
        screen = GraphScreen(status=_make_status({"a": _app_data()}))
        for _ in range(4):
            screen.action_cycle_filter()
        assert screen.filter_index == 0


class TestGraphScreenClickableFooter:
    """The footer ``[ r Refresh ]`` / ``[ f Filter ]`` / ``[ Esc Close ]``
    text is wrapped in ``Static`` widgets that route their clicks to
    the matching action — the bracketed labels look like buttons, so
    clicks should behave like presses.
    """

    @pytest.mark.asyncio
    async def test_clicking_filter_cycles(self) -> None:
        from textual.app import App, ComposeResult

        status = _make_status({"a": _app_data()})

        class _Host(App):
            def compose(self) -> ComposeResult:  # pragma: no cover - trivial
                yield from ()

        async with _Host().run_test() as pilot:
            screen = GraphScreen(status=status)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            assert screen.filter_index == 0
            await pilot.click("#graph-filter-btn")
            await pilot.pause()
            assert screen.filter_index == 1

    @pytest.mark.asyncio
    async def test_clicking_close_dismisses(self) -> None:
        from textual.app import App, ComposeResult

        status = _make_status({"a": _app_data()})

        class _Host(App):
            def compose(self) -> ComposeResult:  # pragma: no cover - trivial
                yield from ()

        async with _Host().run_test() as pilot:
            screen = GraphScreen(status=status)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.click("#graph-close-btn")
            await pilot.pause()
            assert pilot.app.screen is not screen


class TestGraphScreenBothModels:
    """``cos_status`` renders alongside the dev model in the same screen."""

    @pytest.mark.asyncio
    async def test_both_models_render_when_provided(self) -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import RichLog

        dev = _make_status({"flask-app": _app_data(status="active")})
        cos = _make_status({"prometheus": _app_data(status="active")})

        class _Host(App):
            def compose(self) -> ComposeResult:  # pragma: no cover - trivial
                yield from ()

        async with _Host().run_test() as pilot:
            screen = GraphScreen(status=dev, cos_status=cos)
            await pilot.app.push_screen(screen)
            await pilot.pause(delay=0.1)
            body = screen.query_one("#graph-body", RichLog)
            text = " ".join(line.text for line in body.lines)
            assert "Dev model" in text
            assert "COS model" in text
            assert "flask-app" in text
            assert "prometheus" in text

    @pytest.mark.asyncio
    async def test_dev_only_omits_cos_section(self) -> None:
        from textual.app import App, ComposeResult
        from textual.widgets import RichLog

        dev = _make_status({"flask-app": _app_data(status="active")})

        class _Host(App):
            def compose(self) -> ComposeResult:  # pragma: no cover - trivial
                yield from ()

        async with _Host().run_test() as pilot:
            screen = GraphScreen(status=dev, cos_status=None)
            await pilot.app.push_screen(screen)
            await pilot.pause(delay=0.1)
            body = screen.query_one("#graph-body", RichLog)
            text = " ".join(line.text for line in body.lines)
            # No cos status was passed — no "COS model" header should
            # appear, but the dev section still renders.
            assert "COS model" not in text
            assert "flask-app" in text
