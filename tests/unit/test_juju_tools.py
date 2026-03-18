"""Tests for Juju agent tools."""

from unittest import mock

import jubilant
import pytest

from cantrip.agent.tools.juju import (
    CharmSyncTool,
    JujuAddModelTool,
    JujuConfigTool,
    JujuConsumeTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuDispatchTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuWaitTool,
    _agent_charm_dir,
    _is_k8s_model,
    _juju_available,
)


class TestJujuAvailable:
    """Tests for the _juju_available helper."""

    def test_available(self):
        """Returns True when juju is on PATH."""
        with mock.patch("cantrip.agent.tools.juju.shutil.which", return_value="/usr/bin/juju"):
            assert _juju_available() is True

    def test_not_available(self):
        """Returns False when juju is not on PATH."""
        with mock.patch("cantrip.agent.tools.juju.shutil.which", return_value=None):
            assert _juju_available() is False


class TestJujuAddModelTool:
    """Tests for JujuAddModelTool."""

    @pytest.fixture
    def tool(self):
        return JujuAddModelTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_add_model_success(self, tool):
        """Creates a model successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert result.success
        assert result.data["model"] == "dev"
        mock_juju.add_model.assert_called_once_with("dev", cloud=None)

    @pytest.mark.asyncio
    async def test_add_model_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.add_model.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "add-model"],
            stderr="model already exists",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "already exists" in result.error


class TestJujuDestroyModelTool:
    """Tests for JujuDestroyModelTool."""

    @pytest.fixture
    def tool(self):
        return JujuDestroyModelTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(model="dev")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_destroy_model_success(self, tool):
        """Destroys a model successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev")

        assert result.success
        assert result.data["model"] == "dev"
        mock_juju.destroy_model.assert_called_once_with(
            "dev",
            force=False,
            destroy_storage=True,
            no_wait=False,
        )

    @pytest.mark.asyncio
    async def test_destroy_model_force(self, tool):
        """Passes force and no_wait when force=True."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="dev", force=True)

        assert result.success
        mock_juju.destroy_model.assert_called_once_with(
            "dev",
            force=True,
            destroy_storage=True,
            no_wait=True,
        )

    @pytest.mark.asyncio
    async def test_destroy_model_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.destroy_model.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "destroy-model"],
            stderr="model not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model="nonexistent")

        assert not result.success
        assert "not found" in result.error


class TestJujuOfferTool:
    """Tests for JujuOfferTool."""

    @pytest.fixture
    def tool(self):
        return JujuOfferTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(app="grafana", endpoint="grafana-dashboard")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_offer_success(self, tool):
        """Creates an offer successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app="grafana", endpoint="grafana-dashboard", model="cos")

        assert result.success
        assert "grafana:grafana-dashboard" in result.output
        mock_juju.offer.assert_called_once_with("grafana", endpoint="grafana-dashboard")

    @pytest.mark.asyncio
    async def test_offer_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.offer.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "offer"],
            stderr="endpoint not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app="grafana", endpoint="bad-endpoint")

        assert not result.success
        assert "endpoint not found" in result.error


class TestJujuConsumeTool:
    """Tests for JujuConsumeTool."""

    @pytest.fixture
    def tool(self):
        return JujuConsumeTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(model_and_app="cos.grafana")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_consume_success(self, tool):
        """Consumes an offer successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model_and_app="cos.grafana")

        assert result.success
        assert "grafana" in result.output
        mock_juju.consume.assert_called_once_with("cos.grafana", None)

    @pytest.mark.asyncio
    async def test_consume_with_alias(self, tool):
        """Consumes an offer with a local alias."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                model_and_app="cos.grafana",
                alias="cos-grafana",
                model="dev",
            )

        assert result.success
        assert "cos-grafana" in result.output
        mock_juju.consume.assert_called_once_with("cos.grafana", "cos-grafana")

    @pytest.mark.asyncio
    async def test_consume_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.consume.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "consume"],
            stderr="offer not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(model_and_app="cos.nonexistent")

        assert not result.success
        assert "offer not found" in result.error


