"""Targeted tests for under-covered ``CantripApp`` methods (Phase 93.1).

Drives the dormant branches the broad ``test_tui.py`` suite doesn't
reach: the update-check worker's failure path, header-subtitle / model-
info refreshes, the eager-prepare and re-bootstrap preflight handlers,
light-provider resolution, the shared-slash-command clipboard / follow-
up branches, and the resume-prompt modal flow (which also covers
``tui/screens/resume.py``).
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.commands.slash import SlashResult
from cantrip.agent.runtime.preflight import CheckStatus, PreflightEvent
from cantrip.agent.session_preview import SessionPreview
from cantrip.llm.base import Message, Role
from cantrip.tui.app import CantripApp
from cantrip.tui.screens.resume import ResumePromptScreen
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import statusbar as statusbar_widget
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui

_TERMINAL = (140, 50)


def _system_text(app: CantripApp) -> str:
    chat = app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


# ---------------------------------------------------------------------------
# Update-check worker
# ---------------------------------------------------------------------------


class TestUpdateCheckWorker:
    @pytest.mark.asyncio
    async def test_failure_is_swallowed(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                with patch(
                    "cantrip.tui.app.update.check_for_update", side_effect=OSError("offline")
                ):
                    await pilot.app._run_update_check()
                assert pilot.app.pending_update_info is None

    @pytest.mark.asyncio
    async def test_success_stashes_result(self) -> None:
        p1, p2, _ = _patch_app()
        sentinel = MagicMock()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                with patch("cantrip.tui.app.update.check_for_update", return_value=sentinel):
                    await pilot.app._run_update_check()
                assert pilot.app.pending_update_info is sentinel


# ---------------------------------------------------------------------------
# Header / model-info refresh
# ---------------------------------------------------------------------------


class TestHeaderRefresh:
    @pytest.mark.asyncio
    async def test_update_header_subtitle_pushes_model_and_branch(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.provider.name = "gemini"
        mock_agent.provider.model_name = "gemini-3-pro"
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                app.charm_path = pathlib.Path("/some/charm")
                with patch("cantrip.tui.app.git_branch.current_branch", return_value="feature"):
                    app._update_header_subtitle()
                await pilot.pause()
                header = app.query_one("#cantrip-header")
                assert header.model_name == "gemini/gemini-3-pro"
                assert header.charm_path == pathlib.Path("/some/charm")
                assert header.git_branch == "feature"

    @pytest.mark.asyncio
    async def test_update_model_info_sets_thinking_for_supported_models(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.provider.model_name = "claude-opus-4-7"
        mock_agent.provider.name = "anthropic"
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                pilot.app._update_model_info()
                await pilot.pause()
                bar = pilot.app.query_one("#model-info")
                assert bar.thinking_mode == "thinking"


# ---------------------------------------------------------------------------
# Preflight / bootstrap event handlers
# ---------------------------------------------------------------------------


class TestPreflightHandlers:
    @pytest.mark.asyncio
    async def test_prepare_cos_passed_marks_status_bar(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                app._start_prepare()
                await pilot.pause()
                assert app._prepare_group_idx is not None
                # A non-final check just updates the pane (no crash).
                app._on_prepare_event(PreflightEvent("juju", CheckStatus.RUNNING, "", None))
                # COS passing flips the status-bar health badge.
                app._on_prepare_event(PreflightEvent("cos", CheckStatus.PASSED, "", None))
                await pilot.pause()
                bar = app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert bar.cos_health == "● COS healthy"

    @pytest.mark.asyncio
    async def test_on_prepare_event_noop_without_group(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                pilot.app._prepare_group_idx = None
                # Must not raise.
                pilot.app._on_prepare_event(PreflightEvent("cos", CheckStatus.PASSED, "", None))

    @pytest.mark.asyncio
    async def test_start_bootstrap_when_preset_differs(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_type = "vm"
        mock_agent.preflight_result.fully_ready = False
        mock_agent.bootstrap_environment = MagicMock(return_value=_noop())
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                app._start_bootstrap()
                await pilot.pause()
                assert app._bootstrap_started is True
                assert app._bootstrap_group_idx is not None
                app._on_bootstrap_event(PreflightEvent("controller", CheckStatus.PASSED, "", None))
                await pilot.pause()

    @pytest.mark.asyncio
    async def test_start_bootstrap_skips_when_already_ready(self) -> None:
        p1, p2, mock_agent = _patch_app()
        # charm_type matches the default preset and prepare is fully ready.
        from cantrip.agent.runtime.preflight import DEFAULT_PRESET

        mock_agent.state.charm_type = DEFAULT_PRESET
        mock_agent.preflight_result.fully_ready = True
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                app._bootstrap_started = False
                app._start_bootstrap()
                assert app._bootstrap_started is True
                assert app._bootstrap_group_idx is None  # no group created

    @pytest.mark.asyncio
    async def test_start_bootstrap_noop_without_charm_type(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_type = None
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                pilot.app._bootstrap_started = False
                pilot.app._start_bootstrap()
                assert pilot.app._bootstrap_started is False


# ---------------------------------------------------------------------------
# Light-provider resolution
# ---------------------------------------------------------------------------


class TestLightProvider:
    @pytest.mark.asyncio
    async def test_resolve_light_provider_records_name(self) -> None:
        p1, p2, _ = _patch_app()
        light = MagicMock()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                with patch(
                    "cantrip.tui.app.resolve_light_provider", return_value=(light, "haiku-4-5")
                ):
                    out = pilot.app._resolve_light_provider(MagicMock())
                assert out is light
                assert pilot.app._light_model_name == "haiku-4-5"


# ---------------------------------------------------------------------------
# Shared slash commands — clipboard + follow-up branches
# ---------------------------------------------------------------------------


class TestSharedSlashCommands:
    @pytest.mark.asyncio
    async def test_clipboard_and_followup_branches(self) -> None:
        p1, p2, _ = _patch_app()
        result = SlashResult(text="done", clipboard_text="copied!", followup=_noop())
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                chat = app.query_one("#chat", chat_widget.ChatWidget)
                with (
                    patch("cantrip.tui.app.slash_commands.dispatch", return_value=result),
                    patch.object(app, "copy_to_clipboard") as copy,
                ):
                    handled = app._handle_shared_slash_commands("/whatever", chat)
                await pilot.pause()
                assert handled is True
                copy.assert_called_once_with("copied!")
                assert "done" in _system_text(app)

    @pytest.mark.asyncio
    async def test_quit_result_schedules_exit(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                chat = app.query_one("#chat", chat_widget.ChatWidget)
                with (
                    patch(
                        "cantrip.tui.app.slash_commands.dispatch",
                        return_value=SlashResult(text="bye", quit=True),
                    ),
                    patch.object(app, "call_after_refresh") as after,
                ):
                    assert app._handle_shared_slash_commands("/quit", chat) is True
                after.assert_called_once_with(app.exit)

    @pytest.mark.asyncio
    async def test_returns_false_when_unhandled(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                app = pilot.app
                chat = app.query_one("#chat", chat_widget.ChatWidget)
                with patch("cantrip.tui.app.slash_commands.dispatch", return_value=None):
                    assert app._handle_shared_slash_commands("not a command", chat) is False


# ---------------------------------------------------------------------------
# _trailing_reasoning
# ---------------------------------------------------------------------------


class TestTrailingReasoning:
    @pytest.mark.asyncio
    async def test_returns_thinking_content_of_last_assistant_message(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.messages = [
            Message(role=Role.USER, content="hi"),
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={"_thinking_content": "let me think"},
            ),
        ]
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                assert pilot.app._trailing_reasoning() == "let me think"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_assistant_message(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.messages = [Message(role=Role.USER, content="hi")]
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                assert pilot.app._trailing_reasoning() == ""


# ---------------------------------------------------------------------------
# Resume-prompt modal (also covers tui/screens/resume.py)
# ---------------------------------------------------------------------------


def _with_prior_session(mock_agent: MagicMock, *, transcript: list[Message] | None = None) -> None:
    """Wire the mock agent so launch shows the resume prompt."""
    mock_agent.preview_session.return_value = SessionPreview(
        exists=True,
        charm_name="webapp",
        charm_type="vm",
        message_count=4,
        task_counts={"pending": 1, "done": 2, "failed": 1},
        updated_at="2026-05-10T00:00:00",
    )
    mock_agent.transcript_tail = MagicMock(return_value=transcript or [])
    mock_agent.build_resume_summary = MagicMock(return_value="Resumed: 3 tasks")
    mock_agent.load_state = MagicMock(return_value=True)
    mock_agent.archive_session = MagicMock(return_value=pathlib.Path("/c/.cantrip.bak-123"))


class TestResumeModal:
    @pytest.mark.asyncio
    async def test_modal_appears_for_prior_session(self) -> None:
        p1, p2, mock_agent = _patch_app()
        _with_prior_session(mock_agent)
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                await pilot.pause()
                assert isinstance(pilot.app.screen, ResumePromptScreen)
                # The summary line reflects the preview.
                summary = pilot.app.screen.query_one(".resume-summary")
                assert "webapp" in str(summary.render())

    @pytest.mark.asyncio
    async def test_resume_choice_loads_state_and_shows_summary(self) -> None:
        p1, p2, mock_agent = _patch_app()
        _with_prior_session(mock_agent)
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, ResumePromptScreen)
                mock_agent.load_state.assert_called()
                assert "Resumed: 3 tasks" in _system_text(pilot.app)

    @pytest.mark.asyncio
    async def test_fresh_choice_archives_and_announces(self) -> None:
        p1, p2, mock_agent = _patch_app()
        _with_prior_session(mock_agent)
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                await pilot.pause()
                await pilot.press("f")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, ResumePromptScreen)
                mock_agent.archive_session.assert_called()
                assert ".cantrip.bak-123" in _system_text(pilot.app)

    @pytest.mark.asyncio
    async def test_transcript_toggle_renders_lines(self) -> None:
        p1, p2, mock_agent = _patch_app()
        _with_prior_session(
            mock_agent,
            transcript=[
                Message(role=Role.USER, content="build a charm"),
                Message(role=Role.ASSISTANT, content="x" * 250),
            ],
        )
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, ResumePromptScreen)
                await pilot.press("t")
                await pilot.pause()
                lines = " ".join(str(s.render()) for s in screen.query(".transcript-line"))
                assert "USER: build a charm" in lines
                assert "..." in lines  # the long assistant line was truncated
                # Toggling again clears them.
                await pilot.press("t")
                await pilot.pause()
                assert not list(screen.query(".transcript-line"))

    @pytest.mark.asyncio
    async def test_transcript_toggle_with_no_messages(self) -> None:
        p1, p2, mock_agent = _patch_app()
        _with_prior_session(mock_agent, transcript=[])
        with p1, p2:
            async with CantripApp().run_test(size=_TERMINAL) as pilot:
                await pilot.pause()
                screen = pilot.app.screen
                await pilot.press("t")
                await pilot.pause()
                lines = " ".join(str(s.render()) for s in screen.query(".transcript-line"))
                assert "no messages persisted" in lines


async def _noop() -> None:
    """A trivial coroutine for ``run_worker`` / follow-up stubs."""
