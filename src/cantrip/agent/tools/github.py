"""GitHub CLI tools."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for all gh operations (seconds).
_GH_TIMEOUT = 30


class GhRepoCreateTool(Tool):
    """Tool to create a GitHub repository."""

    @property
    def name(self) -> str:
        return "gh_repo_create"

    @property
    def description(self) -> str:
        return "Create a new GitHub repository using the gh CLI. Defaults to a private repository."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Repository name",
                },
                "description": {
                    "type": "string",
                    "description": "Repository description",
                },
                "private": {
                    "type": "boolean",
                    "description": "Whether the repository is private",
                    "default": True,
                },
                "push": {
                    "type": "boolean",
                    "description": "Push local repository to the new remote after creation",
                    "default": False,
                },
            },
            "required": ["name"],
        }

    async def execute(
        self,
        name: str,
        description: str | None = None,
        private: bool = True,
        push: bool = False,
    ) -> ToolResult:
        """Run gh repo create."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        cmd = ["gh", "repo", "create", name]
        cmd.append("--private" if private else "--public")
        if description:
            cmd.extend(["--description", description])
        if push:
            cmd.append("--push")
            cmd.append("--source=.")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh repo create failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
                data={"name": name, "private": private},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh repo create timed out",
            )


class GhPrCreateTool(Tool):
    """Tool to create a GitHub pull request."""

    @property
    def name(self) -> str:
        return "gh_pr_create"

    @property
    def description(self) -> str:
        return "Create a pull request on GitHub using the gh CLI."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Pull request title",
                },
                "body": {
                    "type": "string",
                    "description": "Pull request body/description",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch for the pull request (e.g. main)",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
            },
            "required": ["title", "body"],
        }

    async def execute(
        self,
        title: str,
        body: str,
        base: str | None = None,
        path: str = ".",
    ) -> ToolResult:
        """Run gh pr create."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        cmd = ["gh", "pr", "create", "--title", title, "--body", body]
        if base:
            cmd.extend(["--base", base])

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh pr create failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
                data={"title": title},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh pr create timed out",
            )


class GhIssueListTool(Tool):
    """Tool to list GitHub issues."""

    @property
    def name(self) -> str:
        return "gh_issue_list"

    @property
    def description(self) -> str:
        return "List issues on a GitHub repository using the gh CLI."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": (
                        "Repository in OWNER/REPO format. Defaults to the current repository."
                    ),
                },
                "state": {
                    "type": "string",
                    "description": "Filter by issue state",
                    "enum": ["open", "closed", "all"],
                    "default": "open",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of issues to list",
                    "default": 10,
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository (used when repo is not specified)",
                    "default": ".",
                },
            },
        }

    async def execute(
        self,
        repo: str | None = None,
        state: str = "open",
        limit: int = 10,
        path: str = ".",
    ) -> ToolResult:
        """Run gh issue list."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        cmd = ["gh", "issue", "list", "--state", state, "--limit", str(limit)]
        if repo:
            cmd.extend(["--repo", repo])

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh issue list failed",
                )

            output = result.stdout.strip()
            if not output:
                output = "No issues found."

            return ToolResult(
                success=True,
                output=output,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh issue list timed out",
            )
