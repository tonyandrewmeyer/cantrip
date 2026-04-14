"""Content search tool for the agent.

Wraps ``rg`` (ripgrep) when available, falling back to ``grep -rn``.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.files import PathAwareTool

log = logging.getLogger(__name__)

# Maximum output lines returned to the LLM to avoid flooding context.
_DEFAULT_MAX_RESULTS = 50

# Hard ceiling — even if the caller asks for more, cap here.
_ABSOLUTE_MAX_RESULTS = 200


class GrepTool(PathAwareTool):
    """Search file contents for a pattern using ripgrep or grep."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents for a regex pattern. "
            "Returns matching lines with file paths and line numbers. "
            "Use this to find definitions, usages, imports, or any text across a codebase."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory or file to search in "
                        "(relative to charm directory, defaults to '.')."
                    ),
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Only search files matching this glob pattern (e.g. '*.py', '*.yaml')."
                    ),
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines before and after each match.",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether the search is case-sensitive (default true).",
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        f"Maximum number of matching lines to return (default {_DEFAULT_MAX_RESULTS})."
                    ),
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        context_lines: int = 0,
        case_sensitive: bool = True,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> ToolResult:
        """Run the search and return matching lines."""
        try:
            resolved = self._resolve_path(path)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        if not resolved.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        max_results = min(max(1, max_results), _ABSOLUTE_MAX_RESULTS)

        rg_bin = shutil.which("rg")
        if rg_bin:
            cmd = self._build_rg_command(
                rg_bin,
                pattern,
                resolved,
                glob,
                context_lines,
                case_sensitive,
                max_results,
            )
        else:
            cmd = self._build_grep_command(
                pattern,
                resolved,
                glob,
                context_lines,
                case_sensitive,
                max_results,
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(resolved) if resolved.is_dir() else str(resolved.parent),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="Search timed out after 30 seconds.")

        # grep/rg return exit code 1 for "no matches" — that is not an error.
        if result.returncode > 1:
            return ToolResult(
                success=False,
                output="",
                error=f"Search failed: {result.stderr.strip()}",
            )

        output = result.stdout.strip()
        if not output:
            return ToolResult(
                success=True,
                output="No matches found.",
                data={"match_count": 0},
            )

        lines = output.split("\n")
        truncated = len(lines) > max_results
        if truncated:
            lines = lines[:max_results]

        display = "\n".join(lines)
        if truncated:
            display += f"\n\n(results truncated — showing {max_results} of more matches)"

        return ToolResult(
            success=True,
            output=display,
            data={"match_count": len(lines), "truncated": truncated},
        )

    @staticmethod
    def _build_rg_command(
        rg_bin: str,
        pattern: str,
        path: Path,
        glob: str | None,
        context_lines: int,
        case_sensitive: bool,
        max_results: int,
    ) -> list[str]:
        """Build a ripgrep command."""
        cmd = [rg_bin, "--no-heading", "--line-number", "--color=never"]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if context_lines > 0:
            cmd.extend(["--context", str(context_lines)])
        if glob:
            cmd.extend(["--glob", glob])
        # Fetch slightly more than max_results so we can detect truncation.
        cmd.extend(["--max-count", str(max_results + 1)])
        cmd.append(pattern)
        cmd.append(str(path))
        return cmd

    @staticmethod
    def _build_grep_command(
        pattern: str,
        path: Path,
        glob: str | None,
        context_lines: int,
        case_sensitive: bool,
        max_results: int,
    ) -> list[str]:
        """Build a GNU grep command."""
        grep_bin = shutil.which("grep") or "grep"
        cmd = [grep_bin, "-rn", "--color=never"]
        if not case_sensitive:
            cmd.append("-i")
        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])
        if glob:
            cmd.extend(["--include", glob])
        cmd.extend(["-m", str(max_results + 1)])
        cmd.append(pattern)
        cmd.append(str(path))
        return cmd
