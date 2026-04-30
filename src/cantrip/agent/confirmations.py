"""Confirmation-flow controller — race, push, PR, bootstrap, triage.

Held by :class:`CantripAgent` as ``self._confirmations`` and re-exposed
through thin delegators so the public surface keeps working unchanged.
Each ``handle_*`` method resolves a CONFIRM task from the work queue
and produces a user-facing status message (or follow-up work tasks).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from cantrip.agent.git_branch import (
    BOOTSTRAP_CONFIRM_PREFIX,
    PUSH_CONFIRM_PREFIX,
    bootstrap_github_repo,
    build_pr_body,
    can_bootstrap,
    create_pull_request,
    push_branch,
    suggest_repo_name,
)
from cantrip.agent.github_issues import (
    TRIAGE_CONFIRM_PREFIX,
    build_issue_work_tasks,
)
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.race import RACE_CONFIRM_PREFIX

if TYPE_CHECKING:
    from cantrip.agent.queue import WorkQueue
    from cantrip.agent.state import AgentState
    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)


class ConfirmationsController:
    """Owns the confirmation-flow handlers.

    *create_feature_branch* and *build_push_confirm_task* are callables
    provided by the agent since they are shared with other subsystems.
    """

    def __init__(
        self,
        *,
        state: AgentState,
        work_queue: WorkQueue,
        ensure_store: Callable[[], None],
        get_store: Callable[[], SessionStore | None],
        create_feature_branch: Callable[[str], str | None],
        build_push_confirm_task: Callable[[str, str], AgentTask],
        detect_github_repo: Callable[..., str | None],
    ) -> None:
        self._state = state
        self._work_queue = work_queue
        self._ensure_store = ensure_store
        self._get_store = get_store
        self._create_feature_branch = create_feature_branch
        self._build_push_confirm_task = build_push_confirm_task
        self._detect_github_repo = detect_github_repo

    # -- Race confirmation -----------------------------------------------------

    def handle_race(self, confirm_task_id: str, *, approved: bool) -> str:
        """Resolve a race-cost CONFIRM task and unblock the parent.

        The parent task's id is the suffix of *confirm_task_id*.  Flipping
        ``race_decision`` on the parent lets the executor short-circuit the
        gate on re-entry: approved → run the race, declined → downgrade to
        a single-subagent run.  Returns a short status message for the
        conversation surface.
        """
        parent_id = confirm_task_id.removeprefix(RACE_CONFIRM_PREFIX)
        parent = self._work_queue.get_task(parent_id)

        decision = "approved" if approved else "declined"
        self._work_queue.set_done(
            confirm_task_id,
            f"Race {decision} by user",
        )
        if parent is None:
            log.warning(
                "Race-confirm %s resolved but parent %s not found",
                confirm_task_id,
                parent_id,
            )
            return f"Race confirmation resolved, but parent task `{parent_id}` is gone."

        parent.race_decision = decision
        self._work_queue.unblock(parent_id)

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "race_confirm_resolved",
                {
                    "task_id": parent_id,
                    "task_title": parent.title,
                    "decision": decision,
                },
            )
        if approved:
            return f"Race approved — `{parent.title}` will run with multiple models."
        return f"Race declined — `{parent.title}` will run with a single model."

    # -- Push confirmation -----------------------------------------------------

    def handle_push(self, confirm_task_id: str, *, approved: bool) -> str:
        """Handle an approved or skipped push-confirm task.

        Returns a status message for the user.
        """
        branch_name = confirm_task_id.removeprefix(PUSH_CONFIRM_PREFIX)
        charm_path = str(self._state.charm_path) if self._state.charm_path else "."

        if not approved:
            return f"Branch **{branch_name}** left local for manual review."

        success, output = push_branch(charm_path, branch_name)
        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "branch_pushed" if success else "branch_push_failed",
                {"branch": branch_name, "output": output[:500]},
            )

        if success:
            return (
                f"Pushed **{branch_name}** to origin.\n\n"
                f"Reply **pr** to open a pull request, **draft** for a draft PR, "
                f"or **skip** to skip."
            )
        return f"Push failed:\n```\n{output}\n```"

    # -- PR creation -----------------------------------------------------------

    def handle_pr_creation(
        self,
        branch_name: str,
        *,
        draft: bool = False,
    ) -> str:
        """Create a pull request for *branch_name*.

        Gathers task context from the work queue to build the PR title
        and body.  Returns a status message for the user.
        """
        charm_path = str(self._state.charm_path) if self._state.charm_path else "."
        repo = self._state.github_repo or ""

        # Find work tasks associated with this branch (triage or improvement).
        all_tasks = self._work_queue.all_tasks()
        work_tasks = [
            t
            for t in all_tasks
            if t.category.value not in ("confirm",) and t.id.startswith("triage-")
        ]
        # Fall back to all non-confirm done tasks if no triage tasks found.
        if not work_tasks:
            work_tasks = [t for t in all_tasks if t.category.value != "confirm" and t.result]

        # Extract issue number from branch name if present.
        issue_number: int | None = None
        m = re.search(r"issue-(\d+)", branch_name)
        if m:
            issue_number = int(m.group(1))

        # Build PR title.
        if issue_number:
            confirm_task = self._work_queue.get_task(f"triage-issue-{issue_number}")
            issue_title = ""
            if confirm_task:
                issue_title = confirm_task.title.removeprefix(f"Work on #{issue_number}: ")
            pr_title = (
                f"Fix #{issue_number}: {issue_title}" if issue_title else f"Fix #{issue_number}"
            )
        else:
            pr_title = branch_name.removeprefix("cantrip/").replace("-", " ").capitalize()

        pr_body = build_pr_body(
            work_tasks,
            issue_number=issue_number,
            repo=repo,
        )

        success, url_or_error = create_pull_request(
            charm_path,
            pr_title,
            pr_body,
            draft=draft,
        )

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "pr_created" if success else "pr_creation_failed",
                {
                    "branch": branch_name,
                    "draft": draft,
                    "result": url_or_error[:500],
                },
            )

        if success:
            pr_type = "Draft PR" if draft else "PR"
            return f"{pr_type} created: {url_or_error}"
        return f"PR creation failed:\n```\n{url_or_error}\n```"

    # -- Repository bootstrap --------------------------------------------------

    def should_offer_bootstrap(self) -> bool:
        """Return ``True`` if repo bootstrap should be offered to the user.

        Bootstrap is offered when a charm has been built (or is being
        improved) but no GitHub remote is configured and ``gh`` is
        available.
        """
        if self._state.github_repo:
            return False
        if any(t.id.startswith(BOOTSTRAP_CONFIRM_PREFIX) for t in self._work_queue.all_tasks()):
            return False
        charm_path = str(self._state.charm_path) if self._state.charm_path else None
        return can_bootstrap(charm_path)

    def build_repo_bootstrap_confirm_task(self) -> AgentTask:
        """Build the CONFIRM task that offers to create a GitHub repo."""
        charm_name = self._state.charm_name or "my-charm"
        suggested = suggest_repo_name(charm_name)
        description = (
            f"No GitHub remote detected.  Create a repository for this charm?\n\n"
            f"Default name: **{suggested}** "
            f"(Canonical convention is ``<workload>-operator``).\n\n"
            f"Reply **approve** to create **{suggested}** as a private repo, "
            f"or customise with tokens: ``name=my-repo``, ``org=canonical``, "
            f"``desc=My charm``, ``public``.\n\n"
            f"Reply **skip** to continue without a remote."
        )
        return AgentTask(
            id=f"{BOOTSTRAP_CONFIRM_PREFIX}{suggested}",
            title=f"Create GitHub repo {suggested}?",
            category=TaskCategory.CONFIRM,
            description=description,
        )

    def handle_repo_bootstrap(
        self,
        name: str,
        *,
        private: bool = True,
        description: str = "",
        org: str = "",
    ) -> str:
        """Create a GitHub repository and push the initial commit.

        Updates ``state.github_repo`` on success so that subsequent
        features (issue triage, branch workflow) activate automatically.
        Returns a status message for the user.
        """
        charm_path = str(self._state.charm_path) if self._state.charm_path else "."

        success, result = bootstrap_github_repo(
            charm_path,
            name,
            private=private,
            description=description,
            org=org,
        )

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "repo_bootstrapped" if success else "repo_bootstrap_failed",
                {
                    "name": name,
                    "private": private,
                    "org": org,
                    "result": result[:500],
                },
            )

        if success:
            # Re-detect the remote now that it exists.
            self._state.github_repo = self._detect_github_repo(self._state.charm_path)
            visibility = "private" if private else "public"
            return (
                f"Repository created ({visibility}): {result}\n\n"
                f"Remote set to **{self._state.github_repo or name}**."
            )
        return f"Repository creation failed:\n```\n{result}\n```"

    # -- Triage confirmation ---------------------------------------------------

    def handle_triage(
        self,
        confirm_task_id: str,
    ) -> list[AgentTask]:
        """Process an approved triage-confirm task and generate work tasks.

        Extracts the issue number from the task ID, locates the original
        CONFIRM task description, and builds research → build → test tasks.
        When a GitHub remote is detected, creates a feature branch and
        appends a push-confirmation task.
        """
        confirm_task = self._work_queue.get_task(confirm_task_id)
        if confirm_task is None:
            log.error("Triage confirm task %s not found", confirm_task_id)
            return []

        # Extract issue number from the task ID.
        try:
            issue_number = int(confirm_task_id.removeprefix(TRIAGE_CONFIRM_PREFIX))
        except ValueError:
            log.error("Cannot parse issue number from task ID %s", confirm_task_id)
            return []

        # Build a minimal GitHubIssue from the confirm task description.
        from cantrip.agent.github_issues import GitHubIssue

        issue = GitHubIssue(
            number=issue_number,
            title=confirm_task.title.removeprefix(f"Work on #{issue_number}: "),
            body=confirm_task.description,
        )

        # Create a feature branch for the work.
        branch = self._create_feature_branch(f"issue-{issue_number}-{issue.title}")

        work_tasks = build_issue_work_tasks(
            issue,
            self._state.github_repo or "",
            confirm_task_id,
            charm_path=str(self._state.charm_path) if self._state.charm_path else ".",
        )

        # Append push-confirm task if a branch was created.
        if branch and work_tasks:
            last_task_id = work_tasks[-1].id
            work_tasks.append(self._build_push_confirm_task(branch, last_task_id))

        self._work_queue.add_tasks(work_tasks)

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "triage_issue_approved",
                {
                    "repo": self._state.github_repo,
                    "issue_number": issue_number,
                    "task_count": len(work_tasks),
                    "branch": branch or "",
                },
            )

        return work_tasks
