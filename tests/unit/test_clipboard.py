"""Tests for ``cantrip.clipboard`` -- OSC 52 helpers used by ``/copy``."""

from __future__ import annotations

import base64
import io

from cantrip import clipboard


class TestOsc52Sequence:
    """The escape format must match xterm's OSC 52 spec exactly."""

    def test_short_text_round_trips(self) -> None:
        seq = clipboard.osc52_sequence("hello, world")
        assert seq.startswith(b"\x1b]52;c;")
        assert seq.endswith(b"\x07")
        payload = seq[len(b"\x1b]52;c;") : -1]
        assert base64.b64decode(payload).decode("utf-8") == "hello, world"

    def test_unicode_payload_uses_utf8(self) -> None:
        seq = clipboard.osc52_sequence("café — ✨")
        payload = seq[len(b"\x1b]52;c;") : -1]
        assert base64.b64decode(payload).decode("utf-8") == "café — ✨"

    def test_oversized_payload_truncates_silently(self) -> None:
        # 200KB of ASCII -- well above MAX_CLIPBOARD_BYTES.  The
        # truncation is silent so a large copy never blows up the
        # terminal; the slash command's confirmation message tells
        # the user how many chars actually moved.
        big = "x" * 200_000
        seq = clipboard.osc52_sequence(big)
        payload = seq[len(b"\x1b]52;c;") : -1]
        decoded = base64.b64decode(payload)
        assert len(decoded) == clipboard.MAX_CLIPBOARD_BYTES


class TestWriteToTerminal:
    """``write_to_terminal`` rejects non-tty streams and writes otherwise."""

    def test_writes_when_stream_provided(self) -> None:
        buf = io.BytesIO()
        ok = clipboard.write_to_terminal("payload", stream=buf)
        assert ok is True
        assert buf.getvalue().startswith(b"\x1b]52;c;")
        assert buf.getvalue().endswith(b"\x07")

    def test_rejects_when_no_tty_and_no_stream(self, monkeypatch) -> None:
        # Pytest's captured stdout is not a tty -- the helper should
        # report failure cleanly so the slash-command surface can
        # fall back to printing the body.
        class _NotATty:
            def isatty(self) -> bool:
                return False

        monkeypatch.setattr(clipboard.sys, "__stdout__", _NotATty())
        assert clipboard.write_to_terminal("payload") is False

    def test_handles_oserror_during_write(self, monkeypatch) -> None:
        class _Broken:
            def write(self, _data: bytes) -> int:
                raise OSError("pipe closed")

            def flush(self) -> None:
                pass

        assert clipboard.write_to_terminal("payload", stream=_Broken()) is False
