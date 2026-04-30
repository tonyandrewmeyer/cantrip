"""Tests for :mod:`cantrip.notifications`."""

from __future__ import annotations

import io
import subprocess
from unittest.mock import MagicMock

import pytest

from cantrip import notifications
from cantrip.ui import events as ui_events


def _event(status: str, task_id: str = "t1", title: str = "Build charm") -> ui_events.Event:
    return ui_events.task_updated(
        task_id=task_id,
        title=title,
        status=status,
        category="build",
    )


class TestParseMode:
    def test_none_is_off(self) -> None:
        assert notifications.parse_mode(None) is notifications.NotifyMode.OFF

    def test_empty_is_off(self) -> None:
        assert notifications.parse_mode("") is notifications.NotifyMode.OFF

    def test_known_modes_roundtrip(self) -> None:
        for name in ("off", "bell", "desktop", "both"):
            assert notifications.parse_mode(name) is notifications.NotifyMode(name)

    def test_whitespace_and_case_tolerated(self) -> None:
        assert notifications.parse_mode("  BELL  ") is notifications.NotifyMode.BELL

    def test_unknown_mode_falls_back_to_off(self) -> None:
        assert notifications.parse_mode("sirens") is notifications.NotifyMode.OFF


class TestBellMode:
    def test_done_emits_single_bell(self) -> None:
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BELL,
            stderr=buf,
        )
        notifier.handle(_event("done"))
        assert buf.getvalue() == "\a"

    def test_failed_emits_single_bell(self) -> None:
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BELL,
            stderr=buf,
        )
        notifier.handle(_event("failed"))
        assert buf.getvalue() == "\a"

    def test_non_terminal_statuses_are_silent(self) -> None:
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BELL,
            stderr=buf,
        )
        for status in ("pending", "active", "blocked"):
            notifier.handle(_event(status))
        assert buf.getvalue() == ""

    def test_same_task_id_deduped(self) -> None:
        """Repeated TASK_UPDATED for the same id+terminal status only beeps once."""
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BELL,
            stderr=buf,
        )
        notifier.handle(_event("done"))
        notifier.handle(_event("done"))
        assert buf.getvalue() == "\a"

    def test_distinct_task_ids_each_beep(self) -> None:
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BELL,
            stderr=buf,
        )
        notifier.handle(_event("done", task_id="t1"))
        notifier.handle(_event("failed", task_id="t2"))
        assert buf.getvalue() == "\a\a"

    def test_off_mode_emits_nothing(self) -> None:
        buf = io.StringIO()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.OFF,
            stderr=buf,
        )
        notifier.handle(_event("done"))
        assert buf.getvalue() == ""


class TestDesktopMode:
    def test_done_invokes_notify_send_with_title(self) -> None:
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.DESKTOP,
            which=lambda _: "/usr/bin/notify-send",
            runner=runner,
        )
        notifier.handle(_event("done", title="Deploy charm"))
        runner.assert_called_once()
        argv = runner.call_args.args[0]
        assert argv[0] == "notify-send"
        assert "completed" in argv[1]
        assert argv[2] == "Deploy charm"

    def test_failed_uses_failed_summary(self) -> None:
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.DESKTOP,
            which=lambda _: "/usr/bin/notify-send",
            runner=runner,
        )
        notifier.handle(_event("failed", title="Run tests"))
        argv = runner.call_args.args[0]
        assert "failed" in argv[1]

    def test_missing_notify_send_is_silent(self) -> None:
        runner = MagicMock()
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.DESKTOP,
            which=lambda _: None,
            runner=runner,
        )
        notifier.handle(_event("done"))
        runner.assert_not_called()

    def test_oserror_from_runner_is_swallowed(self) -> None:
        runner = MagicMock(side_effect=OSError("no such file"))
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.DESKTOP,
            which=lambda _: "/usr/bin/notify-send",
            runner=runner,
        )
        # Must not raise — users shouldn't see tracebacks from a notifier.
        notifier.handle(_event("done"))


class TestBothMode:
    def test_both_fires_bell_and_desktop_each_once(self) -> None:
        buf = io.StringIO()
        runner = MagicMock(return_value=subprocess.CompletedProcess([], 0))
        notifier = notifications.TaskNotifier(
            mode=notifications.NotifyMode.BOTH,
            stderr=buf,
            which=lambda _: "/usr/bin/notify-send",
            runner=runner,
        )
        notifier.handle(_event("done"))
        assert buf.getvalue() == "\a"
        assert runner.call_count == 1


class TestInstall:
    @pytest.fixture
    def bus(self) -> ui_events.EventBus:
        return ui_events.EventBus()

    def test_off_mode_skips_subscription(self, bus: ui_events.EventBus) -> None:
        result = notifications.install(bus, mode=notifications.NotifyMode.OFF)
        assert result is None
        # No subscribers registered for TASK_UPDATED.
        assert ui_events.EventType.TASK_UPDATED not in bus._subscribers

    def test_reads_env_var_by_default(
        self, bus: ui_events.EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_NOTIFY", "bell")
        result = notifications.install(bus)
        assert isinstance(result, notifications.TaskNotifier)
        assert result.mode is notifications.NotifyMode.BELL

    def test_env_var_unset_means_off(
        self, bus: ui_events.EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CANTRIP_NOTIFY", raising=False)
        assert notifications.install(bus) is None

    def test_subscriber_fires_on_bus_publish(
        self, bus: ui_events.EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Installed notifier actually receives events from the bus."""
        buf = io.StringIO()
        monkeypatch.setenv("CANTRIP_NOTIFY", "bell")
        notifier = notifications.install(bus)
        assert notifier is not None
        notifier.stderr = buf
        bus.publish(_event("done", task_id="integration-1"))
        assert buf.getvalue() == "\a"
