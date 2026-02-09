"""Tests for Juju agent tools."""

from unittest import mock

import jubilant
import pytest

from cantrip.agent.tools.juju import (
    JujuAddModelTool,
    JujuConfigTool,
    JujuConsumeTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuOfferTool,
    JujuRefreshTool,
    JujuWaitTool,
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
