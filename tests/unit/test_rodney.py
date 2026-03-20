"""Tests for the Rodney agent tool."""

import subprocess
from unittest.mock import patch

import pytest

from cantrip.agent.tools.rodney import RodneyTool


@pytest.fixture
def tool():
    return RodneyTool()


class TestRodneyTool:
    """Tests for RodneyTool."""

    @pytest.mark.asyncio
    async def test_not_installed(self, tool) -> None:
        """Returns a clear error when rodney is not installed."""
        with patch("cantrip.agent.tools.rodney.shutil.which", return_value=None):
            result = await tool.execute(command="start")

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_start_success(self, tool) -> None:
        """Successful start returns success."""
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Chrome started", stderr=""
        )
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch("cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result),
        ):
            result = await tool.execute(command="start")

        assert result.success

    @pytest.mark.asyncio
    async def test_screenshot_success(self, tool) -> None:
        """Screenshot command returns success."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch("cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result),
        ):
            result = await tool.execute(command="screenshot", args=["page.png"])

        assert result.success

    @pytest.mark.asyncio
    async def test_open_failure(self, tool) -> None:
        """Failed command returns error."""
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="Chrome not running"
        )
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch("cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result),
        ):
            result = await tool.execute(command="open", args=["http://localhost:8080"])

        assert not result.success
        assert "failed" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tool) -> None:
        """Timeout produces a clear error."""
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch(
                "cantrip.agent.tools.rodney.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="rodney", timeout=30),
            ),
        ):
            result = await tool.execute(command="wait", args=[".loading"])

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_uses_local_flag(self, tool) -> None:
        """Rodney is invoked with --local for directory-scoped sessions."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch(
                "cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            await tool.execute(command="status")

        cmd = mock_run.call_args[0][0]
        assert "--local" in cmd

    @pytest.mark.asyncio
    async def test_screenshot_gets_longer_timeout(self, tool) -> None:
        """Screenshot commands get a longer timeout than regular commands."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch(
                "cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            await tool.execute(command="screenshot", args=["out.png"])

        assert mock_run.call_args[1]["timeout"] == 60

    @pytest.mark.asyncio
    async def test_regular_command_timeout(self, tool) -> None:
        """Non-screenshot commands get the standard timeout."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch("cantrip.agent.tools.rodney.shutil.which", return_value="/usr/bin/rodney"),
            patch(
                "cantrip.agent.tools.rodney.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            await tool.execute(command="status")

        assert mock_run.call_args[1]["timeout"] == 30

    def test_tool_metadata(self, tool) -> None:
        """Tool has correct name and parameter schema."""
        assert tool.name == "rodney"
        assert "command" in tool.parameters["properties"]
