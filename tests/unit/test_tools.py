"""Tests for agent tools."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftInitTool,
    _inject_coverage_threshold,
    _inject_pre_commit,
)
from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
    _concierge_available,
    _is_already_provisioned,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.testing import _build_pytest_target, _parse_coverage_total


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

    @pytest.mark.asyncio
    async def test_path_prefix_attack_blocked(self, temp_dir):
        """Test that sibling directories with matching prefixes are blocked."""
        tool = ReadFileTool(base_path=temp_dir)
        # Create a sibling directory whose name starts with temp_dir's name.
        evil_dir = temp_dir.parent / (temp_dir.name + "-evil")
        evil_dir.mkdir(exist_ok=True)
        evil_file = evil_dir / "secret.txt"
        evil_file.write_text("stolen")
        try:
            result = await tool.execute(path=str(evil_file))

            assert not result.success
            assert "outside" in result.error.lower()
        finally:
            evil_file.unlink(missing_ok=True)
            evil_dir.rmdir()


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

    @pytest.mark.asyncio
    async def test_write_path_traversal_rejected(self, tool):
        """Writing outside the base path is rejected."""
        result = await tool.execute(path="../../etc/passwd", content="hacked")
        assert not result.success
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_to_read_only_directory(self, temp_dir):
        """Writing to a read-only directory reports an OS error."""
        read_only = temp_dir / "readonly"
        read_only.mkdir()
        read_only.chmod(0o444)
        try:
            tool = WriteFileTool(base_path=read_only)
            result = await tool.execute(path="file.txt", content="data")
            assert not result.success
            assert result.error
        finally:
            read_only.chmod(0o755)


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
        assert "bytes)" in result.output
        assert "dir:  subdir/" in result.output
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
    proc = mock.MagicMock()
    proc.communicate = mock.AsyncMock(return_value=(stdout.encode(), stderr.encode()))
    proc.wait = mock.AsyncMock(return_value=returncode)
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


class TestIsAlreadyProvisioned:
    """Tests for _is_already_provisioned helper."""

    @pytest.mark.asyncio
    async def test_returns_true_when_succeeded(self):
        """Returns True when concierge status reports success."""
        status_proc = _make_fake_process(stdout="Status: succeeded\n")
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/concierge",
            ),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            assert await _is_already_provisioned() is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_provisioned(self):
        """Returns False when concierge status does not contain 'succeeded'."""
        status_proc = _make_fake_process(stdout="Status: not provisioned\n")
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/concierge",
            ),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            assert await _is_already_provisioned() is False

    @pytest.mark.asyncio
    async def test_returns_false_when_concierge_not_available(self):
        """Returns False when concierge is not installed."""
        with mock.patch(
            "cantrip.agent.tools.environment.shutil.which",
            return_value=None,
        ):
            assert await _is_already_provisioned() is False

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """Returns False when concierge status times out."""
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/concierge",
            ),
            mock.patch(
                "cantrip.agent.tools.environment._run_concierge",
                side_effect=TimeoutError,
            ),
        ):
            assert await _is_already_provisioned() is False


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
            mock.patch(
                "cantrip.agent.tools.environment._juju_controller_healthy", return_value=False
            ),
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
            mock.patch(
                "cantrip.agent.tools.environment._juju_controller_healthy", return_value=False
            ),
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
            mock.patch(
                "cantrip.agent.tools.environment._juju_controller_healthy", return_value=False
            ),
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

    @pytest.mark.asyncio
    async def test_custom_app_detects_dockerfile(self, tool, temp_dir):
        """Dockerfile present with no framework suggests K8s substrate."""
        (temp_dir / "Dockerfile").write_text("FROM ubuntu:22.04\nCMD /app\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_dockerfile"] is True
        assert hints["suggested_substrate"] == "k8s"

    @pytest.mark.asyncio
    async def test_custom_app_detects_systemd(self, tool, temp_dir):
        """Systemd service file present suggests machine substrate."""
        (temp_dir / "my-app.service").write_text("[Unit]\nDescription=My App\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_systemd"] is True
        assert hints["suggested_substrate"] == "machine"

    @pytest.mark.asyncio
    async def test_custom_app_detects_docker_compose(self, tool, temp_dir):
        """Docker-compose file is detected in workload hints."""
        (temp_dir / "docker-compose.yml").write_text("services:\n  app:\n    build: .\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert hints["has_docker_compose"] is True

    @pytest.mark.asyncio
    async def test_custom_app_suggests_custom_charm_skill(self, tool, temp_dir):
        """No framework detected mentions custom-charm skill."""
        (temp_dir / "main.rs").write_text("fn main() {}")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert "custom-charm" in result.output.lower()

    @pytest.mark.asyncio
    async def test_custom_app_workload_hints_structure(self, tool, temp_dir):
        """Workload hints dict is present with all expected keys."""
        (temp_dir / "main.c").write_text("int main() { return 0; }")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        hints = result.data["workload_hints"]
        assert "has_dockerfile" in hints
        assert "has_docker_compose" in hints
        assert "has_systemd" in hints
        assert "has_config_files" in hints
        assert "suggested_substrate" in hints


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


class TestCharmcraftInitOpsTracing:
    """Tests for ops-tracing injection in CharmcraftInitTool."""

    _CHARMCRAFT_YAML = """\
