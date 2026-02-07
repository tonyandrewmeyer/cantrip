"""Tests for GitHub CLI tools."""

import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.github import (
    GhIssueListTool,
    GhPrCreateTool,
    GhRepoCreateTool,
)


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
    async def test_create_private_repo(self, tool):
        """Creates a private repository by default."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm\n"
        mock_result.stderr = ""

        with (
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
    async def test_create_auth_failure(self, tool):
        """Reports error when gh authentication fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "To get started with GitHub CLI, please run: gh auth login"

        with (
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
        assert "auth login" in result.error

    @pytest.mark.asyncio
    async def test_create_timeout(self, tool):
        """Reports error on timeout."""
        with (
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
    async def test_create_pr(self, tool):
        """Creates a pull request and returns the URL."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/my-charm/pull/1\n"
        mock_result.stderr = ""

        with (
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
    async def test_list_issues(self, tool):
        """Lists open issues."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1\tFix logging\topen\t2024-01-01\n2\tAdd tests\topen\t2024-01-02\n"
        mock_result.stderr = ""

        with (
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
