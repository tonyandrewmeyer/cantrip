"""Tests for chat and transcript search (Phase 31.1).

Exercises the match-finding, navigation, and highlight behaviour of
``ChatWidget`` and ``TranscriptScreen``.  Uses Textual's headless pilot for
the interactive bits and plain calls for the pure logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets.chat import (
    ChatMessage,
    ChatWidget,
    MessageRole,
    MessageWidget,
    SearchBar,
)

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# App bootstrapping helpers (mirrors the fixture in test_tui.py so these tests
# can run standalone).
# ---------------------------------------------------------------------------


def _mock_agent() -> MagicMock:
    """Build a minimal mock agent so CantripApp can mount cleanly."""
    agent = MagicMock()
    agent.prepare = AsyncMock()
    agent.process_message = AsyncMock(return_value="ok")

    async def _stream(_msg: str):
        yield "ok"

    agent.process_message_streaming = _stream
    agent.state = MagicMock()
    agent.state.charm_type = None
    agent.state.test_results = None
    agent.state.messages = []
    agent.state.github_repo = None
    agent.state.charm_name = None
    agent.state.charm_path = None
    agent.state.dev_model = None
    agent.state.cos_model = None
    agent.preflight_result = MagicMock(fully_ready=True)
    agent.start_executor = MagicMock()
    agent.stop_executor = AsyncMock()
    agent.executor_running = False
    agent.watcher_running = False
    agent.issue_triage_running = False
    agent.work_queue = MagicMock(all_tasks=MagicMock(return_value=[]))
    agent.provider = MagicMock(
        name="gemini",
        model_name="gemini-3-flash-preview",
        context_window_tokens=1_048_576,
    )
    agent.context_manager = MagicMock()
    agent.context_manager.compaction_threshold = 0.80
    agent.context_manager.estimate_tokens = MagicMock(return_value=0)
    agent.store = None
    agent.load_state = MagicMock(return_value=False)
    agent.save_state = MagicMock()
    agent.mcp_registry = MagicMock()
    agent.mcp_registry.configured = []
    agent.start_mcp = AsyncMock()
    agent.stop_mcp = AsyncMock()
    return agent


def _patch_app():
    mock_provider = MagicMock()
    mock_agent = _mock_agent()
    return (
        patch("cantrip.tui.app.create_provider", return_value=mock_provider),
        patch("cantrip.tui.app.CantripAgent", return_value=mock_agent),
        mock_agent,
    )


# ---------------------------------------------------------------------------
# MessageWidget unit tests (no app needed)
# ---------------------------------------------------------------------------


class TestMessageWidgetMatching:
    """``count_matches`` and ``_highlighted_content`` exercised directly."""

    def _make_widget(self, content: str) -> MessageWidget:
        return MessageWidget(ChatMessage(role=MessageRole.USER, content=content))

    def test_count_matches_case_insensitive(self):
        widget = self._make_widget("Juju is a tool; juju charms run on Juju.")
        assert widget.count_matches("juju") == 3

    def test_count_matches_empty_query(self):
        widget = self._make_widget("hello world")
        assert widget.count_matches("") == 0

    def test_count_matches_no_match(self):
        widget = self._make_widget("hello world")
        assert widget.count_matches("missing") == 0

    def test_highlighted_content_wraps_all_matches(self):
        widget = self._make_widget("foo bar foo")
        widget._search_query = "foo"
        widget._active_local_idx = 0
        rendered = widget._highlighted_content()
        # Active match uses "black on yellow", inactive uses "yellow reverse".
        assert rendered.count("[black on yellow]foo[/black on yellow]") == 1
        assert rendered.count("[yellow reverse]foo[/yellow reverse]") == 1

    def test_highlighted_content_escapes_bracket_content(self):
        widget = self._make_widget("use [b] markup foo")
        widget._search_query = "foo"
        widget._active_local_idx = 0
        rendered = widget._highlighted_content()
        # The original ``[b]`` must be escaped so Rich doesn't render bold.
        assert r"\[b]" in rendered
        assert "[black on yellow]foo[/black on yellow]" in rendered

    def test_apply_highlight_clears_state(self):
        widget = self._make_widget("foo bar")
        widget.apply_highlight("foo", 0)
        assert widget._search_query == "foo"
        widget.apply_highlight(None, None)
        assert widget._search_query is None
        assert widget._active_local_idx is None


# ---------------------------------------------------------------------------
# ChatWidget integration (mounted in a headless app)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctrl_f_opens_search_bar():
    """Pressing Ctrl+F opens and focuses the search bar."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            assert not chat.search_active

            await pilot.press("ctrl+f")
            await pilot.pause()

            assert chat.search_active
            bar = chat.query_one(SearchBar)
            assert bar.is_open


@pytest.mark.asyncio
async def test_slash_opens_search_when_input_empty():
    """``/`` in an empty chat input opens the search bar."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)

            await pilot.press("/")
            await pilot.pause()

            assert chat.search_active


@pytest.mark.asyncio
async def test_slash_inserts_when_input_has_text():
    """``/`` in a non-empty chat input is typed as a normal character."""
    from textual.widgets import Input

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat_input = pilot.app.query_one("#chat-input", Input)
            chat_input.value = "etc"

            await pilot.press("/")
            await pilot.pause()

            assert not chat.search_active
            assert "/" in chat_input.value


@pytest.mark.asyncio
async def test_search_finds_matches_across_messages():
    """Typing a query highlights matches in all existing messages."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("Hello Juju world")
            chat.add_assistant_message("Juju is great; juju charms rock.")
            await pilot.pause()

            await pilot.press("ctrl+f")
            await pilot.pause()

            # Type the query directly through the ChatWidget's run_search method
            # so we don't depend on keystroke dispatch timing.
            chat._run_search("juju")
            await pilot.pause()

            # "Hello Juju world" → 1 match; "Juju is great; juju charms..." → 2 matches.
            assert len(chat._match_index) == 3
            assert chat._active_match == 0


