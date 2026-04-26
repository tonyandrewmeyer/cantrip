"""Real-time log streaming from Juju models.

Provides an async generator that tails ``juju debug-log`` output,
yielding log lines as they arrive.  This avoids the complexity of
connecting directly to the Juju controller WebSocket while still
providing real-time log delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil

log = logging.getLogger(__name__)

# Bounded wait for a terminated subprocess to actually exit before we
# escalate to SIGKILL — keeps :func:`stream_lines` from hanging
# indefinitely on a wedged ``juju debug-log`` process.
_TERMINATE_GRACE_SECONDS = 5.0


def juju_available() -> bool:
    """Check whether the ``juju`` CLI is installed."""
    return shutil.which("juju") is not None


async def tail_logs(
    model: str,
    *,
    level: str = "WARNING",
    unit: str | None = None,
    lines: int = 50,
) -> asyncio.subprocess.Process:
    """Start a ``juju debug-log --tail`` subprocess.

    Returns the process handle.  The caller should read from
    ``proc.stdout`` and eventually call ``proc.terminate()``.
    """
    cmd = [
        "juju",
        "debug-log",
        "--model",
        model,
        "--tail",
        "-n",
        str(lines),
        "--level",
        level,
    ]
    if unit:
        cmd.extend(["--include", unit])

    # ``stderr`` is captured to ``DEVNULL`` rather than ``PIPE``: nothing
    # in this module reads it, and a noisy juju binary (controller
    # warnings, deprecation notices) can fill the pipe buffer and
    # deadlock the subprocess waiting for someone to drain it.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return proc


async def stream_lines(
    model: str,
    *,
    level: str = "WARNING",
    unit: str | None = None,
    lines: int = 50,
    max_lines: int = 500,
):
    """Async generator that yields log lines from ``juju debug-log --tail``.

    Yields at most *max_lines* lines before stopping.  The caller can
    also break out of the loop early.  The subprocess is cleaned up
    automatically.
    """
    if not juju_available():
        return

    proc = await tail_logs(model, level=level, unit=unit, lines=lines)
    count = 0
    try:
        assert proc.stdout is not None  # noqa: S101
        while count < max_lines:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=30.0,
                )
            except TimeoutError:
                break
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n")
            count += 1
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        except TimeoutError:
            # SIGTERM didn't take — escalate so we don't leak the
            # subprocess (and don't wedge whatever started us).
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