name: test-charm
type: charm
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"
"""

    _CHARM_PY = """\
#!/usr/bin/env python3
import ops


class TestCharmCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":
    ops.main(TestCharmCharm)
"""

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

    def _scaffold_standard(self, charm_dir: Path) -> None:
        """Pre-create files that charmcraft init would generate for a standard profile."""
        charm_dir.mkdir(parents=True, exist_ok=True)
        (charm_dir / "charmcraft.yaml").write_text(self._CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")
        src = charm_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "charm.py").write_text(self._CHARM_PY)

    @pytest.mark.asyncio
    async def test_tracing_injected_standard_charm(self, tool, temp_dir):
        """Standard profile gets full ops-tracing injection."""
        charm_dir = temp_dir / "test-charm"
        self._scaffold_standard(charm_dir)

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        assert result.data["tracing_injected"] is True

        # requirements.txt should contain ops-tracing.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "ops-tracing" in reqs

        # charmcraft.yaml should have the tracing relation.
        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert "tracing" in charmcraft
        assert "interface: tracing" in charmcraft

        # src/charm.py should have the import and setup call.
        charm_py = (charm_dir / "src" / "charm.py").read_text()
        assert "import ops_tracing" in charm_py
        assert "ops_tracing.setup(self)" in charm_py

    @pytest.mark.asyncio
    async def test_tracing_charmcraft_yaml_only_for_paas(self, tool, temp_dir):
        """PaaS profile only modifies charmcraft.yaml, not requirements.txt or src/charm.py."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success

        # charmcraft.yaml should have tracing.
        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert "interface: tracing" in charmcraft

        # requirements.txt should be untouched.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "ops-tracing" not in reqs

    @pytest.mark.asyncio
    async def test_tracing_no_duplicate(self, tool, temp_dir):
        """Files that already contain tracing are not modified again."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)

        charmcraft_with_tracing = self._CHARMCRAFT_YAML + (
            "\nrequires:\n  tracing:\n    interface: tracing\n    limit: 1\n"
        )
        (charm_dir / "charmcraft.yaml").write_text(charmcraft_with_tracing)
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\nops-tracing\n")

        src = charm_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        charm_py_with_tracing = self._CHARM_PY.replace(
            "import ops\n", "import ops\nimport ops_tracing\n"
        ).replace(
            "super().__init__(framework)",
            "super().__init__(framework)\n        ops_tracing.setup(self)",
        )
        (src / "charm.py").write_text(charm_py_with_tracing)

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success

        # No duplicates in any file.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert reqs.count("ops-tracing") == 1

        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert charmcraft.count("interface: tracing") == 1

        charm_py = (charm_dir / "src" / "charm.py").read_text()
        assert charm_py.count("import ops_tracing") == 1
        assert charm_py.count("ops_tracing.setup") == 1

    @pytest.mark.asyncio
    async def test_tracing_missing_files_still_succeeds(self, tool, temp_dir):
        """Tool succeeds even when expected files are absent."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        # No files pre-created — simulates charmcraft init producing nothing.

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        assert "skipped" in result.output.lower() or "not found" in result.output.lower()


