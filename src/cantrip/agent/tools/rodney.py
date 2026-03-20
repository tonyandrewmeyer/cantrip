"""Rodney agent tool — headless browser automation for visual capture."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for individual rodney commands (seconds).
_TIMEOUT = 30

# Screenshot commands get a longer timeout (pages may need to render).
_SCREENSHOT_TIMEOUT = 60


def _find_rodney() -> str | None:
    """Return the path to the rodney binary, or ``None``."""
    return shutil.which("rodney")


class RodneyTool(Tool):
    """Thin wrapper around the Rodney CLI for headless browser automation.

    Rodney drives a headless Chrome instance for capturing screenshots,
    verifying web UIs, and extracting page content — useful for demo
    documents and visual verification of web-facing charms.
    """

    @property
    def name(self) -> str:
        return "rodney"

    @property
    def description(self) -> str:
        return (
            "Control a headless browser for visual capture and web UI "
            "verification. Supports: start/stop (browser lifecycle), "
            "open (navigate), screenshot (capture page), wait (wait for "
            "element), text (extract text), click (interact), js (run "
            "JavaScript). Requires the rodney CLI to be installed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": [
                        "start",
                        "stop",
                        "status",
                        "open",
                        "screenshot",
                        "screenshot-el",
                        "wait",
                        "waitload",
                        "waitstable",
                        "waitidle",
                        "text",
                        "html",
                        "click",
                        "input",
                        "js",
                        "assert",
                        "exists",
                        "visible",
                        "title",
                        "url",
                    ],
                    "description": "The rodney subcommand to run",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Arguments for the subcommand. For 'open': [url]. "
                        "For 'screenshot': [filename]. For 'wait': [selector]. "
                        "For 'text': [selector]. For 'click': [selector]. "
                        "For 'js': [expression]."
                    ),
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        args: list[str] | None = None,
    ) -> ToolResult:
        """Run a rodney subcommand."""
        rodney = _find_rodney()
        if rodney is None:
            return ToolResult(
                success=False,
                output="",
                error=("rodney not found. Install from: https://github.com/simonw/rodney"),
            )

        cmd = [rodney, "--local", command]
        if args:
            cmd.extend(args)

        timeout = _SCREENSHOT_TIMEOUT if command in ("screenshot", "screenshot-el") else _TIMEOUT

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=output.strip(),
                    error=f"rodney {command} failed (exit code {result.returncode})",
                )

            return ToolResult(
                success=True,
                output=output.strip() or f"rodney {command} completed",
                data={"command": command},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"rodney {command} timed out after {timeout}s",
            )
