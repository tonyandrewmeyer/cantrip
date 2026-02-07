"""Tests for agent tools."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import AnalyseFrameworkTool, CharmcraftInitTool
from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
    _concierge_available,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)


class TestReadFileTool:
    """Tests for ReadFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return ReadFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tool, temp_dir):
        """Test reading an existing file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello world")

        result = await tool.execute(path="test.txt")

        assert result.success
        assert result.output == "hello world"
        assert result.data["size"] == 11

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tool):
        """Test reading a file that doesn't exist."""
        result = await tool.execute(path="nonexistent.txt")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_directory_fails(self, tool, temp_dir):
        """Test that reading a directory fails."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()

        result = await tool.execute(path="subdir")

        assert not result.success
        assert "directory" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_dir):
        """Test that path traversal is blocked."""
        tool = ReadFileTool(base_path=temp_dir)

        result = await tool.execute(path="../../../etc/passwd")

        assert not result.success
        assert "outside" in result.error.lower()


class TestWriteFileTool:
    """Tests for WriteFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return WriteFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool, temp_dir):
        """Test writing a new file."""
        result = await tool.execute(path="new.txt", content="test content")

        assert result.success
        assert (temp_dir / "new.txt").read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, tool, temp_dir):
        """Test that writing creates parent directories."""
        result = await tool.execute(path="sub/dir/file.txt", content="nested")

        assert result.success
        assert (temp_dir / "sub/dir/file.txt").read_text() == "nested"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tool, temp_dir):
        """Test that writing overwrites existing files."""
        existing = temp_dir / "existing.txt"
        existing.write_text("old content")

        result = await tool.execute(path="existing.txt", content="new content")

        assert result.success
        assert existing.read_text() == "new content"