class TestCharmcraftInitPreCommit:
    """Tests for pre-commit injection in CharmcraftInitTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    def test_pre_commit_config_written(self, temp_dir):
        """Writes .pre-commit-config.yaml with format, lint, and unit hooks."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        actions = _inject_pre_commit(temp_dir)

        config = temp_dir / ".pre-commit-config.yaml"
        assert config.exists()
        content = config.read_text()
        assert "id: format" in content
        assert "id: lint" in content
        assert "id: unit" in content
        assert "tox -e format" in content
        assert "tox -e lint" in content
        assert "tox -e unit" in content
        assert any("Created" in a for a in actions)

    def test_pre_commit_skipped_when_exists(self, temp_dir):
        """Skips writing when .pre-commit-config.yaml already exists."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")
        existing = temp_dir / ".pre-commit-config.yaml"
        existing.write_text("repos: []\n")

        actions = _inject_pre_commit(temp_dir)

        # File should be unchanged.
        assert existing.read_text() == "repos: []\n"
        assert any("already exists" in a for a in actions)

    def test_pre_commit_skipped_without_tox_ini(self, temp_dir):
        """Skips pre-commit setup when tox.ini is absent."""
        actions = _inject_pre_commit(temp_dir)

        assert not (temp_dir / ".pre-commit-config.yaml").exists()
        assert any("tox.ini not found" in a for a in actions)

    def test_pre_commit_install_runs(self, temp_dir):
        """Runs pre-commit install when the binary is on PATH."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        with (
            mock.patch(
                "cantrip.agent.tools.charm.shutil.which", return_value="/usr/bin/pre-commit"
            ),
            mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run,
        ):
            actions = _inject_pre_commit(temp_dir)

        mock_run.assert_called_once_with(
            ["pre-commit", "install"],
            cwd=temp_dir,
            capture_output=True,
            timeout=30,
        )
        assert any("Ran pre-commit install" in a for a in actions)

    def test_pre_commit_install_skipped(self, temp_dir):
        """Gracefully skips when pre-commit is not on PATH."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        with mock.patch("cantrip.agent.tools.charm.shutil.which", return_value=None):
            actions = _inject_pre_commit(temp_dir)

        assert (temp_dir / ".pre-commit-config.yaml").exists()
        assert any("pre-commit not found" in a for a in actions)


# ===================================================================
# TestBuildPytestTarget
# ===================================================================


class TestBuildPytestTarget:
    """Tests for _build_pytest_target — selective test execution."""

    @pytest.fixture
    def test_dir(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "tests" / "integration"
            d.mkdir(parents=True)
            (d / "test_deploy.py").write_text("def test_deploy(): pass\n")
            (d / "test_relations.py").write_text("def test_db(): pass\n")
            yield d

    def test_no_pattern_returns_whole_directory(self, test_dir):
        result = _build_pytest_target(test_dir, None)
        assert result == [str(test_dir) + "/"]

    def test_file_name_match(self, test_dir):
        """Plain name matching an existing file resolves to that file."""
        result = _build_pytest_target(test_dir, "test_deploy")
        assert result == [str(test_dir / "test_deploy.py")]

    def test_file_function_form(self, test_dir):
        """file::function form resolves to pytest node ID."""
        result = _build_pytest_target(test_dir, "test_deploy::test_smoke")
        assert result == [f"{test_dir / 'test_deploy.py'}::test_smoke"]

    def test_file_function_nonexistent_file_falls_back_to_k(self, test_dir):
        """file::function with a missing file falls back to -k."""
        result = _build_pytest_target(test_dir, "missing::test_foo")
        assert result == [str(test_dir) + "/", "-k", "test_foo"]

    def test_k_expression_with_or(self, test_dir):
        """Boolean expressions with 'or' are passed to -k."""
        result = _build_pytest_target(test_dir, "deploy or relation")
        assert result == [str(test_dir) + "/", "-k", "deploy or relation"]

    def test_k_expression_with_spaces(self, test_dir):
        """Expressions with spaces are passed to -k."""
        result = _build_pytest_target(test_dir, "test deploy")
        assert result == [str(test_dir) + "/", "-k", "test deploy"]

    def test_unknown_name_falls_back_to_k(self, test_dir):
        """A name that doesn't match any file falls back to -k."""
        result = _build_pytest_target(test_dir, "test_nonexistent")
        assert result == [str(test_dir) + "/", "-k", "test_nonexistent"]

    def test_file_name_with_py_suffix(self, test_dir):
        """Handles .py suffix in file::function form gracefully."""
        result = _build_pytest_target(test_dir, "test_deploy.py::test_smoke")
        assert result == [f"{test_dir / 'test_deploy.py'}::test_smoke"]


