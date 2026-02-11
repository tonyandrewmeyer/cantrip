"""Tests for git version control tools."""

import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.git import (
    GitAddTool,
    GitCloneTool,
    GitCommitTool,
    GitDiffTool,
    GitInitTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)


class TestGitCloneTool:
    """Tests for GitCloneTool."""

    @pytest.fixture
    def tool(self):
        return GitCloneTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute(url="https://github.com/user/repo.git")

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_clone_success(self, tool):
        """Clones a repository."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Cloning into 'repo'...\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(url="https://github.com/user/repo.git")

        assert result.success
        assert "Cloning into" in result.output
        assert result.data["url"] == "https://github.com/user/repo.git"
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "clone", "https://github.com/user/repo.git"]

    @pytest.mark.asyncio
    async def test_clone_into_path(self, tool):
        """Clones into a specified directory."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Cloning into '/tmp/my-app'...\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(
                url="https://github.com/user/repo.git",
                path="/tmp/my-app",
            )

        assert result.success
        assert result.data["path"] == "/tmp/my-app"
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "clone", "https://github.com/user/repo.git", "/tmp/my-app"]

    @pytest.mark.asyncio
    async def test_clone_shallow(self, tool):
        """Creates a shallow clone with --depth."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Cloning into 'repo'...\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(
                url="https://github.com/user/repo.git",
                depth=1,
            )

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--depth" in call_args
        depth_idx = call_args.index("--depth")
        assert call_args[depth_idx + 1] == "1"

    @pytest.mark.asyncio
    async def test_clone_failure(self, tool):
        """Reports error when clone fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: repository 'https://bad-url/' not found"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(url="https://bad-url/")

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_clone_auth_failure(self, tool):
        """Gives a friendly hint when clone fails due to authentication."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = (
            "fatal: Authentication failed for 'https://github.com/private/repo.git'"
        )

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(url="https://github.com/private/repo.git")

        assert not result.success
        assert "could not authenticate" in result.error
        assert "Authentication failed" in result.error

    @pytest.mark.asyncio
    async def test_clone_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
            ),
        ):
            result = await tool.execute(url="https://github.com/user/repo.git")

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_clone_uses_network_timeout(self, tool):
        """Uses the longer network timeout, not the local one."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Cloning into 'repo'...\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            await tool.execute(url="https://github.com/user/repo.git")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 120

    @pytest.mark.asyncio
    async def test_clone_disables_terminal_prompt(self, tool):
        """Sets GIT_TERMINAL_PROMPT=0 to prevent interactive credential prompts."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Cloning into 'repo'...\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            await tool.execute(url="https://github.com/user/repo.git")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"


class TestGitInitTool:
    """Tests for GitInitTool."""

    @pytest.fixture
    def tool(self):
        return GitInitTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_init_success(self, tool):
        """Initialises a new repository."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Initialized empty Git repository in /tmp/test/.git/\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(path="/tmp/test")

        assert result.success
        assert result.data["path"] == "/tmp/test"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "init"]
        assert mock_run.call_args[1]["cwd"] == "/tmp/test"

    @pytest.mark.asyncio
    async def test_init_already_initialised(self, tool):
        """Handles re-initialising an existing repository."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Reinitialized existing Git repository in /tmp/test/.git/\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(path="/tmp/test")

        assert result.success
        assert "Reinitialized" in result.output

    @pytest.mark.asyncio
    async def test_init_failure(self, tool):
        """Reports error when git init fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a directory"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(path="/nonexistent")

        assert not result.success
        assert "not a directory" in result.error

    @pytest.mark.asyncio
    async def test_init_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error


class TestGitStatusTool:
    """Tests for GitStatusTool."""

    @pytest.fixture
    def tool(self):
        return GitStatusTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_clean_status(self, tool):
        """Reports clean working tree."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "On branch main\nnothing to commit, working tree clean\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert "nothing to commit" in result.output

    @pytest.mark.asyncio
    async def test_uncommitted_changes(self, tool):
        """Reports uncommitted changes."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "On branch main\nChanges not staged for commit:\n\tmodified:   src/charm.py\n"
        )
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert "modified" in result.output

    @pytest.mark.asyncio
    async def test_status_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error


