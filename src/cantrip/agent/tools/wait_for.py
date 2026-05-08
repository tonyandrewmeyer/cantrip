"""Block on a typed predicate until it flips or a deadline passes.

Phase 100.1: a single tool with a closed predicate set.  The agent
reaches for ``wait_for`` instead of scripting ``until ...; do sleep``
loops through ``run_command`` or burning a turn on a long-timeout
subprocess.  Predicates are tagged so the schema is enumerable; no
free-form shell text reaches the worker.

Streaming-style (per-line) waits are deliberately out of scope —
revisit only when a real use case shows up.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
import socket
import subprocess
import time
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


# Hard upper bound on a single ``wait_for`` call.  Past this, the
# scheduler / executor pause is the right primitive — not a longer
# wait.  See ``ROADMAP.md`` Phase 99.1 for the cross-turn case.
_MAX_TIMEOUT_SECONDS = 1800

# Closed argv whitelist for ``command_exits_zero``.  Mirrors the spirit
# of ``run_command``'s allowlist but is intentionally narrower — wait
# loops should only poll a handful of well-known status checks.  ``juju``
# is included here even though ``run_command``'s allowlist excludes it,
# because we run argv directly (no PID-namespace sandbox) so the snap
# dbus failure mode doesn't apply.
_COMMAND_ALLOWLIST: frozenset[str] = frozenset({"charmcraft", "juju", "make", "pytest", "test"})

# Per-predicate poll cadence in seconds.  Picked at registration time,
# never tunable from the model — a single typed knob is the whole point
# of this tool versus a generic shell loop.
_POLL_CADENCE: dict[str, float] = {
    "file_exists": 0.5,
    "file_absent": 0.5,
    "process_exited": 0.5,
    "port_open": 0.5,
    "command_exits_zero": 5.0,
    # juju_app_active_idle delegates to ``juju wait-for`` via its
    # own --timeout flag; no Python-side polling.
    "juju_app_active_idle": 0.0,
}

_PREDICATE_NAMES: tuple[str, ...] = tuple(_POLL_CADENCE)

# Per-iteration timeout for subprocess-based predicates.  Short enough
# that the outer poll cadence drives the rhythm, long enough that the
# command actually has a chance to finish.
_COMMAND_PROBE_TIMEOUT = 30


class WaitForTool(Tool):
    """Block until a typed predicate flips or the deadline passes."""

    @property
    def name(self) -> str:
        return "wait_for"

    @property
    def description(self) -> str:
        return (
            "Block until a typed condition is true, then return.  "
            "Use this instead of scripting ``until ...; do sleep`` loops "
            "through run_command, or hanging a turn on a long-timeout "
            "subprocess.  Predicates: "
            "``file_exists`` (path becomes readable), "
            "``file_absent`` (path goes away), "
            "``process_exited`` (PID terminates), "
            "``port_open`` (TCP connect succeeds on host:port), "
            "``command_exits_zero`` (whitelisted argv returns 0), "
            "``juju_app_active_idle`` (all units of an application reach "
            "active/idle).  ``timeout_seconds`` is required and capped "
            f"at {_MAX_TIMEOUT_SECONDS}."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "predicate": {
                    "type": "string",
                    "enum": list(_PREDICATE_NAMES),
                    "description": "Which condition to wait on.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Maximum seconds to wait before returning with "
                        f"timed_out=true.  Capped at {_MAX_TIMEOUT_SECONDS}."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Path for ``file_exists`` / ``file_absent``.",
                },
                "pid": {
                    "type": "integer",
                    "description": "PID for ``process_exited``.",
                },
                "host": {
                    "type": "string",
                    "description": "Host for ``port_open`` (default ``127.0.0.1``).",
                },
                "port": {
                    "type": "integer",
                    "description": "Port for ``port_open``.",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Argv list for ``command_exits_zero``.  Base "
                        "command (first item) must be one of: "
                        + ", ".join(sorted(_COMMAND_ALLOWLIST))
                        + ".  No shell pipelines, no quoting tricks."
                    ),
                },
                "app": {
                    "type": "string",
                    "description": "Application name for ``juju_app_active_idle``.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Optional Juju model for ``juju_app_active_idle``; "
                        "defaults to the currently switched-to model."
                    ),
                },
            },
            "required": ["predicate", "timeout_seconds"],
        }

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        predicate = arguments.get("predicate")
        if predicate == "file_exists":
            return f"Waiting for {arguments.get('path', '?')} to appear…"
        if predicate == "file_absent":
            return f"Waiting for {arguments.get('path', '?')} to disappear…"
        if predicate == "process_exited":
            return f"Waiting for PID {arguments.get('pid', '?')} to exit…"
        if predicate == "port_open":
            host = arguments.get("host", "127.0.0.1")
            return f"Waiting for {host}:{arguments.get('port', '?')} to open…"
        if predicate == "command_exits_zero":
            cmd = arguments.get("command") or []
            label = " ".join(cmd) if cmd else "?"
            return f"Waiting for ``{label}`` to exit zero…"
        if predicate == "juju_app_active_idle":
            return f"Waiting for juju app {arguments.get('app', '?')} to reach active/idle…"
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        predicate = kwargs.get("predicate")
        if predicate not in _POLL_CADENCE:
            return ToolResult(
                success=False,
                output="",
                error=("Unknown predicate.  Valid: " + ", ".join(sorted(_PREDICATE_NAMES))),
            )

        raw_timeout = kwargs.get("timeout_seconds")
        if not isinstance(raw_timeout, int) or raw_timeout <= 0:
            return ToolResult(
                success=False,
                output="",
                error="timeout_seconds is required and must be a positive integer.",
            )
        timeout_seconds = min(raw_timeout, _MAX_TIMEOUT_SECONDS)

        started = time.monotonic()
        if predicate == "juju_app_active_idle":
            return await _wait_juju_app(kwargs, timeout_seconds, started)

        if predicate == "command_exits_zero":
            return await _wait_command_exits_zero(kwargs, timeout_seconds, started)

        cadence = _POLL_CADENCE[predicate]
        deadline = started + timeout_seconds
        probe = _PROBES[predicate]
        validation = probe.validate(kwargs)
        if validation is not None:
            return ToolResult(success=False, output="", error=validation)

        while True:
            ok, detail = probe.check(kwargs)
            if ok:
                elapsed = time.monotonic() - started
                summary = probe.success_caption(kwargs, elapsed, detail)
                return ToolResult(
                    success=True,
                    output=summary,
                    data={
                        "predicate": predicate,
                        "timed_out": False,
                        "elapsed_seconds": round(elapsed, 2),
                        **detail,
                    },
                    caption=summary,
                )
            if time.monotonic() >= deadline:
                elapsed = time.monotonic() - started
                summary = probe.timeout_caption(kwargs, elapsed)
                return ToolResult(
                    success=False,
                    output=summary,
                    error=summary,
                    data={
                        "predicate": predicate,
                        "timed_out": True,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                    caption=summary,
                )
            await asyncio.sleep(cadence)


# --- predicate probes ------------------------------------------------


class _Probe:
    """A single predicate's validate / check / caption handlers."""

    def __init__(
        self,
        validate,
        check,
        success_caption,
        timeout_caption,
    ) -> None:
        self.validate = validate
        self.check = check
        self.success_caption = success_caption
        self.timeout_caption = timeout_caption