# ===================================================================
# TestParseCoverageTotal
# ===================================================================


class TestParseCoverageTotal:
    """Tests for _parse_coverage_total — coverage percentage extraction."""

    def test_typical_coverage_report(self):
        output = (
            "Name             Stmts   Miss  Cover\n"
            "------------------------------------\n"
            "src/charm.py        50      5    90%\n"
            "TOTAL              100     10    90%\n"
        )
        assert _parse_coverage_total(output) == 90

    def test_zero_coverage(self):
        output = "TOTAL    100    100    0%\n"
        assert _parse_coverage_total(output) == 0

    def test_full_coverage(self):
        output = "TOTAL    100    0    100%\n"
        assert _parse_coverage_total(output) == 100

    def test_no_coverage_output(self):
        output = "=== 5 passed in 0.3s ===\n"
        assert _parse_coverage_total(output) is None

    def test_embedded_in_tox_output(self):
        """Coverage line buried in larger tox output is still found."""
        output = (
            "unit: commands[0]> coverage run ...\n"
            "========= 10 passed in 1.2s =========\n"
            "unit: commands[1]> coverage report\n"
            "Name             Stmts   Miss  Cover\n"
            "------------------------------------\n"
            "src/charm.py        80      4    95%\n"
            "TOTAL              200     10    95%\n"
            "unit: OK\n"
        )
        assert _parse_coverage_total(output) == 95


# ===================================================================
# TestInjectCoverageThreshold
# ===================================================================


class TestInjectCoverageThreshold:
    """Tests for _inject_coverage_threshold — pyproject.toml injection."""

    def test_adds_fail_under_to_existing_report_section(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text(
                "[tool.coverage.run]\nbranch = true\n\n"
                "[tool.coverage.report]\nshow_missing = true\n"
            )
            actions = _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "fail_under = 80" in content
            assert len(actions) == 1
            assert "80%" in actions[0]

    def test_skips_when_fail_under_already_set(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[tool.coverage.report]\nfail_under = 90\nshow_missing = true\n")
            actions = _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "fail_under = 90" in content
            assert content.count("fail_under") == 1
            assert "already configured" in actions[0]

    def test_creates_report_section_when_only_run_exists(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[tool.coverage.run]\nbranch = true\n")
            _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "[tool.coverage.report]" in content
            assert "fail_under = 80" in content

    def test_creates_both_sections_when_no_coverage_config(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[project]\nname = 'my-charm'\n")
            _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "[tool.coverage.run]" in content
            assert "[tool.coverage.report]" in content
            assert "fail_under = 80" in content

    def test_no_pyproject_returns_skip_message(self):
        with tempfile.TemporaryDirectory() as td:
            actions = _inject_coverage_threshold(Path(td))
            assert "skipped" in actions[0]
