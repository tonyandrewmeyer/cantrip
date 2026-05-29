"""Tests for git branch operations (Phase 42.3)."""

import subprocess
from unittest import mock

from cantrip.agent.git.git_branch import (
    BRANCH_PREFIX,
    PrFeedback,
    PrReviewComment,
    bootstrap_github_repo,
    build_pr_body,
    can_bootstrap,
    check_upstream_diverged,
    create_branch,
    create_pull_request,
    current_branch,
    gh_available,
    gh_issue_comment,
    gh_pr_view,
    git_init,
    has_git_repo,
    has_remote,
    push_branch,
    slugify,
    switch_branch,
)
from tests.support.git_fakes import FakeTask

# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    """Tests for slugify()."""

    def test_simple_text(self) -> None:
        assert slugify("Add PostgreSQL integration") == "add-postgresql-integration"

    def test_special_characters(self) -> None:
        assert slugify("Fix #42: widget bug!") == "fix-42-widget-bug"

    def test_truncation(self) -> None:
        result = slugify("a" * 100, max_length=20)
        assert len(result) <= 20

    def test_trailing_hyphens_stripped(self) -> None:
        # Truncation might leave a trailing hyphen.
        result = slugify("hello-world-foo", max_length=11)
        assert not result.endswith("-")

    def test_empty_string(self) -> None:
        assert slugify("") == ""

    def test_only_special_chars(self) -> None:
        assert slugify("!@#$%") == ""


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------


