"""Tests for the environment tools (concierge, provisioning)."""

from unittest import mock

import pytest

from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
    _concierge_already_running,
    _concierge_available,
    _healthy_controller_matches_preset,
    _is_already_provisioned,
)


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