class TestJujuDeployTool:
    """Tests for JujuDeployTool resources and trust parameters."""

    @pytest.fixture
    def tool(self):
        return JujuDeployTool()

    @pytest.mark.asyncio
    async def test_deploy_with_resources(self, tool):
        """Passes resources to Jubilant deploy."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                charm="./my-app.charm",
                resources={"oci-image": "localhost:32000/my-app:latest"},
            )

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["resources"] == {"oci-image": "localhost:32000/my-app:latest"}

    @pytest.mark.asyncio
    async def test_deploy_with_trust(self, tool):
        """Passes trust=True to Jubilant deploy."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(charm="traefik-k8s", trust=True)

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert call_kwargs["trust"] is True

    @pytest.mark.asyncio
    async def test_deploy_without_resources_or_trust(self, tool):
        """Does not pass resources or trust when not specified."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(charm="my-charm")

        assert result.success
        mock_juju.deploy.assert_called_once()
        call_kwargs = mock_juju.deploy.call_args[1]
        assert "resources" not in call_kwargs
        assert "trust" not in call_kwargs


class TestJujuRefreshTool:
    """Tests for JujuRefreshTool."""

    @pytest.fixture
    def tool(self):
        return JujuRefreshTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_refresh_success(self, tool):
        """Refreshes a charm successfully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", path="./my-app.charm")

        assert result.success
        assert "my-app" in result.output
        mock_juju.refresh.assert_called_once_with(app="my-app", path="./my-app.charm")

    @pytest.mark.asyncio
    async def test_refresh_with_resources(self, tool):
        """Passes resources to Jubilant refresh."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                app_name="my-app",
                path="./my-app.charm",
                resources={"oci-image": "localhost:32000/my-app:latest"},
            )

        assert result.success
        mock_juju.refresh.assert_called_once_with(
            app="my-app",
            path="./my-app.charm",
            resources={"oci-image": "localhost:32000/my-app:latest"},
        )

    @pytest.mark.asyncio
    async def test_refresh_without_resources(self, tool):
        """Does not pass resources when not specified."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        mock_juju.refresh.assert_called_once_with(app="my-app")

    @pytest.mark.asyncio
    async def test_refresh_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.refresh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "refresh"],
            stderr="app not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "app not found" in result.error


class TestJujuConfigTool:
    """Tests for JujuConfigTool."""

    @pytest.fixture
    def tool(self):
        return JujuConfigTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_get_config(self, tool):
        """Returns current config when values is omitted."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.return_value = {"port": "8080", "debug": "false"}

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        assert "8080" in result.output
        mock_juju.config.assert_called_once_with("my-app", values=None)

    @pytest.mark.asyncio
    async def test_set_config(self, tool):
        """Sets config values when values is provided."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.return_value = None

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                app_name="my-app",
                values={"port": "9090"},
            )

        assert result.success
        assert "Config updated" in result.output
        mock_juju.config.assert_called_once_with("my-app", values={"port": "9090"})

    @pytest.mark.asyncio
    async def test_config_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.config.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "config"],
            stderr="app not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="nonexistent")

        assert not result.success
        assert "app not found" in result.error


class TestJujuWaitTool:
    """Tests for JujuWaitTool."""

    @pytest.fixture
    def tool(self):
        return JujuWaitTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wait_success(self, tool):
        """Returns status when app reaches active/idle."""
        mock_unit = mock.MagicMock()
        mock_unit.workload_status.current = "active"
        mock_unit.agent_status.current = "idle"

        mock_app = mock.MagicMock()
        mock_app.app_status.current = "active"
        mock_app.units = {"my-app/0": mock_unit}

        mock_status = mock.MagicMock()
        mock_status.apps = {"my-app": mock_app}

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.return_value = mock_status

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert result.success
        assert "active/idle" in result.output
        assert "my-app/0" in result.output
        mock_juju.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_timeout(self, tool):
        """Reports timeout when app does not settle."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.side_effect = TimeoutError()

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app", timeout=60)

        assert not result.success
        assert "Timed out" in result.error
        assert "60" in result.error

    @pytest.mark.asyncio
    async def test_wait_error(self, tool):
        """Reports CLI errors."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.wait.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "status"],
            stderr="model not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(app_name="my-app")

        assert not result.success
        assert "model not found" in result.error


class TestAgentCharmDir:
    """Tests for the _agent_charm_dir helper."""

    def test_simple_unit(self):
        """Converts a standard unit name to the on-disk path."""
        assert _agent_charm_dir("my-app/0") == "/var/lib/juju/agents/unit-my-app-0/charm"

    def test_unit_with_higher_number(self):
        """Works with multi-digit unit numbers."""
        assert _agent_charm_dir("postgresql/12") == "/var/lib/juju/agents/unit-postgresql-12/charm"


class TestIsK8sModel:
    """Tests for the _is_k8s_model helper."""

    @pytest.mark.asyncio
    async def test_caas_model(self):
        """Returns True for a Kubernetes (CAAS) model."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"

        with mock.patch("cantrip.agent.tools.juju._run_juju", return_value=mock_info):
            assert await _is_k8s_model(mock_juju) is True

    @pytest.mark.asyncio
    async def test_iaas_model(self):
        """Returns False for a machine (IAAS) model."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"

        with mock.patch("cantrip.agent.tools.juju._run_juju", return_value=mock_info):
            assert await _is_k8s_model(mock_juju) is False


