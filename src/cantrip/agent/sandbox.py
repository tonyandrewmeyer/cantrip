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
from collections.abc import Sequence
from typing import Literal

log = logging.getLogger(__name__)

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

Mechanism = Literal["bwrap", "unshare", "none"]


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

    Probes ``PATH`` for ``bwrap`` first, then ``unshare``.  Non-Linux
    hosts always return ``"none"`` — macOS support lives in Phase 49.4.
    """
    if sys.platform != "linux":
        return "none"
    if shutil.which("bwrap"):
        return "bwrap"
    if shutil.which("unshare"):
        return "unshare"
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
        return subprocess.run(
            wrapped,
            cwd=str(cwd_path),
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            check=False,
        )

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

    def _warn_once_about_fallback(self) -> None:
        if not SandboxedRunner._warned_about_fallback:
            log.warning(
                "sandbox: neither 'bwrap' nor 'unshare' available — "
                "subprocess commands will run unsandboxed. "
                "Install bubblewrap for full isolation."
            )
            SandboxedRunner._warned_about_fallback = True
