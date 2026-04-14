"""Scoped command runner — runs only pre-approved commands."""

import shlex
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Default commands the agent is allowed to run.
DEFAULT_ALLOWLIST: frozenset[str] = frozenset({
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
})

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

    def __init__(self, *, allowlist: frozenset[str] | None = None) -> None:
        self._allowlist = allowlist if allowlist is not None else DEFAULT_ALLOWLIST

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
                        f"Timeout in seconds (default {_DEFAULT_TIMEOUT}, "
                        f"max {_MAX_TIMEOUT})."
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
            return ToolResult(
                success=False, output="", error="Empty command."
            )

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return ToolResult(
                success=False, output="", error=f"Invalid command syntax: {exc}"
            )

        base = parts[0]
        if base not in self._allowlist:
            allowed = ", ".join(sorted(self._allowlist))
            return ToolResult(
                success=False,
                output="",
                error=f"Command '{base}' is not on the allowlist. Allowed: {allowed}",
            )

        timeout = min(max(1, timeout), _MAX_TIMEOUT)

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
            error=f"Command exited with code {result.returncode}" if result.returncode != 0 else "",
            data={
                "returncode": result.returncode,
                "truncated": truncated,
            },
        )
