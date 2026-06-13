"""Targeted Pilot tests for the PR / maintenance-loop dispatch in CantripApp.

Phase 93.1 backfill for ``src/cantrip/tui/app.py``: the post-push PR
prompt and the comment / review / fix / re-triage loop that follows
were the largest single uncovered block in the TUI app module.  The
methods are pure dispatch — they read pending state, call into the
agent, and write system messages — so they exercise cleanly through
the headless Textual test harness.
"""

from unittest.mock import MagicMock

import pytest

from cantrip.agent.git.git_branch import PrFeedback, PrReviewComment
from cantrip.tui.app import CantripApp
from cantrip.tui.widgets import chat as chat_widget
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _system_messages(pilot) -> str:
    """Concatenated text of all system messages, for substring asserts."""
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


def _make_feedback(
    *,
    pr_number: int = 42,
    pr_url: str = "https://github.com/o/r/pull/42",
    state: str = "OPEN",
    review_decision: str = "",
    comments: list[PrReviewComment] | None = None,
) -> PrFeedback:
    """Build a real :class:`PrFeedback` instance — the dispatch reads the
    ``is_approved`` / ``needs_changes`` / ``comments`` properties, so a
    plain ``MagicMock`` would force every test to wire each attribute by
    hand.  Using the real dataclass keeps the tests honest about the
    review-decision semantics."""
    return PrFeedback(
        pr_number=pr_number,
        pr_url=pr_url,
        state=state,
        review_decision=review_decision,
        comments=comments or [],
    )