class TestCharmSyncTool:
    """Tests for CharmSyncTool."""

    @pytest.fixture
    def tool(self):
        return CharmSyncTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(unit="my-app/0")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sync_k8s_charm(self, tool, tmp_path):
        """Syncs files to a K8s unit using scp with container='charm'."""
        # Create a local charm directory with a source file.
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        charm_py = src_dir / "charm.py"
        charm_py.write_text("# charm code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 1

        # Verify ssh called with container="charm" for mkdir.
        mock_juju.ssh.assert_called_once()
        ssh_call = mock_juju.ssh.call_args
        assert ssh_call.kwargs.get("container") == "charm"

        # Verify scp called with container="charm".
        mock_juju.scp.assert_called_once()
        scp_call = mock_juju.scp.call_args
        assert scp_call.kwargs.get("container") == "charm"
        assert "my-app/0:" in scp_call.args[1]

    @pytest.mark.asyncio
    async def test_sync_machine_charm(self, tool, tmp_path):
        """Syncs files to a machine unit using cli('ssh', ..., stdin=...)."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        charm_py = src_dir / "charm.py"
        charm_py.write_text("# charm code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 1

        # Verify ssh called with sudo mkdir (no container kwarg).
        mock_juju.ssh.assert_called_once()
        ssh_call = mock_juju.ssh.call_args
        assert "sudo mkdir" in ssh_call.args[1]
        assert "container" not in ssh_call.kwargs

        # Verify cli called with stdin containing the file content.
        mock_juju.cli.assert_called_once()
        cli_call = mock_juju.cli.call_args
        assert cli_call.args[0] == "ssh"
        assert cli_call.kwargs.get("stdin") == "# charm code"

    @pytest.mark.asyncio
    async def test_sync_no_matching_files(self, tool, tmp_path):
        """Returns success with 0 files when directories are empty."""
        # Create empty src directory (no .py files).
        (tmp_path / "src").mkdir()

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        assert result.data["files_synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_correct_remote_path(self, tool, tmp_path):
        """Verifies the remote path is correctly constructed."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "charm.py").write_text("# code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert result.success
        scp_call = mock_juju.scp.call_args
        expected_remote = "my-app/0:/var/lib/juju/agents/unit-my-app-0/charm/src/charm.py"
        assert scp_call.args[1] == expected_remote

    @pytest.mark.asyncio
    async def test_sync_cli_error(self, tool, tmp_path):
        """CLIError produces a failed ToolResult."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "charm.py").write_text("# code")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "ssh"],
            stderr="connection refused",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", charm_dir=str(tmp_path))

        assert not result.success
        assert "connection refused" in result.error

    @pytest.mark.asyncio
    async def test_sync_custom_directories(self, tool, tmp_path):
        """Respects a custom directories list."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "module.py").write_text("# custom")

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(
                unit="my-app/0",
                charm_dir=str(tmp_path),
                directories=["custom"],
            )

        assert result.success
        assert result.data["files_synced"] == 1
        assert "custom/module.py" in result.data["files"][0]


class TestJujuDispatchTool:
    """Tests for JujuDispatchTool."""

    @pytest.fixture
    def tool(self):
        return JujuDispatchTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool):
        """Error when juju CLI is missing."""
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dispatch_k8s(self, tool):
        """Dispatches on K8s with container='charm'."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.return_value = "hook output"

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert result.success
        assert "hook output" in result.output
        assert result.data["event"] == "update-status"

        ssh_call = mock_juju.ssh.call_args
        assert ssh_call.kwargs.get("container") == "charm"
        cmd = ssh_call.args[1]
        assert "JUJU_DISPATCH_PATH=hooks/update-status" in cmd
        assert "/var/lib/juju/agents/unit-my-app-0/charm/dispatch" in cmd

    @pytest.mark.asyncio
    async def test_dispatch_machine(self, tool):
        """Dispatches on a machine model with sudo."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "iaas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.return_value = "machine output"

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="config-changed")

        assert result.success
        assert "machine output" in result.output

        ssh_call = mock_juju.ssh.call_args
        assert "container" not in ssh_call.kwargs
        cmd = ssh_call.args[1]
        assert cmd.startswith("sudo ")
        assert "JUJU_DISPATCH_PATH=hooks/config-changed" in cmd

    @pytest.mark.asyncio
    async def test_dispatch_cli_error(self, tool):
        """CLIError produces a failed ToolResult."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_info = mock.MagicMock()
        mock_info.model_type = "caas"
        mock_juju.show_model.return_value = mock_info
        mock_juju.ssh.side_effect = jubilant.CLIError(
            returncode=1,
            cmd=["juju", "ssh"],
            stderr="unit not found",
        )

        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju.jubilant.Juju", return_value=mock_juju),
        ):
            result = await tool.execute(unit="my-app/0", event="update-status")

        assert not result.success
        assert "unit not found" in result.error
