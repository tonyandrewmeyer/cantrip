"""Behaviour tests for the Juju status widgets (Phase 93.1 backfill).

Targets the under-covered paths in ``tui/widgets/status.py``: the
``JujuStatusWidget`` filter matcher and ``_refresh_display`` branches
(no model / no apps / apps + relations + offers / highlight / no
filter matches), the ``/`` and ``Escape`` filter keys, ``RelationLine``
click messages, and the ``MultiModelStatusWidget`` expand/collapse
behaviour.
"""

from __future__ import annotations

import pytest
from jubilant import statustypes
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from cantrip.tui.widgets.status import (
    AppBox,
    JujuStatusWidget,
    MultiModelStatusWidget,
    OfferLine,
    RelationLine,
)

pytestmark = pytest.mark.tui

_TERMINAL = (100, 40)


def _status(
    *,
    apps: dict | None = None,
    offers: dict | None = None,
    model_name: str = "dev",
) -> statustypes.Status:
    return statustypes.Status._from_dict(
        {
            "model": {
                "name": model_name,
                "type": "iaas",
                "version": "3.1.0",
                "controller": "lxd",
                "cloud": "localhost",
                "region": "",
                "model-status": {"current": "available"},
            },
            "machines": {},
            "applications": apps or {},
            "offers": offers or {},
        }
    )


def _app(
    *,
    status: str = "active",
    message: str = "",
    units: dict | None = None,
    relations: dict | None = None,
) -> dict:
    return {
        "charm": "demo",
        "charm-origin": "local",
        "charm-name": "demo",
        "charm-rev": 1,
        "exposed": False,
        "application-status": {"current": status, "message": message},
        "units": units
        if units is not None
        else {
            "demo/0": {
                "workload-status": {"current": status, "message": message},
                "juju-status": {"current": "idle"},
                "address": "10.0.0.1",
                "open-ports": [],
            }
        },
        "relations": relations or {},
    }


def _relation(related_app: str, interface: str = "iface") -> list[dict]:
    return [{"related-application": related_app, "interface": interface, "scope": "global"}]


def _offer(app_name: str = "prometheus") -> dict:
    return {
        "application": app_name,
        "endpoints": {"metrics": {"interface": "prometheus_scrape", "role": "provider"}},
    }


