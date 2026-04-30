"""Tests for GitHub CLI tools."""

import json
import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.github import (
    GhIssueListTool,
    GhPrCreateTool,
    GhRepoBootstrapTool,
    GhRepoCreateTool,
    _check_gh_auth,
)

# All tests that exercise the actual gh command (rather than the auth pre-check)
# patch _check_gh_auth to return None so the auth gate is skipped.
_PATCH_AUTH_OK = mock.patch("cantrip.agent.tools.github._check_gh_auth", return_value=None)


class TestCheckGhAuth:
    """Tests for the _check_gh_auth helper."""

    def test_authenticated(self):
        """Returns None when gh auth status succeeds."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0

        with mock.patch(
            "cantrip.agent.tools.github.subprocess.run",
            return_value=mock_result,
        ):
            assert _check_gh_auth() is None

    def test_not_authenticated(self):
        """Returns an error message when gh auth status fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "not logged in"

        with mock.patch(
            "cantrip.agent.tools.github.subprocess.run",
            return_value=mock_result,
        ):
            err = _check_gh_auth()

        assert err is not None
        assert "gh auth login" in err

    def test_timeout(self):
        """Returns an error message when auth status check times out."""
        with mock.patch(
            "cantrip.agent.tools.github.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=10),
        ):
            err = _check_gh_auth()

        assert err is not None
        assert "Timed out" in err


class TestGhRepoCreateTool:
    """Tests for GhRepoCreateTool."""

    @pytest.fixture
    def tool(self):
        return GhRepoCreateTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool):
        """Error when gh CLI is not on PATH."""
        with mock.patch("cantrip.agent.tools.github.shutil.which", return_value=None):
            result = await tool.execute(name="my-charm")

        assert not result.success
        assert "gh CLI not found" in result.error

    @pytest.mark.asyncio
    async def test_not_authenticated(self, tool):
        """Reports a friendly error when gh is not authenticated."""
        with (
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github._check_gh_auth",
                return_value="The GitHub CLI is not authenticated. "
                "Please run `gh auth login` and follow the prompts, then try again.",
            ),
        ):
            result = await tool.execute(name="my-charm")

        assert not result.success
        assert "gh auth login" in result.error

    @pytest.mark.asyncio
    async def test_create_private_repo(self, tool):
        """Creates a private repository by default."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(name="my-charm")

        assert result.success
        assert result.data["name"] == "my-charm"
        assert result.data["private"] is True
        call_args = mock_run.call_args[0][0]
        assert "--private" in call_args
        assert "my-charm" in call_args

    @pytest.mark.asyncio
    async def test_create_public_repo(self, tool):
        """Creates a public repository when private=False."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(name="my-charm", private=False)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--public" in call_args
        assert "--private" not in call_args

    @pytest.mark.asyncio
    async def test_create_with_description(self, tool):
        """Passes description to gh repo create."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(name="my-charm", description="A Juju charm")

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--description" in call_args
        desc_idx = call_args.index("--description")
        assert call_args[desc_idx + 1] == "A Juju charm"

    @pytest.mark.asyncio
    async def test_create_with_push(self, tool):
        """Passes --push and --source=. when push=True."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(name="my-charm", push=True)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--push" in call_args
        assert "--source=." in call_args

    @pytest.mark.asyncio
    async def test_create_failure(self, tool):
        """Reports error when gh repo create fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "repository name already exists"

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(name="my-charm")

        assert not result.success
        assert "already exists" in result.error

    @pytest.mark.asyncio
    async def test_create_timeout(self, tool):
        """Reports error on timeout."""
        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
            ),
        ):
            result = await tool.execute(name="my-charm")

        assert not result.success
        assert "timed out" in result.error


class TestGhPrCreateTool:
    """Tests for GhPrCreateTool."""

    @pytest.fixture
    def tool(self):
        return GhPrCreateTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool):
        """Error when gh CLI is not on PATH."""
        with mock.patch("cantrip.agent.tools.github.shutil.which", return_value=None):
            result = await tool.execute(title="Add feature", body="Description")

        assert not result.success
        assert "gh CLI not found" in result.error

    @pytest.mark.asyncio
    async def test_not_authenticated(self, tool):
        """Reports a friendly error when gh is not authenticated."""
        with (
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github._check_gh_auth",
                return_value="The GitHub CLI is not authenticated. "
                "Please run `gh auth login` and follow the prompts, then try again.",
            ),
        ):
            result = await tool.execute(title="Add feature", body="Description")

        assert not result.success
        assert "gh auth login" in result.error

    @pytest.mark.asyncio
    async def test_create_pr(self, tool):
        """Creates a pull request and returns the URL."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm/pull/1\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(title="Add feature", body="Adds a new feature")

        assert result.success
        assert "pull/1" in result.output
        assert result.data["title"] == "Add feature"
        call_args = mock_run.call_args[0][0]
        assert "--title" in call_args
        assert "--body" in call_args

    @pytest.mark.asyncio
    async def test_create_pr_with_base(self, tool):
        """Specifies a base branch for the PR."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm/pull/2\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(
                title="Fix bug",
                body="Fixes a bug",
                base="develop",
            )

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--base" in call_args
        base_idx = call_args.index("--base")
        assert call_args[base_idx + 1] == "develop"

    @pytest.mark.asyncio
    async def test_create_pr_failure(self, tool):
        """Reports error when PR creation fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "pull request create failed: No commits between main and feature"

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(title="Empty PR", body="No changes")

        assert not result.success
        assert "No commits" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_timeout(self, tool):
        """Reports error on timeout."""
        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
            ),
        ):
            result = await tool.execute(title="Test PR", body="Test")

        assert not result.success
        assert "timed out" in result.error


