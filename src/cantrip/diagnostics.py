"""Centralised "where did the crash go?" log for in-session errors.

UI surfaces (CLI / TUI / Web) should never leak a Python traceback
into the chat window — that's noise for the user and unactionable
without context.  But losing the traceback is just as bad: the
developer has nothing to debug from.

:func:`report_internal_error` splits the difference.  It writes the
full traceback (with a timestamp and a free-form context label) to a
single append-only file under ``$XDG_STATE_HOME/cantrip/`` and
returns a short, user-facing string that names the log path and asks
the user to report it.

Usage::

    try:
        do_thing()
    except Exception as exc:  # noqa: BLE001 — caller wants to surface, not crash
        return diagnostics.report_internal_error("/map", exc)

Pairs naturally with ``log.warning(..., exc_info=True)`` for
operators tailing logs in real time — this module is the
*persistent* record the user can hand to a developer after the fact.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import pathlib
import shlex
import threading
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)

#: Filename for the rolling diagnostics log under
#: ``$XDG_STATE_HOME/cantrip/``.  One file per host (not per
#: charm) so a developer asking "where's the log?" has one
#: answer regardless of which charm was active.
_LOG_FILENAME = "diagnostics.log"

#: Soft cap to keep the file from growing unbounded across long-lived
#: installations.  When an entry would push the log past this size,
#: ``report_internal_error`` truncates the head before appending so
#: the most recent failures stay visible.  Picked at 512 KiB — small
#: enough to grep / paste, large enough to hold ~hundreds of entries.
_MAX_LOG_BYTES = 512 * 1024

# Prevent interleaved appends when two surfaces (e.g. agent loop and
# slash command) hit ``report_internal_error`` simultaneously.
_LOCK = threading.Lock()


def log_path() -> pathlib.Path:
    """Return the diagnostics log path, honouring ``XDG_STATE_HOME``.

    Falls back to the XDG-spec default ``~/.local/state/cantrip/``
    when the env var isn't set.  The directory is *not* created here;
    that happens lazily on first write so a session that never
    logs anything leaves no footprint.
    """
    xdg = os.environ.get("XDG_STATE_HOME")
    base = pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".local" / "state"
    return base / "cantrip" / _LOG_FILENAME


def report_internal_error(context: str, exc: BaseException) -> str:
    """Persist *exc*'s traceback under *context* and return a chat-safe string.

    The returned string names the log path and asks the user to
    report the issue.  Designed so a slash command or background
    task can do ``return diagnostics.report_internal_error(...)``
    and never leak a stack into the chat.

    Best-effort: if the file write itself fails (read-only home,
    full disk), we still log the original exception via the
    standard logger and return the same friendly message — the
    user shouldn't see a second-order failure either.
    """
    path = log_path()
    timestamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    body = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    entry = f"\n{'=' * 72}\n{timestamp}  {context}\n{'-' * 72}\n{body}"

    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _trim_if_needed(path, len(entry.encode("utf-8")))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError as write_exc:
            # Persisting the diagnostic itself failed — log to the
            # standard logger so an operator tailing stderr still
            # sees something, but don't propagate.  The user-facing
            # string still names the path so they can report
            # "diagnostics.log isn't writable" if that's the issue.
            log.warning(
                "diagnostics: cannot write to %s (%s); original error follows",
                path,
                write_exc,
            )
            log.warning("diagnostics: %s — %s", context, exc, exc_info=exc)

    return (
        f"Sorry, something went wrong handling `{context}`.  "
        f"The full traceback was written to `{path}` — please share "
        f"that file when reporting the issue."
    )


def report_command_crash(
    *,
    context: str,
    cmd: Sequence[str] | str,
    returncode: int,
    stdout: str,
    stderr: str,
    cwd: str | pathlib.Path | None = None,
    extra: dict[str, str] | None = None,
) -> pathlib.Path:
    """Persist a crash-shaped subprocess failure for upstream reporting.

    Used when a subprocess exits with a status that looks like an
    internal error (juju panic, unknown exit code) and the verbatim
    command, stdout, and stderr are worth keeping for the user to
    file an upstream bug.  Unlike :func:`report_internal_error`, no
    Python exception is involved — just the four pieces of evidence
    an upstream tracker will ask for.

    Returns the log path so the caller can mention it in the
    user-facing error message.  Best-effort: write failures are
    swallowed (the caller already has a useful error to surface).
    """
    path = log_path()
    timestamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    cmd_text = cmd if isinstance(cmd, str) else " ".join(shlex.quote(str(part)) for part in cmd)

    lines = [
        "",
        "=" * 72,
        f"{timestamp}  {context}  (exit {returncode})",
        "-" * 72,
        f"command: {cmd_text}",
    ]
    if cwd is not None:
        lines.append(f"cwd: {cwd}")
    if extra:
        for key, value in extra.items():
            lines.append(f"{key}: {value}")
    lines.append("--- stdout ---")
    lines.append(stdout if stdout else "(empty)")
    lines.append("--- stderr ---")
    lines.append(stderr if stderr else "(empty)")
    entry = "\n".join(lines) + "\n"

    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _trim_if_needed(path, len(entry.encode("utf-8")))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError as write_exc:
            log.warning(
                "diagnostics: cannot write crash dump to %s (%s)",
                path,
                write_exc,
            )

    return path


def _trim_if_needed(path: pathlib.Path, incoming_bytes: int) -> None:
    """Drop the head of the log so it stays under the soft cap.

    Keeps the most recent half of the file when trimming kicks in —
    the most recent crashes are almost always the most useful ones.
    No-op when the file doesn't exist yet or is already small enough
    to take the new entry.
    """
    try:
        current_bytes = path.stat().st_size
    except OSError:
        return
    if current_bytes + incoming_bytes <= _MAX_LOG_BYTES:
        return
    try:
        existing = path.read_bytes()
    except OSError:
        return
    keep = existing[len(existing) // 2 :]
    # Try to align to the next entry boundary so the kept portion
    # starts cleanly.  Falls back to the raw split if we can't find
    # one — readability matters less than not losing data.
    sep = b"\n" + b"=" * 72 + b"\n"
    boundary = keep.find(sep)
    if boundary >= 0:
        keep = keep[boundary:]
    # Worst case: the next append goes onto an oversized file.  That's
    # bounded by the cap, not unbounded growth, because the next call
    # will try again.
    with contextlib.suppress(OSError):
        path.write_bytes(keep)
