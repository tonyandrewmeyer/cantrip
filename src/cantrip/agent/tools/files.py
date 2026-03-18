"""File operation tools for the agent."""

from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(self, base_path: Path | None = None):
        """Initialise with optional base path restriction."""
        self.base_path = base_path

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
            },
            "required": ["path"],
        }

    def _resolve_path(self, path: str) -> Path:
        """Resolve path, ensuring it's within base_path if set."""
        resolved = Path(path)
        if not resolved.is_absolute() and self.base_path:
            resolved = self.base_path / path
        resolved = resolved.resolve()

        if self.base_path:
            base_resolved = self.base_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError(f"Path {path} is outside allowed directory")

        return resolved

    async def execute(self, path: str) -> ToolResult:
        """Read file contents."""
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


class WriteFileTool(Tool):
    """Tool to write file contents."""

    def __init__(self, base_path: Path | None = None):
        """Initialise with optional base path restriction."""
        self.base_path = base_path

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

    def _resolve_path(self, path: str) -> Path:
        """Resolve path, ensuring it's within base_path if set."""
        resolved = Path(path)
        if not resolved.is_absolute() and self.base_path:
            resolved = self.base_path / path
        resolved = resolved.resolve()

        if self.base_path:
            base_resolved = self.base_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError(f"Path {path} is outside allowed directory")

        return resolved

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


class ListDirectoryTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, base_path: Path | None = None):
        """Initialise with optional base path restriction."""
        self.base_path = base_path

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

    def _resolve_path(self, path: str) -> Path:
        """Resolve path, ensuring it's within base_path if set."""
        resolved = Path(path)
        if not resolved.is_absolute() and self.base_path:
            resolved = self.base_path / path
        resolved = resolved.resolve()

        if self.base_path:
            base_resolved = self.base_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError(f"Path {path} is outside allowed directory")

        return resolved

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
                entry_type = "dir" if entry.is_dir() else "file"
                entries.append(f"{entry_type}: {entry.name}")

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


class EditFileTool(Tool):
    """Tool to make targeted edits to a file."""

    def __init__(self, base_path: Path | None = None):
        """Initialise with optional base path restriction."""
        self.base_path = base_path

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

    def _resolve_path(self, path: str) -> Path:
        """Resolve path, ensuring it's within base_path if set."""
        resolved = Path(path)
        if not resolved.is_absolute() and self.base_path:
            resolved = self.base_path / path
        resolved = resolved.resolve()

        if self.base_path:
            base_resolved = self.base_path.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError(f"Path {path} is outside allowed directory")

        return resolved

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
                return ToolResult(
                    success=False,
                    output="",
                    error=f"String not found in file: {old_string[:50]}...",
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
