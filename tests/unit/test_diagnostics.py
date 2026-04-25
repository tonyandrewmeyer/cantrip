"""Tests for ``cantrip.diagnostics`` — internal-error log + chat string."""

from __future__ import annotations

from pathlib import Path

import pytest

from cantrip import diagnostics


def _raise_and_capture() -> Exception:
    """Return a real exception with a real traceback attached.

    ``raise from`` inside a function gives the formatter a non-empty
    traceback frame to render so the assertions can check that the
    file/line context lands in the log.
    """
    try:
        raise RuntimeError("synthetic boom")
    except RuntimeError as caught:
        return caught


class TestLogPath:
    def test_honours_xdg_state_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert diagnostics.log_path() == tmp_path / "cantrip" / "diagnostics.log"

    def test_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        path = diagnostics.log_path()
        # Falls back to ~/.local/state/cantrip/diagnostics.log per XDG.
        assert path.parent.name == "cantrip"
        assert path.name == "diagnostics.log"
        assert ".local/state" in str(path)


class TestReportInternalError:
    def test_writes_full_traceback_to_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        exc = _raise_and_capture()

        result = diagnostics.report_internal_error("/map", exc)

        log_path = tmp_path / "cantrip" / "diagnostics.log"
        body = log_path.read_text(encoding="utf-8")
        assert "/map" in body
        assert "RuntimeError: synthetic boom" in body
        assert "Traceback" in body
        # Timestamp present (ISO 8601 — has a 'T').
        assert "T" in body

        # Returned chat string is short, friendly, and points at the log.
        assert "something went wrong" in result.lower()
        assert "/map" in result
        assert str(log_path) in result
        # Does NOT include the stack itself.
        assert "RuntimeError" not in result
        assert "Traceback" not in result

    def test_appends_subsequent_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        diagnostics.report_internal_error("first", _raise_and_capture())
        diagnostics.report_internal_error("second", _raise_and_capture())

        body = (tmp_path / "cantrip" / "diagnostics.log").read_text(encoding="utf-8")
        assert "first" in body
        assert "second" in body
        # Both entries land — the file isn't overwritten on the
        # second call.
        assert body.count("RuntimeError: synthetic boom") == 2

    def test_creates_parent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # XDG_STATE_HOME points at a directory that doesn't exist yet.
        target = tmp_path / "nested" / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(target))
        diagnostics.report_internal_error("/map", _raise_and_capture())
        assert (target / "cantrip" / "diagnostics.log").exists()

    def test_returns_chat_string_even_when_log_write_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point at an unwritable path so the file open fails.
        unwritable = tmp_path / "blocked"
        unwritable.write_text("not a directory")
        # Putting cantrip/ underneath a *file* makes mkdir raise
        # FileExistsError — exercises the OSError swallow path.
        monkeypatch.setenv("XDG_STATE_HOME", str(unwritable))

        result = diagnostics.report_internal_error("/map", _raise_and_capture())

        # Still returns a friendly chat string — does not propagate.
        assert "something went wrong" in result.lower()

    def test_log_size_bounded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pre-fill the log past the soft cap, then write again — the
        # head should be trimmed so the file stays bounded.
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        log_path = tmp_path / "cantrip" / "diagnostics.log"
        log_path.parent.mkdir(parents=True)
        # Use a real entry-shape payload so the boundary search works.
        sep = "\n" + "=" * 72 + "\n"
        filler = sep + "old entry body\n" * 60_000
        log_path.write_text(filler, encoding="utf-8")
        assert log_path.stat().st_size > diagnostics._MAX_LOG_BYTES

        diagnostics.report_internal_error("/map", _raise_and_capture())

        # File should be back under the cap (most recent half kept).
        assert log_path.stat().st_size < diagnostics._MAX_LOG_BYTES
        # And the new entry still landed.
        body = log_path.read_text(encoding="utf-8")
        assert "RuntimeError: synthetic boom" in body
