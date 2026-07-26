"""Tests for ``cantrip.diagnostics`` — internal-error log + chat string."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip import diagnostics

if TYPE_CHECKING:
    import pathlib

    import pytest


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
    def test_honours_xdg_state_home(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
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
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
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
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # XDG_STATE_HOME points at a directory that doesn't exist yet.
        target = tmp_path / "nested" / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(target))
        diagnostics.report_internal_error("/map", _raise_and_capture())
        assert (target / "cantrip" / "diagnostics.log").exists()

    def test_returns_chat_string_even_when_log_write_fails(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
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


class TestReportCommandCrash:
    """Tests for ``report_command_crash`` — non-exception subprocess dumps."""

    def test_writes_full_dump_with_extra(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

        path = diagnostics.report_command_crash(
            context="run_command:juju",
            cmd=["juju", "status", "--model", "foo"],
            returncode=46,
            stdout="some stdout",
            stderr="2026/04/26 01:37:44 cmd_run.go:178: oh no",
            cwd="/tmp/charm",
            extra={"juju_version": "juju 3.6.0"},
        )

        assert path == tmp_path / "cantrip" / "diagnostics.log"
        body = path.read_text(encoding="utf-8")
        assert "run_command:juju" in body
        assert "exit 46" in body
        assert "juju status --model foo" in body
        assert "cwd: /tmp/charm" in body
        assert "juju_version: juju 3.6.0" in body
        assert "some stdout" in body
        assert "cmd_run.go" in body

    def test_accepts_string_cmd(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        diagnostics.report_command_crash(
            context="x",
            cmd="juju status",
            returncode=99,
            stdout="",
            stderr="",
        )
        body = (tmp_path / "cantrip" / "diagnostics.log").read_text(encoding="utf-8")
        assert "command: juju status" in body

    def test_empty_streams_marked(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        diagnostics.report_command_crash(
            context="x",
            cmd=["juju"],
            returncode=99,
            stdout="",
            stderr="",
        )
        body = (tmp_path / "cantrip" / "diagnostics.log").read_text(encoding="utf-8")
        assert "--- stdout ---\n(empty)" in body
        assert "--- stderr ---\n(empty)" in body

    def test_swallows_write_failure(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Putting cantrip/ underneath a *file* makes mkdir raise
        # FileExistsError — exercises the OSError swallow path.  Dumps
        # must never propagate (the caller already has an error to
        # surface from the subprocess result).
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")
        monkeypatch.setenv("XDG_STATE_HOME", str(blocked))
        # Returns the (non-existent) path without raising.
        path = diagnostics.report_command_crash(
            context="x",
            cmd=["juju"],
            returncode=99,
            stdout="",
            stderr="",
        )
        assert "diagnostics.log" in str(path)


class TestLogSizeBounded:
    def test_log_size_bounded(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