class _Host(App):
    def __init__(self, widget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


# ---------------------------------------------------------------------------
# JujuStatusWidget._app_matches_filter
# ---------------------------------------------------------------------------


class TestFilterMatcher:
    def _widget_with_filter(self, needle: str) -> JujuStatusWidget:
        w = JujuStatusWidget()
        w.filter_text = needle
        return w

    def test_empty_filter_matches_everything(self) -> None:
        st = _status(apps={"web": _app()})
        w = JujuStatusWidget()
        assert w._app_matches_filter("web", st.apps["web"])

    def test_matches_app_name(self) -> None:
        st = _status(apps={"web-frontend": _app()})
        assert self._widget_with_filter("front")._app_matches_filter(
            "web-frontend", st.apps["web-frontend"]
        )

    def test_matches_app_status_and_message(self) -> None:
        st = _status(apps={"db": _app(status="blocked", message="needs trust")})
        app = st.apps["db"]
        assert self._widget_with_filter("blocked")._app_matches_filter("db", app)
        assert self._widget_with_filter("trust")._app_matches_filter("db", app)

    def test_matches_unit_name_and_workload(self) -> None:
        units = {
            "worker/3": {
                "workload-status": {"current": "maintenance", "message": "installing"},
                "juju-status": {"current": "executing"},
                "address": "10.0.0.9",
                "open-ports": [],
            }
        }
        st = _status(apps={"worker": _app(units=units)})
        app = st.apps["worker"]
        assert self._widget_with_filter("worker/3")._app_matches_filter("worker", app)
        assert self._widget_with_filter("maintenance")._app_matches_filter("worker", app)
        assert self._widget_with_filter("installing")._app_matches_filter("worker", app)

    def test_matches_relation_and_related_app(self) -> None:
        st = _status(apps={"web": _app(relations={"database": _relation("postgresql")})})
        app = st.apps["web"]
        assert self._widget_with_filter("database")._app_matches_filter("web", app)
        assert self._widget_with_filter("postgres")._app_matches_filter("web", app)

    def test_no_match_returns_false(self) -> None:
        st = _status(apps={"web": _app()})
        assert not self._widget_with_filter("zzz")._app_matches_filter("web", st.apps["web"])


# ---------------------------------------------------------------------------
# JujuStatusWidget._refresh_display
# ---------------------------------------------------------------------------


class TestRefreshDisplay:
    @pytest.mark.asyncio
    async def test_no_status_shows_placeholder(self) -> None:
        widget = JujuStatusWidget()
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            placeholders = widget.query(".no-apps")
            assert placeholders
            assert "No model connected" in str(placeholders.first(Static).render())

    @pytest.mark.asyncio
    async def test_status_without_apps_shows_empty_notice(self) -> None:
        widget = JujuStatusWidget(status=_status(apps={}))
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            texts = " ".join(str(s.render()) for s in widget.query(Static))
            assert "No applications deployed." in texts

    @pytest.mark.asyncio
    async def test_apps_relations_and_offers_render(self) -> None:
        st = _status(
            apps={"web": _app(relations={"db": _relation("postgresql")})},
            offers={"prom": _offer()},
        )
        widget = JujuStatusWidget(status=st, current_app="web", role="Dev")
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            assert widget.query(AppBox)
            assert widget.query(RelationLine)
            assert widget.query(OfferLine)
            header = " ".join(str(s.render()) for s in widget.query(".model-header"))
            assert "Dev: dev (localhost)" in header
            assert "1 app" in header

    @pytest.mark.asyncio
    async def test_filter_no_matches_shows_notice(self) -> None:
        widget = JujuStatusWidget(status=_status(apps={"web": _app()}))
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            widget.filter_text = "no-such-app"
            await pilot.pause()
            texts = " ".join(str(s.render()) for s in widget.query(Static))
            assert "No matches for 'no-such-app'." in texts

    @pytest.mark.asyncio
    async def test_update_status_and_set_current_app(self) -> None:
        widget = JujuStatusWidget()
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            widget.update_status(_status(apps={"web": _app(), "db": _app()}))
            await pilot.pause()
            widget.set_current_app("db")
            await pilot.pause()
            boxes = list(widget.query(AppBox))
            assert len(boxes) == 2
            here = [b for b in boxes if b.highlight]
            assert len(here) == 1 and here[0].app_name == "db"


# ---------------------------------------------------------------------------
# Filter key handling + StatusAvailable message
# ---------------------------------------------------------------------------


class TestFilterKeysAndMessages:
    @pytest.mark.asyncio
    async def test_slash_shows_filter_escape_clears(self) -> None:
        widget = JujuStatusWidget(status=_status(apps={"web": _app()}))
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            filter_input = widget.query_one("#status-filter", Input)
            assert "visible" not in filter_input.classes

            widget.key_slash()
            await pilot.pause()
            assert "visible" in filter_input.classes
            assert filter_input.has_focus

            filter_input.value = "web"
            await pilot.pause()
            assert widget.filter_text == "web"

            widget.key_escape()
            await pilot.pause()
            assert "visible" not in filter_input.classes
            assert widget.filter_text == ""
            assert filter_input.value == ""

    @pytest.mark.asyncio
    async def test_first_status_posts_status_available(self) -> None:
        seen: list[object] = []

        class _Catcher(App):
            def compose(self) -> ComposeResult:
                yield JujuStatusWidget()

            def on_juju_status_widget_status_available(
                self, message: JujuStatusWidget.StatusAvailable
            ) -> None:
                seen.append(message)

        async with _Catcher().run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            widget = pilot.app.query_one(JujuStatusWidget)
            widget.status = _status(apps={"web": _app()})
            await pilot.pause()
            assert len(seen) == 1
            # A second update must not re-fire (old was already non-None).
            widget.status = _status(apps={"web": _app(), "db": _app()})
            await pilot.pause()
            assert len(seen) == 1


# ---------------------------------------------------------------------------
# RelationLine
# ---------------------------------------------------------------------------


class TestRelationLine:
    @pytest.mark.asyncio
    async def test_click_posts_selected_message(self) -> None:
        seen: list[RelationLine.Selected] = []

        class _Catcher(App):
            def compose(self) -> ComposeResult:
                yield RelationLine(
                    "db → postgresql",
                    endpoint="db",
                    related_app="postgresql",
                    unit_name="web/0",
                )

            def on_relation_line_selected(self, message: RelationLine.Selected) -> None:
                seen.append(message)

        async with _Catcher().run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            await pilot.click(RelationLine)
            await pilot.pause()
            assert len(seen) == 1
            assert seen[0].endpoint == "db"
            assert seen[0].related_app == "postgresql"
            assert seen[0].unit_name == "web/0"


# ---------------------------------------------------------------------------
# MultiModelStatusWidget
# ---------------------------------------------------------------------------


class TestMultiModelWidget:
    @pytest.mark.asyncio
    async def test_hidden_until_a_model_connects(self) -> None:
        widget = MultiModelStatusWidget()
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            assert widget.display is False

            widget.dev_status = _status(apps={"web": _app()})
            await pilot.pause()
            assert widget.display is True
            dev_section = widget.query_one("#dev-section")
            assert dev_section.display is True
            assert dev_section.query(JujuStatusWidget)

    @pytest.mark.asyncio
    async def test_cos_collapsed_then_expanded_on_click(self) -> None:
        widget = MultiModelStatusWidget()
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            widget.dev_status = _status(apps={"web": _app()})
            widget.cos_status = _status(apps={"prometheus": _app()}, model_name="cos")
            await pilot.pause()

            cos_section = widget.query_one("#cos-section")
            # Collapsed: a summary Static, no nested JujuStatusWidget.
            assert not cos_section.query(JujuStatusWidget)
            assert cos_section.query(".collapsed-summary")

            await pilot.click("#cos-section")
            await pilot.pause()
            assert widget.cos_expanded is True
            assert cos_section.query(JujuStatusWidget)

            # Toggling back collapses it again.
            widget.toggle_cos_expanded()
            await pilot.pause()
            assert widget.cos_expanded is False
            assert not cos_section.query(JujuStatusWidget)

    @pytest.mark.asyncio
    async def test_click_outside_cos_section_does_not_toggle(self) -> None:
        widget = MultiModelStatusWidget()
        async with _Host(widget).run_test(size=_TERMINAL) as pilot:
            await pilot.pause()
            widget.dev_status = _status(apps={"web": _app()})
            widget.cos_status = _status(apps={"prometheus": _app()}, model_name="cos")
            await pilot.pause()
            await pilot.click("#dev-section")
            await pilot.pause()
            assert widget.cos_expanded is False