class TestCurrentBranch:
    """Tests for current_branch()."""

    def test_returns_branch_name(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert current_branch("/path") == "main"

    def test_returns_none_on_failure(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert current_branch("/path") is None

    def test_returns_none_on_detached_head(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="HEAD\n")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert current_branch("/path") is None

    def test_returns_none_on_timeout(self) -> None:
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
        ):
            assert current_branch("/path") is None


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    """Tests for create_branch()."""

    def test_creates_branch_with_prefix(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m:
            branch = create_branch("/path", "Add PostgreSQL")
            assert branch == f"{BRANCH_PREFIX}add-postgresql"
            cmd = m.call_args[0][0]
            assert cmd == ["git", "checkout", "-b", f"{BRANCH_PREFIX}add-postgresql"]

    def test_returns_none_on_failure(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="branch already exists"
        )
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert create_branch("/path", "existing") is None

    def test_empty_description_uses_fallback(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m:
            branch = create_branch("/path", "!@#")
            assert branch == f"{BRANCH_PREFIX}change"
            cmd = m.call_args[0][0]
            assert f"{BRANCH_PREFIX}change" in cmd

    def test_returns_none_on_timeout(self) -> None:
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
        ):
            assert create_branch("/path", "test") is None


# ---------------------------------------------------------------------------
# switch_branch
# ---------------------------------------------------------------------------


class TestSwitchBranch:
    """Tests for switch_branch()."""

    def test_success(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert switch_branch("/path", "cantrip/fix") is True

    def test_failure(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert switch_branch("/path", "nonexistent") is False


# ---------------------------------------------------------------------------
# push_branch
# ---------------------------------------------------------------------------


class TestPushBranch:
    """Tests for push_branch()."""

    def test_success(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="branch set up to track"
        )
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            ok, msg = push_branch("/path", "cantrip/fix")
            assert ok is True
            assert "branch set up to track" in msg

    def test_failure(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="permission denied"
        )
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            ok, msg = push_branch("/path", "cantrip/fix")
            assert ok is False
            assert "permission denied" in msg

    def test_uses_set_upstream(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m:
            push_branch("/path", "cantrip/fix", remote="upstream")
            cmd = m.call_args[0][0]
            assert "-u" in cmd
            assert "upstream" in cmd
            assert "cantrip/fix" in cmd

    def test_timeout(self) -> None:
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            ok, msg = push_branch("/path", "cantrip/fix")
            assert ok is False


# ---------------------------------------------------------------------------
# create_pull_request
# ---------------------------------------------------------------------------


class TestCreatePullRequest:
    """Tests for create_pull_request()."""

    def test_no_gh_binary(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value=None):
            ok, msg = create_pull_request("/path", "Title", "Body")
            assert ok is False
            assert "not found" in msg

    def test_success(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/owner/repo/pull/1\n", stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            ok, url = create_pull_request("/path", "Fix bug", "Description")
            assert ok is True
            assert "pull/1" in url

    def test_failure(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no commits between main and branch"
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            ok, msg = create_pull_request("/path", "Title", "Body")
            assert ok is False
            assert "no commits" in msg

    def test_draft_flag(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/o/r/pull/2\n", stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m,
        ):
            create_pull_request("/path", "Title", "Body", draft=True)
            cmd = m.call_args[0][0]
            assert "--draft" in cmd

    def test_base_branch(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/o/r/pull/3\n", stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m,
        ):
            create_pull_request("/path", "Title", "Body", base="develop")
            cmd = m.call_args[0][0]
            assert "--base" in cmd
            idx = cmd.index("--base")
            assert cmd[idx + 1] == "develop"


# ---------------------------------------------------------------------------
# build_pr_body
# ---------------------------------------------------------------------------


class TestBuildPrBody:
    """Tests for build_pr_body()."""

    def test_includes_issue_reference(self) -> None:
        body = build_pr_body([], issue_number=42, repo="owner/repo")
        assert "#42" in body

    def test_includes_task_summaries(self) -> None:
        tasks = [
            FakeTask(title="Research bug", category="research", status="done"),
            FakeTask(title="Fix bug", category="build", status="done"),
        ]
        body = build_pr_body(tasks)
        assert "Research bug" in body
        assert "Fix bug" in body

    def test_includes_cantrip_attribution(self) -> None:
        body = build_pr_body([])
        assert "Cantrip" in body

    def test_includes_collapsible_details(self) -> None:
        tasks = [FakeTask(title="Fix", category="build", result="Changed files X and Y")]
        body = build_pr_body(tasks)
        assert "<details>" in body
        assert "Changed files X and Y" in body

    def test_truncates_long_results(self) -> None:
        tasks = [FakeTask(title="Fix", category="build", result="x" * 1000)]
        body = build_pr_body(tasks)
        assert "truncated" in body


# ---------------------------------------------------------------------------
# has_git_repo / has_remote / gh_available
# ---------------------------------------------------------------------------


class TestHasGitRepo:
    """Tests for has_git_repo()."""

    def test_true_when_git_dir_exists(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=".git\n")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert has_git_repo("/path") is True

    def test_false_when_not_a_repo(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert has_git_repo("/path") is False

    def test_false_on_timeout(self) -> None:
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
        ):
            assert has_git_repo("/path") is False


class TestHasRemote:
    """Tests for has_remote()."""

    def test_true_when_origin_exists(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/o/r.git\n"
        )
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert has_remote("/path") is True

    def test_false_when_no_origin(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=2, stdout="")
        with mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result):
            assert has_remote("/path") is False


class TestGhAvailable:
    """Tests for gh_available()."""

    def test_true_when_installed_and_authenticated(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            assert gh_available() is True

    def test_false_when_not_installed(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value=None):
            assert gh_available() is False

    def test_false_when_not_authenticated(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            assert gh_available() is False


# ---------------------------------------------------------------------------
# git_init / can_bootstrap
# ---------------------------------------------------------------------------


class TestGitInit:
    """Tests for git_init()."""

    def test_skips_if_already_repo(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=True):
            assert git_init("/path") is True

    def test_inits_new_repo(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with (
            mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=False),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            assert git_init("/path") is True


class TestCanBootstrap:
    """Tests for can_bootstrap()."""

    def test_false_when_no_path(self) -> None:
        assert can_bootstrap(None) is False

    def test_false_when_remote_exists(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.has_remote", return_value=True):
            assert can_bootstrap("/path") is False

    def test_false_when_gh_unavailable(self) -> None:
        with (
            mock.patch("cantrip.agent.git.git_branch.has_remote", return_value=False),
            mock.patch("cantrip.agent.git.git_branch.gh_available", return_value=False),
        ):
            assert can_bootstrap("/path") is False

    def test_true_when_conditions_met(self) -> None:
        with (
            mock.patch("cantrip.agent.git.git_branch.has_remote", return_value=False),
            mock.patch("cantrip.agent.git.git_branch.gh_available", return_value=True),
        ):
            assert can_bootstrap("/path") is True


# ---------------------------------------------------------------------------
# bootstrap_github_repo
# ---------------------------------------------------------------------------


class TestBootstrapGithubRepo:
    """Tests for bootstrap_github_repo()."""

    def test_success(self) -> None:
        gh_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="https://github.com/user/my-charm\n",
            stderr="",
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=True),
            mock.patch("cantrip.agent.git.git_branch._has_commits", return_value=True),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=gh_result),
        ):
            ok, msg = bootstrap_github_repo("/path", "my-charm")
            assert ok is True
            assert "my-charm" in msg

    def test_failure(self) -> None:
        gh_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="name already exists"
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=True),
            mock.patch("cantrip.agent.git.git_branch._has_commits", return_value=True),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=gh_result),
        ):
            ok, msg = bootstrap_github_repo("/path", "my-charm")
            assert ok is False
            assert "already exists" in msg

    def test_inits_repo_when_missing(self) -> None:
        init_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        add_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        commit_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        gh_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/u/r\n", stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=False),
            mock.patch(
                "cantrip.agent.git.git_branch.subprocess.run",
                side_effect=[init_result, add_result, commit_result, gh_result],
            ),
        ):
            ok, msg = bootstrap_github_repo("/path", "my-charm")
            assert ok is True

    def test_uses_org_prefix(self) -> None:
        gh_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/canonical/my-charm\n", stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.has_git_repo", return_value=True),
            mock.patch("cantrip.agent.git.git_branch._has_commits", return_value=True),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=gh_result) as m,
        ):
            bootstrap_github_repo("/path", "my-charm", org="canonical")
            cmd = m.call_args[0][0]
            assert "canonical/my-charm" in cmd


