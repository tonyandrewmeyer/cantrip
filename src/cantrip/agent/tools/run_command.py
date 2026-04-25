"""Scoped command runner — runs only pre-approved commands."""

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.sandbox import SandboxedRunner, SandboxPolicy
from cantrip.agent.tools.base import Tool, ToolResult

# Default commands the agent is allowed to run.
DEFAULT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "make",
        "uv",
        "ruff",
        "pytest",
        "pip",
        "charmcraft",
        "rockcraft",
        "juju",
        "python",
        "python3",
    }
)

# Commands that wrap another command and mask what's really running.
# Rejected categorically (Phase 49.2) — even if an operator adds one to
# the allowlist, "env rm ...", "sudo rm ...", "bash -c 'rm ...'" and
# friends all stay blocked.  Reported as a distinct error so the LLM
# can learn to drop the wrapper instead of retrying the same form.
_WRAPPER_COMMANDS: frozenset[str] = frozenset(
    {
        # Process / environment wrappers.
        "env",
        "sudo",
        "doas",
        "watch",
        "nohup",
        "setsid",
        "timeout",
        "ionice",
        "nice",
        "chroot",
        "stdbuf",
        "script",
        "xargs",
        "exec",
        # Shells — ``sh -c "..."`` defeats command inspection entirely.
        "bash",
        "sh",
        "zsh",
        "dash",
        "ksh",
        "fish",
    }
)

# ``NAME=value`` tokens appearing at the start of a command are treated
# by the shell as environment-variable assignments that apply to the
# following command (``FOO=bar make ...``).  Rejected for the same
# reason as ``env`` — they mask what's actually being invoked.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Package names that must never be installed by the agent.  System
# Docker (and its bundled containerd) actively breaks the ``k8s`` snap
# on dev machines: both ship a containerd that uses
# ``/run/containerd/containerd.sock`` and ``/var/lib/containerd``, and
# they deadlock each other on the boltdb metadata store.  Charms
# *consume* OCI images from Docker Hub, but the agent never needs the
# Docker engine itself — charmcraft, rockcraft, and the k8s snap's
# built-in containerd cover image building and runtime.
#
# Caught as a token-level match so ``apt install docker.io``,
# ``snap install docker``, ``dpkg -i docker-ce_*.deb``, and
# ``apt-get install -y docker-ce containerd.io`` all trip the same
# rule, regardless of whether the base command would otherwise be
# allowed.  See ``fix-broken-juju-k8s`` skill for the recovery flow
# when an earlier install has already wedged the cluster.
_BLOCKED_PACKAGES: frozenset[str] = frozenset(
    {
        "docker",
        "docker.io",
        "docker-ce",
        "docker-ce-cli",
        "docker-engine",
        "docker-compose",
        "docker-compose-plugin",
        "containerd",
        "containerd.io",
    }
)


def _matches_blocked_package(token: str) -> str | None:
    """Return the matching blocked package name, or ``None``.

    Matches a bare token (``docker.io``) and the Debian-binary-package
    filename shape ``<name>_<version>_<arch>.deb`` so ``dpkg -i
    docker-ce_24.0.7-1_amd64.deb`` is rejected the same as ``apt
    install docker-ce``.  A bare path like ``./docker.io`` is also
    checked via its basename.
    """
    if token in _BLOCKED_PACKAGES:
        return token
    # ``./docker.io`` / ``/tmp/docker.io`` — treat as a relative
    # reference to a blocked package only when the basename is the
    # full match.  Avoids false positives on directory paths that
    # merely contain ``docker``.
    base = token.rsplit("/", 1)[-1]
    if base in _BLOCKED_PACKAGES:
        return base
    if base.endswith(".deb"):
        # Debian binary package convention is ``<name>_<version>_<arch>.deb``.
        # Split off the first underscore-segment so we match the package
        # name regardless of the version / architecture suffix.
        stem = base[: -len(".deb")]
        name = stem.split("_", 1)[0]
        if name in _BLOCKED_PACKAGES:
            return name
    return None


# Shell metacharacters that would enable pipelines / compound commands
# under a shell=True interpreter.  We already run with shell=False, so
# these are ineffective today, but rejecting them (a) makes the error
# explicit so the LLM learns to split the command into two calls, and
# (b) keeps a future refactor to shell=True from inheriting a bypass.
_SHELL_METACHAR_PATTERNS: tuple[tuple[str, str], ...] = (
    (";", "command separator ';'"),
    ("&&", "'&&' (AND list)"),
    ("||", "'||' (OR list)"),
    ("|", "pipe '|'"),
    ("`", "backtick command substitution"),
    ("$(", "'$(...)' command substitution"),
    (">", "output redirection '>'"),
    ("<", "input redirection '<'"),
)

