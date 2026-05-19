"""Behaviour and renderer tests for :class:`TranscriptScreen`.

Closes the Phase 93.1 blind spot in ``tui/screens/transcript.py``: the
non-conversation view renderers (tasks / events / checkpoints), the
search bar's open → type → submit → close lifecycle, and view cycling.
The pure ``_*_lines`` helpers are exercised directly with light fakes;
the interactive paths run inside a minimal host app via ``Pilot``.
"""

from __future__ import annotations

import contextlib
import pathlib
import types
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog, Static

from cantrip.transcript.export import TranscriptData
from cantrip.tui.screens.transcript import TranscriptScreen

pytestmark = pytest.mark.tui

_TERMINAL = (100, 40)


class _Host(App):
    """Minimal app used to push the transcript modal under test."""

    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _output_text(screen: TranscriptScreen) -> str:
    """Concatenated visible text of the transcript RichLog."""
    log = screen.query_one("#transcript-output", RichLog)
    return " ".join(line.text for line in log.lines)


def _static_text(screen: TranscriptScreen, selector: str) -> str:
    """Plain text currently displayed by a ``Static`` widget."""
    return str(screen.query_one(selector, Static).render())


# ---------------------------------------------------------------------------
# Pure line-renderer helpers
# ---------------------------------------------------------------------------


class TestLineRenderers:
    def test_conversation_lines_empty(self) -> None:
        data = types.SimpleNamespace(messages=[])
        assert TranscriptScreen._conversation_lines(data) == ["No conversation messages recorded."]

    def test_conversation_lines_truncates_and_lists_tool_calls(self) -> None:
        data = types.SimpleNamespace(
            messages=[
                {
                    "role": "assistant",
                    "timestamp": "2026-05-10T00:00:00",
                    "content": "x" * 600,
                    "tool_calls": [{"name": "read_file"}, "garbled"],
                },
            ]
        )
        lines = TranscriptScreen._conversation_lines(data)
        joined = "\n".join(lines)
        assert "ASSISTANT" in joined
        # 500-char preview plus ellipsis.
        assert "..." in joined
        assert "→ tool call: read_file" in joined
        # The non-dict tool call falls back to "?".
        assert "→ tool call: ?" in joined

    def test_task_lines_empty(self) -> None:
        assert TranscriptScreen._task_lines(types.SimpleNamespace(tasks=[])) == [
            "No tasks recorded."
        ]

    def test_task_lines_with_result_and_subagent_messages(self) -> None:
        data = types.SimpleNamespace(
            tasks=[
                {
                    "id": "t1",
                    "status": "done",
                    "title": "Build charm",
                    "category": "build",
                    "result": "y" * 400,
                },
                {"id": "t2", "status": "bogus", "title": "Mystery"},
            ],
            subagent_messages={
                "t1": [{"tool_calls": [{"name": "x"}]}, {"content": "hi"}],
            },
        )
        lines = TranscriptScreen._task_lines(data)
        joined = "\n".join(lines)
        assert "✓" in joined and "Build charm" in joined
        assert "..." in joined  # result preview truncated at 300 chars
        assert "↳ 2 subagent messages, 1 tool calls" in joined
        assert "? [bold]Mystery[/bold]" in joined  # unknown status icon

    def test_event_lines_empty(self) -> None:
        assert TranscriptScreen._event_lines(types.SimpleNamespace(events=[])) == [
            "No events recorded."
        ]

    def test_event_lines_renders_detail_dict(self) -> None:
        data = types.SimpleNamespace(
            events=[
                {
                    "event_type": "error",
                    "timestamp": "2026-05-10T01:00:00",
                    "detail": {"code": 7, "msg": "boom"},
                },
                {"event_type": "weird", "timestamp": "", "detail": "not-a-dict"},
            ]
        )
        lines = TranscriptScreen._event_lines(data)
        joined = "\n".join(lines)
        assert "error" in joined and "code: 7" in joined and "msg: boom" in joined
        assert "weird" in joined

    def test_checkpoint_lines_empty(self) -> None:
        assert TranscriptScreen._checkpoint_lines(types.SimpleNamespace(checkpoints={})) == [
            "No step checkpoints recorded."
        ]

    def test_checkpoint_lines_groups_by_task(self) -> None:
        data = types.SimpleNamespace(
            checkpoints={
                "t1": [
                    {
                        "step_name": "pack",
                        "ordinal": 0,
                        "kind": "structured",
                        "input_hash": "abcdef123456789",
                        "created_at": "2026-05-10",
                    }
                ],
                "t-missing": [{"step_name": "x", "ordinal": 1, "kind": "k"}],
            },
            tasks=[{"id": "t1", "title": "Build"}],
        )
        lines = TranscriptScreen._checkpoint_lines(data)
        joined = "\n".join(lines)
        assert "Build" in joined and "pack#0" in joined and "abcdef123456" in joined
        assert "(unknown task)" in joined
        assert "(none)" in joined  # missing input_hash

    def test_strip_markup_removes_tags(self) -> None:
        assert TranscriptScreen._strip_markup("[bold]hi[/bold] there") == "hi there"

    def test_apply_line_highlight_wraps_matches(self) -> None:
        out = TranscriptScreen._apply_line_highlight("the Foo and the foo", "foo", is_active=True)
        assert out.count("[black on yellow]") == 2
        # No match → line returned unchanged.
        assert TranscriptScreen._apply_line_highlight("nothing here", "zzz", False) == (
            "nothing here"
        )

    def test_apply_line_highlight_inactive_style(self) -> None:
        out = TranscriptScreen._apply_line_highlight("a foo b", "foo", is_active=False)
        assert "yellow reverse" in out