class TestGitDiffTool:
    """Tests for GitDiffTool."""

    @pytest.fixture
    def tool(self):
        return GitDiffTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_diff_with_changes(self, tool):
        """Shows unstaged changes."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "diff --git a/src/charm.py b/src/charm.py\n+new line\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute()

        assert result.success
        assert "+new line" in result.output
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "diff"]

    @pytest.mark.asyncio
    async def test_diff_no_changes(self, tool):
        """Reports no changes when diff is empty."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert "No changes" in result.output

    @pytest.mark.asyncio
    async def test_diff_staged(self, tool):
        """Shows staged changes with --cached flag."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "diff --git a/src/charm.py b/src/charm.py\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(staged=True)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--cached" in call_args

    @pytest.mark.asyncio
    async def test_diff_with_ref(self, tool):
        """Diffs against a specified ref."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "diff output here\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(ref="HEAD~1")

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "HEAD~1" in call_args

    @pytest.mark.asyncio
    async def test_diff_failure(self, tool):
        """Reports error when git diff fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: bad revision 'nonexistent'"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(ref="nonexistent")

        assert not result.success
        assert "bad revision" in result.error

    @pytest.mark.asyncio
    async def test_diff_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error


class TestGitLogTool:
    """Tests for GitLogTool."""

    @pytest.fixture
    def tool(self):
        return GitLogTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute()

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_log_with_commits(self, tool):
        """Shows commit history."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "commit abc123\nAuthor: Test\nDate: Mon\n\n    Initial commit\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute()

        assert result.success
        assert "Initial commit" in result.output
        call_args = mock_run.call_args[0][0]
        assert "--max-count=10" in call_args

    @pytest.mark.asyncio
    async def test_log_empty_repo(self, tool):
        """Reports no commits for an empty repository."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert result.success
        assert "No commits yet" in result.output

    @pytest.mark.asyncio
    async def test_log_oneline(self, tool):
        """Uses --oneline format."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123 Initial commit\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(oneline=True)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--oneline" in call_args

    @pytest.mark.asyncio
    async def test_log_custom_max_count(self, tool):
        """Uses custom max_count."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123 commit\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(max_count=5)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert "--max-count=5" in call_args

    @pytest.mark.asyncio
    async def test_log_failure(self, tool):
        """Reports error when git log fails."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "not a git repository" in result.error

    @pytest.mark.asyncio
    async def test_log_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error


class TestGitAddTool:
    """Tests for GitAddTool."""

    @pytest.fixture
    def tool(self):
        return GitAddTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute(files=["src/charm.py"])

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_add_files(self, tool):
        """Stages specified files."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(files=["src/charm.py", "charmcraft.yaml"])

        assert result.success
        assert "2 file(s)" in result.output
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "add", "--", "src/charm.py", "charmcraft.yaml"]

    @pytest.mark.asyncio
    async def test_add_empty_list(self, tool):
        """Rejects empty file list."""
        with mock.patch(
            "cantrip.agent.tools.git.shutil.which",
            return_value="/usr/bin/git",
        ):
            result = await tool.execute(files=[])

        assert not result.success
        assert "No files specified" in result.error

    @pytest.mark.asyncio
    async def test_add_missing_files(self, tool):
        """Reports error when git add fails on missing files."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: pathspec 'nonexistent.py' did not match any files"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(files=["nonexistent.py"])

        assert not result.success
        assert "did not match" in result.error

    @pytest.mark.asyncio
    async def test_add_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute(files=["src/charm.py"])

        assert not result.success
        assert "timed out" in result.error


