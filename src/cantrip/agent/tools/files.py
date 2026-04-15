"""File operation tools for the agent."""

from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class PathAwareTool(Tool):
    """Base class for tools that resolve paths relative to a base directory.

    Subclasses inherit ``_resolve_path`` which resolves user-supplied paths
    against an optional *base_path* and prevents path-traversal escapes.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path

    def _resolve_path(self, path: str) -> Path:
        """Resolve *path*, ensuring it stays within ``base_path`` when set."""
        resolved = Path(path)
        if not resolved.is_absolute() and self.base_path:
            resolved = self.base_path / path
        resolved = resolved.resolve()

        if self.base_path:
            base_resolved = self.base_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError(f"Path {path} is outside allowed directory")

        return resolved


class ReadFileTool(PathAwareTool):
    """Tool to read file contents."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Use this to examine existing code or configuration."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to charm directory)",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based, inclusive). Omit to start from the beginning.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based, inclusive). Omit to read to the end.",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolResult:
        """Read file contents, optionally restricted to a line range."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path}",
                )
            if resolved.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path is a directory: {path}",
                )

            content = resolved.read_text()

            if start_line is not None or end_line is not None:
                lines = content.splitlines(keepends=True)
                total = len(lines)
                # Convert to 0-based indices with defaults.
                start = max((start_line or 1) - 1, 0)
                end = min(end_line or total, total)
                if start >= total:
                    return ToolResult(
                        success=True,
                        output="(no lines in requested range)",
                        data={"path": str(resolved), "total_lines": total},
                    )
                content = "".join(lines[start:end])
                return ToolResult(
                    success=True,
                    output=content,
                    data={
                        "path": str(resolved),
                        "size": len(content),
                        "lines": f"{start + 1}-{min(end, total)}",
                        "total_lines": total,
                    },
                )

            return ToolResult(
                success=True,
                output=content,
                data={"path": str(resolved), "size": len(content)},
            )
        except (OSError, UnicodeDecodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class WriteFileTool(PathAwareTool):
    """Tool to write file contents."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write (relative to charm directory)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str) -> ToolResult:
        """Write file contents."""
        try:
            resolved = self._resolve_path(path)

            # Create parent directories if needed
            resolved.parent.mkdir(parents=True, exist_ok=True)

            resolved.write_text(content)
            return ToolResult(
                success=True,
                output=f"Wrote {len(content)} bytes to {path}",
                data={"path": str(resolved), "size": len(content)},
            )
        except (OSError, UnicodeEncodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class ListDirectoryTool(PathAwareTool):
    """Tool to list directory contents."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "List files and directories in a path. Use this to explore the charm structure."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list (relative to charm directory)",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """List directory contents."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not found: {path}",
                )
            if not resolved.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path is not a directory: {path}",
                )

            entries = []
            for entry in sorted(resolved.iterdir()):
                if entry.is_dir():
                    label = f"dir:  {entry.name}/"
                else:
                    size = entry.stat().st_size
                    suffix = " -> " + str(entry.readlink()) if entry.is_symlink() else ""
                    label = f"file: {entry.name}  ({size} bytes){suffix}"
                entries.append(label)

            output = "\n".join(entries) if entries else "(empty directory)"
            return ToolResult(
                success=True,
                output=output,
                data={"path": str(resolved), "count": len(entries)},
            )
        except (OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class EditFileTool(PathAwareTool):
    """Tool to make targeted edits to a file."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace a specific string in a file. Use for targeted edits without rewriting the whole file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace it with",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, path: str, old_string: str, new_string: str) -> ToolResult:
        """Edit file by replacing string."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path}",
                )

            content = resolved.read_text()
            if old_string not in content:
                suffix = "..." if len(old_string) > 50 else ""
                return ToolResult(
                    success=False,
                    output="",
                    error=f"String not found in file: {old_string[:50]}{suffix}",
                )

            # Check for ambiguity
            count = content.count(old_string)
            if count > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"String appears {count} times. Provide more context for unique match.",
                )

            new_content = content.replace(old_string, new_string)
            resolved.write_text(new_content)

            return ToolResult(
                success=True,
                output=f"Replaced string in {path}",
                data={"path": str(resolved)},
            )
        except (OSError, UnicodeDecodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
