"""Showboat agent tool — builds Markdown demos by running real commands."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for individual showboat commands (seconds).
_TIMEOUT = 60


def _find_showboat() -> str | None:
    """Return the path to the showboat binary, or ``None``."""
    return shutil.which("showboat")


class ShowboatTool(Tool):
    """Thin wrapper around the Showboat CLI for building demo documents.

    Showboat builds Markdown documents by running real commands and
    capturing their output inline — ideal for charm demo documents
    with interleaved ``juju`` commands and results.
    """

    @property
    def name(self) -> str:
        return "showboat"

    @property
    def description(self) -> str:
        return (
            "Build a Markdown demo document by running real commands and "
            "capturing output. Supports: init (create document), note (add "
            "commentary), exec (run command and capture output), image (embed "
            "image), pop (remove last entry), verify (re-run and check). "
            "Requires the showboat CLI to be installed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["init", "note", "exec", "image", "pop", "verify"],
                    "description": "The showboat subcommand to run",
                },
                "file": {
                    "type": "string",
                    "description": "Path to the demo Markdown file",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Arguments for the subcommand. For 'init': [title]. "
                        "For 'note': [text]. For 'exec': [lang, code]. "
                        "For 'image': [image_path]. For 'pop'/'verify': []."
                    ),
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for command execution",
                },
            },
            "required": ["command", "file"],
        }

    async def execute(
        self,
        command: str,
        file: str,
        args: list[str] | None = None,
        workdir: str | None = None,
    ) -> ToolResult:
        """Run a showboat subcommand."""
        showboat = _find_showboat()
        if showboat is None:
            return ToolResult(
                success=False,
                output="",
                error=("showboat not found. Install with: pip install showboat"),
            )

        valid_commands = {"init", "note", "exec", "image", "pop", "verify"}
        if command not in valid_commands:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown showboat command: {command}. "
                f"Valid: {', '.join(sorted(valid_commands))}",
            )

        cmd = [showboat, command, file]
        if args:
            cmd.extend(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=workdir,
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=output.strip(),
                    error=f"showboat {command} failed (exit code {result.returncode})",
                )

            return ToolResult(
                success=True,
                output=output.strip() or f"showboat {command} completed",
                data={"command": command, "file": file},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"showboat {command} timed out after {_TIMEOUT}s",
            )