class TestGhIssueListTool:
    """Tests for GhIssueListTool."""

    @pytest.fixture
    def tool(self):
        return GhIssueListTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool):
        """Error when gh CLI is not on PATH."""
        with mock.patch("cantrip.agent.tools.github.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "gh CLI not found" in result.error

    @pytest.mark.asyncio
    async def test_not_authenticated(self, tool):
        """Reports a friendly error when gh is not authenticated."""
        with (
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github._check_gh_auth",
                return_value="The GitHub CLI is not authenticated. "
                "Please run `gh auth login` and follow the prompts, then try again.",
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "gh auth login" in result.error

    @pytest.mark.asyncio
    async def test_list_issues(self, tool):
        """Lists open issues."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1\tFix logging\topen\t2024-01-01\n2\tAdd tests\topen\t2024-01-02\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute()

        assert result.success
        assert "Fix logging" in result.output
        call_args = mock_run.call_args[0][0]
        assert "--state" in call_args
        assert "open" in call_args
        assert "--limit" in call_args
        assert "10" in call_args

    @pytest.mark.asyncio
    async def test_list_issues_empty(self, tool):
        """Reports no issues when list is empty."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert "No issues found" in result.output

    @pytest.mark.asyncio
    async def test_list_issues_with_repo(self, tool):
        """Specifies a repository in OWNER/REPO format."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1\tIssue title\topen\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(repo="canonical/my-charm")

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--repo" in call_args
        repo_idx = call_args.index("--repo")
        assert call_args[repo_idx + 1] == "canonical/my-charm"

    @pytest.mark.asyncio
    async def test_list_closed_issues(self, tool):
        """Filters by closed state."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3\tOld bug\tclosed\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(state="closed")

        assert result.success
        call_args = mock_run.call_args[0][0]
        state_idx = call_args.index("--state")
        assert call_args[state_idx + 1] == "closed"

    @pytest.mark.asyncio
    async def test_list_custom_limit(self, tool):
        """Uses custom limit."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1\tIssue\topen\n"
        mock_result.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(limit=25)

        assert result.success
        call_args = mock_run.call_args[0][0]
        limit_idx = call_args.index("--limit")
        assert call_args[limit_idx + 1] == "25"

    @pytest.mark.asyncio
    async def test_list_failure(self, tool):
        """Reports error when gh issue list fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "could not determine base repo"

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "could not determine base repo" in result.error

    @pytest.mark.asyncio
    async def test_list_timeout(self, tool):
        """Reports error on timeout."""
        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error


class TestGhRepoBootstrapTool:
    """Tests for GhRepoBootstrapTool."""

    @pytest.fixture
    def tool(self):
        return GhRepoBootstrapTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool, tmp_path):
        """Error when gh CLI is not on PATH."""
        with mock.patch("cantrip.agent.tools.github.shutil.which", return_value=None):
            result = await tool.execute(path=str(tmp_path), repo="user/charm")
        assert not result.success
        assert "gh CLI not found" in result.error

    @pytest.mark.asyncio
    async def test_not_authenticated(self, tool, tmp_path):
        """Reports a friendly error when gh is not authenticated."""
        with (
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github._check_gh_auth",
                return_value="The GitHub CLI is not authenticated.",
            ),
        ):
            result = await tool.execute(path=str(tmp_path), repo="user/charm")
        assert not result.success
        assert "not authenticated" in result.error

    @pytest.mark.asyncio
    async def test_missing_path(self, tool, tmp_path):
        """Reports a directory-not-found error for non-existent paths."""
        missing = tmp_path / "does-not-exist"
        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
        ):
            result = await tool.execute(path=str(missing), repo="user/charm")
        assert not result.success
        assert "Directory not found" in result.error

    @pytest.mark.asyncio
    async def test_writes_templates_and_applies_protection(self, tool, tmp_path):
        """Happy path: writes all three artefacts and applies branch protection."""
        protection_ok = mock.MagicMock()
        protection_ok.returncode = 0
        protection_ok.stdout = "{}"
        protection_ok.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=protection_ok,
            ) as mock_run,
        ):
            result = await tool.execute(path=str(tmp_path), repo="user/charm")

        assert result.success, result.error
        assert result.data["branch_protection_applied"] is True
        written = set(result.data["written"])
        assert written == {
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/feature_request.md",
            ".github/workflows/ci.yaml",
        }
        # Files actually on disk.
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").is_file()
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "feature_request.md").is_file()
        assert (tmp_path / ".github" / "workflows" / "ci.yaml").is_file()
        # gh api call uses the expected endpoint and JSON payload on stdin.
        call_args, call_kwargs = mock_run.call_args
        cmd = call_args[0]
        assert cmd[:4] == ["gh", "api", "-X", "PUT"]
        assert cmd[4] == "repos/user/charm/branches/main/protection"
        assert cmd[-2:] == ["--input", "-"]
        payload = json.loads(call_kwargs["input"])
        assert payload["allow_force_pushes"] is False
        assert payload["allow_deletions"] is False
        assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 1

    @pytest.mark.asyncio
    async def test_skips_existing_files(self, tool, tmp_path):
        """Existing template files are left alone and reported as skipped."""
        templates_dir = tmp_path / ".github" / "ISSUE_TEMPLATE"
        templates_dir.mkdir(parents=True)
        (templates_dir / "bug_report.md").write_text("existing content")

        protection_ok = mock.MagicMock()
        protection_ok.returncode = 0
        protection_ok.stdout = ""
        protection_ok.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=protection_ok,
            ),
        ):
            result = await tool.execute(path=str(tmp_path), repo="user/charm")

        assert result.success
        assert ".github/ISSUE_TEMPLATE/bug_report.md" in result.data["skipped"]
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").read_text() == (
            "existing content"
        )

    @pytest.mark.asyncio
    async def test_selective_steps(self, tool, tmp_path):
        """Only the requested artefacts are written; no protection call is made."""
        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
            ) as mock_run,
        ):
            result = await tool.execute(
                path=str(tmp_path),
                repo="user/charm",
                branch_protection=False,
                issue_templates=True,
                ci_workflow=False,
            )

        assert result.success
        mock_run.assert_not_called()
        assert not (tmp_path / ".github" / "workflows").exists()
        assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").is_file()
        assert result.data["branch_protection_applied"] is False

    @pytest.mark.asyncio
    async def test_protection_failure_is_warning(self, tool, tmp_path):
        """Failed branch-protection API call surfaces as a warning, not a crash."""
        protection_failed = mock.MagicMock()
        protection_failed.returncode = 1
        protection_failed.stdout = ""
        protection_failed.stderr = "HTTP 403: requires admin"

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=protection_failed,
            ),
        ):
            result = await tool.execute(path=str(tmp_path), repo="user/charm")

        assert not result.success
        assert result.data["branch_protection_applied"] is False
        assert "HTTP 403" in result.error
        # File writes still happened.
        assert (tmp_path / ".github" / "workflows" / "ci.yaml").is_file()

    @pytest.mark.asyncio
    async def test_detects_repo_slug_when_omitted(self, tool, tmp_path):
        """Auto-detects the repo slug via ``gh repo view`` when repo= is unset."""
        detect_result = mock.MagicMock()
        detect_result.returncode = 0
        detect_result.stdout = "canonical/my-charm\n"
        detect_result.stderr = ""
        protection_ok = mock.MagicMock()
        protection_ok.returncode = 0
        protection_ok.stdout = ""
        protection_ok.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                side_effect=[detect_result, protection_ok],
            ) as mock_run,
        ):
            result = await tool.execute(path=str(tmp_path))

        assert result.success, result.error
        assert mock_run.call_count == 2
        detect_cmd = mock_run.call_args_list[0][0][0]
        assert detect_cmd[:3] == ["gh", "repo", "view"]
        protection_cmd = mock_run.call_args_list[1][0][0]
        assert protection_cmd[4] == "repos/canonical/my-charm/branches/main/protection"

    @pytest.mark.asyncio
    async def test_slug_detection_failure_skips_protection(self, tool, tmp_path):
        """If the repo slug cannot be detected, protection is skipped with a warning."""
        detect_failed = mock.MagicMock()
        detect_failed.returncode = 1
        detect_failed.stdout = ""
        detect_failed.stderr = "no git remotes found"

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=detect_failed,
            ),
        ):
            result = await tool.execute(path=str(tmp_path))

        assert not result.success
        assert result.data["branch_protection_applied"] is False
        assert "Could not detect repository slug" in result.error

    @pytest.mark.asyncio
    async def test_custom_branch(self, tool, tmp_path):
        """``branch`` parameter is threaded into the protection endpoint."""
        protection_ok = mock.MagicMock()
        protection_ok.returncode = 0
        protection_ok.stdout = ""
        protection_ok.stderr = ""

        with (
            _PATCH_AUTH_OK,
            mock.patch(
                "cantrip.agent.tools.github.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.github.subprocess.run",
                return_value=protection_ok,
            ) as mock_run,
        ):
            result = await tool.execute(
                path=str(tmp_path),
                repo="user/charm",
                branch="develop",
                issue_templates=False,
                ci_workflow=False,
            )

        assert result.success
        cmd = mock_run.call_args[0][0]
        assert cmd[4] == "repos/user/charm/branches/develop/protection"
