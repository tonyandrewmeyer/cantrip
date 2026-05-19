"""Behaviour tests for :class:`LogScreen` (Phase 93.1 backfill).

Covers the parts of ``tui/screens/logs.py`` that only ran in manual
use: the ``juju debug-log`` worker (success / error / empty / missing-
binary / timeout), the worker-result handler that paints the RichLog,
level cycling, refresh, and the live-streaming toggle.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cantrip.tui.screens.logs import LogScreen

pytestmark = pytest.mark.tui

_TERMINAL = (100, 40)


class _Host(App):
    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _log_text(screen: LogScreen) -> str:
    return " ".join(line.text for line in screen.query_one("#log-output", RichLog).lines)


async def _push_log(pilot, **kwargs) -> LogScreen:
    screen = LogScreen(**kwargs)
    await pilot.app.push_screen(screen)
    await pilot.pause(delay=0.3)
    return screen


# ---------------------------------------------------------------------------
# The blocking juju-debug-log worker (pure function)
# ---------------------------------------------------------------------------


class TestFetchBlocking:
    def test_success_returns_stdout(self) -> None:
        result = MagicMock(returncode=0, stdout="  line one\nline two  \n", stderr="")
        with patch("subprocess.run", return_value=result):
            out = LogScreen._fetch_logs_blocking("dev", "WARNING")
        assert out == "line one\nline two"

    def test_missing_binary_reports_error(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            out = LogScreen._fetch_logs_blocking("dev", "WARNING")
        assert out.startswith("ERROR:") and "juju CLI not found" in out

    def test_timeout_reports_error(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("juju", 15)):
            out = LogScreen._fetch_logs_blocking("dev", "WARNING")
        assert out == "ERROR:Timed out fetching logs."

    def test_nonzero_returncode_surfaces_stderr(self) -> None:
        result = MagicMock(returncode=1, stdout="", stderr="model not found")
        with patch("subprocess.run", return_value=result):
            out = LogScreen._fetch_logs_blocking("dev", "WARNING")
        assert out == "ERROR:model not found"

    def test_empty_output_marks_level(self) -> None:
        result = MagicMock(returncode=0, stdout="   ", stderr="")
        with patch("subprocess.run", return_value=result):
            out = LogScreen._fetch_logs_blocking("dev", "DEBUG")
        assert out == "EMPTY:DEBUG"


# ---------------------------------------------------------------------------
# Worker-result rendering
# ---------------------------------------------------------------------------


class TestWorkerStateChanged:
    @pytest.mark.asyncio
    async def test_success_path_writes_lines(self) -> None:
        result = MagicMock(returncode=0, stdout="alpha\nbravo", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                text = _log_text(screen)
                assert "alpha" in text and "bravo" in text

    @pytest.mark.asyncio
    async def test_error_result_writes_message_only(self) -> None:
        result = MagicMock(returncode=2, stdout="", stderr="boom")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                text = _log_text(screen)
                assert "boom" in text and "ERROR:" not in text

    @pytest.mark.asyncio
    async def test_empty_result_writes_level_notice(self) -> None:
        result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                assert "No log entries at level WARNING." in _log_text(screen)

    @pytest.mark.asyncio
    async def test_unrelated_worker_is_ignored(self) -> None:
        result = MagicMock(returncode=0, stdout="data", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                before = _log_text(screen)
                fake_event = MagicMock()
                fake_event.worker.name = "something_else"
                screen.on_worker_state_changed(fake_event)
                await pilot.pause()
                assert _log_text(screen) == before

    @pytest.mark.asyncio
    async def test_no_model_shows_notice_and_skips_worker(self) -> None:
        with patch("subprocess.run") as run:
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model=None)
                assert "No development model connected." in _log_text(screen)
            run.assert_not_called()


# ---------------------------------------------------------------------------
# Key actions
# ---------------------------------------------------------------------------


class TestActions:
    @pytest.mark.asyncio
    async def test_cycle_level_advances_and_refetches(self) -> None:
        result = MagicMock(returncode=0, stdout="x", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                assert screen.level == "WARNING"
                await pilot.press("l")
                await pilot.pause(delay=0.2)
                assert screen.level == "INFO"
                # WARNING -> INFO -> DEBUG -> ERROR -> WARNING
                for expected in ("DEBUG", "ERROR", "WARNING"):
                    await pilot.press("l")
                    await pilot.pause(delay=0.1)
                    assert screen.level == expected

    @pytest.mark.asyncio
    async def test_refresh_rekicks_the_worker(self) -> None:
        result = MagicMock(returncode=0, stdout="y", stderr="")
        with patch("subprocess.run", return_value=result) as run:
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                first = run.call_count
                await pilot.press("r")
                await pilot.pause(delay=0.3)
                assert run.call_count > first
                assert isinstance(screen, LogScreen)

    @pytest.mark.asyncio
    async def test_dismiss_closes_the_screen(self) -> None:
        result = MagicMock(returncode=0, stdout="z", stderr="")
        with patch("subprocess.run", return_value=result):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                await _push_log(pilot, model="dev")
                assert isinstance(pilot.app.screen, LogScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, LogScreen)


# ---------------------------------------------------------------------------
# Live streaming
# ---------------------------------------------------------------------------


async def _live_stream(*_args, **_kwargs):
    """Emit two lines, then park so the streaming task stays alive."""
    yield "stream-1"
    yield "stream-2"
    await asyncio.sleep(3600)


class TestStreaming:
    @pytest.mark.asyncio
    async def test_toggle_stream_starts_and_stops(self) -> None:
        result = MagicMock(returncode=0, stdout="static", stderr="")
        with (
            patch("subprocess.run", return_value=result),
            patch("cantrip.juju.log_stream.stream_lines", _live_stream),
        ):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                assert screen.streaming is False

                await pilot.press("t")
                await pilot.pause(delay=0.2)
                assert screen.streaming is True
                text = _log_text(screen)
                assert "Streaming logs at level WARNING" in text
                assert "stream-1" in text and "stream-2" in text

                await pilot.press("t")
                await pilot.pause(delay=0.1)
                assert screen.streaming is False

    @pytest.mark.asyncio
    async def test_stream_loop_swallows_os_error(self) -> None:
        async def boom(*_args, **_kwargs):
            raise OSError("pipe broke")
            yield  # pragma: no cover - unreachable, makes this an async gen

        result = MagicMock(returncode=0, stdout="static", stderr="")
        with (
            patch("subprocess.run", return_value=result),
            patch("cantrip.juju.log_stream.stream_lines", boom),
        ):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                await pilot.press("t")
                await pilot.pause(delay=0.2)
                # The loop's finally-block clears the flag even on error.
                assert screen.streaming is False

    @pytest.mark.asyncio
    async def test_dismiss_stops_an_active_stream(self) -> None:
        result = MagicMock(returncode=0, stdout="static", stderr="")
        with (
            patch("subprocess.run", return_value=result),
            patch("cantrip.juju.log_stream.stream_lines", _live_stream),
        ):
            async with _Host().run_test(size=_TERMINAL) as pilot:
                screen = await _push_log(pilot, model="dev")
                await pilot.press("t")
                await pilot.pause(delay=0.2)
                assert screen.streaming is True
                await pilot.press("escape")
                await pilot.pause()
                assert screen.streaming is False
                assert not isinstance(pilot.app.screen, LogScreen)
