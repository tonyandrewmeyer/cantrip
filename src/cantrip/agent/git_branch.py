"""Git branch and repository operations (Phase 42).

Pure functions that create, switch, push branches, open pull requests,
bootstrap GitHub repositories, and monitor PR feedback using subprocess
calls.  These run at the orchestrator level (not via subagent tools).
"""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Timeout for git operations (seconds).
_GIT_TIMEOUT = 15

# Prefix for all Cantrip-created branches.
BRANCH_PREFIX = "cantrip/"

# Task ID prefix for push-confirmation CONFIRM tasks.
PUSH_CONFIRM_PREFIX = "push-branch-"


def current_branch(charm_path: str) -> str | None:
    """Return the name of the current git branch, or ``None``."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch and branch != "HEAD" else None


def slugify(text: str, max_length: int = 50) -> str:
    """Convert a title into a branch-safe slug.

    Lowercases, replaces non-alphanumeric runs with hyphens, strips
    leading/trailing hyphens, and truncates to *max_length*.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def create_branch(charm_path: str, description: str) -> str | None:
    """Create and switch to a new ``cantrip/<description>`` branch.

    Returns the branch name on success, or ``None`` on failure.
    The *description* is slugified for branch-name safety.
    """
    slug = slugify(description)
    if not slug:
        slug = "change"
    branch_name = f"{BRANCH_PREFIX}{slug}"

    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "checkout", "-b", branch_name],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Failed to create branch %s: %s", branch_name, exc)
        return None

    if result.returncode != 0:
        log.warning(
            "git checkout -b %s failed (rc=%d): %s",
            branch_name,
            result.returncode,
            result.stderr.strip(),
        )
        return None

    log.info("Created and switched to branch %s", branch_name)
    return branch_name


