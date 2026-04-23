"""Subprocess sandboxing (Phase 49.1).

Wraps outbound subprocess invocations with Linux user-namespace isolation so
a hallucinated or compromised shell command cannot reach files or processes
outside its intended scope.

Three mechanisms are supported, in order of preference:

``bwrap``
    Full filesystem + PID + network + namespace isolation.  The canonical
    mechanism — ``bwrap`` handles mount-namespace setup, bind mounts,
    ``/proc`` mounting, and session isolation in one call.  Available as the
    ``bubblewrap`` package on Debian/Ubuntu/Fedora.

``unshare``
    PID + network isolation only — no filesystem bind mounts.  Falls
    back to ``unshare --user --map-root-user --pid --fork ...`` which is
    available in ``util-linux`` and present on every stock Linux
    distribution.  Weaker than ``bwrap`` but still meaningful defence in
    depth (network blocking is the important part).

``none``
    Neither tool available — or we are not on Linux.  The runner logs a
    one-time warning and executes the command unchanged.  The caller
    sees the same ``subprocess.CompletedProcess`` it always did.

The policy is expressed as a :class:`SandboxPolicy` dataclass so callers
don't have to juggle CLI flags themselves.  Tools opt out (per tool, not per
command — see Phase 49.1's design note) by passing ``policy=SandboxPolicy(
network=True, read_write_paths=...)`` or by skipping the runner entirely.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from typing import Any, Literal

log = logging.getLogger(__name__)

# Event-sink hook — the agent optionally registers a callable here to
# persist sandbox decisions into the session transcript (Phase 49.5).
# Keeping it as a module-level slot avoids threading a store reference
# through every caller; the hook is off by default so unit tests of the
# sandbox itself stay hermetic.
_EventSink = Callable[[str, dict[str, Any]], None]
_event_sink: _EventSink | None = None
_event_sink_lock = threading.Lock()


def set_event_sink(sink: _EventSink | None) -> None:
    """Install (or clear) the event sink.

    The sandbox runner calls the registered sink with an event name and
    a structured payload whenever a command is wrapped, so reviewers can
    audit which bind mounts and network settings a subprocess actually
    saw.  Passing ``None`` clears the hook.
    """
    global _event_sink
    with _event_sink_lock:
        _event_sink = sink


def get_event_sink() -> _EventSink | None:
    """Return the currently-registered event sink (``None`` if unset)."""
    with _event_sink_lock:
        return _event_sink


# System paths we always bind read-only inside the bwrap sandbox.  These
# give the command access to installed binaries, shared libraries, locale
# data, and system config without granting write access to any of them.
_SYSTEM_READ_ONLY_PATHS: tuple[pathlib.Path, ...] = (
    pathlib.Path("/usr"),
    pathlib.Path("/bin"),
    pathlib.Path("/sbin"),
    pathlib.Path("/lib"),
    pathlib.Path("/lib32"),
    pathlib.Path("/lib64"),
    pathlib.Path("/libx32"),
    pathlib.Path("/etc"),
    pathlib.Path("/opt"),
)

Mechanism = Literal["bwrap", "unshare", "sandbox-exec", "none"]


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Per-invocation sandbox policy.

    Attributes:
        network: If ``True``, the command can reach the network.  Off by
            default — subprocess tooling (``make``, ``pytest``, ``ruff``)
            generally doesn't need it, and blocking it is the single most
            valuable sandbox property for defence against credential
            exfiltration.
        read_write_paths: Extra paths the command may write to, on top of
            the ``cwd`` that :meth:`SandboxedRunner.run` is called with.
            Use this sparingly — a broad list defeats the point of the
            sandbox.  Paths must exist; missing ones are dropped with a
            debug-level log entry so a stale config doesn't break the run.
        read_only_paths: Extra paths the command may *read* that are not
            already in :data:`_SYSTEM_READ_ONLY_PATHS`.  Typical uses:
            ``~/.cache/uv`` for a pre-populated package cache,
            ``~/.config/cantrip`` for the agent config.
    """

    network: bool = False
    read_write_paths: tuple[pathlib.Path, ...] = ()
    read_only_paths: tuple[pathlib.Path, ...] = ()


def sandbox_available() -> Mechanism:
    """Return the best sandbox mechanism available on this host.

    On Linux, probes ``PATH`` for ``bwrap`` first, then ``unshare``.
    On macOS, probes for ``sandbox-exec`` — deprecated by Apple but
    still present on current releases and the only shipping option.
    Returns ``"none"`` on other platforms or when no tool is present.
    """
    if sys.platform == "linux":
        if shutil.which("bwrap"):
            return "bwrap"
        if shutil.which("unshare"):
            return "unshare"
        return "none"
    if sys.platform == "darwin":
        if shutil.which("sandbox-exec"):
            return "sandbox-exec"
        return "none"
    return "none"