def _validate_path(args: dict[str, Any]) -> str | None:
    if not isinstance(args.get("path"), str) or not args["path"]:
        return "predicate file_exists/file_absent requires ``path`` (non-empty string)."
    return None


def _check_file_exists(args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    return os.path.exists(args["path"]), {"path": args["path"]}


def _check_file_absent(args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    return (not os.path.exists(args["path"])), {"path": args["path"]}


def _validate_pid(args: dict[str, Any]) -> str | None:
    pid = args.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return "predicate process_exited requires ``pid`` (positive integer)."
    return None


def _check_process_exited(args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Return (exited, detail).

    Best-effort exit-code reporting: if the PID is one of our children,
    ``waitpid`` reports the exit code; otherwise ``kill(pid, 0)`` only
    tells us whether the process is gone.  Foreign-PID waits report
    ``exit_code=None`` rather than fabricating a value.
    """
    pid = args["pid"]
    detail: dict[str, Any] = {"pid": pid}
    try:
        wpid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        wpid, status = 0, 0
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            detail["exit_code"] = None
            return True, detail
        except PermissionError:
            # Process exists but is owned by another user — treat as
            # still running.  Only ``kill`` raises this; ``waitpid``
            # would have returned ECHILD instead.
            return False, detail
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                detail["exit_code"] = None
                return True, detail
            log.warning("kill(%s, 0) raised %s", pid, exc)
            return False, detail
        return False, detail

    if wpid == 0:
        return False, detail
    if os.WIFEXITED(status):
        detail["exit_code"] = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        detail["exit_code"] = -os.WTERMSIG(status)
    else:
        detail["exit_code"] = None
    return True, detail


def _validate_port(args: dict[str, Any]) -> str | None:
    port = args.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return "predicate port_open requires ``port`` (1..65535)."
    return None


def _check_port_open(args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    host = args.get("host") or "127.0.0.1"
    port = args["port"]
    detail = {"host": host, "port": port}
    try:
        with contextlib.closing(socket.create_connection((host, port), timeout=1.0)):
            return True, detail
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False, detail


_PROBES: dict[str, _Probe] = {
    "file_exists": _Probe(
        validate=_validate_path,
        check=_check_file_exists,
        success_caption=lambda args, elapsed, _detail: (
            f"{args['path']} appeared after {elapsed:.1f}s"
        ),
        timeout_caption=lambda args, elapsed: (
            f"{args['path']} did not appear within {elapsed:.0f}s"
        ),
    ),
    "file_absent": _Probe(
        validate=_validate_path,
        check=_check_file_absent,
        success_caption=lambda args, elapsed, _detail: (
            f"{args['path']} was removed after {elapsed:.1f}s"
        ),
        timeout_caption=lambda args, elapsed: (
            f"{args['path']} was still present after {elapsed:.0f}s"
        ),
    ),
    "process_exited": _Probe(
        validate=_validate_pid,
        check=_check_process_exited,
        success_caption=lambda args, elapsed, detail: (
            f"PID {args['pid']} exited after {elapsed:.1f}s"
            + (f" (exit {detail['exit_code']})" if detail.get("exit_code") is not None else "")
        ),
        timeout_caption=lambda args, elapsed: (
            f"PID {args['pid']} was still running after {elapsed:.0f}s"
        ),
    ),
    "port_open": _Probe(
        validate=_validate_port,
        check=_check_port_open,
        success_caption=lambda args, elapsed, _detail: (
            f"{args.get('host') or '127.0.0.1'}:{args['port']} opened after {elapsed:.1f}s"
        ),
        timeout_caption=lambda args, elapsed: (
            f"{args.get('host') or '127.0.0.1'}:{args['port']} did not open within {elapsed:.0f}s"
        ),
    ),
}


# --- juju and command predicates -------------------------------------


async def _wait_juju_app(args: dict[str, Any], timeout_seconds: int, started: float) -> ToolResult:
    """Delegate to ``juju wait-for application`` via Jubilant.

    ``juju`` enforces its own ``--timeout``; we don't poll in Python.
    A failure (timeout, missing binary, app not found) is surfaced as
    ``timed_out`` so the caller's recovery logic doesn't have to
    distinguish between juju exit codes.
    """
    app = args.get("app")
    if not isinstance(app, str) or not app:
        return ToolResult(
            success=False,
            output="",
            error="predicate juju_app_active_idle requires ``app`` (non-empty string).",
        )
    model = args.get("model") if isinstance(args.get("model"), str) else None

    # Late import keeps ``cantrip.agent.tools.wait_for`` import-cheap.
    from cantrip.agent.tools import juju_subprocess

    settled = await asyncio.to_thread(juju_subprocess.wait_for_app, app, model, timeout_seconds)
    elapsed = time.monotonic() - started
    target = f"{app}" + (f"@{model}" if model else "")
    if settled:
        summary = f"juju app {target} reached active/idle after {elapsed:.1f}s"
        return ToolResult(
            success=True,
            output=summary,
            data={
                "predicate": "juju_app_active_idle",
                "timed_out": False,
                "elapsed_seconds": round(elapsed, 2),
                "app": app,
                "model": model,
            },
            caption=summary,
        )
    summary = f"juju app {target} did not reach active/idle within {timeout_seconds}s"
    return ToolResult(
        success=False,
        output=summary,
        error=summary,
        data={
            "predicate": "juju_app_active_idle",
            "timed_out": True,
            "elapsed_seconds": round(elapsed, 2),
            "app": app,
            "model": model,
        },
        caption=summary,
    )


async def _wait_command_exits_zero(
    args: dict[str, Any], timeout_seconds: int, started: float
) -> ToolResult:
    """Loop a whitelisted argv until it exits zero or the deadline passes.

    Honours the same allow/deny machinery as ``run_command``: the base
    command must be on :data:`_COMMAND_ALLOWLIST`, and any destructive
    argv shape (``rm -rf``, ``git push --force``, ``git reset --hard``)
    requires ``approve_destructive: true`` from the composed policy
    stack — the same gate ``RunCommandTool`` consults.
    """
    raw = args.get("command")
    if not isinstance(raw, list) or not raw or not all(isinstance(p, str) for p in raw):
        return ToolResult(
            success=False,
            output="",
            error=(
                "predicate command_exits_zero requires ``command`` (non-empty list of strings)."
            ),
        )
    argv: list[str] = list(raw)
    base = argv[0]
    if base not in _COMMAND_ALLOWLIST:
        allowed = ", ".join(sorted(_COMMAND_ALLOWLIST))
        return ToolResult(
            success=False,
            output="",
            error=(
                f"command_exits_zero base {base!r} is not on the allowlist. Allowed: {allowed}"
            ),
        )

    # Late import: keeps the policy module out of import-time graphs
    # for sessions that never call wait_for.
    from cantrip.agent.policy import (
        compose_policies,
        destructive_command_check,
        discover_policies,
    )

    is_destructive, shape = destructive_command_check(argv)
    if is_destructive:
        composed = compose_policies(*discover_policies())
        if not composed.approve_destructive:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Destructive command shape {shape!r} requires "
                    "``approve_destructive: true`` in a policy file "
                    "(``~/.config/cantrip/policies/*.yaml`` or "
                    "``<charm>/cantrip.policies.yaml``)."
                ),
            )

    cadence = _POLL_CADENCE["command_exits_zero"]
    deadline = started + timeout_seconds
    label = " ".join(argv)
    last_returncode: int | None = None
    while True:
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=_COMMAND_PROBE_TIMEOUT,
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"Command not found: {base}",
            )
        except subprocess.TimeoutExpired:
            last_returncode = None
        else:
            last_returncode = proc.returncode
            if proc.returncode == 0:
                elapsed = time.monotonic() - started
                summary = f"``{label}`` exited zero after {elapsed:.1f}s"
                return ToolResult(
                    success=True,
                    output=summary,
                    data={
                        "predicate": "command_exits_zero",
                        "timed_out": False,
                        "elapsed_seconds": round(elapsed, 2),
                        "returncode": 0,
                    },
                    caption=summary,
                )
        if time.monotonic() >= deadline:
            elapsed = time.monotonic() - started
            summary = (
                f"``{label}`` did not exit zero within {elapsed:.0f}s "
                f"(last returncode: {last_returncode})"
            )
            return ToolResult(
                success=False,
                output=summary,
                error=summary,
                data={
                    "predicate": "command_exits_zero",
                    "timed_out": True,
                    "elapsed_seconds": round(elapsed, 2),
                    "last_returncode": last_returncode,
                },
                caption=summary,
            )
        await asyncio.sleep(cadence)
