"""Branch-coverage backfill for ``cantrip.agent.git_branch``.

The base ``test_git_branch.py`` covers the success paths and several
common failures.  This file targets the remaining subprocess /
gh-shell-out failure arms: TimeoutExpired / OSError / FileNotFoundError
and a handful of failure-rc branches that don't reach a real git repo.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from cantrip.agent import git_branch as gb
from tests.support.git_fakes import FakeTask


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# switch_branch
# ---------------------------------------------------------------------------


class TestSuggestRepoName:
    """Default GitHub repo name conventions."""

    def test_appends_operator_suffix(self) -> None:
        assert gb.suggest_repo_name("foo") == "foo-operator"

    def test_does_not_double_append_for_known_suffixes(self) -> None:
        assert gb.suggest_repo_name("foo-charm") == "foo-charm"
        assert gb.suggest_repo_name("foo-operator") == "foo-operator"
        assert gb.suggest_repo_name("foo-k8s") == "foo-k8s"
        assert gb.suggest_repo_name("foo-machine") == "foo-machine"

    def test_empty_or_whitespace_returns_unchanged(self) -> None:
        assert gb.suggest_repo_name("") == ""
        assert gb.suggest_repo_name("   ") == "   "


class TestBuildPrBodyIssueOnly:
    """Issue number with no repo lands in the alternate phrasing."""

    def test_issue_only_uses_addresses_phrasing(self) -> None:
        body = gb.build_pr_body([], issue_number=42)
        assert "Addresses issue #42" in body


class TestSwitchBranchExceptions:
    """``switch_branch`` failure arms."""

    def test_timeout_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1),
        ):
            assert gb.switch_branch(".", "feat/x") is False

    def test_oserror_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert gb.switch_branch(".", "feat/x") is False


# ---------------------------------------------------------------------------
# create_pull_request — exception path and base/draft flags
# ---------------------------------------------------------------------------


class TestCreatePullRequestExceptions:
    """``create_pull_request`` exception path and rc != 0."""

    def test_subprocess_oserror(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            ok, msg = gb.create_pull_request(".", "title", "body")
        assert ok is False
        assert "eperm" in msg


# ---------------------------------------------------------------------------
# build_pr_body — failed-status icon and truncation
# ---------------------------------------------------------------------------


class TestBuildPrBodyBranches:
    """Failed-task icon and result-truncation branches."""

    def test_failed_task_uses_cross_icon(self) -> None:
        body = gb.build_pr_body(
            [FakeTask(title="t1", category="BUILD", status="failed")],
        )
        assert "✗" in body

    def test_blocked_task_uses_circle_icon(self) -> None:
        body = gb.build_pr_body(
            [FakeTask(title="t1", category="BUILD", status="blocked")],
        )
        assert "○" in body

    def test_task_without_title_is_skipped(self) -> None:
        body = gb.build_pr_body(
            [FakeTask(title="", category="BUILD", status="done")],
        )
        # No bullet entry should appear because the title was missing.
        assert "**BUILD**" not in body


# ---------------------------------------------------------------------------
# has_remote / gh_available exception paths
# ---------------------------------------------------------------------------


class TestHasRemoteExceptions:
    def test_timeout_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1),
        ):
            assert gb.has_remote(".") is False

    def test_oserror_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert gb.has_remote(".") is False


class TestGhAvailableExceptions:
    def test_no_gh_binary(self) -> None:
        with patch("cantrip.agent.git_branch.shutil.which", return_value=None):
            assert gb.gh_available() is False

    def test_subprocess_error(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            assert gb.gh_available() is False


# ---------------------------------------------------------------------------
# git_init / git_add_and_commit
# ---------------------------------------------------------------------------


class TestGitInitExceptions:
    def test_subprocess_error_returns_false(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=False),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            assert gb.git_init(".") is False


class TestGitAddAndCommit:
    def test_add_failure_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            return_value=_proc(returncode=1, stderr="lock"),
        ):
            assert gb.git_add_and_commit(".", "init") is False

    def test_subprocess_exception_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert gb.git_add_and_commit(".", "init") is False


# ---------------------------------------------------------------------------
# bootstrap_github_repo failure routes
# ---------------------------------------------------------------------------


class TestBootstrapGithubRepo:
    """``bootstrap_github_repo`` failure routes."""

    def test_init_failure(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=False),
            patch("cantrip.agent.git_branch.git_init", return_value=False),
        ):
            ok, msg = gb.bootstrap_github_repo(".", "myrepo")
        assert ok is False
        assert "Failed to initialise" in msg

    def test_initial_commit_failure_after_init(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=False),
            patch("cantrip.agent.git_branch.git_init", return_value=True),
            patch("cantrip.agent.git_branch.git_add_and_commit", return_value=False),
        ):
            ok, msg = gb.bootstrap_github_repo(".", "myrepo")
        assert ok is False
        assert "initial commit" in msg.lower()

    def test_initial_commit_failure_when_repo_has_no_commits(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=True),
            patch("cantrip.agent.git_branch._has_commits", return_value=False),
            patch("cantrip.agent.git_branch.git_add_and_commit", return_value=False),
        ):
            ok, msg = gb.bootstrap_github_repo(".", "myrepo")
        assert ok is False
        assert "initial commit" in msg.lower()

    def test_gh_subprocess_error(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=True),
            patch("cantrip.agent.git_branch._has_commits", return_value=True),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            ok, msg = gb.bootstrap_github_repo(".", "myrepo")
        assert ok is False
        assert "eperm" in msg

    def test_org_prefix_is_threaded(self) -> None:
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0, stdout="https://github.com/canon/myrepo")

        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=True),
            patch("cantrip.agent.git_branch._has_commits", return_value=True),
            patch("cantrip.agent.git_branch.subprocess.run", side_effect=_mock_run),
        ):
            ok, url = gb.bootstrap_github_repo(
                ".",
                "myrepo",
                org="canon",
                description="A charm",
            )
        assert ok is True
        cmd = captured[0]
        assert "canon/myrepo" in cmd
        assert "--description" in cmd

    def test_public_flag(self) -> None:
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0, stdout="https://github.com/x/y")

        with (
            patch("cantrip.agent.git_branch.has_git_repo", return_value=True),
            patch("cantrip.agent.git_branch._has_commits", return_value=True),
            patch("cantrip.agent.git_branch.subprocess.run", side_effect=_mock_run),
        ):
            gb.bootstrap_github_repo(".", "myrepo", private=False)
        assert "--public" in captured[0]


# ---------------------------------------------------------------------------
# _has_commits exceptions
# ---------------------------------------------------------------------------


class TestHasCommits:
    def test_oserror_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert gb._has_commits(".") is False

    def test_returns_true_when_rev_parse_succeeds(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            return_value=_proc(returncode=0),
        ):
            assert gb._has_commits(".") is True


# ---------------------------------------------------------------------------
# check_upstream_diverged
# ---------------------------------------------------------------------------


class TestCheckUpstreamDiverged:
    """All failure / parse arms in ``check_upstream_diverged``."""

    def test_fetch_failure_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=OSError("offline"),
        ):
            assert gb.check_upstream_diverged(".") == (False, 0)

    def test_rev_list_failure_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=[
                _proc(returncode=0),  # fetch
                OSError("eperm"),  # rev-list
            ],
        ):
            assert gb.check_upstream_diverged(".") == (False, 0)

    def test_rev_list_non_zero_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=[
                _proc(returncode=0),  # fetch
                _proc(returncode=128),  # rev-list
            ],
        ):
            assert gb.check_upstream_diverged(".") == (False, 0)

    def test_invalid_count_returns_false(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=[
                _proc(returncode=0),
                _proc(returncode=0, stdout="not-a-number"),
            ],
        ):
            assert gb.check_upstream_diverged(".") == (False, 0)

    def test_diverged_count_returned(self) -> None:
        with patch(
            "cantrip.agent.git_branch.subprocess.run",
            side_effect=[
                _proc(returncode=0),
                _proc(returncode=0, stdout="3"),
            ],
        ):
            assert gb.check_upstream_diverged(".") == (True, 3)


# ---------------------------------------------------------------------------
# gh_issue_comment
# ---------------------------------------------------------------------------


class TestGhIssueComment:
    """``gh_issue_comment`` failure arms."""

    def test_no_gh_binary(self) -> None:
        with patch("cantrip.agent.git_branch.shutil.which", return_value=None):
            ok, msg = gb.gh_issue_comment("o/r", 1, "hi")
        assert ok is False
        assert "gh CLI not found" in msg

    def test_subprocess_error(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            ok, msg = gb.gh_issue_comment("o/r", 1, "hi")
        assert ok is False
        assert "eperm" in msg

    def test_non_zero_rc_returns_failure(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                return_value=_proc(returncode=1, stderr="rate limited"),
            ),
        ):
            ok, msg = gb.gh_issue_comment("o/r", 1, "hi")
        assert ok is False
        assert "rate limited" in msg


# ---------------------------------------------------------------------------
# gh_pr_view
# ---------------------------------------------------------------------------


class TestGhPrView:
    """``gh_pr_view`` failure arms and parsing branches."""

    def test_no_gh_binary(self) -> None:
        with patch("cantrip.agent.git_branch.shutil.which", return_value=None):
            assert gb.gh_pr_view("o/r", 1) is None

    def test_subprocess_error(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            assert gb.gh_pr_view("o/r", 1) is None

    def test_non_zero_returncode(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                return_value=_proc(returncode=1),
            ),
        ):
            assert gb.gh_pr_view("o/r", 1) is None

    def test_invalid_json(self) -> None:
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                return_value=_proc(returncode=0, stdout="not json"),
            ),
        ):
            assert gb.gh_pr_view("o/r", 1) is None

    def test_aggregates_reviews_and_comments(self) -> None:
        payload = {
            "number": 42,
            "url": "https://github.com/o/r/pull/42",
            "state": "OPEN",
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "id": 1,
                    "body": "looks good",
                    "state": "APPROVED",
                    "author": {"login": "alice"},
                },
                {
                    "id": 2,
                    "body": "",  # empty bodies are skipped
                    "author": {"login": "bob"},
                },
            ],
            "comments": [
                {
                    "id": 3,
                    "body": "nit: rename",
                    "author": {"login": "carol"},
                },
                {
                    "id": 4,
                    "body": "",  # also skipped
                    "author": {"login": "dave"},
                },
            ],
        }
        with (
            patch("cantrip.agent.git_branch.shutil.which", return_value="/bin/gh"),
            patch(
                "cantrip.agent.git_branch.subprocess.run",
                return_value=_proc(returncode=0, stdout=json.dumps(payload)),
            ),
        ):
            feedback = gb.gh_pr_view("o/r", 42)
        assert feedback is not None
        assert feedback.pr_number == 42
        assert feedback.is_approved is True
        # Empty-body reviews / comments are filtered.
        assert len(feedback.comments) == 2
        authors = {c.author for c in feedback.comments}
        assert authors == {"alice", "carol"}


# ---------------------------------------------------------------------------
# can_bootstrap
# ---------------------------------------------------------------------------


class TestCanBootstrap:
    """``can_bootstrap`` decision logic."""

    def test_no_path_returns_false(self) -> None:
        assert gb.can_bootstrap(None) is False

    def test_existing_remote_returns_false(self) -> None:
        with patch("cantrip.agent.git_branch.has_remote", return_value=True):
            assert gb.can_bootstrap(".") is False

    def test_no_remote_no_gh_returns_false(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_remote", return_value=False),
            patch("cantrip.agent.git_branch.gh_available", return_value=False),
        ):
            assert gb.can_bootstrap(".") is False

    def test_no_remote_gh_present_returns_true(self) -> None:
        with (
            patch("cantrip.agent.git_branch.has_remote", return_value=False),
            patch("cantrip.agent.git_branch.gh_available", return_value=True),
        ):
            assert gb.can_bootstrap(".") is True


# ---------------------------------------------------------------------------
# PrFeedback formatting
# ---------------------------------------------------------------------------


class TestPrFeedbackFormatting:
    """``PrFeedback.format_for_chat`` body shapes."""

    def test_no_review_decision(self) -> None:
        fb = gb.PrFeedback(
            pr_number=1,
            pr_url="u",
            state="OPEN",
            review_decision="",
        )
        out = fb.format_for_chat()
        # No "(APPROVED)" suffix because review_decision is blank.
        assert "PR #1" in out
        assert "OPEN" in out
        assert "(" not in out.split("\n")[0]

    def test_with_comments(self) -> None:
        fb = gb.PrFeedback(
            pr_number=1,
            pr_url="u",
            state="OPEN",
            review_decision="APPROVED",
            comments=[
                gb.PrReviewComment(
                    id=1,
                    author="alice",
                    body="rename this",
                    path="src/foo.py",
                    line=42,
                ),
            ],
        )
        out = fb.format_for_chat()
        assert "src/foo.py:42" in out
        assert "alice" in out

    def test_no_comments_default_message(self) -> None:
        fb = gb.PrFeedback(
            pr_number=1,
            pr_url="u",
            state="OPEN",
            review_decision="REVIEW_REQUIRED",
        )
        assert "No review comments" in fb.format_for_chat()
