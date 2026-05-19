"""Smoke tests guarding against modal-container collapse.

All four modals (``TranscriptScreen``, ``LogScreen``, ``RelationDetailScreen``,
``GraphScreen``) used to wrap their container in ``Center()``, whose
``height: auto`` caused the inner ``Vertical(height: 80%)`` to resolve
against a zero-height parent and collapse to a single row — so the
modal appeared blank.  These tests mount each screen with fixture
data and assert the output widget renders with non-zero rows.
"""

from __future__ import annotations

import pathlib
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cantrip.tui.screens.graph import GraphScreen
from cantrip.tui.screens.logs import LogScreen
from cantrip.tui.screens.relation import RelationDetailScreen
from cantrip.tui.screens.transcript import TranscriptScreen

pytestmark = pytest.mark.tui

# A terminal size large enough that 80%/90%-height containers have
# room to render meaningful content.
_TERMINAL = (100, 40)


class _Host(App):
    """Minimal app used to push a modal screen under test."""

    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _assert_has_rendered_rows(screen, container_id: str, output_id: str) -> None:
    """Fail if *container_id* has zero height or *output_id* has no lines.

    Both conditions indicate the modal has collapsed and would look
    blank to the user.
    """
    container = screen.query_one(f"#{container_id}")
    output = screen.query_one(f"#{output_id}", RichLog)
    assert container.size.height > 0, (
        f"#{container_id} collapsed to height 0 — modal will look blank"
    )
    assert output.size.height > 1, (
        f"#{output_id} has height {output.size.height} — not enough space to render"
    )
    assert len(output.lines) > 0, (
        f"#{output_id} has no lines — on_mount did not pre-fill the widget"
    )


class TestTranscriptModal:
    """TranscriptScreen renders an empty-state message when the DB is absent."""

    @pytest.mark.asyncio
    async def test_missing_db_path_renders_notice(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            with tempfile.TemporaryDirectory() as td:
                screen = TranscriptScreen(db_path=pathlib.Path(td) / "absent.db")
                await pilot.app.push_screen(screen)
                await pilot.pause()
                _assert_has_rendered_rows(screen, "transcript-container", "transcript-output")
                text = " ".join(
                    line.text for line in screen.query_one("#transcript-output", RichLog).lines
                )
                assert "No .cantrip session file found." in text

    @pytest.mark.asyncio
    async def test_empty_db_renders_empty_view(self) -> None:
        """A transcript DB with the right schema but no rows still shows a notice."""
        with tempfile.TemporaryDirectory() as td:
            db_path = pathlib.Path(td) / "session.db"
            # ``load_transcript`` tolerates a DB whose tables are missing by
            # returning empty collections, so an empty file is enough to
            # exercise the "no messages" branch.
            sqlite3.connect(db_path).close()

            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = TranscriptScreen(db_path=db_path)
                await pilot.app.push_screen(screen)
                await pilot.pause()
                _assert_has_rendered_rows(screen, "transcript-container", "transcript-output")


class TestLogModal:
    """LogScreen renders a notice or fetched output with visible height."""

    @pytest.mark.asyncio
    async def test_no_model_renders_notice(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = LogScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            _assert_has_rendered_rows(screen, "log-container", "log-output")
            text = " ".join(line.text for line in screen.query_one("#log-output", RichLog).lines)
            assert "No development model connected." in text

    @pytest.mark.asyncio
    async def test_empty_juju_output_renders_level_notice(self) -> None:
        """When juju returns no log lines, the ``EMPTY:`` branch fires."""
        result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = LogScreen(model="dev")
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.4)
                _assert_has_rendered_rows(screen, "log-container", "log-output")
                text = " ".join(
                    line.text for line in screen.query_one("#log-output", RichLog).lines
                )
                assert "No log entries at level" in text


class TestRelationModal:
    """RelationDetailScreen's container must size itself properly too."""

    @pytest.mark.asyncio
    async def test_no_model_renders_notice(self) -> None:
        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = RelationDetailScreen("app/0", "db", "postgresql", model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            _assert_has_rendered_rows(screen, "relation-container", "relation-output")


class TestGraphModal:
    """GraphScreen body must also render with visible height."""

    @pytest.mark.asyncio
    async def test_no_model_renders_notice(self) -> None:
        from textual.widgets import OptionList

        async with _Host().run_test(size=_TERMINAL) as pilot:
            screen = GraphScreen(model=None)
            await pilot.app.push_screen(screen)
            await pilot.pause()
            container = screen.query_one("#graph-container")
            assert container.size.height > 0, "#graph-container collapsed — modal will look blank"
            opts = screen.query_one("#graph-options", OptionList)
            assert opts.size.height > 0
            assert opts.option_count >= 1  # the "No model connected." notice
