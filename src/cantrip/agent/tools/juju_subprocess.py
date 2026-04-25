"""Shared helpers for running Juju CLI commands via subprocess.

Several tool modules (acceptance, chaos, scaling, upgrade) need to invoke
``juju`` as a subprocess.  This module provides the common helpers so the
pattern is defined once.
"""

import functools
import shutil
import subprocess

# Default timeout for juju subprocess calls (seconds).
JUJU_SUBPROCESS_TIMEOUT = 60

# Stderr substrings that suggest the juju binary itself entered a
# crash path rather than reporting a normal CLI failure.  ``cmd_run.go``
# is part of juju's internal command runner and only appears in stderr
# when something has gone wrong inside the binary; ``panic:`` /
# ``runtime error:`` / ``goroutine `` are Go runtime crash markers.
# Used by :func:`looks_like_juju_crash` to decide whether to write a
# repro dump to ``diagnostics.log``.
_CRASH_STDERR_NEEDLES: tuple[str, ...] = (
    "panic:",
    "runtime error:",
    "fatal error:",
    "cmd_run.go",
    "goroutine ",
)


def looks_like_juju_crash(returncode: int, stderr: str) -> bool:
    """Return ``True`` if a juju exit looks like an internal error.

    Standard juju exit codes are 0 (success), 1 (general error) and
    2 (usage error).  Anything else is treated as crash-shaped.  Even
    for codes 1 and 2, stderr containing Go runtime / cmd_run.go
    markers also counts — juju occasionally panics through its
    standard error path.
    """
    if returncode == 0:
        return False
    if returncode not in (1, 2):
        return True
    lower = stderr.lower()
    return any(needle in lower for needle in _CRASH_STDERR_NEEDLES)


@functools.lru_cache(maxsize=1)
def juju_version() -> str | None:
    """Return the juju CLI version string, or ``None`` if unavailable.

    Cached so repeated crash dumps don't fork a subprocess each time.
    Best-effort: any failure (juju missing, hangs past 5 s, non-zero
    exit) returns ``None`` and the crash dump skips the version line.
    """
    try:
        result = subprocess.run(
            ["juju", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def juju_available() -> bool:
    """Check whether the juju CLI is installed."""
    return shutil.which("juju") is not None


def run_juju(
    args: list[str],
    model: str | None = None,
    *,
    timeout: int = JUJU_SUBPROCESS_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a juju CLI command and return the completed process.

    Args:
        args: Command arguments after ``juju`` (e.g. ``["status", "--format", "json"]``).
        model: Optional model name passed via ``--model``.
        timeout: Subprocess timeout in seconds.

    Side effect: when juju exits with a crash-shaped status (see
    :func:`looks_like_juju_crash`), the verbatim cmd / stdout /
    stderr are appended to ``diagnostics.log`` so the user has full
    repro material to file an upstream bug — even after the
    conversation context rolls over.
    """
    cmd = ["juju"] + args
    if model:
        cmd.extend(["--model", model])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if looks_like_juju_crash(result.returncode, result.stderr or ""):
        # Late import keeps ``cantrip.diagnostics`` out of the
        # import-time graph for tools that never crash.
        from cantrip import diagnostics

        extra: dict[str, str] = {}
        version = juju_version()
        if version:
            extra["juju_version"] = version
        diagnostics.report_command_crash(
            context="juju_subprocess:run_juju",
            cmd=cmd,
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            extra=extra or None,
        )
    return result


def wait_for_app(app: str, model: str | None, timeout: int) -> bool:
    """Wait for all units of an application to reach active/idle.

    Uses ``juju wait-for application`` with a generous subprocess timeout
    (the juju timeout + 30 s buffer) so the CLI can report its own errors.
    """
    cmd = ["juju", "wait-for", "application", app, "--timeout", f"{timeout}s"]
    if model:
        cmd.extend(["--model", model])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