def switch_branch(charm_path: str, branch_name: str) -> bool:
    """Switch to an existing branch.  Returns ``True`` on success."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "checkout", branch_name],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def push_branch(
    charm_path: str,
    branch_name: str,
    remote: str = "origin",
) -> tuple[bool, str]:
    """Push *branch_name* to *remote* with ``-u`` (set upstream).

    Returns ``(success, message)`` where *message* is the git output
    or error text.
    """
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "push", "-u", remote, branch_name],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return False, output
    return True, output


def create_pull_request(
    charm_path: str,
    title: str,
    body: str,
    *,
    draft: bool = False,
    base: str | None = None,
) -> tuple[bool, str]:
    """Create a pull request via ``gh pr create``.

    Returns ``(success, url_or_error)``.  On success the second element
    is the PR URL printed by ``gh``.
    """
    if not shutil.which("gh"):
        return False, "gh CLI not found."

    cmd = ["gh", "pr", "create", "--title", title, "--body", body]
    if draft:
        cmd.append("--draft")
    if base:
        cmd.extend(["--base", base])

    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()


def build_pr_body(
    tasks: list[object],
    *,
    issue_number: int | None = None,
    repo: str = "",
) -> str:
    """Build a PR body from completed work-queue tasks.

    Each task is expected to have ``title``, ``category``, ``status``,
    and ``result`` attributes (duck-typed to avoid importing AgentTask).
    """
    lines: list[str] = ["## Summary\n"]

    if issue_number and repo:
        lines.append(f"Resolves #{issue_number}\n")
    elif issue_number:
        lines.append(f"Addresses issue #{issue_number}\n")

    # Collect task summaries.
    task_lines: list[str] = []
    for task in tasks:
        title = getattr(task, "title", "")
        category = getattr(task, "category", "")
        status = getattr(task, "status", "")
        if not title:
            continue
        icon = "✓" if str(status) == "done" else "✗" if str(status) == "failed" else "○"
        task_lines.append(f"- {icon} **{category}**: {title}")

    if task_lines:
        lines.append("\n".join(task_lines))
        lines.append("")

    # Collapsible agent details.
    detail_lines: list[str] = []
    for task in tasks:
        result_text = getattr(task, "result", None)
        title = getattr(task, "title", "unknown")
        if result_text:
            # Truncate long results.
            preview = result_text[:500]
            if len(result_text) > 500:
                preview += "\n…(truncated)"
            detail_lines.append(f"### {title}\n```\n{preview}\n```\n")

    if detail_lines:
        lines.append("<details>")
        lines.append("<summary>Agent work details</summary>\n")
        lines.extend(detail_lines)
        lines.append("</details>\n")

    lines.append("---")
    lines.append("*Created by [Cantrip](https://github.com/canonical/cantrip)*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Repository bootstrap (Phase 42.5)
# ---------------------------------------------------------------------------


def has_git_repo(charm_path: str) -> bool:
    """Return ``True`` if *charm_path* is inside a git repository."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "--git-dir"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def has_remote(charm_path: str) -> bool:
    """Return ``True`` if the git repo at *charm_path* has an ``origin`` remote."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "remote", "get-url", "origin"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def gh_available() -> bool:
    """Return ``True`` if ``gh`` is installed and authenticated."""
    if not shutil.which("gh"):
        return False
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def git_init(charm_path: str) -> bool:
    """Initialise a git repository at *charm_path* if one does not exist."""
    if has_git_repo(charm_path):
        return True
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "init"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def git_add_and_commit(charm_path: str, message: str) -> bool:
    """Stage all files and create an initial commit."""
    try:
        add = subprocess.run(  # noqa: S603, S607
            ["git", "add", "."],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if add.returncode != 0:
            return False
        commit = subprocess.run(  # noqa: S603, S607
            ["git", "commit", "-m", message],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return commit.returncode == 0


def bootstrap_github_repo(
    charm_path: str,
    name: str,
    *,
    private: bool = True,
    description: str = "",
    org: str = "",
) -> tuple[bool, str]:
    """Create a GitHub repo and push the initial commit.

    Handles git init, initial commit, ``gh repo create``, and push.
    Returns ``(success, message)``.
    """
    # Ensure we have a git repo with at least one commit.
    if not has_git_repo(charm_path):
        if not git_init(charm_path):
            return False, "Failed to initialise git repository."
        if not git_add_and_commit(charm_path, f"Initial commit: {name}"):
            return False, "Failed to create initial commit."
    elif not _has_commits(charm_path):
        if not git_add_and_commit(charm_path, f"Initial commit: {name}"):
            return False, "Failed to create initial commit."

    # Build gh repo create command.
    repo_name = f"{org}/{name}" if org else name
    cmd = [
        "gh",
        "repo",
        "create",
        repo_name,
        "--private" if private else "--public",
        "--source",
        ".",
        "--push",
    ]
    if description:
        cmd.extend(["--description", description])

    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return False, output

    # The repo URL is typically on the first line of stdout.
    repo_url = result.stdout.strip().split("\n")[0] if result.stdout.strip() else output
    return True, repo_url


def _has_commits(charm_path: str) -> bool:
    """Return ``True`` if the git repo has at least one commit."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "HEAD"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def check_upstream_diverged(charm_path: str, branch: str = "main") -> tuple[bool, int]:
    """Check if the local default branch is behind the remote.

    Runs ``git fetch`` then compares ``HEAD`` with ``origin/<branch>``.
    Returns ``(diverged, commits_behind)`` where *diverged* is ``True``
    if the remote has commits not in the local branch.
    """
    # Fetch quietly first.
    try:
        subprocess.run(  # noqa: S603, S607
            ["git", "fetch", "origin", branch],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False, 0

    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
            cwd=charm_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False, 0

    if result.returncode != 0:
        return False, 0

    try:
        behind = int(result.stdout.strip())
    except ValueError:
        return False, 0

    return behind > 0, behind


def gh_issue_comment(repo: str, issue_number: int, body: str) -> tuple[bool, str]:
    """Post a comment on a GitHub issue via ``gh issue comment``.

    Returns ``(success, message)``.
    """
    if not shutil.which("gh"):
        return False, "gh CLI not found."

    cmd = [
        "gh",
        "issue",
        "comment",
        str(issue_number),
        "--repo",
        repo,
        "--body",
        body,
    ]

    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()


@dataclass
class PrReviewComment:
    """A review comment on a pull request."""

    id: int
    author: str
    body: str
    path: str = ""
    line: int | None = None
    state: str = ""


@dataclass
class PrFeedback:
    """Aggregated feedback from a pull request."""

    pr_number: int
    pr_url: str
    state: str  # OPEN, CLOSED, MERGED
    review_decision: str  # APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED, ""
    comments: list[PrReviewComment] = field(default_factory=list)

    @property
    def needs_changes(self) -> bool:
        """Whether reviewers have requested changes."""
        return self.review_decision == "CHANGES_REQUESTED"

    @property
    def is_approved(self) -> bool:
        """Whether the PR is approved."""
        return self.review_decision == "APPROVED"

    def format_for_chat(self) -> str:
        """Format feedback for display in chat."""
        lines = [f"**PR #{self.pr_number}** — {self.state}"]
        if self.review_decision:
            lines[0] += f" ({self.review_decision})"

        if not self.comments:
            lines.append("No review comments.")
            return "\n".join(lines)

        lines.append(f"\n**{len(self.comments)} review comment(s):**\n")
        for c in self.comments:
            loc = f" (`{c.path}:{c.line}`)" if c.path else ""
            lines.append(f"- **{c.author}**{loc}: {c.body[:200]}")

        return "\n".join(lines)


def gh_pr_view(
    repo: str,
    pr_number: int,
) -> PrFeedback | None:
    """Fetch PR status and review comments via ``gh pr view``.

    Returns ``None`` if ``gh`` is unavailable or the command fails.
    """
    if not shutil.which("gh"):
        return None

    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "number,url,state,reviewDecision,reviews,comments",
    ]

    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    comments: list[PrReviewComment] = []

    # Extract review comments (from reviews).
    for review in data.get("reviews", []):
        body = review.get("body", "").strip()
        if body:
            comments.append(
                PrReviewComment(
                    id=review.get("id", 0),
                    author=review.get("author", {}).get("login", "unknown"),
                    body=body,
                    state=review.get("state", ""),
                )
            )

    # Extract general PR comments.
    for comment in data.get("comments", []):
        body = comment.get("body", "").strip()
        if body:
            comments.append(
                PrReviewComment(
                    id=comment.get("id", 0),
                    author=comment.get("author", {}).get("login", "unknown"),
                    body=body,
                )
            )

    return PrFeedback(
        pr_number=data.get("number", pr_number),
        pr_url=data.get("url", ""),
        state=data.get("state", "OPEN"),
        review_decision=data.get("reviewDecision", "") or "",
        comments=comments,
    )


def can_bootstrap(charm_path: str | None) -> bool:
    """Return ``True`` if repo bootstrap is possible and needed.

    Bootstrap is offered when:
    1. charm_path exists
    2. There is no ``origin`` remote (or no git repo)
    3. ``gh`` is available and authenticated
    """
    if not charm_path:
        return False
    if has_remote(charm_path):
        return False
    return gh_available()
