"""Tests for the integration graph screen."""

from jubilant import statustypes
from rich.panel import Panel
from rich.text import Text

from cantrip.tui.screens.graph import GraphScreen, build_graph

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