@pytest.mark.asyncio
async def test_navigate_match_cycles_forward():
    """Navigating past the last match wraps around to the first."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("foo bar foo")
            chat.add_assistant_message("foo again")
            await pilot.pause()

            chat.open_search()
            chat._run_search("foo")
            await pilot.pause()
            assert len(chat._match_index) == 3
            assert chat._active_match == 0

            chat.navigate_match(forward=True)
            assert chat._active_match == 1
            chat.navigate_match(forward=True)
            assert chat._active_match == 2
            chat.navigate_match(forward=True)
            assert chat._active_match == 0  # wrapped


@pytest.mark.asyncio
async def test_navigate_match_backward_wraps():
    """Previous from the first match wraps to the last."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("foo foo foo")
            await pilot.pause()

            chat.open_search()
            chat._run_search("foo")
            await pilot.pause()

            chat.navigate_match(forward=False)
            assert chat._active_match == 2


@pytest.mark.asyncio
async def test_empty_query_clears_highlights():
    """Clearing the search text removes all highlights."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("needle in haystack")
            await pilot.pause()

            chat.open_search()
            chat._run_search("needle")
            await pilot.pause()
            assert chat._match_index

            chat._run_search("")
            await pilot.pause()
            assert not chat._match_index


@pytest.mark.asyncio
async def test_close_search_hides_bar_and_restores_focus():
    """Closing the search bar returns focus to the chat input."""
    from textual.widgets import Input

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat_input = pilot.app.query_one("#chat-input", Input)

            await pilot.press("ctrl+f")
            await pilot.pause()
            assert chat.search_active

            chat.close_search()
            await pilot.pause()

            assert not chat.search_active
            assert chat_input.has_focus


@pytest.mark.asyncio
async def test_no_match_shows_no_matches_status():
    """Searching for something absent shows a 'no matches' indicator."""
    from textual.widgets import Input

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("hello world")
            await pilot.pause()

            chat.open_search()
            bar = chat.query_one(SearchBar)
            bar.query_one("#search-input", Input).value = "nonexistent"
            await pilot.pause()

            status = bar.query_one("#search-status")
            assert "no matches" in str(status.render())


# ---------------------------------------------------------------------------
# TranscriptScreen search
# ---------------------------------------------------------------------------


class TestTranscriptSearchHelpers:
    """Pure helpers on ``TranscriptScreen`` — exercised without mounting."""

    def test_strip_markup_removes_tags(self):
        from cantrip.tui.screens.transcript import TranscriptScreen

        text = "[bold blue]USER[/bold blue]  [dim]12:00[/dim]"
        assert TranscriptScreen._strip_markup(text) == "USER  12:00"

    def test_apply_line_highlight_wraps_match(self):
        from cantrip.tui.screens.transcript import TranscriptScreen

        out = TranscriptScreen._apply_line_highlight("hello juju world", "juju", True)
        assert "[black on yellow]juju[/black on yellow]" in out

    def test_apply_line_highlight_inactive_match_uses_dim_style(self):
        from cantrip.tui.screens.transcript import TranscriptScreen

        out = TranscriptScreen._apply_line_highlight("juju and juju", "juju", False)
        # Both matches get the inactive style because is_active=False.
        assert out.count("[yellow reverse]juju[/yellow reverse]") == 2

    def test_apply_line_highlight_no_match_returns_input(self):
        from cantrip.tui.screens.transcript import TranscriptScreen

        out = TranscriptScreen._apply_line_highlight("hello", "foo", True)
        assert out == "hello"

    def test_apply_line_highlight_case_insensitive(self):
        from cantrip.tui.screens.transcript import TranscriptScreen

        out = TranscriptScreen._apply_line_highlight("Juju and juju", "JUJU", True)
        # Preserves original casing inside the highlight.
        assert "[black on yellow]Juju[/black on yellow]" in out
        assert "[black on yellow]juju[/black on yellow]" in out


@pytest.mark.asyncio
async def test_transcript_screen_search_opens_and_finds_match(tmp_path):
    """Pressing `/` on TranscriptScreen opens the search bar and matches are found."""
    from cantrip.agent.store import SessionStore
    from cantrip.tui.screens.transcript import TranscriptScreen

    # Seed a session store with one message containing a findable keyword.
    db_path = tmp_path / ".cantrip"
    store = SessionStore(db_path)
    store.open()
    store.record_message(role="user", content="find the needle in this haystack")
    store.close()

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            screen = TranscriptScreen(db_path=db_path)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            # Press / to open the search bar.
            await pilot.press("/")
            await pilot.pause()
            bar = screen.query_one("#transcript-search")
            assert bar.has_class("-visible")

            # Type a query that matches the seeded message.
            from textual.widgets import Input

            bar.query_one("#search-input", Input).value = "needle"
            await pilot.pause()
            assert screen._match_line_indices  # at least one match found

            # Esc closes the search bar but keeps the screen open.
            await pilot.press("escape")
            await pilot.pause()
            assert not bar.has_class("-visible")
            assert pilot.app.screen is screen
