"""TUI tests using Textual's headless testing support.

Exercises CantripApp widget composition, key bindings, and message
flow with the LLM provider and agent fully mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.state import TestResults
from cantrip.tui.app import CantripApp
from cantrip.tui.screens.help import HelpScreen
from cantrip.tui.widgets.chat import ChatWidget, MessageRole, MessageWidget
from cantrip.tui.widgets.statusbar import StatusBar

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent() -> MagicMock:
    """Return a mock CantripAgent with a no-op prepare."""
    agent = MagicMock()
    agent.prepare = AsyncMock()
    agent.process_message = AsyncMock(return_value="Test reply")
    agent.state = MagicMock()
    agent.state.charm_type = None
    agent.state.test_results = None
    agent.preflight_result = MagicMock()
    agent.preflight_result.fully_ready = True
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
    async def test_status_panel_starts_hidden(self):
        """#right-panel display is False on mount."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                right_panel = pilot.app.query_one("#right-panel")
                assert right_panel.display is False

    @pytest.mark.asyncio
    async def test_f2_toggles_status_panel(self):
        """Press F2 twice: panel shows then hides."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                right_panel = pilot.app.query_one("#right-panel")
                assert right_panel.display is False

                await pilot.press("f2")
                assert right_panel.display is True

                await pilot.press("f2")
                assert right_panel.display is False

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

                # After clearing, the welcome message should be restored.
                scroll = chat.query_one("#chat-scroll")
                welcome_widgets = scroll.query(".welcome-message")
                assert len(welcome_widgets) == 1

    @pytest.mark.asyncio
    async def test_welcome_message_shown(self):
        """Chat scroll contains 'Welcome to Cantrip' on mount.

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
                assert len(welcome_widgets) == 1

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
        """Mock agent returns 'Test reply'; verify assistant message appears."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.process_message = AsyncMock(return_value="Test reply")
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
    async def test_header_subtitle_shows_help(self):
        """Header subtitle contains 'F1 Help' on mount."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                assert "F1 Help" in pilot.app.sub_title

    @pytest.mark.asyncio
    async def test_f4_debug_stub(self):
        """Press F4 posts a notification."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test(notifications=True) as pilot:
                await pilot.press("f4")
                await pilot.pause()
                assert len(pilot.app._notifications) >= 1
                assert any("Debug" in str(n.title) for n in pilot.app._notifications)

    @pytest.mark.asyncio
    async def test_test_summary_shown_after_agent_response(self):
        """Test results appear in status bar after successful agent response."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = TestResults(
            test_type="unit", passed=5, failed=0, error=0, skipped=0
        )
        mock_agent.process_message = AsyncMock(return_value="All tests passed.")
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
        mock_agent.process_message = AsyncMock(return_value="Some tests failed.")
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
        mock_agent.process_message = AsyncMock(return_value="No tests run.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("H", "i")
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

                status_bar = pilot.app.query_one("#status-bar", StatusBar)
                assert status_bar.test_summary == ""
