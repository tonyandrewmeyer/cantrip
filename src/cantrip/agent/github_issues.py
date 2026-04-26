"""GitHub issue triage background worker (Phase 42.2).

Periodically fetches open issues from a GitHub repository and presents
actionable candidates to the user via CONFIRM tasks.  Runs once per
session (or on explicit user request) to avoid hammering the GitHub API.
"""

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from cantrip.agent.queue import AgentTask, TaskCategory

log = logging.getLogger(__name__)

# Timeout for ``gh`` CLI calls (seconds).
_GH_TIMEOUT = 30

# Maximum issues to fetch per triage run.
_MAX_ISSUES = 20

# Labels that strongly signal an issue is actionable.
_ACTIONABLE_LABELS = frozenset(
    {
        "bug",
        "fix",
        "enhancement",
        "feature",
        "feature-request",
        "good first issue",
        "help wanted",
    }
)

# Labels that signal an issue should be skipped.
_SKIP_LABELS = frozenset(
    {
        "wontfix",
        "won't fix",
        "duplicate",
        "invalid",
        "question",
        "discussion",
        "meta",
        "epic",
    }
)

# Minimum body length (characters) for an issue to be considered actionable.
_MIN_BODY_LENGTH = 50

# Prefix for triage CONFIRM task IDs to identify them.
TRIAGE_CONFIRM_PREFIX = "triage-issue-"


@dataclass
class GitHubIssue:
    """A GitHub issue fetched via the ``gh`` CLI."""

    number: int
    title: str
    labels: list[str] = field(default_factory=list)
    body: str = ""
    comment_count: int = 0
    url: str = ""

    @property
    def label_set(self) -> frozenset[str]:
        """Lower-cased label names for matching."""
        return frozenset(label.lower() for label in self.labels)


def fetch_issues(repo: str) -> list[GitHubIssue]:
    """Fetch open issues from *repo* via ``gh issue list``.

    Returns an empty list if ``gh`` is unavailable, not authenticated,
    or the command fails.
    """
    if not shutil.which("gh"):
        log.debug("gh CLI not found — skipping issue fetch")
        return []

    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(_MAX_ISSUES),
        "--json",
        "number,title,labels,body,comments,url",
    ]
    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Failed to fetch GitHub issues: %s", exc)
        return []

    if result.returncode != 0:
        log.warning("gh issue list failed (rc=%d): %s", result.returncode, result.stderr.strip())
        return []

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.warning("Failed to parse gh issue list output")
        return []

    issues: list[GitHubIssue] = []
    for item in raw:
        labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
        comments = item.get("comments", [])
        issues.append(
            GitHubIssue(
                number=item.get("number", 0),
                title=item.get("title", ""),
                labels=labels,
                body=item.get("body", "") or "",
                comment_count=len(comments) if isinstance(comments, list) else 0,
                url=item.get("url", ""),
            )
        )
    return issues


def rank_issues(issues: list[GitHubIssue]) -> list[GitHubIssue]:
    """Filter and rank issues by actionability.

    Drops issues with skip labels or insufficient detail, then sorts
    by a simple score: actionable labels, body length, comment count.
    """
    candidates: list[tuple[float, GitHubIssue]] = []
    for issue in issues:
        lower_labels = issue.label_set
        # Skip issues with exclusion labels.
        if lower_labels & _SKIP_LABELS:
            continue
        # Skip issues with very short bodies (likely incomplete).
        if len(issue.body.strip()) < _MIN_BODY_LENGTH:
            continue

        score = 0.0
        # Bonus for actionable labels.
        if lower_labels & _ACTIONABLE_LABELS:
            score += 10.0
        # Longer descriptions are usually more actionable.
        score += min(len(issue.body) / 500, 5.0)
        # Comments indicate engagement.
        score += min(issue.comment_count, 5)

        candidates.append((score, issue))

    # Sort descending by score.
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [issue for _, issue in candidates]


def build_triage_confirm_task(issue: GitHubIssue, repo: str) -> AgentTask:
    """Create a CONFIRM task asking the user whether to work on an issue."""
    description = (
        f"**GitHub Issue #{issue.number}** — [{repo}](https://github.com/{repo}/issues/{issue.number})\n\n"
        f"**Title:** {issue.title}\n\n"
    )
    if issue.labels:
        description += f"**Labels:** {', '.join(issue.labels)}\n\n"

    # Include a truncated body preview.
    body_preview = issue.body.strip()
    if len(body_preview) > 800:
        body_preview = body_preview[:800] + "\n\n…(truncated)"
    description += f"**Description:**\n{body_preview}\n\n"
    description += (
        "This issue looks actionable. Approve this task to have the agent "
        "research, implement a fix, write tests, and prepare the changes."
    )

    return AgentTask(
        id=f"{TRIAGE_CONFIRM_PREFIX}{issue.number}",
        title=f"Work on #{issue.number}: {issue.title}",
        category=TaskCategory.CONFIRM,
        description=description,
    )