# ---------------------------------------------------------------------------
# check_upstream_diverged
# ---------------------------------------------------------------------------


class TestCheckUpstreamDiverged:
    """Tests for check_upstream_diverged()."""

    def test_not_diverged(self) -> None:
        fetch_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        count_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="0\n")
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=[fetch_result, count_result],
        ):
            diverged, behind = check_upstream_diverged("/path")
            assert diverged is False
            assert behind == 0

    def test_diverged(self) -> None:
        fetch_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        count_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="3\n")
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=[fetch_result, count_result],
        ):
            diverged, behind = check_upstream_diverged("/path")
            assert diverged is True
            assert behind == 3

    def test_fetch_fails_gracefully(self) -> None:
        with mock.patch(
            "cantrip.agent.git.git_branch.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            diverged, behind = check_upstream_diverged("/path")
            assert diverged is False


# ---------------------------------------------------------------------------
# gh_issue_comment
# ---------------------------------------------------------------------------


class TestGhIssueComment:
    """Tests for gh_issue_comment()."""

    def test_success(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            ok, msg = gh_issue_comment("owner/repo", 42, "Fixed!")
            assert ok is True

    def test_failure(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="not found")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            ok, msg = gh_issue_comment("owner/repo", 42, "Fixed!")
            assert ok is False
            assert "not found" in msg

    def test_no_gh(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value=None):
            ok, msg = gh_issue_comment("owner/repo", 42, "Fixed!")
            assert ok is False

    def test_passes_correct_args(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result) as m,
        ):
            gh_issue_comment("owner/repo", 99, "Done")
            cmd = m.call_args[0][0]
            assert "99" in cmd
            assert "--repo" in cmd
            assert "owner/repo" in cmd


# ---------------------------------------------------------------------------
# gh_pr_view
# ---------------------------------------------------------------------------


class TestGhPrView:
    """Tests for gh_pr_view()."""

    def test_no_gh(self) -> None:
        with mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value=None):
            assert gh_pr_view("owner/repo", 1) is None

    def test_command_failure(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="not found")
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            assert gh_pr_view("owner/repo", 1) is None

    def test_parses_feedback(self) -> None:
        import json

        data = {
            "number": 42,
            "url": "https://github.com/owner/repo/pull/42",
            "state": "OPEN",
            "reviewDecision": "CHANGES_REQUESTED",
            "reviews": [
                {
                    "id": 1,
                    "author": {"login": "reviewer"},
                    "body": "Please fix the typo",
                    "state": "CHANGES_REQUESTED",
                }
            ],
            "comments": [
                {
                    "id": 2,
                    "author": {"login": "bot"},
                    "body": "CI passed",
                }
            ],
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            feedback = gh_pr_view("owner/repo", 42)

        assert feedback is not None
        assert feedback.pr_number == 42
        assert feedback.state == "OPEN"
        assert feedback.needs_changes is True
        assert feedback.is_approved is False
        assert len(feedback.comments) == 2
        assert feedback.comments[0].author == "reviewer"
        assert feedback.comments[1].body == "CI passed"

    def test_approved_pr(self) -> None:
        import json

        data = {
            "number": 10,
            "url": "https://github.com/o/r/pull/10",
            "state": "OPEN",
            "reviewDecision": "APPROVED",
            "reviews": [],
            "comments": [],
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with (
            mock.patch("cantrip.agent.git.git_branch.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.git.git_branch.subprocess.run", return_value=result),
        ):
            feedback = gh_pr_view("owner/repo", 10)

        assert feedback is not None
        assert feedback.is_approved is True
        assert feedback.needs_changes is False


# ---------------------------------------------------------------------------
# PrFeedback
# ---------------------------------------------------------------------------


class TestPrFeedback:
    """Tests for PrFeedback data class."""

    def test_format_for_chat_no_comments(self) -> None:
        fb = PrFeedback(pr_number=1, pr_url="", state="OPEN", review_decision="")
        text = fb.format_for_chat()
        assert "No review comments" in text

    def test_format_for_chat_with_comments(self) -> None:
        fb = PrFeedback(
            pr_number=5,
            pr_url="",
            state="OPEN",
            review_decision="CHANGES_REQUESTED",
            comments=[
                PrReviewComment(
                    id=1, author="alice", body="Fix this", path="src/main.py", line=10
                ),
            ],
        )
        text = fb.format_for_chat()
        assert "alice" in text
        assert "Fix this" in text
        assert "src/main.py:10" in text
        assert "CHANGES_REQUESTED" in text
