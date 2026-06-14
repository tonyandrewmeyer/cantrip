"""Issue triage and upstream-check controller.

Held by :class:`CantripAgent` as ``self._triage_ctl`` and re-exposed
through thin delegators so the public surface (``issue_triage_running`` /
``start_issue_triage`` / ``stop_issue_triage`` / ``retriage_issues`` /
``comment_on_issue`` / ``check_upstream``) keeps working unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from cantrip.agent.git.git_branch import check_upstream_diverged, gh_issue_comment
from cantrip.agent.watcher.github_issues import IssueTriage

if TYPE_CHECKING:
    from cantrip.agent.queue import AgentTask, WorkQueue
    from cantrip.agent.state import AgentState
    from cantrip.agent.store import SessionStore

from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)


class TriageController:
    """Owns the GitHub issue-triage lifecycle, issue commenting, and upstream checks.

    *ensure_store* is invoked before recording events so the session
    store is initialised.  *get_store* returns the current store
    (may be ``None``).
    """

    def __init__(
        self,
        *,
        state: AgentState,
        event_bus: ui_events.EventBus,
        work_queue: WorkQueue,
        ensure_store: Callable[[], None],
        get_store: Callable[[], SessionStore | None],
    ) -> None:
        self._state = state
        self._event_bus = event_bus
        self._work_queue = work_queue
        self._ensure_store = ensure_store
        self._get_store = get_store
        self._issue_triage: IssueTriage | None = None

    @property
    def running(self) -> bool:
        """Whether the GitHub issue triage worker is active."""
        return self._issue_triage is not None and self._issue_triage.running

    def start(self) -> bool:
        """Start the background issue triage worker.

        Returns ``False`` if no ``github_repo`` is detected or triage
        has already run this session.
        """
        if not self._state.github_repo:
            return False
        if self._issue_triage is not None:
            return False

        def _on_issues_found(confirm_tasks: list[AgentTask]) -> None:
            for task in confirm_tasks:
                self._work_queue.add_task(task)
            self._event_bus.publish(
                ui_events.chat_message(
                    role="system",
                    content=(
                        f"Found {len(confirm_tasks)} actionable GitHub issue(s) "
                        f"— check the task list to approve."
                    ),
                )
            )
            self._ensure_store()
            store = self._get_store()
            if store:
                store.record_event(
                    "issue_triage_complete",
                    {
                        "repo": self._state.github_repo,
                        "candidates": len(confirm_tasks),
                    },
                )

        self._issue_triage = IssueTriage(
            repo=self._state.github_repo,
            on_issues_found=_on_issues_found,
        )
        self._issue_triage.start()
        log.info("Issue triage started for %s", self._state.github_repo)
        return True

    async def stop(self) -> None:
        """Stop the issue triage worker if running."""
        if self._issue_triage:
            await self._issue_triage.stop()
            self._issue_triage = None

    def retriage(self) -> bool:
        """Re-run issue triage to check for new issues.

        Preserves the set of already-examined issues so the user is
        not re-prompted for issues they have already seen.  Returns
        ``False`` if triage cannot run (no repo or already running).
        """
        if not self._state.github_repo:
            return False
        if self._issue_triage and self._issue_triage.running:
            return False

        # Preserve examined set across triage runs.
        examined: set[int] = set()
        if self._issue_triage:
            examined = self._issue_triage.examined_issues

        def _on_issues_found(confirm_tasks: list[AgentTask]) -> None:
            for task in confirm_tasks:
                self._work_queue.add_task(task)
            if confirm_tasks:
                self._event_bus.publish(
                    ui_events.chat_message(
                        role="system",
                        content=(
                            f"Found {len(confirm_tasks)} new actionable issue(s) "
                            f"— check the task list to approve."
                        ),
                    )
                )

        self._issue_triage = IssueTriage(
            repo=self._state.github_repo,
            on_issues_found=_on_issues_found,
        )
        # Transfer examined set from previous run.
        self._issue_triage._examined = examined  # noqa: SLF001
        self._issue_triage.start()
        log.info("Issue re-triage started for %s", self._state.github_repo)
        return True

    def comment_on_issue(self, issue_number: int, pr_url: str) -> str:
        """Post a comment on a resolved GitHub issue.

        Returns a status message for the user.
        """
        repo = self._state.github_repo
        if not repo:
            return "No GitHub repository detected."

        body = (
            f"This issue has been addressed by {pr_url}.\n\n"
            f"*Automated by [Cantrip](https://github.com/canonical/cantrip)*"
        )
        success, result = gh_issue_comment(repo, issue_number, body)

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "issue_commented" if success else "issue_comment_failed",
                {"issue_number": issue_number, "result": result[:500]},
            )

        if success:
            return f"Commented on issue #{issue_number}."
        return f"Failed to comment on issue #{issue_number}: {result}"

    def check_upstream(self) -> str | None:
        """Check if the default branch has diverged from the remote.

        Returns a warning message if behind, or ``None`` if up to date.
        """
        if not self._state.charm_path:
            return None
        diverged, behind = check_upstream_diverged(str(self._state.charm_path))
        if diverged:
            return (
                f"**Warning:** The default branch is {behind} commit(s) behind "
                f"origin. Consider pulling or rebasing before starting new work."
            )
        return None
