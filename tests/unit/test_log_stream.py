"""Tests for ``cantrip.juju.log_stream``."""

from __future__ import annotations

from unittest import mock

import pytest

from cantrip.juju import log_stream


def _make_stdout(lines: list[bytes]) -> mock.AsyncMock:
    """Build an AsyncMock ``stdout`` that yields ``lines`` then EOF."""
    queue = list(lines) + [b""]  # Trailing empty bytes marks EOF.
    stdout = mock.AsyncMock()
    stdout.readline.side_effect = queue
    return stdout


def _make_proc(stdout: mock.AsyncMock) -> mock.AsyncMock:
    """Build a fake ``asyncio.subprocess.Process``."""
    proc = mock.AsyncMock()
    proc.stdout = stdout
    # ``terminate`` and ``kill`` are sync on a real Process; don't let
    # AsyncMock turn them into coroutines that leak un-awaited warnings.
    proc.terminate = mock.MagicMock()
    proc.kill = mock.MagicMock()
    return proc


class TestJujuAvailable:
    def test_returns_true_when_juju_on_path(self) -> None:
        with mock.patch("cantrip.juju.log_stream.shutil.which", return_value="/usr/bin/juju"):
            assert log_stream.juju_available() is True

    def test_returns_false_when_missing(self) -> None:
        with mock.patch("cantrip.juju.log_stream.shutil.which", return_value=None):
            assert log_stream.juju_available() is False


class TestTailLogs:
    @pytest.mark.asyncio
    async def test_builds_expected_command(self) -> None:
        proc = _make_proc(_make_stdout([]))

        with mock.patch(
            "cantrip.juju.log_stream.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as create:
            result = await log_stream.tail_logs("dev", level="INFO", lines=25)

        assert result is proc
        args = create.call_args[0]
        assert args[0] == "juju"
        assert "debug-log" in args
        assert "--model" in args and args[args.index("--model") + 1] == "dev"
        assert "--tail" in args
        assert "-n" in args and args[args.index("-n") + 1] == "25"
        assert "--level" in args and args[args.index("--level") + 1] == "INFO"
        assert "--include" not in args  # No unit filter supplied.

    @pytest.mark.asyncio
    async def test_includes_unit_filter(self) -> None:
        proc = _make_proc(_make_stdout([]))

        with mock.patch(
            "cantrip.juju.log_stream.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as create:
            await log_stream.tail_logs("dev", unit="my-app/0")

        args = create.call_args[0]
        assert "--include" in args
        assert args[args.index("--include") + 1] == "my-app/0"

    @pytest.mark.asyncio
    async def test_stderr_is_devnull_not_pipe(self) -> None:
        """stderr is captured to DEVNULL so a noisy juju binary can't
        deadlock the subprocess by filling the pipe buffer with no
        reader on our side.
        """
        import asyncio as _asyncio

        proc = _make_proc(_make_stdout([]))

        with mock.patch(
            "cantrip.juju.log_stream.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as create:
            await log_stream.tail_logs("dev")

        assert create.call_args.kwargs["stderr"] is _asyncio.subprocess.DEVNULL


class TestStreamLines:
    @pytest.mark.asyncio
    async def test_yields_decoded_lines_and_strips_trailing_newline(self) -> None:
        stdout = _make_stdout([b"first line\n", b"second line\n", b"third line\n"])
        proc = _make_proc(stdout)

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
        ):
            collected: list[str] = []
            async for line in log_stream.stream_lines("dev"):
                collected.append(line)

        assert collected == ["first line", "second line", "third line"]
        proc.terminate.assert_called_once()
        proc.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_short_circuits_when_juju_missing(self) -> None:
        with mock.patch("cantrip.juju.log_stream.juju_available", return_value=False):
            collected = [line async for line in log_stream.stream_lines("dev")]
        assert collected == []

    @pytest.mark.asyncio
    async def test_respects_max_lines(self) -> None:
        stdout = _make_stdout([b"a\n", b"b\n", b"c\n", b"d\n", b"e\n"])
        proc = _make_proc(stdout)

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
        ):
            collected = [line async for line in log_stream.stream_lines("dev", max_lines=3)]

        assert collected == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_stops_on_timeout(self) -> None:
        """wait_for raising TimeoutError should terminate the stream."""
        stdout = mock.AsyncMock()
        proc = _make_proc(stdout)

        def _raise_timeout(coro, *_args, **_kwargs):
            coro.close()
            raise TimeoutError

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
            mock.patch(
                "cantrip.juju.log_stream.asyncio.wait_for",
                side_effect=_raise_timeout,
            ),
        ):
            collected = [line async for line in log_stream.stream_lines("dev")]

        assert collected == []
        proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminate_ignores_already_dead_process(self) -> None:
        """ProcessLookupError on terminate must be swallowed by the cleanup."""
        stdout = _make_stdout([b"one\n"])
        proc = _make_proc(stdout)
        proc.terminate.side_effect = ProcessLookupError

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
        ):
            collected = [line async for line in log_stream.stream_lines("dev")]

        assert collected == ["one"]
        proc.terminate.assert_called_once()
        proc.wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kills_process_when_terminate_grace_expires(self) -> None:
        """If proc.wait() doesn't return after terminate() within the
        grace window, escalate to SIGKILL so a wedged subprocess can't
        hang the caller indefinitely.
        """
        stdout = _make_stdout([b"line\n"])
        proc = _make_proc(stdout)

        # First wait_for is the readline call (let it succeed); second
        # is the post-terminate proc.wait() — that one times out.
        readline_call = {"n": 0}

        async def _wait_for(coro, *_args, **_kwargs):
            readline_call["n"] += 1
            if readline_call["n"] == 1:
                return await coro
            coro.close()
            raise TimeoutError

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
            mock.patch(
                "cantrip.juju.log_stream.asyncio.wait_for",
                side_effect=_wait_for,
            ),
        ):
            collected = [line async for line in log_stream.stream_lines("dev", max_lines=1)]

        assert collected == ["line"]
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_decodes_invalid_utf8_with_replacement(self) -> None:
        """Bad bytes survive as U+FFFD replacements, not as an exception."""
        stdout = _make_stdout([b"bad \xff byte\n"])
        proc = _make_proc(stdout)

        with (
            mock.patch("cantrip.juju.log_stream.juju_available", return_value=True),
            mock.patch("cantrip.juju.log_stream.tail_logs", return_value=proc),
        ):
            collected = [line async for line in log_stream.stream_lines("dev")]

        assert collected == ["bad \ufffd byte"]
