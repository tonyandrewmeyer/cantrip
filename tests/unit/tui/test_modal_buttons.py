"""The bracketed footer / title-bar labels on modal screens are buttons.

Several modals (logs, relation, transcript, traces, help, tool-error)
used to render their ``[r] Refresh  [Esc] Close`` footer as a plain
``Static`` whose ``[r]`` / ``[Esc]`` tokens were eaten by Rich-markup
parsing, *and* had no click handler — so the affordance the bracketed
text suggested did nothing.  These tests mount each modal in a host app
and click the labels, asserting the matching action fires (or the
screen dismisses).  ``file_detail`` and ``graph`` already had the
behaviour and are covered here too so the pattern stays uniform.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from cantrip.tui.screens.file_detail import FileDetailScreen
from cantrip.tui.screens.graph import GraphScreen
from cantrip.tui.screens.help import HelpScreen
from cantrip.tui.screens.logs import LogScreen
from cantrip.tui.screens.relation import RelationDetailScreen
from cantrip.tui.screens.tool_error import ToolErrorScreen
from cantrip.tui.screens.traces import TraceScreen
from cantrip.tui.screens.transcript import TranscriptScreen

pytestmark = pytest.mark.tui

_TERMINAL = (120, 40)


class _Host(App):
    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _no_subprocess():
    return patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr=""))


# ---------------------------------------------------------------------------
# Refresh-style buttons fire the matching action
# ---------------------------------------------------------------------------


class TestRefreshButtons:
    @pytest.mark.asyncio
    async def test_file_detail_refresh_and_close(self) -> None:
        with _no_subprocess():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = FileDetailScreen(pathlib.Path(__file__))
                await pilot.app.push_screen(screen)
                await pilot.pause()
                calls: list[str] = []
                screen.action_refresh = lambda: calls.append("refresh")  # type: ignore[method-assign]
                await pilot.click("#file-refresh-btn")
                await pilot.pause()
                assert calls == ["refresh"]
                await pilot.click("#file-close-btn")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, FileDetailScreen)

    @pytest.mark.asyncio
    async def test_graph_refresh_filter_close(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = GraphScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            calls: list[str] = []
            screen.action_refresh = lambda: calls.append("refresh")  # type: ignore[method-assign]
            screen.action_cycle_filter = lambda: calls.append("filter")  # type: ignore[method-assign]
            await pilot.click("#graph-refresh-btn")
            await pilot.pause()
            await pilot.click("#graph-filter-btn")
            await pilot.pause()
            assert calls == ["refresh", "filter"]
            await pilot.click("#graph-close-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, GraphScreen)

    @pytest.mark.asyncio
    async def test_logs_footer_buttons(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = LogScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            calls: list[str] = []
            screen.action_refresh = lambda: calls.append("refresh")  # type: ignore[method-assign]
            screen.action_cycle_level = lambda: calls.append("level")  # type: ignore[method-assign]
            screen.action_cycle_model = lambda: calls.append("model")  # type: ignore[method-assign]
            screen.action_toggle_stream = lambda: calls.append("stream")  # type: ignore[method-assign]
            await pilot.click("#log-refresh-btn")
            await pilot.click("#log-level-btn")
            await pilot.click("#log-model-btn")
            await pilot.click("#log-stream-btn")
            await pilot.pause()
            assert calls == ["refresh", "level", "model", "stream"]
            await pilot.click("#log-close-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, LogScreen)

    @pytest.mark.asyncio
    async def test_logs_title_hint_closes(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = LogScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.click("#log-close")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, LogScreen)

    @pytest.mark.asyncio
    async def test_relation_footer_buttons(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = RelationDetailScreen("app/0", "db", "postgresql", model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            calls: list[str] = []
            screen.action_refresh = lambda: calls.append("refresh")  # type: ignore[method-assign]
            await pilot.click("#relation-refresh-btn")
            await pilot.pause()
            assert calls == ["refresh"]
            await pilot.click("#relation-close-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, RelationDetailScreen)

    @pytest.mark.asyncio
    async def test_transcript_footer_buttons(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = TranscriptScreen(db_path=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            search_calls: list[str] = []
            screen.action_search = lambda: search_calls.append("search")  # type: ignore[method-assign]
            await pilot.click("#transcript-search-btn")
            await pilot.pause()
            assert search_calls == ["search"]

            assert screen.view == "conversation"
            await pilot.click("#transcript-view-btn")
            await pilot.pause()
            assert screen.view == "tasks"

            refresh_calls: list[str] = []
            screen.action_refresh = lambda: refresh_calls.append("refresh")  # type: ignore[method-assign]
            await pilot.click("#transcript-refresh-btn")
            await pilot.pause()
            assert refresh_calls == ["refresh"]

            await pilot.click("#transcript-close-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, TranscriptScreen)


# ---------------------------------------------------------------------------
# Close-only modals: the bracketed label dismisses the screen
# ---------------------------------------------------------------------------


class TestCloseOnlyModals:
    @pytest.mark.asyncio
    async def test_traces_close_button(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            await pilot.app.push_screen(TraceScreen(cos_model=None))
            await pilot.pause()
            assert isinstance(pilot.app.screen, TraceScreen)
            await pilot.click("#trace-close")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, TraceScreen)

    @pytest.mark.asyncio
    async def test_help_close_button(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            await pilot.app.push_screen(HelpScreen())
            await pilot.pause()
            assert isinstance(pilot.app.screen, HelpScreen)
            await pilot.click("#help-close")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, HelpScreen)

    @pytest.mark.asyncio
    async def test_tool_error_close_buttons(self) -> None:
        # Title-hint variant.
        async with _Host().run_test(size=_TERMINAL) as pilot:
            await pilot.app.push_screen(ToolErrorScreen("charmcraft_pack failed", "boom\ntrace"))
            await pilot.pause()
            await pilot.click("#tool-error-close")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, ToolErrorScreen)

        # Footer variant.
        async with _Host().run_test(size=_TERMINAL) as pilot:
            await pilot.app.push_screen(ToolErrorScreen("charmcraft_pack failed", "boom"))
            await pilot.pause()
            await pilot.click("#tool-error-footer")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, ToolErrorScreen)


# ---------------------------------------------------------------------------
# The bracketed key hints actually render now (markup not eaten)
# ---------------------------------------------------------------------------


class TestHintsRender:
    @pytest.mark.asyncio
    async def test_footer_labels_show_their_keys(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = LogScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            labels = {
                wid: str(screen.query_one(f"#{wid}").render())
                for wid in (
                    "log-refresh-btn",
                    "log-level-btn",
                    "log-model-btn",
                    "log-stream-btn",
                    "log-close-btn",
                    "log-close",
                )
            }
            assert "r Refresh" in labels["log-refresh-btn"]
            assert "l Level" in labels["log-level-btn"]
            assert "m Model" in labels["log-model-btn"]
            assert "t Stream" in labels["log-stream-btn"]
            assert "Esc Close" in labels["log-close-btn"]
            assert "Esc Close" in labels["log-close"]
