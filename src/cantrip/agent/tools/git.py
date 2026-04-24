"""Git version control tools."""

import os
import re
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for local git operations (seconds).
_GIT_TIMEOUT = 30

# Timeout for network git operations (seconds).
_GIT_NETWORK_TIMEOUT = 120

# Environment variable that opts in to GPG signing of commits.  By default
# Cantrip passes ``--no-gpg-sign`` so automated commits never hang on a
# passphrase prompt or fail on a missing key; setting ``CANTRIP_GPG_SIGN``
# to a truthy value ("1", "true", "yes", "on", case-insensitive) lets the
# user's git config (``commit.gpgsign``) take effect instead.
_GPG_SIGN_ENV = "CANTRIP_GPG_SIGN"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _gpg_sign_enabled() -> bool:
    """Return whether the user has opted in to GPG signing via env var."""
    return os.environ.get(_GPG_SIGN_ENV, "").strip().lower() in _TRUTHY


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
            # Strip the protocol/auth prefix so the caption stays on one line
            # (``git@github.com:foo/bar.git`` → ``github.com:foo/bar``).
            display_url = re.sub(r"^[a-z]+://(?:[^@]+@)?", "", url)
            display_url = re.sub(r"^git@", "", display_url)
            display_url = re.sub(r"\.git$", "", display_url)
            result.caption = f"Cloned {display_url}"

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
                "branch": {
                    "type": "string",
                    "description": "Branch name to show history for (defaults to current branch)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Show only commits touching this file path",
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        max_count: int = 10,
        oneline: bool = False,
        branch: str | None = None,
        file_path: str | None = None,
    ) -> ToolResult:
        """Run git log."""
        args = ["log", f"--max-count={max_count}"]
        if oneline:
            args.append("--oneline")
        if branch:
            args.append(branch)
        if file_path:
            args.extend(["--", file_path])

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
        args = ["commit", "-m", message]
        if not _gpg_sign_enabled():
            args.insert(1, "--no-gpg-sign")
        result = _run_git(args, cwd=path)
        if result.success:
            # Use the commit subject (first non-empty line) so the caption
            # carries the same context that ``git log --oneline`` shows.
            subject = next(
                (line.strip() for line in message.splitlines() if line.strip()),
                "(empty message)",
            )
            if len(subject) > 60:
                subject = subject[:59] + "…"
            result.caption = f"Committed: {subject!r}"
        return result


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
            target = f"{remote}/{branch}" if branch else remote
            result.caption = f"Pushed → {target}"

        return result


class GitBranchTool(Tool):
    """Tool to create or list git branches."""

    @property
    def name(self) -> str:
        return "git_branch"

    @property
    def description(self) -> str:
        return "Create a new git branch or list existing branches."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Branch name to create. Omit to list branches.",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
            },
        }

    async def execute(
        self,
        name: str | None = None,
        path: str = ".",
    ) -> ToolResult:
        """Create or list branches."""
        if name:
            return _run_git(["checkout", "-b", name], cwd=path)
        result = _run_git(["branch", "--list", "-a"], cwd=path)
        if result.success and not result.output:
            result.output = "No branches found."
        return result


class GitCheckoutTool(Tool):
    """Tool to switch git branches."""

    @property
    def name(self) -> str:
        return "git_checkout"

    @property
    def description(self) -> str:
        return "Switch to an existing git branch."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch name to switch to",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
            },
            "required": ["branch"],
        }

    async def execute(
        self,
        branch: str,
        path: str = ".",
    ) -> ToolResult:
        """Switch branches."""
        return _run_git(["checkout", branch], cwd=path)


class GitStashTool(Tool):
    """Tool to stash or restore uncommitted changes."""

    @property
    def name(self) -> str:
        return "git_stash"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Stash action: 'push' to stash, 'pop' to restore, 'list' to show stashes.",
                    "enum": ["push", "pop", "list"],
                    "default": "push",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "message": {
                    "type": "string",
                    "description": "Description for the stash (only used with 'push')",
                },
            },
        }

    @property
    def description(self) -> str:
        return "Stash uncommitted changes (push), restore them (pop), or list stashes."

    async def execute(
        self,
        action: str = "push",
        path: str = ".",
        message: str | None = None,
    ) -> ToolResult:
        """Stash operations."""
        if action == "push":
            args = ["stash", "push"]
            if message:
                args.extend(["-m", message])
        elif action == "pop":
            args = ["stash", "pop"]
        elif action == "list":
            args = ["stash", "list"]
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown stash action: {action}. Use 'push', 'pop', or 'list'.",
            )

        result = _run_git(args, cwd=path)
        if result.success and not result.output:
            if action == "push":
                result.output = "Changes stashed."
            elif action == "list":
                result.output = "No stashes."
        return result
