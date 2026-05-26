"""Phase 69.3 ``Ctrl-X`` shell-mode coverage.

Two layers:

* ``parse_shell_input`` / ``run_shell_command`` / ``metadata_for_persisted_row``
  are exercised directly on a stub :class:`SandboxedRunner` so the parsing
  rules and metadata shape are nailed down without spinning the TUI.
* The Pilot tests drive ``ChatInput.toggle_shell_mode`` and
  ``CantripApp.on_input_submitted`` end to end so the dispatch
  contract — Ctrl-X flips the mode, shell submissions become SHELL
  rows rather than user messages, and the agent worker is never
  fired — survives future refactors of the input dispatch chain.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Input

from cantrip.tui.actions import shell as shell_action
from cantrip.tui.app import CantripApp
from cantrip.tui.widgets import chat as chat_widget
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


class TestParseShellInput:
    """``parse_shell_input`` covers the ``$$`` prefix + tokenisation rules."""

    def test_plain_command_splits_and_keeps_visible(self) -> None:
        parsed = shell_action.parse_shell_input("ls -la /tmp")
        assert parsed.argv == ("ls", "-la", "/tmp")
        assert parsed.hidden_from_agent is False
        assert parsed.error is None

    def test_double_dollar_marks_incognito_and_strips_prefix(self) -> None:
        parsed = shell_action.parse_shell_input("$$ cat .env")
        assert parsed.argv == ("cat", ".env")
        assert parsed.hidden_from_agent is True
        assert parsed.error is None

    def test_double_dollar_without_space_still_strips(self) -> None:
        parsed = shell_action.parse_shell_input("$$cat /etc/hosts")
        assert parsed.argv == ("cat", "/etc/hosts")
        assert parsed.hidden_from_agent is True

    def test_only_double_dollar_returns_error(self) -> None:
        parsed = shell_action.parse_shell_input("$$")
        assert parsed.argv == ()
        assert parsed.hidden_from_agent is True
        assert parsed.error is not None
        assert "incognito" in parsed.error

    def test_empty_input_returns_error(self) -> None:
        parsed = shell_action.parse_shell_input("   ")
        assert parsed.argv == ()
        assert parsed.error == "Empty command."

    def test_unbalanced_quote_surfaces_friendly_error(self) -> None:
        parsed = shell_action.parse_shell_input('echo "still open')
        assert parsed.argv == ()
        assert parsed.error is not None
        assert "Invalid shell syntax" in parsed.error

    def test_quoted_args_preserved(self) -> None:
        parsed = shell_action.parse_shell_input('echo "hello world"')
        assert parsed.argv == ("echo", "hello world")
        assert parsed.hidden_from_agent is False


class TestRunShellCommand:
    """``run_shell_command`` wraps the sandbox runner."""

    def test_captures_stdout_stderr_and_exit_code(self) -> None:
        runner = MagicMock()
        runner.run.return_value = subprocess.CompletedProcess(
            args=["echo", "hi"],
            returncode=0,
            stdout="hi\n",
            stderr="",
        )
        result = shell_action.run_shell_command(["echo", "hi"], cwd="/tmp", runner=runner)
        assert result.exit_code == 0
        assert result.output == "hi\n"
        assert result.timed_out is False

    def test_missing_binary_returns_127(self) -> None:
        runner = MagicMock()
        runner.run.side_effect = FileNotFoundError(2, "No such file", "nonesuch-bin")
        result = shell_action.run_shell_command(["nonesuch-bin"], cwd="/tmp", runner=runner)
        assert result.exit_code == 127
        assert "command not found" in result.output

    def test_timeout_surfaces_124_and_marks_flag(self) -> None:
        runner = MagicMock()
        runner.run.side_effect = subprocess.TimeoutExpired(cmd=["sleep", "999"], timeout=0.1)
        result = shell_action.run_shell_command(
            ["sleep", "999"], cwd="/tmp", runner=runner, timeout=0.1
        )
        assert result.exit_code == 124
        assert result.timed_out is True

    def test_output_truncated_above_cap(self) -> None:
        runner = MagicMock()
        big = "a" * (shell_action._MAX_OUTPUT_CHARS + 100)
        runner.run.return_value = subprocess.CompletedProcess(
            args=["yes"],
            returncode=0,
            stdout=big,
            stderr="",
        )
        result = shell_action.run_shell_command(["yes"], cwd="/tmp", runner=runner)
        assert "output truncated" in result.output
        assert len(result.output) <= shell_action._MAX_OUTPUT_CHARS + 200


class TestMetadata:
    def test_metadata_records_argv_exit_code_and_hidden_flag(self) -> None:
        result = shell_action.ShellRunResult(
            argv=("cat", ".env"),
            exit_code=0,
            output="SECRET=xyz\n",
        )
        meta = shell_action.metadata_for_persisted_row(result, hidden_from_agent=True)
        assert meta["argv"] == ["cat", ".env"]
        assert meta["exit_code"] == 0
        assert meta["hidden_from_agent"] is True
        assert meta["timed_out"] is False
        # Phase 72.2 follow-up: ``output`` is now persisted so the
        # ``@terminal`` context provider can render the last visible
        # shell-mode block without re-running the command.
        assert meta["output"] == "SECRET=xyz\n"


# ---------------------------------------------------------------------------
# TUI integration tests (Pilot-driven)
# ---------------------------------------------------------------------------


class TestChatInputShellModeToggle:
    """``Ctrl-X`` flips the input's shell-mode flag and styling."""

    @pytest.mark.asyncio
    async def test_default_state_is_agent_mode(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                assert chat_input.shell_mode is False
                assert "-shell-mode" not in chat_input.classes
                assert chat_input.placeholder == chat_widget.ChatInput.AGENT_PLACEHOLDER

    @pytest.mark.asyncio
    async def test_toggle_flips_flag_class_and_placeholder(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                chat_input.toggle_shell_mode()
                assert chat_input.shell_mode is True
                assert "-shell-mode" in chat_input.classes
                assert chat_input.placeholder == chat_widget.ChatInput.SHELL_PLACEHOLDER
                # Flipping again returns to agent mode.
                chat_input.toggle_shell_mode()
                assert chat_input.shell_mode is False
                assert "-shell-mode" not in chat_input.classes
                assert chat_input.placeholder == chat_widget.ChatInput.AGENT_PLACEHOLDER


class TestShellSubmissionDispatch:
    """``on_input_submitted`` short-circuits before the agent when shell-mode is on."""

    @pytest.mark.asyncio
    async def test_shell_submission_runs_subprocess_not_agent(self) -> None:
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                chat_input.toggle_shell_mode()
                chat_input.value = "echo hello"

                fake_result = shell_action.ShellRunResult(
                    argv=("echo", "hello"),
                    exit_code=0,
                    output="hello\n",
                )
                with patch.object(
                    shell_action, "run_shell_command", return_value=fake_result
                ) as run_call:
                    event = Input.Submitted(chat_input, "echo hello")
                    await pilot.app.on_input_submitted(event)

                run_call.assert_called_once()
                # Agent worker must not have fired.
                if hasattr(mock_agent.process_message_streaming, "assert_not_called"):
                    mock_agent.process_message_streaming.assert_not_called()
                # A SHELL row appears in chat; no USER row.
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                roles = [m.role for m in chat._messages]
                assert chat_widget.MessageRole.SHELL in roles
                assert chat_widget.MessageRole.USER not in roles

    @pytest.mark.asyncio
    async def test_double_dollar_marks_metadata_hidden(self) -> None:
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                chat_input.toggle_shell_mode()
                chat_input.value = "$$ cat .env"

                fake_store = MagicMock()
                mock_agent.store = fake_store
                fake_result = shell_action.ShellRunResult(
                    argv=("cat", ".env"),
                    exit_code=0,
                    output="SECRET=xyz\n",
                )
                with patch.object(shell_action, "run_shell_command", return_value=fake_result):
                    event = Input.Submitted(chat_input, "$$ cat .env")
                    await pilot.app.on_input_submitted(event)

                fake_store.record_message.assert_called_once()
                kwargs = fake_store.record_message.call_args.kwargs
                assert kwargs["role"] == "shell"
                assert kwargs["metadata"]["hidden_from_agent"] is True
                assert kwargs["metadata"]["argv"] == ["cat", ".env"]

    @pytest.mark.asyncio
    async def test_plain_shell_persists_with_visible_flag_false(self) -> None:
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                chat_input.toggle_shell_mode()
                chat_input.value = "ls"

                fake_store = MagicMock()
                mock_agent.store = fake_store
                fake_result = shell_action.ShellRunResult(
                    argv=("ls",),
                    exit_code=0,
                    output="README.md\n",
                )
                with patch.object(shell_action, "run_shell_command", return_value=fake_result):
                    event = Input.Submitted(chat_input, "ls")
                    await pilot.app.on_input_submitted(event)

                kwargs = fake_store.record_message.call_args.kwargs
                assert kwargs["metadata"]["hidden_from_agent"] is False

    @pytest.mark.asyncio
    async def test_invalid_syntax_surfaces_system_message(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat_input = pilot.app.query_one("#chat-input", chat_widget.ChatInput)
                chat_input.toggle_shell_mode()
                value = 'echo "broken'
                chat_input.value = value

                with patch.object(shell_action, "run_shell_command") as run_call:
                    event = Input.Submitted(chat_input, value)
                    await pilot.app.on_input_submitted(event)

                run_call.assert_not_called()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                system_text = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Invalid shell syntax" in system_text