# ---------------------------------------------------------------------------
# Screen behaviour
# ---------------------------------------------------------------------------


def _fixture() -> TranscriptData:
    return TranscriptData(
        messages=[
            {"role": "user", "timestamp": "t0", "content": "build me a charm"},
            {"role": "assistant", "timestamp": "t1", "content": "on it"},
        ],
        tasks=[{"id": "t1", "status": "done", "title": "Plan", "category": "research"}],
        events=[{"event_type": "session_start", "timestamp": "t0", "detail": {}}],
        checkpoints={"t1": [{"step_name": "research", "ordinal": 0, "kind": "json"}]},
    )


@contextlib.contextmanager
def _transcript_data(*, exists: bool = True):
    """Patch the DB-existence probe and ``load_transcript`` for a whole test."""
    with (
        patch.object(pathlib.Path, "exists", return_value=exists),
        patch("cantrip.transcript.export.load_transcript", side_effect=lambda _p: _fixture()),
    ):
        yield


async def _push_transcript(pilot) -> TranscriptScreen:
    """Push a TranscriptScreen against the fixture transcript."""
    screen = TranscriptScreen(db_path=pathlib.Path("/does/not/matter.db"))
    await pilot.app.push_screen(screen)
    await pilot.pause()
    return screen


class TestViewCycling:
    @pytest.mark.asyncio
    async def test_cycle_view_walks_all_four_views(self) -> None:
        with _transcript_data():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                assert screen.view == "conversation"
                assert "build me a charm" in _output_text(screen)

                await pilot.press("v")
                await pilot.pause()
                assert screen.view == "tasks"
                assert "Plan" in _output_text(screen)

                await pilot.press("v")
                await pilot.pause()
                assert screen.view == "events"
                assert "session_start" in _output_text(screen)

                await pilot.press("v")
                await pilot.pause()
                assert screen.view == "checkpoints"
                assert "research#0" in _output_text(screen)

                await pilot.press("v")
                await pilot.pause()
                assert screen.view == "conversation"

    @pytest.mark.asyncio
    async def test_refresh_rerenders_current_view(self) -> None:
        with _transcript_data():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                with patch(
                    "cantrip.transcript.export.load_transcript", side_effect=lambda _p: _fixture()
                ) as loader:
                    await pilot.press("r")
                    await pilot.pause()
                    loader.assert_called()
                assert isinstance(screen, TranscriptScreen)

    @pytest.mark.asyncio
    async def test_missing_db_shows_notice(self) -> None:
        with _transcript_data(exists=False):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                assert "No .cantrip session file found." in _output_text(screen)


class TestSearchBar:
    @pytest.mark.asyncio
    async def test_search_open_type_submit_close(self) -> None:
        with _transcript_data():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                search_bar = screen.query_one("#transcript-search")
                assert not search_bar.has_class("-visible")

                # `/` opens the search bar and focuses its input.
                await pilot.press("slash")
                await pilot.pause()
                assert search_bar.has_class("-visible")
                assert screen.query_one("#search-input", Input).has_focus

                # Type a query that matches a transcript line.
                for ch in "charm":
                    await pilot.press(ch)
                await pilot.pause()
                assert screen._search_query == "charm"
                assert screen._match_line_indices
                # The status label shows the active/total match counter.
                assert "/" in _static_text(screen, "#search-status")

                # Enter advances to the next match (wraps with one match).
                await pilot.press("enter")
                await pilot.pause()

                # Esc closes the search bar but leaves the screen open.
                await pilot.press("escape")
                await pilot.pause()
                assert not search_bar.has_class("-visible")
                assert screen._search_query == ""
                assert isinstance(pilot.app.screen, TranscriptScreen)

                # A second Esc now dismisses the screen.
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, TranscriptScreen)

    @pytest.mark.asyncio
    async def test_search_with_no_matches_sets_label(self) -> None:
        with _transcript_data():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                await pilot.press("slash")
                await pilot.pause()
                for ch in "zzzz":
                    await pilot.press(ch)
                await pilot.pause()
                assert not screen._match_line_indices
                assert _static_text(screen, "#search-status") == "no matches"
                # Submitting with no matches is a no-op.
                await pilot.press("enter")
                await pilot.pause()
                assert screen._active_match == 0

    @pytest.mark.asyncio
    async def test_switching_view_clears_search(self) -> None:
        with _transcript_data():
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_transcript(pilot)
                await pilot.press("slash")
                await pilot.pause()
                for ch in "charm":
                    await pilot.press(ch)
                await pilot.pause()
                assert screen._search_query == "charm"
                # Close the search bar so `v` reaches the screen binding,
                # then cycle the view — the prior query must not survive.
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("v")
                await pilot.pause()
                assert screen.view == "tasks"
                assert screen._search_query == ""
                assert not screen.query_one("#transcript-search").has_class("-visible")