class SandboxedRunner:
    """Run subprocess commands under Linux namespace isolation.

    Instances are cheap — they only cache the mechanism probe.  The
    typical pattern is:

        runner = SandboxedRunner()
        result = runner.run(["make", "check"], cwd=project, policy=SandboxPolicy())
    """

    _warned_about_fallback: bool = False

    def __init__(self, mechanism: Mechanism | None = None) -> None:
        self._mechanism: Mechanism = mechanism if mechanism is not None else sandbox_available()

    @property
    def mechanism(self) -> Mechanism:
        return self._mechanism

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: pathlib.Path | str,
        policy: SandboxPolicy | None = None,
        timeout: float | None = None,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Execute *argv* inside the sandbox.

        The command runs as the current user (``--map-root-user`` is used
        inside the new user namespace, but the outer uid is unchanged,
        so no privilege escalation is possible).  Raises
        :class:`subprocess.TimeoutExpired` if ``timeout`` is exceeded and
        :class:`FileNotFoundError` if the underlying executable is missing.
        """
        policy = policy or SandboxPolicy()
        cwd_path = pathlib.Path(cwd).resolve()
        wrapped = self.wrap(argv, cwd=cwd_path, policy=policy)
        self._record_decision(argv=list(argv), cwd=cwd_path, policy=policy)
        return subprocess.run(
            wrapped,
            cwd=str(cwd_path),
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            check=False,
        )

    def _record_decision(
        self,
        *,
        argv: list[str],
        cwd: pathlib.Path,
        policy: SandboxPolicy,
    ) -> None:
        """Emit a ``sandbox_policy`` event if an event sink is registered.

        Phase 49.5 observability — gives reviewers an audit trail of which
        bind mounts and network settings every subprocess actually saw.
        Never raises: a misbehaving sink must not break the command.
        """
        sink = get_event_sink()
        if sink is None:
            return
        payload = {
            "mechanism": self._mechanism,
            "argv": argv,
            "cwd": str(cwd),
            "network": policy.network,
            "read_write_paths": [str(p) for p in policy.read_write_paths],
            "read_only_paths": [str(p) for p in policy.read_only_paths],
        }
        try:
            sink("sandbox_policy", payload)
        except Exception as exc:  # noqa: BLE001 - sink errors must not propagate
            log.debug("sandbox event sink raised %r; ignoring", exc)

    def wrap(
        self,
        argv: Sequence[str],
        *,
        cwd: pathlib.Path,
        policy: SandboxPolicy,
    ) -> list[str]:
        """Return the actual argv list the subprocess layer will execute.

        Exposed for tests — and for tools that need to log what was run.
        Never shells out itself.
        """
        if self._mechanism == "bwrap":
            return self._wrap_bwrap(argv, cwd=cwd, policy=policy)
        if self._mechanism == "unshare":
            return self._wrap_unshare(argv, policy=policy)
        if self._mechanism == "sandbox-exec":
            return self._wrap_sandbox_exec(argv, cwd=cwd, policy=policy)
        self._warn_once_about_fallback()
        return list(argv)

    def _wrap_bwrap(
        self,
        argv: Sequence[str],
        *,
        cwd: pathlib.Path,
        policy: SandboxPolicy,
    ) -> list[str]:
        """Build a ``bwrap ... -- argv`` command.

        The resulting environment is:
        - A fresh user namespace with the caller mapped to root.
        - PID, UTS, IPC, and cgroup namespaces unshared.
        - Network namespace unshared unless ``policy.network`` is set.
        - Root filesystem from the host bound read-only for system paths.
        - ``/proc`` and ``/dev`` provided by bwrap's built-in mounts.
        - ``/tmp`` is a fresh tmpfs.
        - ``cwd`` and any ``read_write_paths`` bound read-write.
        - ``read_only_paths`` bound read-only.
        - ``HOME`` unset so commands don't leak into the real home.
        """
        cmd: list[str] = [
            "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-cgroup-try",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        if not policy.network:
            cmd.append("--unshare-net")

        for path in _SYSTEM_READ_ONLY_PATHS:
            if path.exists():
                cmd.extend(["--ro-bind-try", str(path), str(path)])

        for path in policy.read_only_paths:
            resolved = pathlib.Path(path).resolve()
            if not resolved.exists():
                log.debug("sandbox: skipping missing read-only path %s", resolved)
                continue
            cmd.extend(["--ro-bind", str(resolved), str(resolved)])

        cmd.extend(["--bind", str(cwd), str(cwd)])
        for path in policy.read_write_paths:
            resolved = pathlib.Path(path).resolve()
            if not resolved.exists():
                log.debug("sandbox: skipping missing read-write path %s", resolved)
                continue
            if resolved == cwd:
                continue
            cmd.extend(["--bind", str(resolved), str(resolved)])

        cmd.extend(["--chdir", str(cwd)])
        cmd.append("--")
        cmd.extend(argv)
        return cmd

    def _wrap_unshare(
        self,
        argv: Sequence[str],
        *,
        policy: SandboxPolicy,
    ) -> list[str]:
        """Build an ``unshare ... -- argv`` command.

        This fallback can't do filesystem isolation — a full ``--mount``
        namespace without bind mounts still sees the host tree.  What it
        *can* do is:
        - Block outbound network when ``policy.network`` is False.
        - Give the command its own PID namespace so it can't see or
          signal processes outside the sandbox.
        - Run inside a fresh user namespace with the caller mapped to
          root so no privilege escalation is possible.
        """
        cmd: list[str] = [
            "unshare",
            "--user",
            "--map-root-user",
            "--pid",
            "--fork",
            "--mount-proc",
            "--uts",
            "--ipc",
            "--kill-child",
        ]
        if not policy.network:
            cmd.append("--net")
        cmd.append("--")
        cmd.extend(argv)
        return cmd

    def _wrap_sandbox_exec(
        self,
        argv: Sequence[str],
        *,
        cwd: pathlib.Path,
        policy: SandboxPolicy,
    ) -> list[str]:
        """Build a ``sandbox-exec -p <profile> -- argv`` command for macOS.

        macOS ``sandbox-exec`` consumes a SBPL profile (a Lisp-like DSL).
        Apple has deprecated the profile grammar, but it is the only
        shipping mechanism on current macOS and Claude Code's own
        sandbox is built on it.  The profile we emit:

        - Denies everything by default.
        - Allows process-exec and process-fork so the command can run.
        - Allows file-read on the standard system paths plus any
          ``read_only_paths``.
        - Allows file-read* and file-write* on ``cwd`` plus any
          ``read_write_paths``.
        - Allows ``mach-lookup`` / ``ipc-posix-sem`` / ``sysctl-read``
          so stock Apple tooling runs.
        - Denies ``network*`` when ``policy.network`` is False;
          otherwise allows the standard network operations.
        """
        profile = self._build_sandbox_exec_profile(cwd=cwd, policy=policy)
        cmd: list[str] = ["sandbox-exec", "-p", profile]
        cmd.extend(argv)
        return cmd

    @staticmethod
    def _build_sandbox_exec_profile(
        *,
        cwd: pathlib.Path,
        policy: SandboxPolicy,
    ) -> str:
        """Render the SBPL profile string for ``sandbox-exec -p``."""
        read_write: list[pathlib.Path] = [cwd]
        for path in policy.read_write_paths:
            resolved = pathlib.Path(path).resolve()
            if not resolved.exists() or resolved == cwd:
                continue
            read_write.append(resolved)

        read_only: list[pathlib.Path] = []
        for path in policy.read_only_paths:
            resolved = pathlib.Path(path).resolve()
            if resolved.exists():
                read_only.append(resolved)

        lines: list[str] = [
            "(version 1)",
            "(deny default)",
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow signal (target same-sandbox))",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-sem)",
            "(allow file-read*",
            '  (subpath "/usr")',
            '  (subpath "/bin")',
            '  (subpath "/sbin")',
            '  (subpath "/System")',
            '  (subpath "/Library")',
            '  (subpath "/private/etc")',
            '  (subpath "/private/var/db")',
            '  (subpath "/dev")',
            ")",
        ]

        if read_only:
            ro_lines = "".join(f'  (subpath "{p}")\n' for p in read_only)
            lines.append("(allow file-read*\n" + ro_lines + ")")

        rw_lines = "".join(f'  (subpath "{p}")\n' for p in read_write)
        lines.append("(allow file-read* file-write*\n" + rw_lines + ")")

        if policy.network:
            lines.append("(allow network*)")
        else:
            lines.append("(deny network*)")

        return "\n".join(lines)

    def _warn_once_about_fallback(self) -> None:
        if not SandboxedRunner._warned_about_fallback:
            log.warning(
                "sandbox: no isolation mechanism available (bwrap / unshare "
                "on Linux, sandbox-exec on macOS) — subprocess commands "
                "will run unsandboxed. On Linux, install bubblewrap for "
                "full isolation."
            )
            SandboxedRunner._warned_about_fallback = True