class TestListDirectoryTool:
    """Tests for ListDirectoryTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return ListDirectoryTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tool):
        """Test listing an empty directory."""
        result = await tool.execute(path=".")

        assert result.success
        assert "empty" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_directory_contents(self, tool, temp_dir):
        """Test listing directory with contents."""
        (temp_dir / "file.txt").write_text("content")
        (temp_dir / "subdir").mkdir()

        result = await tool.execute(path=".")

        assert result.success
        assert "file: file.txt" in result.output
        assert "dir: subdir" in result.output
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tool):
        """Test listing a nonexistent directory."""
        result = await tool.execute(path="nonexistent")

        assert not result.success
        assert "not found" in result.error.lower()


class TestEditFileTool:
    """Tests for EditFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return EditFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_edit_replaces_string(self, tool, temp_dir):
        """Test that edit replaces a string."""
        test_file = temp_dir / "test.py"
        test_file.write_text("def hello():\n    return 'world'")

        result = await tool.execute(
            path="test.py",
            old_string="'world'",
            new_string="'universe'",
        )

        assert result.success
        assert test_file.read_text() == "def hello():\n    return 'universe'"

    @pytest.mark.asyncio
    async def test_edit_string_not_found(self, tool, temp_dir):
        """Test that edit fails if string not found."""
        test_file = temp_dir / "test.py"
        test_file.write_text("some content")

        result = await tool.execute(
            path="test.py",
            old_string="nonexistent",
            new_string="replacement",
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_ambiguous_match(self, tool, temp_dir):
        """Test that edit fails on ambiguous matches."""
        test_file = temp_dir / "test.py"
        test_file.write_text("foo bar foo")

        result = await tool.execute(
            path="test.py",
            old_string="foo",
            new_string="baz",
        )

        assert not result.success
        assert "2 times" in result.error


def _make_fake_process(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Build a mock async subprocess for Concierge tests."""
    proc = mock.AsyncMock()
    proc.communicate.return_value = (stdout.encode(), stderr.encode())
    proc.returncode = returncode
    return proc


class TestConciergeAvailable:
    """Tests for the _concierge_available helper."""

    def test_available(self):
        """Returns True when concierge is on PATH."""
        with mock.patch(
            "cantrip.agent.tools.environment.shutil.which", return_value="/usr/bin/concierge"
        ):
            assert _concierge_available() is True

    def test_not_available(self):
        """Returns False when concierge is not on PATH."""
        with mock.patch("cantrip.agent.tools.environment.shutil.which", return_value=None):
            assert _concierge_available() is False


class TestConciergePrepareTool:
    """Tests for ConciergePrepareTool."""

    @pytest.fixture
    def tool(self):
        return ConciergePrepareTool()

    @pytest.mark.asyncio
    async def test_concierge_not_installed(self, tool):
        """Error when concierge is not on PATH."""
        with mock.patch(
            "cantrip.agent.tools.environment._concierge_available", return_value=False
        ):
            result = await tool.execute(preset="k8s")

        assert not result.success
        assert "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_already_provisioned(self, tool):
        """Skips prepare when environment already succeeded."""
        status_proc = _make_fake_process(stdout="Status: succeeded\n")

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            result = await tool.execute(preset="k8s")

        assert result.success
        assert result.data.get("already_provisioned") is True
        assert "already provisioned" in result.output.lower()

    @pytest.mark.asyncio
    async def test_prepare_success(self, tool):
        """Runs prepare when not already provisioned."""
        status_proc = _make_fake_process(stdout="Status: not provisioned\n")
        prepare_proc = _make_fake_process(stdout="Done.\n")

        call_count = 0

        async def fake_exec(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_proc
            return prepare_proc

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        ):
            result = await tool.execute(preset="k8s")

        assert result.success
        assert result.data.get("preset") == "k8s"

    @pytest.mark.asyncio
    async def test_prepare_failure(self, tool):
        """Reports error when prepare command fails."""
        status_proc = _make_fake_process(stdout="Status: not provisioned\n")
        prepare_proc = _make_fake_process(returncode=1, stderr="bootstrap failed")

        call_count = 0

        async def fake_exec(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_proc
            return prepare_proc

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        ):
            result = await tool.execute(preset="machine")

        assert not result.success
        assert "bootstrap failed" in result.error

    @pytest.mark.asyncio
    async def test_prepare_timeout(self, tool):
        """Reports error on timeout."""
        status_proc = _make_fake_process(stdout="Status: not provisioned\n")

        call_count = 0

        async def fake_exec(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_proc
            # Second call (prepare) will time out.
            proc = mock.AsyncMock()
            proc.communicate.side_effect = TimeoutError
            proc.returncode = None
            return proc

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            mock.patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            result = await tool.execute(preset="k8s")

        assert not result.success
        assert "timed out" in result.error.lower()


class TestConciergeStatusTool:
    """Tests for ConciergeStatusTool."""

    @pytest.fixture
    def tool(self):
        return ConciergeStatusTool()

    @pytest.mark.asyncio
    async def test_concierge_not_installed(self, tool):
        """Error when concierge is not on PATH."""
        with mock.patch(
            "cantrip.agent.tools.environment._concierge_available", return_value=False
        ):
            result = await tool.execute()

        assert not result.success
        assert "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_status_success(self, tool):
        """Returns status output on success."""
        proc = _make_fake_process(stdout="Status: succeeded\nPreset: k8s\n")

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await tool.execute()

        assert result.success
        assert "succeeded" in result.output.lower()

    @pytest.mark.asyncio
    async def test_status_failure(self, tool):
        """Reports error when status command fails."""
        proc = _make_fake_process(returncode=1, stderr="no provider")

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch("asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await tool.execute()

        assert not result.success
        assert "no provider" in result.error

    @pytest.mark.asyncio
    async def test_status_timeout(self, tool):
        """Reports error on timeout."""
        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.environment._run_concierge",
                side_effect=TimeoutError,
            ),
        ):
            result = await tool.execute()

        assert not result.success
        assert "timed out" in result.error.lower()


class TestAnalyseFrameworkTool:
    """Tests for AnalyseFrameworkTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return AnalyseFrameworkTool()

    @pytest.mark.asyncio
    async def test_detect_flask(self, tool, temp_dir):
        """Detects Flask and returns the correct profile."""
        (temp_dir / "requirements.txt").write_text("flask>=3.0\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "flask"
        assert result.data["profile"] == "flask-framework"
        assert result.data["needs_experimental"] is False

    @pytest.mark.asyncio
    async def test_detect_express(self, tool, temp_dir):
        """Detects Express from package.json."""
        (temp_dir / "package.json").write_text('{"dependencies": {"express": "^4.18.0"}}')

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "express"
        assert result.data["profile"] == "express-framework"
        assert result.data["language"] == "javascript"

    @pytest.mark.asyncio
    async def test_detect_spring_boot_maven(self, tool, temp_dir):
        """Detects Spring Boot from pom.xml."""
        (temp_dir / "pom.xml").write_text(
            "<project><parent>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-parent</artifactId>"
            "</parent></project>"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "spring-boot"
        assert result.data["profile"] == "spring-boot-framework"
        assert result.data["language"] == "java"

    @pytest.mark.asyncio
    async def test_detect_spring_boot_gradle(self, tool, temp_dir):
        """Detects Spring Boot from build.gradle.kts."""
        (temp_dir / "build.gradle.kts").write_text(
            'plugins { id("org.springframework.boot") version "3.2.0" }\n'
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] == "spring-boot"
        assert result.data["language"] == "java"

    @pytest.mark.asyncio
    async def test_profile_returned_for_django(self, tool, temp_dir):
        """Returns the correct profile for Django."""
        (temp_dir / "requirements.txt").write_text("django>=4.2\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["profile"] == "django-framework"

    @pytest.mark.asyncio
    async def test_needs_experimental_for_go(self, tool, temp_dir):
        """Reports needs_experimental for Go."""
        (temp_dir / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["framework"] == "go"
        assert result.data["needs_experimental"] is True

    @pytest.mark.asyncio
    async def test_needs_experimental_for_fastapi(self, tool, temp_dir):
        """Reports needs_experimental for FastAPI."""
        (temp_dir / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["framework"] == "fastapi"
        assert result.data["needs_experimental"] is True

    @pytest.mark.asyncio
    async def test_suggestion_includes_skill_hint(self, tool, temp_dir):
        """Suggestion text mentions the twelve-factor skill."""
        (temp_dir / "requirements.txt").write_text("flask\n")

        result = await tool.execute(path=str(temp_dir))

        assert "twelve-factor" in result.output.lower()

    @pytest.mark.asyncio
    async def test_unknown_framework(self, tool, temp_dir):
        """Returns no profile for an unknown codebase."""
        (temp_dir / "main.rs").write_text("fn main() {}")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["framework"] is None
        assert result.data["profile"] is None

    @pytest.mark.asyncio
    async def test_nodejs_without_express(self, tool, temp_dir):
        """Node.js without Express has no framework profile."""
        (temp_dir / "package.json").write_text('{"dependencies": {"next": "^14.0.0"}}')

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["language"] == "javascript"
        assert result.data["framework"] is None
        assert result.data["profile"] is None


class TestCharmcraftInitGitignore:
    """Tests for CharmcraftInitTool .gitignore handling."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftInitTool()

    def _mock_charmcraft(self):
        """Return a mock that simulates a successful charmcraft init."""
        return mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Initialised.", stderr=""),
        )

    @pytest.mark.asyncio
    async def test_gitignore_created_with_cantrip_and_source(self, tool, temp_dir):
        """A new .gitignore should contain both .cantrip and .source/ entries."""
        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        gitignore = temp_dir / "test-charm" / ".gitignore"
        content = gitignore.read_text()
        assert ".cantrip" in content
        assert ".source/" in content

    @pytest.mark.asyncio
    async def test_gitignore_appends_missing_entries(self, tool, temp_dir):
        """Existing .gitignore gets missing entries appended."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        gitignore = charm_dir / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")

        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        content = gitignore.read_text()
        assert ".cantrip" in content
        assert ".source/" in content
        assert "*.pyc" in content

    @pytest.mark.asyncio
    async def test_gitignore_does_not_duplicate(self, tool, temp_dir):
        """Entries already present are not repeated."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        gitignore = charm_dir / ".gitignore"
        gitignore.write_text(".cantrip\n.source/\n")

        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        content = gitignore.read_text()
        assert content.count(".cantrip") == 1
        assert content.count(".source/") == 1
