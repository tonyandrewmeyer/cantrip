"""Tests for ``CantripAgent`` GitHub / PR / issue-triage helpers.

Targets ROADMAP 57.6 core.py coverage.  Uses ``FakeProvider`` and mocks
the ``git_branch`` / ``github_issues`` module functions that actually
shell out to ``gh`` and ``git`` so none of these tests touch the
network or the real working tree.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.git_branch import PrFeedback, PrReviewComment
from cantrip.agent.queue import AgentTask, TaskCategory
from tests.conftest import FakeProvider


def _agent(tmp_path: Path | None = None) -> CantripAgent:
    """Build an agent with a FakeProvider; ``charm_path`` optional."""
    return CantripAgent(provider=FakeProvider(), charm_path=tmp_path)


# ---------------------------------------------------------------------------
# check_upstream / check_pr_feedback
# ---------------------------------------------------------------------------


class TestCheckUpstream:
    """``check_upstream`` is a thin wrapper that formats a divergence warning."""

    def test_returns_none_without_charm_path(self) -> None:
        agent = _agent()
        assert agent.check_upstream() is None

    def test_returns_none_when_not_diverged(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.check_upstream_diverged",
            return_value=(False, 0),
        ):
            assert agent.check_upstream() is None

    def test_returns_warning_when_behind(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.check_upstream_diverged",
            return_value=(True, 3),
        ):
            msg = agent.check_upstream()
        assert msg is not None
        assert "3 commit" in msg


class TestCheckPrFeedback:
    """``check_pr_feedback`` forwards to gh_pr_view."""

    def test_returns_none_without_repo(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        assert agent.check_pr_feedback(7) is None

    def test_forwards_to_gh_pr_view(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        fake = PrFeedback(
            pr_number=7,
            pr_url="https://github.com/o/r/pull/7",
            state="OPEN",
            review_decision="",
        )
        with patch("cantrip.agent.core.gh_pr_view", return_value=fake) as gh:
            result = agent.check_pr_feedback(7)
        gh.assert_called_once_with("o/r", 7)
        assert result is fake


# ---------------------------------------------------------------------------
# should_offer_bootstrap
# ---------------------------------------------------------------------------


class TestShouldOfferBootstrap:
    """Bootstrap is gated on no-remote + gh available."""

    def test_false_when_repo_already_configured(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        assert agent.should_offer_bootstrap() is False

    def test_passes_charm_path_to_can_bootstrap(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        with patch("cantrip.agent.core.can_bootstrap", return_value=True) as cb:
            assert agent.should_offer_bootstrap() is True
        cb.assert_called_once_with(str(tmp_path))


# ---------------------------------------------------------------------------
# comment_on_issue
# ---------------------------------------------------------------------------


class TestCommentOnIssue:
    """``comment_on_issue`` formats a resolved-by comment and reports status."""

    def test_no_repo_returns_message(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        result = agent.comment_on_issue(7, "https://github.com/o/r/pull/8")
        assert "No GitHub repository" in result

    def test_success_posts_and_records_event(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        with patch(
            "cantrip.agent.core.gh_issue_comment",
            return_value=(True, "ok"),
        ) as gh:
            result = agent.comment_on_issue(7, "https://github.com/o/r/pull/8")
        gh.assert_called_once()
        assert "Commented on issue #7." in result

    def test_failure_returns_error_message(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        with patch(
            "cantrip.agent.core.gh_issue_comment",
            return_value=(False, "rate limited"),
        ):
            result = agent.comment_on_issue(7, "pr-url")
        assert "Failed to comment on issue #7" in result
        assert "rate limited" in result


# ---------------------------------------------------------------------------
# handle_push_confirmation
# ---------------------------------------------------------------------------


class TestHandlePushConfirmation:
    """All four arms of ``handle_push_confirmation``."""

    def test_skipped_branch_returns_manual_message(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        result = agent.handle_push_confirmation("push-branch-feat", approved=False)
        assert "left local" in result

    def test_approved_push_success(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.push_branch",
            return_value=(True, "pushed"),
        ):
            result = agent.handle_push_confirmation("push-branch-feat", approved=True)
        assert "Pushed **feat**" in result
        assert "Reply **pr**" in result

    def test_approved_push_failure(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.push_branch",
            return_value=(False, "permission denied"),
        ):
            result = agent.handle_push_confirmation("push-branch-feat", approved=True)
        assert "Push failed" in result
        assert "permission denied" in result


# ---------------------------------------------------------------------------
# handle_pr_creation
# ---------------------------------------------------------------------------


class TestHandlePrCreation:
    """``handle_pr_creation`` formats title + body and forwards to gh."""

    def test_success_draft_is_labelled(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"

        with (
            patch(
                "cantrip.agent.core.create_pull_request",
                return_value=(True, "https://github.com/o/r/pull/9"),
            ) as cpr,
            patch("cantrip.agent.core.build_pr_body", return_value="body"),
        ):
            result = agent.handle_pr_creation("cantrip/issue-7-fix-login", draft=True)

        assert "Draft PR created" in result
        assert "https://github.com/o/r/pull/9" in result
        # Title reflects issue number extraction.
        assert "Fix #7" in cpr.call_args.args[1]

    def test_success_without_issue_number_falls_back_to_branch_title(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with (
            patch(
                "cantrip.agent.core.create_pull_request",
                return_value=(True, "https://x/pull/1"),
            ) as cpr,
            patch("cantrip.agent.core.build_pr_body", return_value=""),
        ):
            agent.handle_pr_creation("cantrip/improve-README", draft=False)
        assert cpr.call_args.args[1] == "Improve readme"

    def test_failure_returns_error(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with (
            patch(
                "cantrip.agent.core.create_pull_request",
                return_value=(False, "gh failed"),
            ),
            patch("cantrip.agent.core.build_pr_body", return_value=""),
        ):
            result = agent.handle_pr_creation("cantrip/feat")
        assert "PR creation failed" in result
        assert "gh failed" in result


# ---------------------------------------------------------------------------
# handle_repo_bootstrap
# ---------------------------------------------------------------------------


class TestHandleRepoBootstrap:
    """``handle_repo_bootstrap`` shells out to gh and updates state on success."""

    def test_success_private(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with (
            patch(
                "cantrip.agent.core.bootstrap_github_repo",
                return_value=(True, "https://github.com/u/n"),
            ),
            patch("cantrip.agent.core.detect_github_repo", return_value="u/n"),
        ):
            result = agent.handle_repo_bootstrap("n", private=True, description="d", org="")
        assert "private" in result
        assert agent.state.github_repo == "u/n"

    def test_success_public(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with (
            patch(
                "cantrip.agent.core.bootstrap_github_repo",
                return_value=(True, "https://github.com/u/n"),
            ),
            patch("cantrip.agent.core.detect_github_repo", return_value="u/n"),
        ):
            result = agent.handle_repo_bootstrap("n", private=False, description="", org="u")
        assert "public" in result

    def test_failure_returns_error(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        with patch(
            "cantrip.agent.core.bootstrap_github_repo",
            return_value=(False, "gh not auth"),
        ):
            result = agent.handle_repo_bootstrap("n")
        assert "Repository creation failed" in result
        assert "gh not auth" in result


# ---------------------------------------------------------------------------
# create_pr_fix_tasks
# ---------------------------------------------------------------------------


class TestCreatePrFixTasks:
    """``create_pr_fix_tasks`` produces a fix task + push-confirm task."""

    def test_generates_fix_task_and_push_confirm(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        feedback = PrFeedback(
            pr_number=12,
            pr_url="https://x/pull/12",
            state="OPEN",
            review_decision="CHANGES_REQUESTED",
            comments=[
                PrReviewComment(
                    id=1,
                    author="alice",
                    body="please rename this",
                    path="src/foo.py",
                    line=10,
                ),
            ],
        )
        tasks = agent.create_pr_fix_tasks(feedback, "cantrip/issue-5")
        assert len(tasks) == 2
        assert tasks[0].id == "pr-fix-12"
        assert tasks[0].category == TaskCategory.BUILD
        assert tasks[1].category == TaskCategory.CONFIRM
        assert tasks[1].id.startswith("push-branch-")

    def test_empty_comment_bodies_are_skipped(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        feedback = PrFeedback(
            pr_number=13,
            pr_url="url",
            state="OPEN",
            review_decision="CHANGES_REQUESTED",
            comments=[PrReviewComment(id=1, author="a", body="")],
        )
        tasks = agent.create_pr_fix_tasks(feedback, "cantrip/feat")
        # Still generates a fix task even if all comments are empty.
        assert len(tasks) == 2


# ---------------------------------------------------------------------------
# _create_feature_branch
# ---------------------------------------------------------------------------


class TestCreateFeatureBranch:
    """``_create_feature_branch`` short-circuits when prerequisites are missing."""

    def test_returns_none_without_github_repo(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        assert agent._create_feature_branch("feat") is None

    def test_returns_none_without_charm_path(self) -> None:
        agent = _agent()
        agent.state.github_repo = "o/r"
        agent.state.charm_path = None
        assert agent._create_feature_branch("feat") is None

    def test_creates_branch_when_both_present(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        with patch(
            "cantrip.agent.core.create_branch",
            return_value="cantrip/feat",
        ):
            result = agent._create_feature_branch("feat")
        assert result == "cantrip/feat"


# ---------------------------------------------------------------------------
# handle_triage_confirmation
# ---------------------------------------------------------------------------


class TestHandleTriageConfirmation:
    """``handle_triage_confirmation`` turns an approved issue into work tasks."""

    def test_missing_confirm_task_returns_empty(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        assert agent.handle_triage_confirmation("triage-issue-99") == []

    def test_malformed_id_returns_empty(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        task = AgentTask(
            id="triage-issue-abc",
            title="Work on #abc: ?",
            category=TaskCategory.CONFIRM,
            description="",
        )
        agent.work_queue.add_task(task)
        assert agent.handle_triage_confirmation("triage-issue-abc") == []

    def test_happy_path_appends_push_confirm_when_branch_created(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        task = AgentTask(
            id="triage-issue-7",
            title="Work on #7: Broken login",
            category=TaskCategory.CONFIRM,
            description="Login is broken on firefox.",
        )
        agent.work_queue.add_task(task)

        work_task = AgentTask(
            id="triage-research-7",
            title="Research issue #7",
            category=TaskCategory.RESEARCH,
        )

        with (
            patch(
                "cantrip.agent.core.build_issue_work_tasks",
                return_value=[work_task],
            ),
            patch(
                "cantrip.agent.core.create_branch",
                return_value="cantrip/issue-7-broken-login",
            ),
        ):
            tasks = agent.handle_triage_confirmation("triage-issue-7")

        assert len(tasks) == 2
        assert tasks[-1].category == TaskCategory.CONFIRM
        assert "push-branch-cantrip/issue-7-broken-login" in tasks[-1].id

    def test_happy_path_without_branch_has_no_push_confirm(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        task = AgentTask(
            id="triage-issue-9",
            title="Work on #9: Docs",
            category=TaskCategory.CONFIRM,
            description="Docs typo.",
        )
        agent.work_queue.add_task(task)

        work_task = AgentTask(
            id="triage-research-9",
            title="Research",
            category=TaskCategory.RESEARCH,
        )
        with patch(
            "cantrip.agent.core.build_issue_work_tasks",
            return_value=[work_task],
        ):
            tasks = agent.handle_triage_confirmation("triage-issue-9")
        # No push-confirm (no github_repo → no branch).
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# Issue-triage worker lifecycle
# ---------------------------------------------------------------------------


class TestIssueTriageWorker:
    """``start_issue_triage`` / ``stop_issue_triage`` / ``retriage_issues``."""

    def test_start_without_repo_returns_false(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        assert agent.start_issue_triage() is False

    def test_start_second_time_returns_false(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        fake_triage = MagicMock()
        fake_triage.running = False
        agent._issue_triage = fake_triage
        assert agent.start_issue_triage() is False

    def test_start_happy_path(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        fake = MagicMock()
        with patch("cantrip.agent.core.IssueTriage", return_value=fake) as cls:
            assert agent.start_issue_triage() is True
        cls.assert_called_once()
        fake.start.assert_called_once()
        assert agent._issue_triage is fake

    @pytest.mark.asyncio
    async def test_stop_clears_worker(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        fake = MagicMock()

        async def _stop() -> None:
            return None

        fake.stop.side_effect = _stop
        agent._issue_triage = fake
        await agent.stop_issue_triage()
        assert agent._issue_triage is None

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_noop(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent._issue_triage = None
        await agent.stop_issue_triage()  # must not raise

    def test_issue_triage_running_reflects_state(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        assert agent.issue_triage_running is False
        fake = MagicMock()
        fake.running = True
        agent._issue_triage = fake
        assert agent.issue_triage_running is True

    def test_retriage_without_repo_returns_false(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = None
        assert agent.retriage_issues() is False

    def test_retriage_while_running_returns_false(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        existing = MagicMock()
        existing.running = True
        agent._issue_triage = existing
        assert agent.retriage_issues() is False

    def test_retriage_preserves_examined_set(self, tmp_path: Path) -> None:
        agent = _agent(tmp_path)
        agent.state.github_repo = "o/r"
        prev = MagicMock()
        prev.running = False
        prev.examined_issues = {1, 2, 3}
        agent._issue_triage = prev

        new_worker = MagicMock()
        with patch("cantrip.agent.core.IssueTriage", return_value=new_worker):
            assert agent.retriage_issues() is True
        assert new_worker._examined == {1, 2, 3}
        new_worker.start.assert_called_once()
