"""Tests for the RunCommandTool (scoped command runner)."""

import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.run_command import (
    _DEFAULT_TIMEOUT,
    _MAX_OUTPUT_CHARS,
    _MAX_TIMEOUT,
    DEFAULT_ALLOWLIST,
    RunCommandTool,
)


@pytest.fixture
def tool():
    return RunCommandTool()


@pytest.fixture
def custom_tool():
    return RunCommandTool(allowlist=frozenset({"echo", "ls"}))


class TestRunCommandProperties:
    """Tests for tool metadata."""

    def test_name(self, tool):
        assert tool.name == "run_command"

    def test_required_params(self, tool):
        assert "command" in tool.parameters["required"]

    def test_description_lists_commands(self, tool):
        assert "make" in tool.description
        assert "pytest" in tool.description

    def test_custom_allowlist_in_description(self, custom_tool):
        assert "echo" in custom_tool.description
        assert "make" not in custom_tool.description


class TestRunCommandExecution:
    """Tests for command execution."""

    @pytest.mark.anyio
    async def test_allowed_command_success(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert result.success
        assert "hello" in result.output
        assert result.data["returncode"] == 0

    @pytest.mark.anyio
    async def test_blocked_command(self, tool):
        result = await tool.execute(command="rm -rf /")
        assert not result.success
        assert "not on the allowlist" in result.error
        assert "rm" in result.error

    @pytest.mark.anyio
    async def test_empty_command(self, tool):
        result = await tool.execute(command="")
        assert not result.success
        assert "Empty" in result.error

    @pytest.mark.anyio
    async def test_nonzero_exit_code(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error occurred"

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="ls nonexistent")

        assert not result.success
        assert "exit" in result.error.lower()
        assert result.data["returncode"] == 1

    @pytest.mark.anyio
    async def test_timeout(self, custom_tool):
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["echo"], timeout=60),
        ):
            result = await custom_tool.execute(command="echo slow")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.anyio
    async def test_command_not_found(self, custom_tool):
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_stderr_appended(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output\n"
        mock_result.stderr = "warning\n"

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert result.success
        assert "output" in result.output
        assert "stderr" in result.output
        assert "warning" in result.output

    @pytest.mark.anyio
    async def test_output_truncated(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "x" * (_MAX_OUTPUT_CHARS + 100)
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo big")

        assert result.success
        assert result.data["truncated"]
        assert "truncated" in result.output

    @pytest.mark.anyio
    async def test_timeout_clamped(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            await custom_tool.execute(command="echo hi", timeout=9999)

        # Should be clamped to _MAX_TIMEOUT.
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["timeout"] == _MAX_TIMEOUT

    @pytest.mark.anyio
    async def test_invalid_syntax(self, tool):
        result = await tool.execute(command="make 'unclosed")
        assert not result.success
        assert "syntax" in result.error.lower()

    @pytest.mark.anyio
    async def test_custom_cwd(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            await custom_tool.execute(command="ls", cwd="/tmp")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["cwd"] == "/tmp"


class TestRunCommandConstants:
    """Tests for module-level constants."""

    def test_default_allowlist(self):
        assert "make" in DEFAULT_ALLOWLIST
        assert "uv" in DEFAULT_ALLOWLIST
        assert "pytest" in DEFAULT_ALLOWLIST
        assert "ruff" in DEFAULT_ALLOWLIST
        assert "rm" not in DEFAULT_ALLOWLIST

    def test_default_timeout(self):
        assert _DEFAULT_TIMEOUT == 60

    def test_max_timeout(self):
        assert _MAX_TIMEOUT == 300
