"""Tests for agent tools."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    _inject_coverage_threshold,
    _inject_pre_commit,
)
from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
    _concierge_already_running,
    _concierge_available,
    _healthy_controller_matches_preset,
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


def _raise_timeout(coro, *_args, **_kwargs):
    """Side-effect replacement for ``asyncio.wait_for`` that closes the
    pending coroutine before raising, so mocked timeout tests don't
    emit unawaited-coroutine warnings."""
    coro.close()
    raise TimeoutError


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
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[],
            ),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            assert await _is_already_provisioned() == (True, None)

    @pytest.mark.asyncio
    async def test_returns_false_when_not_provisioned(self):
        """Returns (False, None) when concierge status does not contain 'succeeded'."""
        status_proc = _make_fake_process(stdout="Status: not provisioned\n")
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/concierge",
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[],
            ),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            assert await _is_already_provisioned() == (False, None)

    @pytest.mark.asyncio
    async def test_returns_false_when_concierge_not_available(self):
        """Returns (False, None) when concierge is not installed and no controllers."""
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value=None,
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[],
            ),
        ):
            assert await _is_already_provisioned() == (False, None)

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """Returns (False, None) when concierge status times out."""
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/concierge",
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[],
            ),
            mock.patch(
                "cantrip.agent.tools.environment._run_concierge",
                side_effect=TimeoutError,
            ),
        ):
            assert await _is_already_provisioned() == (False, None)

    @pytest.mark.asyncio
    async def test_matching_k8s_controller_is_provisioned(self):
        """A microk8s controller satisfies preset='k8s'."""
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "microk8s"}],
        ):
            assert await _is_already_provisioned("k8s") == (True, None)

    @pytest.mark.asyncio
    async def test_matching_machine_controller_is_provisioned(self):
        """An LXD controller satisfies preset='machine'."""
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "localhost"}],
        ):
            assert await _is_already_provisioned("machine") == (True, None)

    @pytest.mark.asyncio
    async def test_mismatched_controller_reports_cloud(self):
        """A K8s controller with preset='machine' returns (False, <cloud>)."""
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "microk8s"}],
        ):
            assert await _is_already_provisioned("machine") == (False, "microk8s")

    @pytest.mark.asyncio
    async def test_mixed_controllers_match_either_preset(self):
        """When both LXD and K8s controllers exist, either preset matches."""
        controllers = [
            {"name": "lxd-ctrl", "cloud": "localhost"},
            {"name": "k8s-ctrl", "cloud": "microk8s"},
        ]
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=controllers,
        ):
            assert await _is_already_provisioned("k8s") == (True, None)
            assert await _is_already_provisioned("machine") == (True, None)


class TestHealthyControllerMatchesPreset:
    """Tests for the preset-matching helper itself."""

    def test_no_controllers(self):
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[],
        ):
            assert _healthy_controller_matches_preset("k8s") == (False, None)

    def test_no_preset_with_any_controller(self):
        """Legacy: preset=None matches as soon as one controller exists."""
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "whatever"}],
        ):
            assert _healthy_controller_matches_preset(None) == (True, None)

    def test_k8s_preset_matches_kubernetes_cloud(self):
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "kubernetes"}],
        ):
            assert _healthy_controller_matches_preset("k8s") == (True, None)

    def test_machine_preset_rejects_k8s(self):
        with mock.patch(
            "cantrip.agent.tools.environment._list_healthy_controllers",
            return_value=[{"name": "c1", "cloud": "k8s"}],
        ):
            assert _healthy_controller_matches_preset("machine") == (False, "k8s")


class TestConciergeAlreadyRunning:
    """Tests for the running-process guardrail."""

    def test_no_pgrep_returns_false(self):
        """No pgrep on PATH → proceed rather than refuse."""
        with mock.patch("cantrip.agent.tools.environment.shutil.which", return_value=None):
            assert _concierge_already_running() is False

    def test_pgrep_match_returns_true(self):
        """pgrep exit 0 means a concierge process is running."""
        fake_result = mock.Mock(returncode=0, stdout="12345\n", stderr="")
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/pgrep",
            ),
            mock.patch(
                "cantrip.agent.tools.environment.subprocess.run",
                return_value=fake_result,
            ),
        ):
            assert _concierge_already_running() is True

    def test_pgrep_no_match_returns_false(self):
        """pgrep exit 1 means no match."""
        fake_result = mock.Mock(returncode=1, stdout="", stderr="")
        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/pgrep",
            ),
            mock.patch(
                "cantrip.agent.tools.environment.subprocess.run",
                return_value=fake_result,
            ),
        ):
            assert _concierge_already_running() is False

    def test_pgrep_timeout_returns_false(self):
        """A timeout shouldn't block concierge — fail open."""
        import subprocess as _sp

        with (
            mock.patch(
                "cantrip.agent.tools.environment.shutil.which",
                return_value="/usr/bin/pgrep",
            ),
            mock.patch(
                "cantrip.agent.tools.environment.subprocess.run",
                side_effect=_sp.TimeoutExpired(cmd=["pgrep"], timeout=5),
            ),
        ):
            assert _concierge_already_running() is False


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
        """Skips prepare when a matching controller already exists."""
        status_proc = _make_fake_process(stdout="Status: succeeded\n")

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.environment._concierge_already_running", return_value=False
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[{"name": "c1", "cloud": "microk8s"}],
            ),
            mock.patch("asyncio.create_subprocess_exec", return_value=status_proc),
        ):
            result = await tool.execute(preset="k8s")

        assert result.success
        assert result.data.get("already_provisioned") is True
        assert "already provisioned" in result.output.lower()

    @pytest.mark.asyncio
    async def test_running_concierge_refused(self, tool):
        """Refuses to launch when another concierge is already running."""
        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.environment._concierge_already_running", return_value=True
            ),
        ):
            result = await tool.execute(preset="k8s")

        assert not result.success
        assert "already running" in result.error.lower()
        assert result.data.get("concierge_running") is True

    @pytest.mark.asyncio
    async def test_mismatched_controller_refused(self, tool):
        """Refuses to clobber a healthy controller on the wrong substrate."""
        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.environment._concierge_already_running", return_value=False
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers",
                return_value=[{"name": "c1", "cloud": "localhost"}],
            ),
        ):
            result = await tool.execute(preset="k8s")

        assert not result.success
        assert "localhost" in result.error
        assert "k8s" in result.error
        assert result.data.get("mismatch_cloud") == "localhost"
        assert result.data.get("requested_preset") == "k8s"

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
                "cantrip.agent.tools.environment._concierge_already_running", return_value=False
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers", return_value=[]
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
                "cantrip.agent.tools.environment._concierge_already_running", return_value=False
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers", return_value=[]
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
            # Second call (prepare) will time out.  ``kill`` is sync on
            # the real Process, so override the AsyncMock's inferred
            # async behaviour.
            proc = mock.AsyncMock()
            proc.communicate.side_effect = TimeoutError
            proc.returncode = None
            proc.kill = mock.MagicMock()
            return proc

        with (
            mock.patch("cantrip.agent.tools.environment._concierge_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.environment._concierge_already_running", return_value=False
            ),
            mock.patch(
                "cantrip.agent.tools.environment._list_healthy_controllers", return_value=[]
            ),
            mock.patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            mock.patch("asyncio.wait_for", side_effect=_raise_timeout),
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


class TestCharmcraftInitPaasRequirements:
    """Tests for the PaaS requirements.txt re-assertion.

    The agent has been observed overwriting a freshly-scaffolded charm's
    requirements.txt with the app's (e.g. ``cp app.py requirements.txt
    flask-demo/``).  That wipes ``paas-charm`` and the deployed charm
    then dies at install with ``ModuleNotFoundError: No module named
    'paas_charm'``.  ``_ensure_paas_requirements`` guarantees the lines
    are there again.
    """

    _PAAS_CHARMCRAFT_YAML = """\
name: test-charm
type: charm
base: ubuntu@24.04
platforms:
  amd64:
extensions:
  - flask-framework
"""

    _NON_PAAS_CHARMCRAFT_YAML = """\
name: test-charm
type: charm
base: ubuntu@24.04
platforms:
  amd64:
"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftInitTool()

    def _mock_charmcraft(self):
        return mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Initialised.", stderr=""),
        )

    @pytest.mark.asyncio
    async def test_app_requirements_overwrite_is_repaired(self, tool, temp_dir):
        """Simulate the observed bug: requirements.txt has only the app's deps."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("flask>=3.0\n")

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" in reqs, f"paas-charm missing from reqs: {reqs!r}"
        assert "ops" in reqs, f"ops missing from reqs: {reqs!r}"
        # The application's dep must survive the repair.
        assert "flask>=3.0" in reqs

    @pytest.mark.asyncio
    async def test_already_present_paas_deps_are_not_duplicated(self, tool, temp_dir):
        """A well-formed PaaS requirements.txt is left alone."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text(
            "ops ~= 2.17\npaas-charm>=1.0,<2\nflask>=3.0\n"
        )

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert reqs.count("paas-charm") == 1
        # One ``ops`` line (excluding ``ops-tracing`` which PaaS skips anyway).
        ops_lines = [ln for ln in reqs.splitlines() if ln.strip().startswith("ops")]
        assert len(ops_lines) == 1

    @pytest.mark.asyncio
    async def test_missing_requirements_file_is_created(self, tool, temp_dir):
        """When the agent deletes requirements.txt entirely the file is rebuilt."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
        # Deliberately no requirements.txt.

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs_path = charm_dir / "requirements.txt"
        assert reqs_path.exists()
        reqs = reqs_path.read_text()
        assert "paas-charm" in reqs
        assert "ops" in reqs

    @pytest.mark.asyncio
    async def test_non_paas_charm_untouched(self, tool, temp_dir):
        """A non-PaaS charm's requirements.txt must NOT gain paas-charm."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._NON_PAAS_CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" not in reqs

    @pytest.mark.asyncio
    async def test_ops_tracing_is_not_treated_as_ops(self, tool, temp_dir):
        """``ops-tracing`` alone must not satisfy the ``ops`` requirement.

        Because the regex that looks for ``ops`` had to avoid false
        positives on ``ops-tracing``, a requirements.txt containing only
        ``ops-tracing`` should still get ``ops`` added.  Otherwise the
        charm's ``import ops`` fails even though the deps look complete.
        """
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("ops-tracing\npaas-charm>=1.0,<2\n")

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        # One standalone ops line, plus the original ops-tracing line.
        bare_ops_lines = [
            ln
            for ln in reqs.splitlines()
            if ln.strip().startswith("ops")
            and not ln.strip().startswith("ops-")
            and not ln.strip().startswith("ops_")
        ]
        assert len(bare_ops_lines) == 1
        assert "ops-tracing" in reqs


class TestCharmcraftPackPaasRequirementsGuard:
    """Pre-pack guard against a broken PaaS requirements.txt.

    Even if the agent's init step produced a correct requirements.txt,
    a subsequent ``cp`` or ``edit_file`` can still overwrite it.  The
    pack tool runs the same re-assertion one last time before handing
    off to ``charmcraft pack`` so a broken charm is never shipped.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftPackTool()

    @pytest.mark.asyncio
    async def test_pack_repairs_overwritten_requirements(self, tool, temp_dir):
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir()
        (charm_dir / "charmcraft.yaml").write_text(
            "name: x\ntype: charm\nextensions:\n  - flask-framework\n"
        )
        # Simulate the post-``cp`` state that caused the live test failure.
        (charm_dir / "requirements.txt").write_text("flask>=3.0\n")

        # ``charmcraft pack`` itself is mocked — we only care about the guard.
        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="packed", stderr=""),
        ):
            result = await tool.execute(path=str(charm_dir))

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" in reqs
        assert "flask>=3.0" in reqs

    @pytest.mark.asyncio
    async def test_pack_does_not_touch_non_paas_requirements(self, tool, temp_dir):
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir()
        (charm_dir / "charmcraft.yaml").write_text("name: x\ntype: charm\n")
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="packed", stderr=""),
        ):
            await tool.execute(path=str(charm_dir))

        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" not in reqs


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


