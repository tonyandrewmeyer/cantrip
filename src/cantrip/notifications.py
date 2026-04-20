"""Task-completion notifications — terminal bell and desktop popups.

Opt-in via the ``CANTRIP_NOTIFY`` environment variable:

* ``off`` (default) — no notifications.
* ``bell`` — write ``\\a`` to stderr on terminal-state transitions.
* ``desktop`` — shell out to ``notify-send`` on terminal transitions.
* ``both`` — do both.

A :class:`TaskNotifier` subscribes to ``TASK_UPDATED`` events on the
shared event bus and fires at most once per task, when it first reaches
``done`` or ``failed``.  Non-terminal status changes (``active``,
``blocked``) are ignored.  ``notify-send`` is detected on the PATH at
first use; if it is missing the desktop path silently degrades to a
no-op so users on non-Linux hosts see no errors.
"""

from __future__ import annotations

import enum
import logging
import os
import shutil
import subprocess
import sys
import typing
from dataclasses import dataclass, field

from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)

ENV_VAR = "CANTRIP_NOTIFY"

_TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "failed"})


class NotifyMode(enum.StrEnum):
    """Notification delivery channels a user can opt into."""

    OFF = "off"
    BELL = "bell"
    DESKTOP = "desktop"
    BOTH = "both"


def parse_mode(value: str | None) -> NotifyMode:
    """Resolve a user-supplied string to a :class:`NotifyMode`.

    Returns :attr:`NotifyMode.OFF` for ``None``, empty strings, or any
    value the enum doesn't recognise — a typo in ``CANTRIP_NOTIFY``
    must not be louder than disabling the feature.
    """
    if not value:
        return NotifyMode.OFF
    try:
        return NotifyMode(value.strip().lower())
    except ValueError:
        log.warning("Invalid %s=%r — defaulting to off", ENV_VAR, value)
        return NotifyMode.OFF


@dataclass
class TaskNotifier:
    """Fire notifications when tasks reach a terminal state.

    The notifier dedupes by task id so duplicated ``TASK_UPDATED`` events
    (e.g. from a snapshot replay after reconnect) don't stack beeps.
    """

    mode: NotifyMode = NotifyMode.OFF
    stderr: typing.TextIO = field(default_factory=lambda: sys.stderr)
    which: typing.Callable[[str], str | None] = shutil.which
    runner: typing.Callable[..., subprocess.CompletedProcess] = subprocess.run
    _seen: set[str] = field(default_factory=set)
    _desktop_available: bool | None = None

    def handle(self, event: ui_events.Event) -> None:
        """Subscribe this to :data:`EventType.TASK_UPDATED` on the bus."""
        if self.mode is NotifyMode.OFF:
            return
        payload = event.payload
        status = str(payload.get("status") or "")
        if status not in _TERMINAL_STATUSES:
            return
        task_id = payload.get("id")
        if not task_id or task_id in self._seen:
            return
        self._seen.add(str(task_id))
        title = str(payload.get("title") or task_id)
        self._emit(status, title)

    def _emit(self, status: str, title: str) -> None:
        if self.mode in (NotifyMode.BELL, NotifyMode.BOTH):
            self._emit_bell()
        if self.mode in (NotifyMode.DESKTOP, NotifyMode.BOTH):
            self._emit_desktop(status, title)

    def _emit_bell(self) -> None:
        try:
            self.stderr.write("\a")
            self.stderr.flush()
        except OSError as exc:
            log.debug("Bell write failed: %s", exc)

    def _emit_desktop(self, status: str, title: str) -> None:
        if self._desktop_available is None:
            self._desktop_available = self.which("notify-send") is not None
        if not self._desktop_available:
            return
        verb = "completed" if status == "done" else "failed"
        summary = f"Cantrip task {verb}"
        try:
            self.runner(
                ["notify-send", summary, title],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.debug("notify-send failed: %s", exc)


def install(
    event_bus: ui_events.EventBus,
    *,
    mode: NotifyMode | None = None,
) -> TaskNotifier | None:
    """Wire up a :class:`TaskNotifier` on the shared event bus.

    ``mode`` defaults to ``parse_mode(os.environ[CANTRIP_NOTIFY])`` so
    surfaces can just call ``install(bus)`` after binding the loop.
    Returns ``None`` — with no subscription created — when the resolved
    mode is :attr:`NotifyMode.OFF`.
    """
    if mode is None:
        mode = parse_mode(os.environ.get(ENV_VAR))
    if mode is NotifyMode.OFF:
        return None
    notifier = TaskNotifier(mode=mode)
    event_bus.subscribe(ui_events.EventType.TASK_UPDATED, notifier.handle)
    return notifier


__all__ = [
    "ENV_VAR",
    "NotifyMode",
    "TaskNotifier",
    "install",
    "parse_mode",
]
