"""Git version control tools."""

import os
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for local git operations (seconds).
_GIT_TIMEOUT = 30

# Timeout for network git operations (seconds).
_GIT_NETWORK_TIMEOUT = 120

# Patterns in stderr that indicate an authentication or permission failure.
_AUTH_PATTERNS = (
    "Authentication failed",
    "Permission denied",
    "could not read Username",
    "terminal prompts disabled",
    "Invalid username or password",
    "denied to",
)


def _no_prompt_env() -> dict[str, str]:
    """Return an environment dict that prevents git from prompting for credentials."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _auth_hint(stderr: str) -> str:
    """Return a user-friendly message when a git network operation fails due to auth."""
    for pattern in _AUTH_PATTERNS:
        if pattern in stderr:
            return (
                f"{stderr.strip()}\n\n"
                "It looks like git could not authenticate with the remote. "
                "Please configure credentials (e.g. SSH keys or a credential helper) "
                "and try again."
            )
    return stderr or "git operation failed"


def _run_git(
    args: list[str],
    *,
    cwd: str | None = None,
    timeout: int = _GIT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> ToolResult:
    """Run a git command and return a ``ToolResult``.

    Handles the git-not-found check, subprocess timeout, and non-zero
    exit code — the three concerns every git tool repeats.
    """
    if not shutil.which("git"):
        return ToolResult(success=False, output="", error="git not found. Is it installed?")

    label = args[0] if args else "git"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, output="", error=f"git {label} timed out")

    if result.returncode != 0:
        return ToolResult(
            success=False,
            output=result.stdout,
            error=result.stderr or f"git {label} failed",
        )

    # Some commands (clone, push) write progress to stderr on success.
    output = result.stdout.strip() or result.stderr.strip()
    return ToolResult(success=True, output=output)


class GitCloneTool(Tool):
    """Tool to clone a git repository."""

    @property
    def name(self) -> str:
        return "git_clone"

    @property
    def description(self) -> str:
        return (
            "Clone a git repository into a local directory. "
            "Useful for fetching the source code of an application to be charmed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Repository URL (HTTPS or SSH)",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to clone into (defaults to repo name)",
                },
                "depth": {
                    "type": "integer",
                    "description": (
                        "Create a shallow clone with this many commits of history. "
                        "Use 1 for the fastest clone when full history is not needed."
                    ),
                },
            },
            "required": ["url"],
        }

    async def execute(
        self,
        url: str,
        path: str | None = None,
        depth: int | None = None,
    ) -> ToolResult:
        """Run git clone."""
        args = ["clone"]
        if depth is not None:
            args.extend(["--depth", str(depth)])
        args.append(url)
        if path:
            args.append(path)

        result = _run_git(args, timeout=_GIT_NETWORK_TIMEOUT, env=_no_prompt_env())

        # git clone writes progress to stderr; on failure, add auth hints.
        if not result.success:
            result.error = _auth_hint(result.error or "")
        else:
            result.data = {"url": url, "path": path}

        return result


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
        result = _run_git(["init"], cwd=path)
        if result.success:
            result.data = {"path": path}
        return result


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
        return _run_git(["status"], cwd=path)


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
        args = ["diff"]
        if staged:
            args.append("--cached")
        if ref:
            args.append(ref)

        result = _run_git(args, cwd=path)
        if result.success and not result.output:
            result.output = "No changes."
        return result


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
        args = ["log", f"--max-count={max_count}"]
        if oneline:
            args.append("--oneline")

        result = _run_git(args, cwd=path)
        if result.success and not result.output:
            result.output = "No commits yet."
        return result


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
        if not files:
            return ToolResult(success=False, output="", error="No files specified to stage.")

        result = _run_git(["add", "--", *files], cwd=path)
        if result.success:
            result.output = f"Staged {len(files)} file(s)."
        return result


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
        return _run_git(["commit", "--no-gpg-sign", "-m", message], cwd=path)


class GitPushTool(Tool):
    """Tool to push commits to a remote repository."""

    @property
    def name(self) -> str:
        return "git_push"

    @property
    def description(self) -> str:
        return (
            "Push local commits to a remote repository. "
            "Requires that the remote is configured and that you have push access."
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
                "remote": {
                    "type": "string",
                    "description": "Remote name to push to",
                    "default": "origin",
                },
                "branch": {
                    "type": "string",
                    "description": ("Branch to push. Defaults to the current branch."),
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": "Set the upstream tracking reference (-u)",
                    "default": False,
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to execute. Ask the user to confirm the push "
                        "(remote, branch, what will be pushed) before setting this."
                    ),
                    "default": False,
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = False,
        confirmed: bool = False,
    ) -> ToolResult:
        """Run git push."""
        if not confirmed:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Push requires explicit user confirmation. "
                    "Show the user what will be pushed (remote, branch, commits) "
                    "and ask them to confirm, then call again with confirmed=true."
                ),
            )

        args = ["push"]
        if set_upstream:
            args.append("-u")
        args.append(remote)
        if branch:
            args.append(branch)

        result = _run_git(args, cwd=path, timeout=_GIT_NETWORK_TIMEOUT, env=_no_prompt_env())

        if not result.success:
            result.error = _auth_hint(result.error or "")
        else:
            result.output = result.output or "Pushed successfully."
            result.data = {"remote": remote, "branch": branch}

        return result
