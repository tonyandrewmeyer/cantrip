"""PR review tools — fetch and reply to pull request review comments."""

import json
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for all gh operations (seconds).
_GH_TIMEOUT = 30

_GH_NOT_FOUND = "gh CLI not found. Is it installed?"

_GH_NOT_AUTHENTICATED = (
    "The GitHub CLI is not authenticated. "
    "Please run `gh auth login` and follow the prompts, then try again."
)


def _check_gh() -> str | None:
    """Return an error message if gh is missing or unauthenticated, else ``None``."""
    if not shutil.which("gh"):
        return _GH_NOT_FOUND
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "Timed out checking gh authentication status."
    if result.returncode != 0:
        return _GH_NOT_AUTHENTICATED
    return None


class PrReviewTool(Tool):
    """Fetch review comments on a pull request."""

    @property
    def name(self) -> str:
        return "pr_review"

    @property
    def description(self) -> str:
        return (
            "Fetch review comments on a GitHub pull request. "
            "Returns structured data: file, line, body, author, and state."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in OWNER/REPO format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number.",
                },
            },
            "required": ["repo", "pr_number"],
        }

    async def execute(self, repo: str, pr_number: int) -> ToolResult:
        """Fetch PR review comments via ``gh api``."""
        err = _check_gh()
        if err:
            return ToolResult(success=False, output="", error=err)

        cmd = [
            "gh", "api",
            f"repos/{repo}/pulls/{pr_number}/comments",
            "--paginate",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, output="", error="gh api timed out"
            )

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output="",
                error=result.stderr.strip() or "gh api failed",
            )

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                output="",
                error="Failed to parse gh api response as JSON",
            )

        if not isinstance(raw, list):
            raw = [raw]

        comments = _extract_comments(raw)

        if not comments:
            return ToolResult(
                success=True,
                output="No review comments on this PR.",
                data={"count": 0, "comments": []},
            )

        lines = [_format_comment(c) for c in comments]
        return ToolResult(
            success=True,
            output="\n\n---\n\n".join(lines),
            data={"count": len(comments), "comments": comments},
        )


def _extract_comments(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distil raw API response into structured comment records."""
    comments = []
    for item in raw:
        comment: dict[str, Any] = {
            "id": item.get("id"),
            "author": item.get("user", {}).get("login", "unknown"),
            "body": item.get("body", ""),
            "path": item.get("path"),
            "line": item.get("line") or item.get("original_line"),
            "side": item.get("side"),
            "in_reply_to_id": item.get("in_reply_to_id"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        comments.append(comment)
    return comments


def _format_comment(comment: dict[str, Any]) -> str:
    """Format a single comment for display."""
    header_parts = [f"**{comment['author']}**"]
    if comment.get("path"):
        loc = comment["path"]
        if comment.get("line"):
            loc += f":{comment['line']}"
        header_parts.append(f"on `{loc}`")
    if comment.get("in_reply_to_id"):
        header_parts.append(f"(reply to #{comment['in_reply_to_id']})")
    header = " ".join(header_parts)
    return f"{header}\n{comment['body']}"


class PrReviewReplyTool(Tool):
    """Post a reply to a pull request review comment."""

    @property
    def name(self) -> str:
        return "pr_review_reply"

    @property
    def description(self) -> str:
        return (
            "Post a reply to an existing review comment on a GitHub pull request. "
            "Use the comment ID from pr_review results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in OWNER/REPO format.",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number.",
                },
                "comment_id": {
                    "type": "integer",
                    "description": "ID of the review comment to reply to.",
                },
                "body": {
                    "type": "string",
                    "description": "Reply body text.",
                },
            },
            "required": ["repo", "pr_number", "comment_id", "body"],
        }

    async def execute(
        self, repo: str, pr_number: int, comment_id: int, body: str,
    ) -> ToolResult:
        """Post a reply via ``gh api``."""
        err = _check_gh()
        if err:
            return ToolResult(success=False, output="", error=err)

        payload = json.dumps({"body": body})
        cmd = [
            "gh", "api",
            f"repos/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
            "--method", "POST",
            "--input", "-",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                input=payload,
                timeout=_GH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, output="", error="gh api timed out"
            )

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output="",
                error=result.stderr.strip() or "gh api failed",
            )

        return ToolResult(
            success=True,
            output=f"Reply posted to comment #{comment_id}.",
            data={"comment_id": comment_id},
        )
