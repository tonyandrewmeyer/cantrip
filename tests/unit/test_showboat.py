"""Tests for the Showboat agent tool."""

import subprocess
from unittest.mock import patch

import pytest

from cantrip.agent.tools.showboat import ShowboatTool


@pytest.fixture
def tool():
    return ShowboatTool()


class TestShowboatTool:
    """Tests for ShowboatTool."""

    @pytest.mark.asyncio
    async def test_not_installed(self, tool) -> None:
        """Returns a clear error when showboat is not installed."""
        with patch("cantrip.agent.tools.showboat.shutil.which", return_value=None):
            result = await tool.execute(command="init", file="demo.md", args=["Title"])

        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_invalid_command(self, tool) -> None:
        """Rejects unknown subcommands."""
        with patch("cantrip.agent.tools.showboat.shutil.which", return_value="/usr/bin/showboat"):
            result = await tool.execute(command="invalid", file="demo.md")

        assert not result.success
        assert "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_init_success(self, tool) -> None:
        """Successful init returns success."""
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Created demo.md", stderr=""
        )
        with (
            patch("cantrip.agent.tools.showboat.shutil.which", return_value="/usr/bin/showboat"),
            patch("cantrip.agent.tools.showboat.subprocess.run", return_value=fake_result),
        ):
            result = await tool.execute(command="init", file="demo.md", args=["My Demo"])

        assert result.success
        assert "demo.md" in result.output

    @pytest.mark.asyncio
    async def test_exec_failure(self, tool) -> None:
        """Failed exec returns error with output."""
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="command not found"
        )
        with (
            patch("cantrip.agent.tools.showboat.shutil.which", return_value="/usr/bin/showboat"),
            patch("cantrip.agent.tools.showboat.subprocess.run", return_value=fake_result),
        ):
            result = await tool.execute(command="exec", file="demo.md", args=["bash", "ls"])

        assert not result.success
        assert "failed" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tool) -> None:
        """Timeout produces a clear error."""
        with (
            patch("cantrip.agent.tools.showboat.shutil.which", return_value="/usr/bin/showboat"),
            patch(
                "cantrip.agent.tools.showboat.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="showboat", timeout=60),
            ),
        ):
            result = await tool.execute(command="exec", file="demo.md", args=["bash", "sleep 999"])

        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_workdir_passed(self, tool) -> None:
        """Working directory is forwarded to subprocess."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with (
            patch("cantrip.agent.tools.showboat.shutil.which", return_value="/usr/bin/showboat"),
            patch(
                "cantrip.agent.tools.showboat.subprocess.run", return_value=fake_result
            ) as mock_run,
        ):
            await tool.execute(command="exec", file="demo.md", args=["bash", "ls"], workdir="/tmp")

        assert mock_run.call_args[1]["cwd"] == "/tmp"

    @pytest.mark.asyncio
    async def test_all_valid_commands_accepted(self, tool) -> None:
        """All documented commands are accepted."""
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        for cmd in ("init", "note", "exec", "image", "pop", "verify"):
            with (
                patch(
                    "cantrip.agent.tools.showboat.shutil.which",
                    return_value="/usr/bin/showboat",
                ),
                patch(
                    "cantrip.agent.tools.showboat.subprocess.run",
                    return_value=fake_result,
                ),
            ):
                result = await tool.execute(command=cmd, file="demo.md")
                assert result.success, f"command {cmd} should succeed"

    def test_tool_metadata(self, tool) -> None:
        """Tool has correct name and parameter schema."""
        assert tool.name == "showboat"
        assert "command" in tool.parameters["properties"]
        assert "file" in tool.parameters["properties"]
