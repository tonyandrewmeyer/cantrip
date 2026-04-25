"""Shared helpers for running Juju CLI commands via Jubilant.

Several tool modules (acceptance, chaos, scaling, upgrade) need to invoke
``juju`` to perform operations Jubilant doesn't expose as a typed method
(``status --format json``, ``wait-for application``, ``debug-log``,
``scale-application``, ``remove-relation`` ...).  This module funnels
all of them through :meth:`jubilant.Juju.cli` so we never spawn a raw
``juju`` subprocess from within Cantrip's sandboxed runner — that path
trips snap's ``[Process 1 is a manager process, refusing.]`` dbus error
on systems where the juju snap is installed.
"""

import functools
import shutil
import subprocess

import jubilant

# Default timeout for juju subprocess calls (seconds).
#
# Jubilant's ``cli()`` does not enforce a Python-level timeout — most
# juju subcommands return promptly, and the few that don't (``wait-for
# application``, ``run``) take their own ``--timeout`` flag.  This
# constant is preserved so callers that pass ``timeout=`` keep working,
# but it is no longer applied at the Python boundary.
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
    Best-effort: any failure (juju missing, non-zero exit) returns
    ``None`` and the crash dump skips the version line.
    """
    try:
        text = jubilant.Juju().cli("version", include_model=False).strip()
    except (jubilant.CLIError, FileNotFoundError, OSError):
        return None
    return text or None


def juju_available() -> bool:
    """Check whether the juju CLI is installed."""
    return shutil.which("juju") is not None


def run_juju(
    args: list[str],
    model: str | None = None,
    *,
    timeout: int = JUJU_SUBPROCESS_TIMEOUT,  # noqa: ARG001 — preserved for caller compat.
) -> subprocess.CompletedProcess[str]:
    """Run a juju CLI command via Jubilant and return a CompletedProcess.

    Args:
        args: Command arguments after ``juju`` (e.g. ``["status", "--format", "json"]``).
        model: Optional model name; injected by Jubilant as ``--model``.
        timeout: Accepted for backward compatibility but not enforced —
            see module docstring.

    Side effect: when juju exits with a crash-shaped status (see
    :func:`looks_like_juju_crash`), the verbatim cmd / stdout /
    stderr are appended to ``diagnostics.log`` so the user has full
    repro material to file an upstream bug — even after the
    conversation context rolls over.
    """
    juju = jubilant.Juju(model=model) if model else jubilant.Juju()
    cmd_for_log = ["juju", *args]
    if model:
        cmd_for_log.extend(["--model", model])

    try:
        stdout = juju.cli(*args, include_model=bool(model))
    except jubilant.CLIError as exc:
        result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=exc.cmd or cmd_for_log,
            returncode=exc.returncode,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )
    else:
        return subprocess.CompletedProcess(
            args=cmd_for_log,
            returncode=0,
            stdout=stdout,
            stderr="",
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
            cmd=list(result.args) if isinstance(result.args, list) else cmd_for_log,
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            extra=extra or None,
        )
    return result


def wait_for_app(app: str, model: str | None, timeout: int) -> bool:
    """Wait for all units of an application to reach active/idle.

    Uses ``juju wait-for application`` (via Jubilant's ``cli()``) with
    its own ``--timeout`` flag — juju enforces the deadline itself.
    """
    juju = jubilant.Juju(model=model) if model else jubilant.Juju()
    try:
        juju.cli(
            "wait-for",
            "application",
            app,
            "--timeout",
            f"{timeout}s",
            include_model=bool(model),
        )
    except (jubilant.CLIError, FileNotFoundError, OSError):
        return False
    return True