class TestPrResponse:
    """Every branch of ``_handle_pr_response``."""

    @pytest.mark.asyncio
    async def test_no_agent_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._pending_pr_branch = "feat"
                assert pilot.app._confirmations._handle_pr_response("pr") is False

    @pytest.mark.asyncio
    async def test_no_pending_branch_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = None
                assert pilot.app._confirmations._handle_pr_response("pr") is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["pr", "yes", "y", "ok", "PR", " Yes "])
    async def test_approve_tokens_create_pr_non_draft(self, token: str) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = None
        mock_agent.handle_pr_creation = MagicMock(return_value="PR opened: link")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = "feat"
                ok = pilot.app._confirmations._handle_pr_response(token)
                assert ok is True
                mock_agent.handle_pr_creation.assert_called_once_with("feat", draft=False)
                assert pilot.app._pending_pr_branch is None

    @pytest.mark.asyncio
    async def test_draft_token_passes_draft_true(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = None
        mock_agent.handle_pr_creation = MagicMock(return_value="Draft PR opened.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = "feat"
                pilot.app._confirmations._handle_pr_response("draft")
                mock_agent.handle_pr_creation.assert_called_once_with("feat", draft=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["skip", "no", "n", "SKIP", " No "])
    async def test_skip_tokens_offer_retriage_without_creating_pr(self, token: str) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = None  # short-circuits _offer_retriage
        mock_agent.handle_pr_creation = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = "feat"
                ok = pilot.app._confirmations._handle_pr_response(token)
                assert ok is True
                assert pilot.app._pending_pr_branch is None
                mock_agent.handle_pr_creation.assert_not_called()
                assert "PR creation skipped." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_unrelated_message_returns_false(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_pr_creation = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = "feat"
                assert pilot.app._confirmations._handle_pr_response("nonsense") is False
                # Branch is sticky on an unrelated message.
                assert pilot.app._pending_pr_branch == "feat"
                mock_agent.handle_pr_creation.assert_not_called()


class TestOfferMaintenanceContinuation:
    """Every branch of ``_offer_maintenance_continuation``."""

    @pytest.mark.asyncio
    async def test_no_agent_is_silent(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._confirmations._offer_maintenance_continuation("feat", "anything")
                assert pilot.app._pending_maintenance is None

    @pytest.mark.asyncio
    async def test_issue_branch_with_pr_url_arms_full_loop(self) -> None:
        """``issue-7-fix`` + a PR URL → full {comment, review, next, done} prompt."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_maintenance_continuation(
                    "issue-7-fix",
                    "Pushed: https://github.com/o/r/pull/42",
                )
                pending = pilot.app._pending_maintenance
                assert pending == {
                    "issue_number": 7,
                    "pr_url": "https://github.com/o/r/pull/42",
                    "pr_number": 42,
                    "branch": "issue-7-fix",
                }
                msgs = _system_messages(pilot)
                assert "**comment**" in msgs
                assert "issue #7" in msgs
                assert "**review**" in msgs

    @pytest.mark.asyncio
    async def test_no_issue_in_branch_falls_to_pr_only_loop(self) -> None:
        """Plain ``feat`` branch + PR URL → review-only prompt without
        a comment option."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_maintenance_continuation(
                    "feat",
                    "Pushed: https://github.com/o/r/pull/9",
                )
                pending = pilot.app._pending_maintenance
                assert pending == {
                    "pr_url": "https://github.com/o/r/pull/9",
                    "pr_number": 9,
                    "branch": "feat",
                }
                msgs = _system_messages(pilot)
                assert "**review**" in msgs
                assert "**comment**" not in msgs

    @pytest.mark.asyncio
    async def test_no_pr_url_falls_through_to_retriage(self) -> None:
        """No PR URL in *pr_result* → ``_offer_retriage`` takes over and
        sets the ``retriage_only`` sentinel."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = "o/r"
        mock_agent.check_upstream = MagicMock(return_value="")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_maintenance_continuation(
                    "issue-7-fix",
                    "Pushed but PR step skipped.",
                )
                assert pilot.app._pending_maintenance == {"retriage_only": True}


class TestOfferRetriage:
    """Every branch of ``_offer_retriage``."""

    @pytest.mark.asyncio
    async def test_no_agent_is_silent(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._confirmations._offer_retriage()
                assert pilot.app._pending_maintenance is None

    @pytest.mark.asyncio
    async def test_no_repo_is_silent(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = None
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_retriage()
                assert pilot.app._pending_maintenance is None
                assert "next" not in _system_messages(pilot).lower()

    @pytest.mark.asyncio
    async def test_clean_upstream_only_writes_prompt(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = "o/r"
        mock_agent.check_upstream = MagicMock(return_value="")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_retriage()
                msgs = _system_messages(pilot)
                assert "**next**" in msgs
                assert "**done**" in msgs
                assert pilot.app._pending_maintenance == {"retriage_only": True}

    @pytest.mark.asyncio
    async def test_upstream_warning_is_surfaced_before_prompt(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.github_repo = "o/r"
        mock_agent.check_upstream = MagicMock(return_value="Upstream has moved on.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._confirmations._offer_retriage()
                msgs = _system_messages(pilot)
                assert "Upstream has moved on." in msgs
                assert "**next**" in msgs
                assert pilot.app._pending_maintenance == {"retriage_only": True}


class TestMaintenanceResponse:
    """Every branch of ``_handle_maintenance_response``."""

    @pytest.mark.asyncio
    async def test_no_agent_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._pending_maintenance = {"retriage_only": True}
                assert pilot.app._confirmations._handle_maintenance_response("next") is False

    @pytest.mark.asyncio
    async def test_no_pending_state_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = None
                assert pilot.app._confirmations._handle_maintenance_response("next") is False

    # --- "comment" -----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_comment_with_pr_number_transitions_to_review_prompt(self) -> None:
        """``comment`` posts to the issue and stays armed for ``review``."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.comment_on_issue = MagicMock(return_value="Commented on issue #7.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {
                    "issue_number": 7,
                    "pr_url": "https://github.com/o/r/pull/42",
                    "pr_number": 42,
                    "branch": "issue-7-fix",
                }
                ok = pilot.app._confirmations._handle_maintenance_response("comment")
                assert ok is True
                mock_agent.comment_on_issue.assert_called_once_with(
                    7, "https://github.com/o/r/pull/42"
                )
                # ``issue_number`` is consumed; pr_number / pr_url / branch persist.
                assert pilot.app._pending_maintenance == {
                    "pr_url": "https://github.com/o/r/pull/42",
                    "pr_number": 42,
                    "branch": "issue-7-fix",
                }
                msgs = _system_messages(pilot)
                assert "Commented on issue #7." in msgs
                assert "**review**" in msgs

    @pytest.mark.asyncio
    async def test_comment_without_pr_number_collapses_to_retriage_only(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.comment_on_issue = MagicMock(return_value="ok")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {
                    "issue_number": 7,
                    "branch": "issue-7-fix",
                }
                pilot.app._confirmations._handle_maintenance_response("comment")
                assert pilot.app._pending_maintenance == {"retriage_only": True}
                # Default pr_url falls back to the empty string when missing.
                mock_agent.comment_on_issue.assert_called_once_with(7, "")

    @pytest.mark.asyncio
    async def test_comment_without_issue_number_falls_through(self) -> None:
        """``comment`` only fires when an ``issue_number`` is pending."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.comment_on_issue = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                assert pilot.app._confirmations._handle_maintenance_response("comment") is False
                mock_agent.comment_on_issue.assert_not_called()

    # --- "review" ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_review_handles_fetch_failure(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock(return_value=None)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"pr_number": 42, "branch": "feat"}
                pilot.app._confirmations._handle_maintenance_response("review")
                assert "Could not fetch feedback for PR #42." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_review_approved_collapses_to_retriage(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock(
            return_value=_make_feedback(review_decision="APPROVED")
        )
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"pr_number": 42, "branch": "feat"}
                pilot.app._confirmations._handle_maintenance_response("review")
                assert "**approved**" in _system_messages(pilot)
                assert pilot.app._pending_maintenance == {"retriage_only": True}

    @pytest.mark.asyncio
    async def test_review_changes_requested_arms_fix_state(self) -> None:
        feedback = _make_feedback(
            review_decision="CHANGES_REQUESTED",
            comments=[PrReviewComment(id=1, author="reviewer", body="please fix")],
        )
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock(return_value=feedback)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"pr_number": 42, "branch": "feat"}
                pilot.app._confirmations._handle_maintenance_response("review")
                assert pilot.app._pending_maintenance == {
                    "awaiting_fix": True,
                    "pr_number": 42,
                    "branch": "feat",
                    "feedback": feedback,
                }
                msgs = _system_messages(pilot)
                assert "**fix**" in msgs
                assert "**skip**" in msgs

    @pytest.mark.asyncio
    async def test_review_comments_without_changes_request_is_informational(self) -> None:
        feedback = _make_feedback(
            review_decision="",
            comments=[PrReviewComment(id=1, author="x", body="nit")],
        )
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock(return_value=feedback)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"pr_number": 42, "branch": "feat"}
                pilot.app._confirmations._handle_maintenance_response("review")
                assert pilot.app._pending_maintenance == {"retriage_only": True}
                # The formatted feedback summary is rendered to chat.
                assert "PR #42" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_review_no_comments_yet(self) -> None:
        feedback = _make_feedback(review_decision="REVIEW_REQUIRED", comments=[])
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock(return_value=feedback)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"pr_number": 42, "branch": "feat"}
                pilot.app._confirmations._handle_maintenance_response("review")
                assert "no review comments yet" in _system_messages(pilot)
                assert pilot.app._pending_maintenance == {"retriage_only": True}

    @pytest.mark.asyncio
    async def test_review_without_pr_number_falls_through(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.check_pr_feedback = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                assert pilot.app._confirmations._handle_maintenance_response("review") is False
                mock_agent.check_pr_feedback.assert_not_called()

    # --- "fix" ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fix_creates_tasks_when_feedback_present(self) -> None:
        feedback = _make_feedback(review_decision="CHANGES_REQUESTED")
        p1, p2, mock_agent = _patch_app()
        task = MagicMock()
        task.title = "Address review nit"
        mock_agent.create_pr_fix_tasks = MagicMock(return_value=[task])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {
                    "awaiting_fix": True,
                    "pr_number": 42,
                    "branch": "feat",
                    "feedback": feedback,
                }
                pilot.app._confirmations._handle_maintenance_response("fix")
                mock_agent.create_pr_fix_tasks.assert_called_once_with(feedback, "feat")
                assert pilot.app._pending_maintenance is None
                assert "Address review nit" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_fix_with_no_resulting_tasks_reports_failure(self) -> None:
        feedback = _make_feedback(review_decision="CHANGES_REQUESTED")
        p1, p2, mock_agent = _patch_app()
        mock_agent.create_pr_fix_tasks = MagicMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {
                    "awaiting_fix": True,
                    "pr_number": 42,
                    "branch": "feat",
                    "feedback": feedback,
                }
                pilot.app._confirmations._handle_maintenance_response("fix")
                assert "Could not create fix tasks." in _system_messages(pilot)
                assert pilot.app._pending_maintenance is None

    @pytest.mark.asyncio
    async def test_fix_without_feedback_clears_state_silently(self) -> None:
        """``awaiting_fix`` without a ``feedback`` payload still consumes
        the state — the inner branch is a defensive no-op rather than
        raising."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.create_pr_fix_tasks = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {
                    "awaiting_fix": True,
                    "pr_number": 42,
                    "branch": "feat",
                }
                ok = pilot.app._confirmations._handle_maintenance_response("fix")
                assert ok is True
                mock_agent.create_pr_fix_tasks.assert_not_called()
                assert pilot.app._pending_maintenance is None

    @pytest.mark.asyncio
    async def test_fix_without_awaiting_flag_falls_through(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.create_pr_fix_tasks = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                assert pilot.app._confirmations._handle_maintenance_response("fix") is False

    # --- "next" / "more" / terminators / unrelated ---------------------------

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["next", "more"])
    async def test_next_kicks_off_retriage_when_started(self, token: str) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.retriage_issues = MagicMock(return_value=True)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                pilot.app._confirmations._handle_maintenance_response(token)
                mock_agent.retriage_issues.assert_called_once()
                assert pilot.app._pending_maintenance is None
                assert "Checking for new issues" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_next_reports_when_no_issues_started(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.retriage_issues = MagicMock(return_value=False)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                pilot.app._confirmations._handle_maintenance_response("next")
                assert "No new issues to check." in _system_messages(pilot)
                assert pilot.app._pending_maintenance is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["done", "stop", "skip", "no", "n"])
    async def test_terminator_tokens_clear_state(self, token: str) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                ok = pilot.app._confirmations._handle_maintenance_response(token)
                assert ok is True
                assert pilot.app._pending_maintenance is None
                assert "Maintenance loop stopped." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_unrelated_message_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"retriage_only": True}
                assert (
                    pilot.app._confirmations._handle_maintenance_response("hello there") is False
                )
                # State is sticky on an unrelated reply.
                assert pilot.app._pending_maintenance == {"retriage_only": True}
