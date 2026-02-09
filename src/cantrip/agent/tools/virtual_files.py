"""Tools for reading and searching virtual files."""

import re
from typing import Any

from cantrip.agent.context import VirtualFileStore
from cantrip.agent.tools.base import Tool, ToolResult


class VirtualFileReadTool(Tool):
    """Read a virtual file by ID, optionally with a line range."""

    def __init__(self, store: VirtualFileStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "virtual_file_read"

    @property
    def description(self) -> str:
        return (
            "Read a virtual file by ID. Virtual files contain content that "
            "was too large for the context window. Optionally specify "
            "start_line and end_line for a line range (1-indexed)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The virtual file ID (e.g. vf_1).",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to return (1-indexed, inclusive).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to return (1-indexed, exclusive).",
                },
            },
            "required": ["file_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool."""
        file_id: str = kwargs.get("file_id", "")
        start_line: int | None = kwargs.get("start_line")
        end_line: int | None = kwargs.get("end_line")

        vf = self._store.get(file_id)
        if vf is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Virtual file not found: {file_id}",
            )

        if start_line is not None and end_line is not None:
            content = self._store.get_lines(file_id, start_line, end_line)
            if content is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Virtual file not found: {file_id}",
                )
            return ToolResult(success=True, output=content)

        return ToolResult(success=True, output=vf.content)


class VirtualFileSearchTool(Tool):
    """Search virtual files by regex pattern."""

    def __init__(self, store: VirtualFileStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "virtual_file_search"

    @property
    def description(self) -> str:
        return (
            "Search virtual files by regex pattern. Returns matching lines "
            "formatted as 'file_id:line_number: line'. Optionally filter to "
            "a specific file_id."
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
                "file_id": {
                    "type": "string",
                    "description": "Optional: search only this virtual file.",
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 20).",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool."""
        pattern: str = kwargs.get("pattern", "")
        file_id: str | None = kwargs.get("file_id")
        max_matches: int = kwargs.get("max_matches", 20)

        try:
            matches = self._store.search(pattern, file_id=file_id, max_matches=max_matches)
        except re.error as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid regex pattern: {e}",
            )

        if not matches:
            return ToolResult(success=True, output="No matches found.")

        lines = [f"{m.file_id}:{m.line_number}: {m.line}" for m in matches]
        return ToolResult(success=True, output="\n".join(lines))