# Hard ceiling on command execution time.
_MAX_TIMEOUT = 300

# Default timeout.
_DEFAULT_TIMEOUT = 60

# Truncate output beyond this many characters.
_MAX_OUTPUT_CHARS = 50_000


class RunCommandTool(Tool):
    """Run a pre-approved command with timeout and output capture.

    Not a general shell — rejects anything whose base command is not on
    the allowlist.
    """

    def __init__(
        self,
        *,
        allowlist: frozenset[str] | None = None,
        base_path: Path | None = None,
        sandbox_runner: SandboxedRunner | None = None,
    ) -> None:
        self._allowlist = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
        self._base_path = base_path
        # The sandbox is the belt + braces in addition to the allowlist /
        # wrapper denylist / shell-metacharacter checks above — even if a
        # prompt injection or hallucination smuggles past every gate, the
        # resulting subprocess still can't reach the network or write
        # outside its working directory.  Lazily create a default runner
        # on first use so import-time side effects stay minimal.
        self._sandbox_runner = sandbox_runner

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        allowed = ", ".join(sorted(self._allowlist))
        return (
            "Run a command from a restricted allowlist. "
            f"Allowed commands: {allowed}. "
            "Use this for builds, lints, tests, and other safe operations."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The full command to run (e.g. 'make lint', 'uv run pytest -v'). "
                        "The base command (first word) must be on the allowlist."
                    ),
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the command (defaults to '.').",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Timeout in seconds (default {_DEFAULT_TIMEOUT}, max {_MAX_TIMEOUT})."
                    ),
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        cwd: str = ".",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> ToolResult:
        """Run the command if its base is on the allowlist."""
        command = command.strip()
        if not command:
            return ToolResult(success=False, output="", error="Empty command.")

        # Reject shell metacharacters before parsing.  The checks that
        # follow all inspect ``parts[0]``, so a compound command like
        # ``make && rm -rf /`` would otherwise slip through the base-
        # command gate even though ``subprocess.run(parts, ...)`` does
        # not interpret the ``&&`` (Phase 49.2).
        for needle, label in _SHELL_METACHAR_PATTERNS:
            if needle in command:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Shell metacharacter rejected: {label}. "
                        "Run each command as a separate run_command call."
                    ),
                )

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=f"Invalid command syntax: {exc}")

        # Strip leading ``NAME=value`` env-var assignments — the shell
        # treats them as a wrapper around the following command
        # (``FOO=bar make lint``).  Reject the prefix rather than
        # silently running the inner command, so the LLM sees the
        # exact form it sent.
        if parts and _ENV_ASSIGNMENT_RE.match(parts[0]):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Environment-variable assignment '{parts[0]}' is not allowed as a "
                    "wrapper. Set env vars via the tool's own mechanism, not on the "
                    "command line."
                ),
            )

        base = parts[0]

        # Reject any attempt to install Docker or the system containerd —
        # they conflict with the ``k8s`` snap's bundled containerd on
        # the dev machine.  Token-level match (whole word, plus the
        # ``<package>_<version>_<arch>.deb`` filename shape so ``dpkg
        # -i docker-ce_24.0.7-1_amd64.deb`` trips the same rule).
        # Trips regardless of which package manager is invoked or
        # whether the base command would otherwise be allowed.
        for token in parts[1:]:
            blocked = _matches_blocked_package(token)
            if blocked is not None:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Refusing to install blocked package '{blocked}'. "
                        "System Docker / containerd conflict with the "
                        "k8s snap's bundled containerd and wedge the "
                        "cluster.  Charms consume OCI images via "
                        "registry tools — they don't need a local "
                        "Docker engine.  If the cluster is already "
                        "broken, load the 'fix-broken-juju-k8s' skill."
                    ),
                    caption=f"Blocked install: {blocked}",
                )

        # Wrapper denylist takes precedence over the allowlist so that
        # adding ``env`` / ``bash`` to the allowlist (e.g. during local
        # experimentation) doesn't silently open a bypass.
        if base in _WRAPPER_COMMANDS:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Wrapper command '{base}' is blocked — it masks what is really "
                    "being run. Invoke the underlying command directly."
                ),
            )

        if base not in self._allowlist:
            allowed = ", ".join(sorted(self._allowlist))
            return ToolResult(
                success=False,
                output="",
                error=f"Command '{base}' is not on the allowlist. Allowed: {allowed}",
            )

        # Phase 80.5: destructive-argument gate.  Even when the base
        # command is on the allowlist, shapes like ``rm -rf`` /
        # ``git push --force`` / ``git reset --hard`` require a policy
        # layer with ``approve_destructive: true`` before the
        # subprocess fires.  Pattern match happens on ``parts`` (the
        # shlex-parsed argv) so flag-order and separator variations
        # still trip the regex.
        from cantrip.agent.policy import (
            compose_policies,
            destructive_command_check,
            discover_policies,
        )

        is_destructive, shape = destructive_command_check(parts)
        if is_destructive:
            composed = compose_policies(*discover_policies())
            if not composed.approve_destructive:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Destructive command shape {shape!r} requires explicit "
                        "approval.  Add ``approve_destructive: true`` to a "
                        "policy file (``~/.config/cantrip/policies/*.yaml`` or "
                        "``<charm>/cantrip.policies.yaml``) to enable it."
                    ),
                )

        timeout = min(max(1, timeout), _MAX_TIMEOUT)

        # Validate cwd is within the project tree when a base path is set.
        if self._base_path is not None:
            resolved_cwd = Path(cwd).resolve()
            base_resolved = self._base_path.resolve()
            if not resolved_cwd.is_relative_to(base_resolved):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Working directory '{cwd}' is outside the project tree.",
                )

        runner = self._sandbox_runner or SandboxedRunner()
        policy = SandboxPolicy(
            network=False,
            read_write_paths=(Path(cwd).resolve(),),
        )
        try:
            result = runner.run(
                parts,
                cwd=Path(cwd),
                policy=policy,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds.",
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"Command not found: {base}",
            )
        except OSError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to run command: {exc}",
            )

        output = result.stdout
        if result.stderr:
            output = output + "\n--- stderr ---\n" + result.stderr if output else result.stderr

        # When juju exits with a crash-shaped status, persist the full
        # repro material (cmd, cwd, stdout, stderr, juju version) to
        # ``diagnostics.log`` before the 50 KB output truncation kicks
        # in.  Lets the user open an upstream issue with verbatim
        # evidence even after the conversation context has rolled over.
        crash_dump_path: Path | None = None
        if base == "juju" and result.returncode != 0:
            from cantrip import diagnostics
            from cantrip.agent.tools.juju_subprocess import (
                juju_version,
                looks_like_juju_crash,
            )

            if looks_like_juju_crash(result.returncode, result.stderr or ""):
                extra: dict[str, str] = {}
                version = juju_version()
                if version:
                    extra["juju_version"] = version
                crash_dump_path = diagnostics.report_command_crash(
                    context="run_command:juju",
                    cmd=parts,
                    cwd=str(Path(cwd).resolve()),
                    returncode=result.returncode,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    extra=extra or None,
                )

        truncated = len(output) > _MAX_OUTPUT_CHARS
        if truncated:
            output = output[:_MAX_OUTPUT_CHARS] + "\n\n(output truncated)"

        if crash_dump_path is not None:
            output = (
                output.rstrip()
                + "\n\n[juju exit looks crash-shaped — full repro material captured to "
                + f"{crash_dump_path}]"
            )

        # Caption: "<base> (exit N)" or "<base> (exit N): <40-char snippet>".
        # Newlines are collapsed so the caption stays on one line in the
        # chat block; failing commands surface the start of their error
        # without the user having to open the transcript.
        snippet = output.strip().replace("\n", " ")
        if len(snippet) > 40:
            snippet = snippet[:39] + "…"
        caption = f"{base} (exit {result.returncode})"
        if snippet:
            caption = f"{caption}: {snippet}"

        error_text = ""
        if result.returncode != 0:
            error_text = f"Command exited with code {result.returncode}"
            if crash_dump_path is not None:
                error_text += f" (crash dump: {crash_dump_path})"

        return ToolResult(
            success=result.returncode == 0,
            output=output.strip(),
            error=error_text,
            data={
                "returncode": result.returncode,
                "truncated": truncated,
            },
            caption=caption,
        )
