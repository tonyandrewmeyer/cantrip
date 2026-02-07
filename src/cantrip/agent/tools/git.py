"""Git version control tools."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for all git operations (seconds).
_GIT_TIMEOUT = 30


class GitInitTool(Tool):
    """Tool to initialise a new git repository."""

    @property
    def name(self) -> str:
        return "git_init"

    @property
    def description(self) -> str:
        return "Initialise a new git repository in the given directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to initialise as a git repository",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run git init."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        try:
            result = subprocess.run(
                ["git", "init"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git init failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
                data={"path": path},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git init timed out",
            )


class GitStatusTool(Tool):
    """Tool to show the working tree status."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Show the git working tree status (modified, staged, untracked files)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run git status."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        try:
            result = subprocess.run(
                ["git", "status"],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git status failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git status timed out",
            )


class GitDiffTool(Tool):
    """Tool to show changes in the working tree."""

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return (
            "Show changes in the working tree. "
            "By default shows unstaged changes; use staged=true to show staged changes, "
            "or provide a ref to diff against."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Show staged (cached) changes instead of unstaged",
                    "default": False,
                },
                "ref": {
                    "type": "string",
                    "description": "Git ref to diff against (e.g. HEAD~1, a branch name)",
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        staged: bool = False,
        ref: str | None = None,
    ) -> ToolResult:
        """Run git diff."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        if ref:
            cmd.append(ref)

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git diff failed",
                )

            output = result.stdout.strip()
            if not output:
                output = "No changes."

            return ToolResult(
                success=True,
                output=output,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git diff timed out",
            )


class GitLogTool(Tool):
    """Tool to show commit history."""

    @property
    def name(self) -> str:
        return "git_log"

    @property
    def description(self) -> str:
        return "Show the git commit history."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "max_count": {
                    "type": "integer",
                    "description": "Maximum number of commits to show",
                    "default": 10,
                },
                "oneline": {
                    "type": "boolean",
                    "description": "Use one-line format for each commit",
                    "default": False,
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        max_count: int = 10,
        oneline: bool = False,
    ) -> ToolResult:
        """Run git log."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        cmd = ["git", "log", f"--max-count={max_count}"]
        if oneline:
            cmd.append("--oneline")

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git log failed",
                )

            output = result.stdout.strip()
            if not output:
                output = "No commits yet."

            return ToolResult(
                success=True,
                output=output,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git log timed out",
            )


class GitAddTool(Tool):
    """Tool to stage files for commit."""

    @property
    def name(self) -> str:
        return "git_add"

    @property
    def description(self) -> str:
        return (
            "Stage files for the next commit. "
            "Takes an explicit list of file paths — does not support -A or '.' catch-alls."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to stage",
                },
            },
            "required": ["files"],
        }

    async def execute(self, files: list[str], path: str = ".") -> ToolResult:
        """Run git add with explicit file paths."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        if not files:
            return ToolResult(
                success=False,
                output="",
                error="No files specified to stage.",
            )

        try:
            result = subprocess.run(
                ["git", "add", "--", *files],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git add failed",
                )

            return ToolResult(
                success=True,
                output=f"Staged {len(files)} file(s).",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git add timed out",
            )


class GitCommitTool(Tool):
    """Tool to create a git commit."""

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return "Create a git commit with the staged changes."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message",
                },
            },
            "required": ["message"],
        }

    async def execute(self, message: str, path: str = ".") -> ToolResult:
        """Run git commit."""
        if not shutil.which("git"):
            return ToolResult(
                success=False,
                output="",
                error="git not found. Is it installed?",
            )

        try:
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "git commit failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="git commit timed out",
            )