class TestInjectGithubWorkflows:
    """Tests for workflow/Dependabot/SECURITY.md scaffolding."""

    def test_creates_all_expected_files(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            actions = inject_github_workflows(target, "my-charm")

            assert (target / ".github" / "workflows" / "ci.yaml").exists()
            assert (target / ".github" / "workflows" / "security.yaml").exists()
            assert (target / ".github" / "workflows" / "release.yaml").exists()
            assert (target / ".github" / "dependabot.yml").exists()
            assert (target / "SECURITY.md").exists()
            assert len(actions) == 5
            assert all("Created" in a for a in actions)

    def test_preserves_existing_files(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            workflows = target / ".github" / "workflows"
            workflows.mkdir(parents=True)
            existing_ci = workflows / "ci.yaml"
            existing_ci.write_text("name: custom CI\n")

            actions = inject_github_workflows(target, "my-charm")

            assert existing_ci.read_text() == "name: custom CI\n"
            assert any("already exists" in a and "ci.yaml" in a for a in actions)
            assert (workflows / "security.yaml").exists()

    def test_actions_pinned_to_full_shas(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            ci = (target / ".github" / "workflows" / "ci.yaml").read_text()
            security = (target / ".github" / "workflows" / "security.yaml").read_text()
            release = (target / ".github" / "workflows" / "release.yaml").read_text()

            # No floating tag pins like ``@v4`` without a SHA.
            import re

            combined = ci + security + release
            for match in re.finditer(r"uses:\s*\S+", combined):
                line = match.group(0)
                # Every ``uses:`` line must have an @<40-hex-sha>.
                assert re.search(r"@[0-9a-f]{40}", line), f"unpinned action: {line}"

    def test_checkout_sets_persist_credentials_false(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                # Every checkout step should be followed by persist-credentials: false.
                assert content.count("actions/checkout@") == content.count(
                    "persist-credentials: false"
                ), f"{name} has a checkout without persist-credentials: false"

    def test_workflows_have_empty_workflow_level_permissions(self):
        import yaml

        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                parsed = yaml.safe_load(content)
                # Workflow-level permissions should be an empty mapping so
                # each job must opt in to what it needs.
                assert parsed.get("permissions") == {}, (
                    f"{name} should declare empty workflow-level permissions"
                )

    def test_release_uses_environment_and_avoids_pull_request_target(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            release = (target / ".github" / "workflows" / "release.yaml").read_text()
            assert "environment: charmhub" in release
            assert "workflow_dispatch" in release
            # Tag creation happens via gh api, not via git push.
            assert "git push origin" not in release
            # Never use pull_request_target.
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                assert "pull_request_target" not in content

    def test_dependabot_includes_cooldowns(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            config = (target / ".github" / "dependabot.yml").read_text()
            assert "cooldown:" in config
            assert "default-days: 14" in config
            assert "github-actions" in config
            assert "pip" in config

    def test_generated_yaml_parses(self):
        """Every generated YAML file must parse cleanly."""
        import yaml

        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for path in (
                target / ".github" / "workflows" / "ci.yaml",
                target / ".github" / "workflows" / "security.yaml",
                target / ".github" / "workflows" / "release.yaml",
                target / ".github" / "dependabot.yml",
            ):
                yaml.safe_load(path.read_text())
