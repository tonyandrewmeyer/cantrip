"""Scoped command runner — runs only pre-approved commands."""

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

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
    ) -> None:
        self._allowlist = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
        self._base_path = base_path

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

        try:
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
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

        truncated = len(output) > _MAX_OUTPUT_CHARS
        if truncated:
            output = output[:_MAX_OUTPUT_CHARS] + "\n\n(output truncated)"

        return ToolResult(
            success=result.returncode == 0,
            output=output.strip(),
            error=f"Command exited with code {result.returncode}"
            if result.returncode != 0
            else "",
            data={
                "returncode": result.returncode,
                "truncated": truncated,
            },
        )
