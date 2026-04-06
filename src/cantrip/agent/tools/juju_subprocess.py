"""Shared helpers for running Juju CLI commands via subprocess.

Several tool modules (acceptance, chaos, scaling, upgrade) need to invoke
``juju`` as a subprocess.  This module provides the common helpers so the
pattern is defined once.
"""

import subprocess

# Default timeout for juju subprocess calls (seconds).
JUJU_SUBPROCESS_TIMEOUT = 60


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
    """
    cmd = ["juju"] + args
    if model:
        cmd.extend(["--model", model])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