def build_issue_work_tasks(
    issue: GitHubIssue,
    repo: str,
    confirm_task_id: str,
    *,
    charm_path: str = ".",
) -> list[AgentTask]:
    """Generate the research → build → test task chain for an approved issue.

    The first task depends on *confirm_task_id* so that work only starts
    after user approval.
    """
    issue_ref = f"#{issue.number}"
    issue_context = (
        f"GitHub Issue {issue_ref}: {issue.title}\n"
        f"Repository: {repo}\n"
        f"URL: https://github.com/{repo}/issues/{issue.number}\n\n"
        f"{issue.body}\n"
    )

    research_id = f"triage-research-{issue.number}"
    build_id = f"triage-build-{issue.number}"
    test_id = f"triage-test-{issue.number}"

    tasks = [
        AgentTask(
            id=research_id,
            title=f"Research {issue_ref}: {issue.title}",
            category=TaskCategory.RESEARCH,
            description=(
                f"Investigate GitHub issue {issue_ref} and determine what needs to change.\n\n"
                f"{issue_context}\n"
                f"Read the relevant source files in `{charm_path}` to understand the "
                f"current implementation. Identify the root cause (for bugs) or the "
                f"required changes (for features). Summarise your findings clearly."
            ),
            dependencies=[confirm_task_id],
        ),
        AgentTask(
            id=build_id,
            title=f"Fix {issue_ref}: {issue.title}",
            category=TaskCategory.BUILD,
            description=(
                f"Implement the changes for GitHub issue {issue_ref}.\n\n"
                f"{issue_context}\n"
                f"Apply the fix or feature in `{charm_path}`. Follow existing code "
                f"conventions. Commit with a message referencing the issue "
                f"(e.g. 'Fix {issue_ref}: ...' or 'Closes {issue_ref}')."
            ),
            dependencies=[research_id],
        ),
        AgentTask(
            id=test_id,
            title=f"Test {issue_ref}: {issue.title}",
            category=TaskCategory.TEST,
            description=(
                f"Verify the changes for GitHub issue {issue_ref}.\n\n"
                f"Run existing tests to check for regressions. If the change is "
                f"testable, add or update tests. Run `run_charm_tests unit` and "
                f"verify the suite passes."
            ),
            dependencies=[build_id],
        ),
    ]

    return tasks


class IssueTriage:
    """Background worker that fetches and triages GitHub issues.

    Follows the ``EventWatcher`` lifecycle pattern: ``start()`` launches
    an asyncio task, ``stop()`` cancels it.  The worker runs **once** per
    session — after fetching and ranking issues it presents the top
    candidate(s) as CONFIRM tasks and stops polling.
    """

    def __init__(
        self,
        repo: str,
        on_issues_found: Callable[[list[AgentTask]], None] | None = None,
    ) -> None:
        self._repo = repo
        self._on_issues_found = on_issues_found
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # Issues already examined (by number) — avoids re-prompting.
        self._examined: set[int] = set()

    @property
    def running(self) -> bool:
        """Whether the triage worker is active."""
        return self._running

    @property
    def examined_issues(self) -> set[int]:
        """Issue numbers already examined this session."""
        return self._examined

    def start(self) -> None:
        """Start the background triage task.

        Can be called again after a previous run has completed to
        re-check for new issues (the ``_examined`` set is preserved
        so already-seen issues are not re-proposed).
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the triage task."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        log.info("Issue triage stopped")

    async def _run(self) -> None:
        """Fetch issues, rank, and create CONFIRM tasks for the top candidates."""
        try:
            # Run the blocking gh call in a thread to avoid blocking the loop.
            issues = await asyncio.to_thread(fetch_issues, self._repo)
            if not issues:
                log.info("No open issues found for %s", self._repo)
                return

            ranked = rank_issues(issues)
            if not ranked:
                log.info("No actionable issues found for %s", self._repo)
                return

            # Present the top candidate (avoid overwhelming the user).
            confirm_tasks: list[AgentTask] = []
            for issue in ranked[:3]:
                if issue.number in self._examined:
                    continue
                self._examined.add(issue.number)
                confirm_tasks.append(build_triage_confirm_task(issue, self._repo))

            if confirm_tasks and self._on_issues_found:
                self._on_issues_found(confirm_tasks)

            log.info(
                "Issue triage found %d actionable issues for %s, presented %d",
                len(ranked),
                self._repo,
                len(confirm_tasks),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — triage runs in a background loop; one bad pass must not kill the watcher.
            log.exception("Issue triage failed for %s", self._repo)
        finally:
            self._running = False
