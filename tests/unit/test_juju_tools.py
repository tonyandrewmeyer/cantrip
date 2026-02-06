"""Tests for Juju agent tools."""

from unittest import mock

import jubilant
import pytest

from cantrip.agent.tools.juju import (
    JujuAddModelTool,
    JujuConsumeTool,
    JujuDestroyModelTool,
    JujuOfferTool,
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
        mock_juju.add_model.assert_called_once_with("dev")

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