class TestGitCommitTool:
    """Tests for GitCommitTool."""

    @pytest.fixture
    def tool(self):
        return GitCommitTool()

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute(message="Initial commit")

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_commit_success(self, tool):
        """Creates a commit without GPG signing."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[main abc1234] Initial commit\n 1 file changed, 10 insertions(+)\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(message="Initial commit")

        assert result.success
        assert "Initial commit" in result.output
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "commit", "--no-gpg-sign", "-m", "Initial commit"]

    @pytest.mark.asyncio
    async def test_commit_empty_staging(self, tool):
        """Reports error when nothing is staged."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "nothing to commit, working tree clean"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(message="Empty commit")

        assert not result.success
        assert "nothing to commit" in result.error

    @pytest.mark.asyncio
    async def test_commit_with_path(self, tool):
        """Uses the correct working directory."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[main abc1234] Add feature\n"
        mock_result.stderr = ""

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(message="Add feature", path="/tmp/my-charm")

        assert result.success
        assert mock_run.call_args[1]["cwd"] == "/tmp/my-charm"

    @pytest.mark.asyncio
    async def test_commit_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            result = await tool.execute(message="Test commit")

        assert not result.success
        assert "timed out" in result.error


class TestGitPushTool:
    """Tests for GitPushTool."""

    @pytest.fixture
    def tool(self):
        return GitPushTool()

    @pytest.mark.asyncio
    async def test_push_refused_without_confirmation(self, tool):
        """Calling without confirmed returns a refusal."""
        result = await tool.execute()

        assert not result.success
        assert "requires explicit user confirmation" in result.error

    @pytest.mark.asyncio
    async def test_push_refused_with_confirmed_false(self, tool):
        """Explicitly passing confirmed=False returns the same refusal."""
        result = await tool.execute(confirmed=False)

        assert not result.success
        assert "requires explicit user confirmation" in result.error

    @pytest.mark.asyncio
    async def test_git_not_installed(self, tool):
        """Error when git is not on PATH."""
        with mock.patch("cantrip.agent.tools.git.shutil.which", return_value=None):
            result = await tool.execute(confirmed=True)

        assert not result.success
        assert "git not found" in result.error

    @pytest.mark.asyncio
    async def test_push_success(self, tool):
        """Pushes to the remote when confirmed."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "To github.com:user/repo.git\n   abc123..def456  main -> main\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(confirmed=True)

        assert result.success
        assert "main -> main" in result.output
        assert result.data["remote"] == "origin"
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "push", "origin"]

    @pytest.mark.asyncio
    async def test_push_with_branch(self, tool):
        """Pushes a specific branch."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Everything up-to-date\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(branch="feature", confirmed=True)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "push", "origin", "feature"]
        assert result.data["branch"] == "feature"

    @pytest.mark.asyncio
    async def test_push_set_upstream(self, tool):
        """Passes -u flag when set_upstream is True."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Branch 'main' set up to track 'origin/main'.\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            result = await tool.execute(set_upstream=True, branch="main", confirmed=True)

        assert result.success
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "push", "-u", "origin", "main"]

    @pytest.mark.asyncio
    async def test_push_auth_failure(self, tool):
        """Gives a friendly hint when push fails due to authentication."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = (
            "remote: Permission denied to user/repo.git\n"
            "fatal: unable to access 'https://github.com/user/repo.git/'"
        )

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(confirmed=True)

        assert not result.success
        assert "could not authenticate" in result.error
        assert "Permission denied" in result.error

    @pytest.mark.asyncio
    async def test_push_generic_failure(self, tool):
        """Reports non-auth errors without the auth hint."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: failed to push some refs to 'origin'"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(confirmed=True)

        assert not result.success
        assert "failed to push" in result.error
        assert "could not authenticate" not in result.error

    @pytest.mark.asyncio
    async def test_push_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
            ),
        ):
            result = await tool.execute(confirmed=True)

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_push_uses_network_timeout(self, tool):
        """Uses the longer network timeout, not the local one."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Everything up-to-date\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            await tool.execute(confirmed=True)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 120

    @pytest.mark.asyncio
    async def test_push_disables_terminal_prompt(self, tool):
        """Sets GIT_TERMINAL_PROMPT=0 to prevent interactive credential prompts."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "Everything up-to-date\n"

        with (
            mock.patch(
                "cantrip.agent.tools.git.shutil.which",
                return_value="/usr/bin/git",
            ),
            mock.patch(
                "cantrip.agent.tools.git.subprocess.run",
                return_value=mock_result,
            ) as mock_run,
        ):
            await tool.execute(confirmed=True)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
