"""Tests for ``cantrip.agent.tools.juju_subprocess`` — crash heuristic + run_juju dump."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools import juju_subprocess


class TestLooksLikeJujuCrash:
    def test_zero_returncode_is_never_crash(self) -> None:
        assert juju_subprocess.looks_like_juju_crash(0, "anything goes") is False

    def test_unusual_returncode_is_crash(self) -> None:
        # Anything outside {0, 1, 2} counts.
        assert juju_subprocess.looks_like_juju_crash(46, "") is True
        assert juju_subprocess.looks_like_juju_crash(139, "") is True

    def test_routine_error_exit_one_is_not_crash(self) -> None:
        assert juju_subprocess.looks_like_juju_crash(1, "ERROR model not found") is False

    @pytest.mark.parametrize(
        "needle",
        ["panic:", "runtime error:", "fatal error:", "cmd_run.go", "goroutine "],
    )
    def test_crash_marker_in_stderr_promotes_exit_one(self, needle: str) -> None:
        # Even with returncode 1, a panic-like stderr counts as crash-shaped.
        stderr = f"some line\n{needle} oh no\nnext line"
        assert juju_subprocess.looks_like_juju_crash(1, stderr) is True

    def test_marker_match_is_case_insensitive(self) -> None:
        assert juju_subprocess.looks_like_juju_crash(1, "PANIC: BOOM") is True


class TestJujuVersion:
    def setup_method(self) -> None:
        # Each test starts with a clean cache so the mocked subprocess
        # actually fires.
        juju_subprocess.juju_version.cache_clear()

    def test_returns_stripped_stdout(self) -> None:
        completed = mock.MagicMock()
        completed.returncode = 0
        completed.stdout = "3.6.0-genericlinux-amd64\n"
        with mock.patch(
            "cantrip.agent.tools.juju_subprocess.subprocess.run",
            return_value=completed,
        ):
            assert juju_subprocess.juju_version() == "3.6.0-genericlinux-amd64"

    def test_returns_none_when_juju_missing(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.juju_subprocess.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert juju_subprocess.juju_version() is None

    def test_returns_none_on_nonzero_exit(self) -> None:
        completed = mock.MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        with mock.patch(
            "cantrip.agent.tools.juju_subprocess.subprocess.run",
            return_value=completed,
        ):
            assert juju_subprocess.juju_version() is None


class TestRunJujuCrashDump:
    """``run_juju`` dumps repro material when juju exits crash-shaped."""

    def setup_method(self) -> None:
        juju_subprocess.juju_version.cache_clear()

    def test_crash_shaped_exit_writes_dump(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setattr(
            "cantrip.agent.tools.juju_subprocess.juju_version",
            lambda: "juju 3.6.0",
        )

        completed = mock.MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 46
        completed.stdout = ""
        completed.stderr = "2026/04/26 01:37:44 cmd_run.go:178: oh no\n"

        with mock.patch(
            "cantrip.agent.tools.juju_subprocess.subprocess.run",
            return_value=completed,
        ):
            result = juju_subprocess.run_juju(["status"], model="foo")

        assert result.returncode == 46
        log_file = tmp_path / "cantrip" / "diagnostics.log"
        assert log_file.exists()
        body = log_file.read_text(encoding="utf-8")
        assert "juju_subprocess:run_juju" in body
        assert "juju status --model foo" in body
        assert "exit 46" in body
        assert "cmd_run.go" in body
        assert "juju 3.6.0" in body

    def test_normal_exit_one_does_not_dump(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

        completed = mock.MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "ERROR model not found"

        with mock.patch(
            "cantrip.agent.tools.juju_subprocess.subprocess.run",
            return_value=completed,
        ):
            juju_subprocess.run_juju(["status"])

        assert not (tmp_path / "cantrip" / "diagnostics.log").exists()
