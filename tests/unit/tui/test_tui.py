"""TUI tests using Textual's headless testing support.

Exercises CantripApp widget composition, key bindings, and message
flow with the LLM provider and agent fully mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Input

from cantrip.agent.cos_endpoints import CosEndpoints
from cantrip.agent.state import TestResults
from cantrip.tui.app import CantripApp
from cantrip.tui.screens.help import HelpScreen
from cantrip.tui.screens.logs import LogScreen
from cantrip.tui.screens.traces import TraceScreen
from cantrip.tui.widgets.chat import (
    ChatWidget,
    MessageRole,
    MessageWidget,
    SlashCommandSuggestions,
)
from cantrip.tui.widgets.status import MultiModelStatusWidget
from cantrip.tui.widgets.statusbar import StatusBar
from cantrip.tui.widgets.tasks import TaskChecklistWidget

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _streaming_reply(*chunks: str):
    """Return a factory that produces an async generator yielding *chunks*.

    The TUI calls ``agent.process_message_streaming(message)`` and iterates
    the result — this helper builds a mock that matches that contract.
    """

    async def _gen(_msg: str):
        for chunk in chunks:
            yield chunk

    return _gen


def _mock_agent() -> MagicMock:
    """Return a mock CantripAgent with a no-op prepare."""
    agent = MagicMock()
    agent.prepare = AsyncMock()
    agent.process_message = AsyncMock(return_value="Test reply")
    # Streaming path used by the TUI — default to a single-chunk reply.
    agent.process_message_streaming = _streaming_reply("Test reply")
    agent.state = MagicMock()
    agent.state.charm_type = None
    agent.state.test_results = None
    agent.state.messages = []
    agent.preflight_result = MagicMock()
    agent.preflight_result.fully_ready = True
    # Executor mocks.
    agent.start_executor = MagicMock()
    agent.stop_executor = AsyncMock()
    agent.executor_running = False
    agent.work_queue = MagicMock()
    agent.work_queue.all_tasks = MagicMock(return_value=[])
    # Provider mocks for model info bar.
    agent.provider = MagicMock()
    agent.provider.name = "gemini"
    agent.provider.model_name = "gemini-3-flash-preview"
    agent.provider.context_window_tokens = 1_048_576
    # Context manager mocks.
    agent.context_manager = MagicMock()
    agent.context_manager.compaction_threshold = 0.80
    agent.context_manager.estimate_tokens = MagicMock(return_value=0)
    # Store mocks (None by default — no session store).
    agent.store = None
    # Session resume — default to no prior session.
    agent.load_state = MagicMock(return_value=False)
    agent.save_state = MagicMock()
    # Phase 31.3 preview path — default to "no prior session", so the
    # resume modal is skipped and tests see a clean app.
    no_preview = MagicMock()
    no_preview.exists = False
    agent.preview_session = MagicMock(return_value=no_preview)
    agent.transcript_tail = MagicMock(return_value=[])
    agent.archive_session = MagicMock(return_value=None)
    # MCP mocks (default: no servers configured so start_mcp is skipped).
    agent.mcp_registry = MagicMock()
    agent.mcp_registry.configured = []
    agent.start_mcp = AsyncMock()
    agent.stop_mcp = AsyncMock()
    # Arena (Phase 47.5) — default to "no arena pending" so a plain
    # MagicMock (truthy) doesn't mis-route every chat message through
    # the arena intercept and render a MagicMock into the chat widget.
    agent.active_arena = None
    return agent


def _patch_app():
    """Context manager that patches create_provider and CantripAgent."""
    mock_provider = MagicMock()
    mock_agent = _mock_agent()

    provider_patch = patch("cantrip.tui.app.create_provider", return_value=mock_provider)
    agent_patch = patch("cantrip.tui.app.CantripAgent", return_value=mock_agent)

    return provider_patch, agent_patch, mock_agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTuiWidgets:
    """Test that the app mounts with the expected widget tree."""

    @pytest.mark.asyncio
    async def test_app_mounts_with_expected_widgets(self):
        """Verify #chat, #chat-input, and #juju-status exist after mount."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                app = pilot.app
                assert app.query_one("#chat") is not None
                assert app.query_one("#chat-input") is not None
                assert app.query_one("#juju-status") is not None

    @pytest.mark.asyncio
    async def test_status_panel_starts_visible(self):
        """#right-panel is visible on mount (charm file tree shown by default)."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                right_panel = pilot.app.query_one("#right-panel")
                assert right_panel.display is True

    @pytest.mark.asyncio
    async def test_f2_toggles_status_panel(self):
        """Press F2 twice: panel hides then shows."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                right_panel = pilot.app.query_one("#right-panel")
                assert right_panel.display is True

                await pilot.press("f2")
                assert right_panel.display is False

                await pilot.press("f2")
                assert right_panel.display is True

    @pytest.mark.asyncio
    async def test_tool_block_renders_success(self):
        """Phase 75: ``add_tool_block(success=True)`` appends a tool message."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "read_file(path=src/foo.py)",
                    success=True,
                )
                await pilot.pause()
                assert widget.message.role == MessageRole.TOOL
                assert "read_file" in widget.message.content
                assert "🔧" in widget.message.content
                assert "tool-failed" not in widget.classes

    @pytest.mark.asyncio
    async def test_tool_block_renders_failure_with_error_class(self):
        """Failed tool calls pick up the ``tool-failed`` CSS hint."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    'run_command(command="make check")',
                    success=False,
                    duration_ms=120,
                )
                await pilot.pause()
                assert widget.message.role == MessageRole.TOOL
                assert "✗" in widget.message.content
                assert "tool-failed" in widget.classes

    @pytest.mark.asyncio
    async def test_tool_block_slow_call_shows_duration(self):
        """Durations above the 500 ms threshold appear in parentheses."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "charmcraft_pack",
                    success=True,
                    duration_ms=2340,
                )
                await pilot.pause()
                assert "2340 ms" in widget.message.content

    @pytest.mark.asyncio
    async def test_tool_block_fast_call_hides_duration(self):
        """Fast calls (below the threshold) don't clutter the chat."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "read_file(path=x)",
                    success=True,
                    duration_ms=30,
                )
                await pilot.pause()
                assert "ms" not in widget.message.content

    @pytest.mark.asyncio
    async def test_tool_block_dim_markup_is_not_escaped(self):
        """The ``[dim](N ms)[/dim]`` suffix renders as markup, not literal."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "fetch(url=https://example.com)",
                    success=True,
                    duration_ms=1291,
                )
                await pilot.pause()
                rendered = widget._render_body()
                assert isinstance(rendered, str)
                assert "[dim](1291 ms)[/dim]" in rendered
                assert r"\[dim\]" not in rendered

    @pytest.mark.asyncio
    async def test_tool_block_escapes_caption_brackets(self):
        """Brackets inside the caption are escaped so they can't break rendering."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "read_file(path=[a/b])",
                    success=True,
                    duration_ms=600,
                )
                await pilot.pause()
                rendered = widget._render_body()
                assert isinstance(rendered, str)
                # ``rich.markup.escape`` escapes the tag-opening ``[`` so the
                # bracketed substring can't be misread as a Rich tag.
                assert r"\[a/b]" in rendered
                assert "[dim](600 ms)[/dim]" in rendered

    @pytest.mark.asyncio
    async def test_ctrl_l_clears_chat(self):
        """Ctrl+L clears chat and restores the welcome message."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                # Add a user message so there is content beyond the welcome.
                chat.add_user_message("Hello")
                await pilot.pause()

                await pilot.press("ctrl+l")
                await pilot.pause()

                # After clearing, the welcome block should be restored.
                scroll = chat.query_one("#chat-scroll")
                welcome_widgets = scroll.query(".welcome-message")
                assert len(welcome_widgets) > 0

    @pytest.mark.asyncio
    async def test_welcome_message_shown(self):
        """Chat scroll shows the welcome block on mount with useful examples.

        Patch _start_prepare so no system message is added, isolating the
        welcome message from preflight noise.
        """
        p1, p2, _ = _patch_app()
        prepare_patch = patch.object(CantripApp, "_start_prepare")
        with p1, p2, prepare_patch:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                welcome_widgets = scroll.query(".welcome-message")
                assert len(welcome_widgets) > 0
                combined = " ".join(str(w.render()) for w in welcome_widgets).lower()
                # No longer suggests postgres as an example — there's
                # already an excellent postgres charm on Charmhub.
                assert "postgres" not in combined
                # Shows the improve-mode example and source-URL input.
                assert "improve" in combined
                assert "github.com" in combined

    @pytest.mark.asyncio
    async def test_slash_quit_exits_app(self):
        """``/quit`` dispatches and schedules a clean app shutdown."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                exit_mock = MagicMock()
                pilot.app.exit = exit_mock  # type: ignore[method-assign]
                for ch in "/quit":
                    await pilot.press(ch if ch != "/" else "slash")
                await pilot.press("enter")
                await pilot.pause()
                exit_mock.assert_called()

    @pytest.mark.asyncio
    async def test_slash_help_reaches_dispatcher(self):
        """Typing ``/help`` + Enter dispatches the shared slash-command handler.

        Regression: ``/`` used to open search on an empty input, which meant
        slash commands could never be typed in the TUI.
        """
        p1, p2, _ = _patch_app()
        with p1, p2, patch("cantrip.tui.app.slash_commands.dispatch") as dispatch:
            from cantrip.agent.commands.slash import SlashResult

            dispatch.return_value = SlashResult(text="slash-help-response")
            async with CantripApp().run_test() as pilot:
                for ch in "/help":
                    await pilot.press(ch if ch != "/" else "slash")
                await pilot.press("enter")
                await pilot.pause()

                dispatch.assert_called_once()
                # The message handed to the dispatcher is the full /help verb.
                _, args, _ = dispatch.mock_calls[0]
                assert args[1] == "/help"

    @pytest.mark.asyncio
    async def test_input_submission_adds_user_message(self):
        """Type text + enter creates a user message widget."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "e", "l", "l", "o")
                await pilot.press("enter")
                await pilot.pause()

                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                message_widgets = scroll.query(MessageWidget)
                # At least one message widget should exist (the user message).
                assert len(message_widgets) >= 1
                # The first (and possibly only real) message should be the user's.
                user_msgs = [w for w in message_widgets if w.message.role.value == "user"]
                assert len(user_msgs) >= 1
                assert user_msgs[0].message.content == "Hello"

    @pytest.mark.asyncio
    async def test_agent_response_shown(self):
        """Mock agent streams 'Test reply'; verify assistant message appears."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.process_message_streaming = _streaming_reply("Test reply")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                # Allow the background worker to complete.
                await pilot.pause(delay=0.5)

                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                message_widgets = scroll.query(MessageWidget)
                assistant_msgs = [
                    w for w in message_widgets if w.message.role.value == "assistant"
                ]
                assert len(assistant_msgs) >= 1
                assert assistant_msgs[0].message.content == "Test reply"

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self):
        """Pressing enter with empty input adds no message."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()

                chat = pilot.app.query_one("#chat", ChatWidget)
                # No user messages should have been added (system messages
                # from preflight may exist, but that's fine).
                user_messages = [m for m in chat._messages if m.role == MessageRole.USER]
                assert len(user_messages) == 0

    @pytest.mark.asyncio
    async def test_f1_opens_help_screen(self):
        """Press F1 to open HelpScreen, then Esc to dismiss."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("f1")
                await pilot.pause()
                assert isinstance(pilot.app.screen, HelpScreen)

                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, HelpScreen)

    @pytest.mark.asyncio
    async def test_help_screen_content(self):
        """HelpScreen contains expected sections."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("f1")
                await pilot.pause()

                container = pilot.app.screen.query_one("#help-container")
                assert container is not None
                # Check via the static widgets inside the container.
                statics = container.query("Static")
                combined = " ".join(str(s.render()) for s in statics)
                assert "Quick Start" in combined
                assert "Keyboard Shortcuts" in combined
                assert "Links" in combined

    @pytest.mark.asyncio
    async def test_status_bar_mounted(self):
        """StatusBar widget is mounted with the expected id."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                status_bar = pilot.app.query_one("#status-bar")
                assert isinstance(status_bar, StatusBar)

    @pytest.mark.asyncio
    async def test_status_bar_reactives(self):
        """Setting reactive properties updates status bar content."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                status_bar = pilot.app.query_one("#status-bar", StatusBar)
                status_bar.task_label = "⟳ Building rock"
                status_bar.cos_health = "● COS healthy"
                await pilot.pause()

                content = pilot.app.query_one("#status-bar-content")
                text = str(content.render())
                assert "Building rock" in text
                assert "COS healthy" in text

    @pytest.mark.asyncio
    async def test_header_renders_brand_mark(self):
        """Phase 108.8: the slim header always carries ``✦ cantrip``.

        Replaces the legacy ``self.sub_title`` assertion — the
        ``CantripHeader`` widget is the new home for header content,
        and the F1 hint moved to the welcome body and the bottom
        binding row (it was the least-load-bearing segment of the
        old subtitle).
        """
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                from cantrip.tui.widgets.header import CantripHeader

                header = pilot.app.query_one("#cantrip-header", CantripHeader)
                rendered = str(header.query_one("#cantrip-header-text").render())
                assert "✦ cantrip" in rendered

    @pytest.mark.asyncio
    async def test_f4_opens_trace_screen(self):
        """Press F4 to open TraceScreen, then Esc to dismiss."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("f4")
                await pilot.pause()
                assert isinstance(pilot.app.screen, TraceScreen)

                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, TraceScreen)

    @pytest.mark.asyncio
    async def test_trace_screen_renders_unknown_when_no_status(self):
        """Default TraceScreen renders an 'Unknown' status when no poll data."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.app.push_screen(TraceScreen(cos_model="cos"))
                await pilot.pause()
                texts = [str(w.render()) for w in pilot.app.screen.query("Static")]
                blob = "\n".join(texts)
                assert "Unknown" in blob
                # Falls back to the local port-forward URL.
                assert "http://localhost:3000" in blob

    @pytest.mark.asyncio
    async def test_trace_screen_renders_real_grafana_urls(self):
        """When endpoints carry a Grafana URL, real links show up in the body."""
        endpoints = CosEndpoints(
            known=True,
            grafana_url="http://grafana.example:3000",
            grafana_active=True,
            has_grafana=True,
            has_tempo=True,
            has_loki=True,
        )
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.app.push_screen(TraceScreen(cos_model="cos", endpoints=endpoints))
                await pilot.pause()
                texts = [str(w.render()) for w in pilot.app.screen.query("Static")]
                blob = "\n".join(texts)
                assert "Reachable" in blob
                assert "http://grafana.example:3000" in blob
                # Tempo/Loki deep-links include the datasource in the left pane.
                assert "datasource" in blob
                assert "tempo" in blob
                assert "loki" in blob

    @pytest.mark.asyncio
    async def test_resume_modal_shown_when_prior_session_exists(self):
        """Session preview with exists=True pushes the ResumePromptScreen."""
        from cantrip.tui.screens.resume import ResumePromptScreen

        p1, p2, agent = _patch_app()
        preview = MagicMock()
        preview.exists = True
        preview.summary.return_value = "Prior session: my-charm"
        agent.preview_session = MagicMock(return_value=preview)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                assert isinstance(pilot.app.screen, ResumePromptScreen)
                # Dismiss with R — triggers load_state.
                await pilot.press("r")
                await pilot.pause()
                agent.load_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_modal_fresh_archives_without_loading(self):
        """Pressing F on the resume modal archives and skips load_state."""
        from pathlib import Path

        from cantrip.tui.screens.resume import ResumePromptScreen

        p1, p2, agent = _patch_app()
        preview = MagicMock()
        preview.exists = True
        preview.summary.return_value = "Prior session: my-charm"
        agent.preview_session = MagicMock(return_value=preview)
        agent.archive_session = MagicMock(return_value=Path("/tmp/.cantrip.bak-20260420T000000Z"))
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                assert isinstance(pilot.app.screen, ResumePromptScreen)
                await pilot.press("f")
                await pilot.pause()
                agent.archive_session.assert_called_once()
                agent.load_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_modal_transcript_toggle(self):
        """Pressing T shows the transcript; pressing it again hides it."""
        from cantrip.llm.base import Message, Role
        from cantrip.tui.screens.resume import ResumePromptScreen

        p1, p2, agent = _patch_app()
        preview = MagicMock()
        preview.exists = True
        preview.summary.return_value = "Prior session"
        agent.preview_session = MagicMock(return_value=preview)
        agent.transcript_tail = MagicMock(
            return_value=[Message(role=Role.USER, content="hello from history")]
        )
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, ResumePromptScreen)
                await pilot.press("t")
                await pilot.pause()
                # The transcript container should now have a Static inside it.
                container = screen.query_one("#resume-transcript")
                statics = list(container.query("Static"))
                blob = "\n".join(str(s.render()) for s in statics)
                assert "hello from history" in blob
                # Toggle off.
                await pilot.press("t")
                await pilot.pause()
                statics = list(container.query("Static"))
                assert statics == []

    @pytest.mark.asyncio
    async def test_no_resume_modal_when_no_prior_session(self):
        """Default mock (no prior session) does not push a resume modal."""
        from cantrip.tui.screens.resume import ResumePromptScreen

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                assert not isinstance(pilot.app.screen, ResumePromptScreen)

    @pytest.mark.asyncio
    async def test_trace_screen_reports_unreachable(self):
        """An inactive Grafana surfaces as 'Not reachable'."""
        endpoints = CosEndpoints(
            known=True,
            grafana_url=None,
            grafana_active=False,
            has_grafana=True,
            has_tempo=False,
            has_loki=False,
        )
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.app.push_screen(TraceScreen(cos_model="cos", endpoints=endpoints))
                await pilot.pause()
                blob = "\n".join(str(w.render()) for w in pilot.app.screen.query("Static"))
                assert "Not reachable" in blob

    @pytest.mark.asyncio
    async def test_f3_opens_log_screen(self):
        """Press F3 to open LogScreen, then Esc to dismiss."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # Patch subprocess to avoid real juju calls.
                with patch("cantrip.tui.screens.logs.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0, stdout="log line 1\nlog line 2", stderr=""
                    )
                    await pilot.press("f3")
                    await pilot.pause()
                    assert isinstance(pilot.app.screen, LogScreen)

                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(pilot.app.screen, LogScreen)

    @pytest.mark.asyncio
    async def test_multi_model_status_widget_mounted(self):
        """#juju-status is a MultiModelStatusWidget after mount."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                widget = pilot.app.query_one("#juju-status")
                assert isinstance(widget, MultiModelStatusWidget)

    @pytest.mark.asyncio
    async def test_cos_status_click_toggles_expansion(self):
        """Clicking the COS section toggles between collapsed and expanded."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                widget = pilot.app.query_one("#juju-status", MultiModelStatusWidget)

                # Set a mock COS status so the collapsed summary renders.
                mock_app = MagicMock()
                mock_app.app_status.current = "active"
                mock_status = MagicMock()
                mock_status.apps = {"grafana": mock_app}
                widget.cos_status = mock_status
                await pilot.pause()

                # Initially collapsed.
                assert widget.cos_expanded is False

                # Toggle via the public method (simulates the click handler).
                widget.toggle_cos_expanded()
                await pilot.pause()
                assert widget.cos_expanded is True

                # Toggle back.
                widget.toggle_cos_expanded()
                await pilot.pause()
                assert widget.cos_expanded is False

    @pytest.mark.asyncio
    async def test_cos_expansion_renders_app_list(self):
        """Expanding the COS section must list each app, not just the model header.

        Regression guard for the "expand shows only 'Model: cos (k8s)'" bug:
        the JujuStatusWidget mounted with ``status=...`` in ``__init__`` must
        fill its #status-container with the app rows after it's mounted.
        """
        from cantrip.tui.widgets.status import AppBox, JujuStatusWidget

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                widget = pilot.app.query_one("#juju-status", MultiModelStatusWidget)

                # Three COS apps so the test notices if only the header rendered.
                def _mock_app(name: str) -> MagicMock:
                    m = MagicMock()
                    m.app_status.current = "active"
                    m.app_status.message = ""
                    m.units = {f"{name}/0": MagicMock(workload_status=MagicMock(current="active"))}
                    m.relations = {}
                    return m

                mock_status = MagicMock()
                mock_status.model.name = "cos"
                mock_status.model.cloud = "k8s"
                mock_status.apps = {
                    "grafana": _mock_app("grafana"),
                    "prometheus": _mock_app("prometheus"),
                    "loki": _mock_app("loki"),
                }
                widget.cos_status = mock_status
                await pilot.pause()

                widget.toggle_cos_expanded()
                await pilot.pause()
                # A second pause lets the newly-mounted JujuStatusWidget's
                # watch_status callback fire after its #status-container has
                # composed.
                await pilot.pause()

                inner = widget.query_one(JujuStatusWidget)
                app_boxes = list(inner.query(AppBox))
                assert len(app_boxes) == 3, (
                    f"Expected 3 AppBox rows after COS expansion, got {len(app_boxes)}"
                )

    @pytest.mark.asyncio
    async def test_cos_expansion_renders_offers(self):
        """Expanded COS view must list offers, so the user sees what their
        dev charm can consume via ``juju consume``."""
        from cantrip.tui.widgets.status import JujuStatusWidget, OfferLine

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                widget = pilot.app.query_one("#juju-status", MultiModelStatusWidget)

                # Status with two apps and two offers — mirrors a minimal COS:
                # grafana-dashboard + prometheus_scrape endpoints offered to
                # other models.
                prom_ep = MagicMock(interface="prometheus_scrape", role="provider")
                graf_ep = MagicMock(interface="grafana_dashboard", role="requirer")
                offer_prom = MagicMock()
                offer_prom.app = "prometheus"
                offer_prom.endpoints = {"metrics-endpoint": prom_ep}
                offer_graf = MagicMock()
                offer_graf.app = "grafana"
                offer_graf.endpoints = {"grafana-dashboard": graf_ep}

                def _mock_app(name: str) -> MagicMock:
                    m = MagicMock()
                    m.app_status.current = "active"
                    m.app_status.message = ""
                    m.units = {f"{name}/0": MagicMock(workload_status=MagicMock(current="active"))}
                    m.relations = {}
                    return m

                mock_status = MagicMock()
                mock_status.model.name = "cos"
                mock_status.model.cloud = "k8s"
                mock_status.apps = {
                    "prometheus": _mock_app("prometheus"),
                    "grafana": _mock_app("grafana"),
                }
                mock_status.offers = {
                    "prometheus-receive-remote-write": offer_prom,
                    "grafana-dashboards": offer_graf,
                }
                widget.cos_status = mock_status
                await pilot.pause()
                widget.toggle_cos_expanded()
                await pilot.pause()
                await pilot.pause()

                inner = widget.query_one(JujuStatusWidget)
                offer_lines = list(inner.query(OfferLine))
                assert len(offer_lines) == 2, f"Expected 2 OfferLine rows, got {len(offer_lines)}"
                rendered = " ".join(str(ol.render()) for ol in offer_lines)
                assert "prometheus-receive-remote-write" in rendered
                assert "grafana-dashboards" in rendered
                assert "prometheus_scrape" in rendered
                assert "grafana_dashboard" in rendered

    @pytest.mark.asyncio
    async def test_multi_model_pane_hidden_until_a_model_attaches(self):
        """The pane claims no real estate while neither model is connected.

        Before Phase 65, an idle session showed "Dev Model / Not connected
        / COS Model / Not deployed" — four lines of dead state — under the
        charm-files tree.  The pane now hides itself until a status arrives,
        and each section hides individually when its own model is None.
        """
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pane = pilot.app.query_one("#juju-status", MultiModelStatusWidget)
                await pilot.pause()
                assert pane.display is False

                mock_app = MagicMock()
                mock_app.app_status.current = "active"
                mock_app.app_status.message = ""
                mock_app.units = {
                    "flask/0": MagicMock(workload_status=MagicMock(current="active"))
                }
                mock_app.relations = {}
                mock_status = MagicMock()
                mock_status.model.name = "dev"
                mock_status.model.cloud = "lxd"
                mock_status.apps = {"flask": mock_app}
                pane.dev_status = mock_status
                await pilot.pause()
                assert pane.display is True

                # COS section stays hidden because cos_status is still None.
                cos_section = pane.query_one("#cos-section")
                assert cos_section.display is False

    @pytest.mark.asyncio
    async def test_cos_expanded_reactive_repaints_on_direct_set(self):
        """Setting ``cos_expanded`` directly must repaint, not just via toggle.

        ``cos_expanded`` is a reactive — without a ``watch_cos_expanded``
        handler, mutating the attribute outside the click toggle would
        leave the previous render on screen.  Guard that the watcher
        wires the redraw so a future refactor doesn't drop it silently.
        """
        from cantrip.tui.widgets.status import JujuStatusWidget

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                widget = pilot.app.query_one("#juju-status", MultiModelStatusWidget)

                def _mock_app(name: str) -> MagicMock:
                    m = MagicMock()
                    m.app_status.current = "active"
                    m.app_status.message = ""
                    m.units = {f"{name}/0": MagicMock(workload_status=MagicMock(current="active"))}
                    m.relations = {}
                    return m

                mock_status = MagicMock()
                mock_status.model.name = "cos"
                mock_status.model.cloud = "k8s"
                mock_status.apps = {"grafana": _mock_app("grafana")}
                widget.cos_status = mock_status
                await pilot.pause()

                assert widget.cos_expanded is False
                # Direct assignment, not via the click-driven toggle.
                widget.cos_expanded = True
                await pilot.pause()
                # The expanded JujuStatusWidget for COS should now exist.
                inner = widget.query(JujuStatusWidget)
                assert any(j.status is not None and j.status.model.name == "cos" for j in inner), (
                    "Direct cos_expanded=True must repaint to show the COS pane"
                )

    @pytest.mark.asyncio
    async def test_expanded_cos_renders_apps_visibly(self):
        """COS expansion shows the app list, not just the model header.

        Regression for the layout bug where ``JujuStatusWidget`` declared
        ``height: 100%`` and got mounted inside ``.model-section``
        (``height: auto``) — the recursion collapsed the inner content
        so only the ``Model: cos (k8s)`` line ever rendered after a
        click-to-expand.  Asserting on virtual_size catches the case
        where AppBoxes exist in the DOM but get squashed to zero
        height by their container.
        """
        from cantrip.tui.widgets.status import AppBox

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(size=(140, 60)) as pilot:
                await pilot.pause()
                widget = pilot.app.query_one("#juju-status", MultiModelStatusWidget)

                def _mock_app(name: str, status: str = "active") -> MagicMock:
                    m = MagicMock()
                    m.app_status.current = status
                    m.app_status.message = ""
                    m.units = {f"{name}/0": MagicMock(workload_status=MagicMock(current=status))}
                    m.relations = {}
                    return m

                mock_status = MagicMock()
                mock_status.model.name = "cos"
                mock_status.model.cloud = "k8s"
                mock_status.apps = {
                    "prometheus": _mock_app("prometheus"),
                    "loki": _mock_app("loki"),
                    "grafana": _mock_app("grafana", status="blocked"),
                }
                widget.cos_status = mock_status
                await pilot.pause()
                widget.toggle_cos_expanded()
                await pilot.pause()
                await pilot.pause()

                boxes = list(widget.query(AppBox))
                assert len(boxes) == 3
                # Each AppBox must have a non-zero virtual size; this
                # is what the bug regressed (DOM said boxes existed,
                # layout said they were zero-height).
                for box in boxes:
                    assert box.virtual_size.height > 0, (
                        f"AppBox {box.app_name!r} rendered with virtual height 0 — "
                        "JujuStatusWidget likely collapsed its layout"
                    )

    @pytest.mark.asyncio
    async def test_juju_status_pane_is_scrollable(self):
        """#juju-status must scroll when content exceeds its height.

        The right panel packs task-checklist + charm-files + juju-status
        into a fixed column; without ``overflow-y: auto`` on #juju-status,
        an expanded COS section with more apps than fit in the pane's
        share of the column gets clipped at the bottom, so the user only
        ever sees the "Model: cos (k8s)" header.  Guard the CSS token.
        """
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pane = pilot.app.query_one("#juju-status", MultiModelStatusWidget)
                assert pane.styles.overflow_y == "auto", (
                    f"#juju-status must have overflow-y: auto, got {pane.styles.overflow_y!r}"
                )

    @pytest.mark.asyncio
    async def test_test_summary_shown_after_agent_response(self):
        """Test results appear in status bar after successful agent response."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = TestResults(
            test_type="unit", passed=5, failed=0, error=0, skipped=0
        )
        mock_agent.process_message_streaming = _streaming_reply("All tests passed.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                content = pilot.app.query_one("#status-bar-content")
                text = str(content.render())
                assert "✓" in text
                assert "5 passed" in text

    @pytest.mark.asyncio
    async def test_test_summary_shows_failures(self):
        """Failed test results show cross icon in status bar."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = TestResults(
            test_type="unit", passed=3, failed=2, error=0, skipped=0
        )
        mock_agent.process_message_streaming = _streaming_reply("Some tests failed.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                content = pilot.app.query_one("#status-bar-content")
                text = str(content.render())
                assert "✗" in text
                assert "2 failed" in text

    @pytest.mark.asyncio
    async def test_test_summary_not_set_when_no_results(self):
        """Status bar test summary stays empty when test_results is None."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = None
        mock_agent.process_message_streaming = _streaming_reply("No tests run.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                status_bar = pilot.app.query_one("#status-bar", StatusBar)
                assert status_bar.test_summary == ""

    @pytest.mark.asyncio
    async def test_task_checklist_widget_mounted(self):
        """#task-checklist widget exists after mount."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                checklist = pilot.app.query_one("#task-checklist")
                assert isinstance(checklist, TaskChecklistWidget)

    @pytest.mark.asyncio
    async def test_right_panel_visible_with_tasks(self):
        """Right panel stays visible when TasksAvailable is posted."""
        from cantrip.agent.queue import AgentTask, TaskCategory

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                right_panel = pilot.app.query_one("#right-panel")
                assert right_panel.display is True

                checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
                task = AgentTask(title="Do something", category=TaskCategory.BUILD)
                checklist.notify_changed([task])
                await pilot.pause(delay=0.7)

                assert right_panel.display is True

    @pytest.mark.asyncio
    async def test_ctrl_c_cancels_agent_response(self):
        """Ctrl+C cancels a running agent response worker."""
        import asyncio

        p1, p2, mock_agent = _patch_app()

        async def _slow_stream(_msg: str):
            await asyncio.sleep(10)
            yield "never"

        # Make the agent take a long time so we can cancel mid-flight.
        mock_agent.process_message_streaming = _slow_stream
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # Submit a message to start the agent worker.
                input_widget = pilot.app.query_one("#chat-input")
                input_widget.value = "Hi"
                await pilot.press("enter")
                await pilot.pause(delay=0.3)

                # Worker should be running; input disabled.
                assert input_widget.disabled is True

                # Cancel via Ctrl+C.
                await pilot.press("ctrl+c")
                await pilot.pause(delay=0.5)

                # Input should be re-enabled after cancellation.
                assert input_widget.disabled is False

                # "Operation cancelled." system message should appear.
                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                messages = scroll.query(MessageWidget)
                system_msgs = [
                    w
                    for w in messages
                    if w.message.role == MessageRole.SYSTEM
                    and "cancelled" in w.message.content.lower()
                ]
                assert len(system_msgs) >= 1

    @pytest.mark.asyncio
    async def test_ctrl_c_no_op_without_running_worker(self):
        """Ctrl+C does nothing when no agent worker is running."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # Press Ctrl+C with no worker running — should not crash.
                await pilot.press("ctrl+c")
                await pilot.pause()

                # Input should remain enabled.
                input_widget = pilot.app.query_one("#chat-input")
                assert input_widget.disabled is False

    @pytest.mark.asyncio
    async def test_escape_cancels_agent_response(self):
        """Escape cancels a running agent response worker (Claude-Code-style)."""
        import asyncio

        p1, p2, mock_agent = _patch_app()

        async def _slow_stream(_msg: str):
            await asyncio.sleep(10)
            yield "never"

        mock_agent.process_message_streaming = _slow_stream
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                input_widget = pilot.app.query_one("#chat-input")
                input_widget.value = "Hi"
                await pilot.press("enter")
                await pilot.pause(delay=0.3)

                assert input_widget.disabled is True

                await pilot.press("escape")
                await pilot.pause(delay=0.5)

                assert input_widget.disabled is False

                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                messages = scroll.query(MessageWidget)
                system_msgs = [
                    w
                    for w in messages
                    if w.message.role == MessageRole.SYSTEM
                    and "cancelled" in w.message.content.lower()
                ]
                assert len(system_msgs) >= 1

    @pytest.mark.asyncio
    async def test_streaming_chunks_append_to_same_widget(self):
        """Multi-chunk streaming response assembles into one assistant message."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.process_message_streaming = _streaming_reply("Hello", " ", "world", "!")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                chat = pilot.app.query_one("#chat", ChatWidget)
                scroll = chat.query_one("#chat-scroll")
                assistant_msgs = [
                    w
                    for w in scroll.query(MessageWidget)
                    if w.message.role == MessageRole.ASSISTANT
                ]
                # Exactly one assistant widget — chunks were appended, not
                # rendered as separate messages.
                assert len(assistant_msgs) == 1
                assert assistant_msgs[0].message.content == "Hello world!"

    @pytest.mark.asyncio
    async def test_streaming_empty_response_shows_placeholder(self):
        """Empty stream produces a '(no response)' assistant message."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.process_message_streaming = _streaming_reply()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                chat = pilot.app.query_one("#chat", ChatWidget)
                assistant_msgs = [m for m in chat._messages if m.role == MessageRole.ASSISTANT]
                assert len(assistant_msgs) == 1
                assert assistant_msgs[0].content == "(no response)"

    @pytest.mark.asyncio
    async def test_model_info_bar_shows_estimated_cost(self):
        """ModelInfoBar displays an estimated session cost when usage exists."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.provider.name = "claude"
        mock_agent.provider.model_name = "claude-sonnet-4-6"
        mock_agent.provider.context_window_tokens = 200_000
        mock_agent.cache_creation_tokens = 0
        mock_agent.cache_read_tokens = 0

        # Mock the store with session-scoped usage.  Sonnet 4.6 pricing:
        # $3/M in, $15/M out → 100k in + 10k out = $0.30 + $0.15 = $0.45.
        store = MagicMock()
        store.get_usage_since = MagicMock(
            return_value={
                "prompt_tokens": 100_000,
                "completion_tokens": 10_000,
                "request_count": 4,
            }
        )
        store.get_total_usage = MagicMock(
            return_value={"prompt_tokens": 100_000, "completion_tokens": 10_000}
        )
        store.get_usage_by_model = MagicMock(
            return_value=[
                {
                    "provider": "claude",
                    "model": "claude-sonnet-4-6",
                    "prompt_tokens": 100_000,
                    "completion_tokens": 10_000,
                    "request_count": 4,
                }
            ]
        )
        store.get_usage_by_model_since = MagicMock(
            return_value=[
                {
                    "provider": "claude",
                    "model": "claude-sonnet-4-6",
                    "prompt_tokens": 100_000,
                    "completion_tokens": 10_000,
                    "request_count": 4,
                }
            ]
        )
        mock_agent.store = store
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                # Force a refresh so the cost values are populated.
                pilot.app._update_model_info()
                await pilot.pause()

                bar = pilot.app.query_one("#model-info")
                # $0.30 (input) + $0.15 (output) = $0.45 exactly.
                assert bar.session_cost_usd == pytest.approx(0.45)
                assert bar.alltime_cost_usd == pytest.approx(0.45)

                line2 = pilot.app.query_one("#model-info-line2")
                rendered = str(line2.render())
                assert "$0.45" in rendered

    @pytest.mark.asyncio
    async def test_model_info_bar_shows_cache_hit_rate(self):
        """ModelInfoBar shows Claude prompt-caching hit rate on line 2.

        Regression guard for Phase 41.6 bullet 3: the reactive pipeline
        from ``CantripAgent.cache_read_tokens`` /
        ``cache_creation_tokens`` through ``ModelInfoBar`` must render
        the ``cache: X% hit`` suffix when prompt caching is active.
        """
        p1, p2, mock_agent = _patch_app()
        mock_agent.provider.name = "claude"
        mock_agent.provider.model_name = "claude-sonnet-4-6"
        mock_agent.provider.context_window_tokens = 200_000
        # 800 read + 200 write = 80% hit rate.
        mock_agent.cache_creation_tokens = 200
        mock_agent.cache_read_tokens = 800

        store = MagicMock()
        store.get_usage_since = MagicMock(
            return_value={
                "prompt_tokens": 10_000,
                "completion_tokens": 1_000,
                "request_count": 2,
            }
        )
        store.get_total_usage = MagicMock(
            return_value={"prompt_tokens": 10_000, "completion_tokens": 1_000}
        )
        store.get_usage_by_model = MagicMock(return_value=[])
        store.get_usage_by_model_since = MagicMock(return_value=[])
        mock_agent.store = store

        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.pause()
                pilot.app._update_model_info()
                await pilot.pause()

                bar = pilot.app.query_one("#model-info")
                assert bar.cache_creation_tokens == 200
                assert bar.cache_read_tokens == 800

                line2 = pilot.app.query_one("#model-info-line2")
                rendered = str(line2.render())
                assert "cache: 80% hit" in rendered

    @pytest.mark.asyncio
    async def test_streaming_flips_status_bar_after_first_chunk(self):
        """The status bar shows 'Streaming...' once the first chunk arrives."""
        import asyncio

        first_chunk_seen = asyncio.Event()
        keep_streaming = asyncio.Event()

        async def _paced_stream(_msg: str):
            yield "first"
            first_chunk_seen.set()
            await keep_streaming.wait()
            yield " rest"

        p1, p2, mock_agent = _patch_app()
        mock_agent.process_message_streaming = _paced_stream
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                # Wait for the first chunk to arrive.
                await asyncio.wait_for(first_chunk_seen.wait(), timeout=2.0)
                await pilot.pause()

                status_bar = pilot.app.query_one("#status-bar", StatusBar)
                assert status_bar.task_label == "⟳ Streaming..."

                # Unblock the stream so the worker can finish cleanly.
                keep_streaming.set()
                await pilot.pause(delay=0.3)


class TestSlashCommandSuggestions:
    """Slash-command autocomplete popup + its wiring to ChatInput."""

    @pytest.mark.asyncio
    async def test_slash_prefix_shows_matching_suggestions(self):
        """Typing ``/c`` reveals the popup with ``/cost`` as the first match."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("slash", "c")
                await pilot.pause()

                popup = pilot.app.query_one("#slash-suggestions", SlashCommandSuggestions)
                assert popup.is_visible
                verbs = [cmd.verb for cmd in popup.matches]
                assert "/cost" in verbs
                # Strict prefix — /help or /memory must not appear.
                assert "/help" not in verbs

    @pytest.mark.asyncio
    async def test_tab_completes_unique_match(self):
        """``/c`` + Tab populates the input with ``/cost ``."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("slash", "c")
                await pilot.pause()
                await pilot.press("tab")
                await pilot.pause()

                chat_input = pilot.app.query_one("#chat-input", Input)
                assert chat_input.value == "/cost "

    @pytest.mark.asyncio
    async def test_escape_dismisses_popup(self):
        """Escape hides the popup without clearing the input."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("slash", "c")
                await pilot.pause()
                popup = pilot.app.query_one("#slash-suggestions", SlashCommandSuggestions)
                assert popup.is_visible

                await pilot.press("escape")
                await pilot.pause()
                assert not popup.is_visible
                chat_input = pilot.app.query_one("#chat-input", Input)
                assert chat_input.value == "/c"

    @pytest.mark.asyncio
    async def test_down_arrow_moves_active_suggestion(self):
        """Down arrow cycles the active row when multiple matches exist."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # ``/`` alone matches every shared verb plus /feelings.
                await pilot.press("slash")
                await pilot.pause()

                popup = pilot.app.query_one("#slash-suggestions", SlashCommandSuggestions)
                assert popup.is_visible
                assert len(popup.matches) > 1
                first = popup.active()
                assert first is not None

                await pilot.press("down")
                await pilot.pause()
                second = popup.active()
                assert second is not None
                assert second.verb != first.verb

    @pytest.mark.asyncio
    async def test_popup_hides_on_space(self):
        """Adding a space after the verb hides the popup (command has args now)."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("slash", "h", "e", "l", "p")
                await pilot.pause()
                popup = pilot.app.query_one("#slash-suggestions", SlashCommandSuggestions)
                assert popup.is_visible

                await pilot.press("space")
                await pilot.pause()
                assert not popup.is_visible

    @pytest.mark.asyncio
    async def test_non_slash_input_does_not_show_popup(self):
        """Typing plain text never reveals the popup."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("h", "e", "l", "l", "o")
                await pilot.pause()
                popup = pilot.app.query_one("#slash-suggestions", SlashCommandSuggestions)
                assert not popup.is_visible

    @pytest.mark.asyncio
    async def test_tab_with_ambiguous_prefix_does_nothing(self):
        """Tab without a unique match or visible active row falls through."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # Before typing anything, the popup has no active entry.
                # Tab should not rewrite the empty input value.
                await pilot.press("tab")
                await pilot.pause()
                chat_input = pilot.app.query_one("#chat-input", Input)
                assert chat_input.value == ""
