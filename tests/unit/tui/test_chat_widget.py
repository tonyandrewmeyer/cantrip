"""Behaviour tests for chat-widget sub-components (Phase 93.1 backfill).

Targets the under-covered interactive pieces in ``tui/widgets/chat.py``:
the ``@``-mention suggestion popup, the ``ChatInput`` key routing /
shell-mode toggle / mention acceptance, and the ``SearchBar``.
"""

from __future__ import annotations

import types

import pytest
from textual.app import App, ComposeResult

from cantrip.agent.commands.slash import CommandInfo
from cantrip.agent.context_providers import ArgStyle, ProviderInfo
from cantrip.tui.widgets.chat import (
    ChatInput,
    MentionSuggestions,
    SearchBar,
    SlashCommandSuggestions,
)

pytestmark = pytest.mark.tui

_TERMINAL = (100, 30)


def _provider(name: str, hint: str = "") -> ProviderInfo:
    return ProviderInfo(
        name=name, summary=f"{name} provider", arg_style=ArgStyle.NONE, args_hint=hint
    )


_CATALOGUE = (
    _provider("file", "<path>"),
    _provider("docs", "<query>"),
    _provider("fetch"),
)


def _fake_key(key: str):
    """A minimal stand-in for ``textual.events.Key``."""
    return types.SimpleNamespace(key=key, stop=lambda: None, prevent_default=lambda: None)


# ---------------------------------------------------------------------------
# MentionSuggestions
# ---------------------------------------------------------------------------


class _MentionHost(App):
    def __init__(self) -> None:
        super().__init__()
        self.popup = MentionSuggestions(_CATALOGUE, id="mentions")

    def compose(self) -> ComposeResult:
        yield self.popup


class TestMentionSuggestions:
    @pytest.mark.asyncio
    async def test_matches_make_it_visible_no_matches_hide_it(self) -> None:
        async with _MentionHost().run_test(size=_TERMINAL) as pilot:
            popup = pilot.app.popup
            assert not popup.is_visible

            popup.update_from_input("look at @fi", len("look at @fi"))
            await pilot.pause()
            assert popup.is_visible
            assert [m.name for m in popup.matches] == ["file"]
            assert popup.prefix == "@fi"
            assert popup.active().name == "file"

            # A bare "@" matches everything.
            popup.update_from_input("ping @", len("ping @"))
            await pilot.pause()
            assert {m.name for m in popup.matches} == {"file", "docs", "fetch"}

            # No trailing mention → hidden.
            popup.update_from_input("no mention", 4)
            await pilot.pause()
            assert not popup.is_visible
            assert popup.matches == ()
            assert popup.active() is None

            # Trailing mention with no catalogue match → also hidden.
            popup.update_from_input("@zzz", 4)
            await pilot.pause()
            assert not popup.is_visible

    @pytest.mark.asyncio
    async def test_move_wraps_and_render_marks_active_row(self) -> None:
        async with _MentionHost().run_test(size=_TERMINAL) as pilot:
            popup = pilot.app.popup
            popup.update_from_input("@", 1)
            await pilot.pause()
            assert popup.active().name == "file"
            popup.move(1)
            await pilot.pause()
            assert popup.active().name == "docs"
            popup.move(-1)
            popup.move(-1)
            await pilot.pause()
            # Wrapped past the start back to the last entry.
            assert popup.active().name == "fetch"
            rows = list(popup.query(".suggestion-row"))
            active_rows = [r for r in rows if r.has_class("-active")]
            assert len(active_rows) == 1
            spare = [r for r in rows if r.has_class("-spare")]
            # Only the three matched rows are live; the rest are spares.
            assert len(rows) - len(spare) == 3

    @pytest.mark.asyncio
    async def test_hide_clears_state(self) -> None:
        async with _MentionHost().run_test(size=_TERMINAL) as pilot:
            popup = pilot.app.popup
            popup.update_from_input("@fi", 3)
            await pilot.pause()
            assert popup.is_visible
            popup.hide()
            await pilot.pause()
            assert not popup.is_visible
            assert popup.matches == () and popup.prefix == ""

    @pytest.mark.asyncio
    async def test_update_catalogue_replaces_entries(self) -> None:
        async with _MentionHost().run_test(size=_TERMINAL) as pilot:
            popup = pilot.app.popup
            popup.update_catalogue((_provider("custom"),))
            popup.update_from_input("@cu", 3)
            await pilot.pause()
            assert [m.name for m in popup.matches] == ["custom"]
            popup.update_from_input("@file", 5)
            await pilot.pause()
            assert not popup.is_visible  # old "file" entry is gone


# ---------------------------------------------------------------------------
# ChatInput
# ---------------------------------------------------------------------------


class _InputHost(App):
    def __init__(self) -> None:
        super().__init__()
        self.chat_input = ChatInput(id="chat-input")
        self.slash = SlashCommandSuggestions((CommandInfo("/help", "Show help"),), id="slash")
        self.mentions = MentionSuggestions(_CATALOGUE, id="mentions")
        self.shell_events: list[bool] = []

    def compose(self) -> ComposeResult:
        yield self.chat_input
        yield self.slash
        yield self.mentions

    def on_mount(self) -> None:
        self.chat_input.bind_suggestions(self.slash)
        self.chat_input.bind_mentions(self.mentions)
        self.chat_input.focus()

    def on_chat_input_shell_mode_changed(self, message: ChatInput.ShellModeChanged) -> None:
        self.shell_events.append(message.shell_mode)


class TestChatInput:
    @pytest.mark.asyncio
    async def test_shell_mode_toggle_updates_placeholder_and_posts_event(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            assert ci.shell_mode is False
            await pilot.press("ctrl+x")
            await pilot.pause()
            assert ci.shell_mode is True
            assert ci.placeholder == ChatInput.SHELL_PLACEHOLDER
            assert "-shell-mode" in ci.classes
            await pilot.press("ctrl+x")
            await pilot.pause()
            assert ci.shell_mode is False
            assert ci.placeholder == ChatInput.AGENT_PLACEHOLDER
            assert "-shell-mode" not in ci.classes
            assert pilot.app.shell_events == [True, False]

    @pytest.mark.asyncio
    async def test_active_panel_prefers_slash_then_mention(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            assert ci._active_panel() is None
            pilot.app.mentions.update_from_input("@fi", 3)
            await pilot.pause()
            assert ci._active_panel() is pilot.app.mentions
            pilot.app.slash.update_from_value("/he")
            await pilot.pause()
            # Slash popup wins when both are somehow visible.
            assert ci._active_panel() is pilot.app.slash

    @pytest.mark.asyncio
    async def test_accept_mention_replaces_only_the_prefix(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            ci.value = "look at @fi and continue"
            ci.cursor_position = len("look at @fi")
            pilot.app.mentions.update_from_input(ci.value, ci.cursor_position)
            await pilot.pause()
            info = pilot.app.mentions.active()
            assert info.name == "file"
            ci._accept_mention(info)
            await pilot.pause()
            assert ci.value == "look at @file  and continue"
            assert not pilot.app.mentions.is_visible

    @pytest.mark.asyncio
    async def test_accept_mention_no_prefix_just_hides(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            # mentions popup never opened → no prefix recorded.
            ci.value = "plain text"
            ci._accept_mention(pilot.app.mentions._catalogue[0])
            await pilot.pause()
            assert ci.value == "plain text"  # unchanged

    @pytest.mark.asyncio
    async def test_on_key_routes_to_visible_mention_panel(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            pilot.app.mentions.update_from_input("@", 1)
            await pilot.pause()
            assert pilot.app.mentions.active().name == "file"

            ci.on_key(_fake_key("down"))
            await pilot.pause()
            assert pilot.app.mentions.active().name == "docs"

            ci.on_key(_fake_key("up"))
            await pilot.pause()
            assert pilot.app.mentions.active().name == "file"

            # Tab accepts the active mention.
            ci.value = "@"
            ci.cursor_position = 1
            ci.on_key(_fake_key("tab"))
            await pilot.pause()
            assert ci.value == "@file "
            assert not pilot.app.mentions.is_visible

            # Escape with the (now hidden) panel — re-open then escape.
            pilot.app.mentions.update_from_input("@fi", 3)
            await pilot.pause()
            ci.on_key(_fake_key("escape"))
            await pilot.pause()
            assert not pilot.app.mentions.is_visible

    @pytest.mark.asyncio
    async def test_ctrl_x_hides_open_panel_before_toggling(self) -> None:
        async with _InputHost().run_test(size=_TERMINAL) as pilot:
            ci = pilot.app.chat_input
            pilot.app.mentions.update_from_input("@fi", 3)
            await pilot.pause()
            assert pilot.app.mentions.is_visible
            ci.on_key(_fake_key("ctrl+x"))
            await pilot.pause()
            assert not pilot.app.mentions.is_visible
            assert ci.shell_mode is True


# ---------------------------------------------------------------------------
# SearchBar
# ---------------------------------------------------------------------------


class _SearchHost(App):
    def __init__(self) -> None:
        super().__init__()
        self.bar = SearchBar(id="search-bar")
        self.events: list[object] = []

    def compose(self) -> ComposeResult:
        yield self.bar

    def on_search_bar_changed(self, message: SearchBar.Changed) -> None:
        self.events.append(("changed", message.query))

    def on_search_bar_dismissed(self, _message: SearchBar.Dismissed) -> None:
        self.events.append(("dismissed",))

    def on_search_bar_navigate(self, message: SearchBar.Navigate) -> None:
        self.events.append(("navigate", message.forward))


class TestSearchBar:
    @pytest.mark.asyncio
    async def test_show_hide_and_query_text(self) -> None:
        async with _SearchHost().run_test(size=_TERMINAL) as pilot:
            bar = pilot.app.bar
            assert not bar.is_open
            assert bar.query_text == ""
            bar.show()
            await pilot.pause()
            assert bar.is_open
            bar.query_one("#search-input").value = "needle"
            await pilot.pause()
            assert bar.query_text == "needle"
            bar.set_status("2/5")
            await pilot.pause()
            bar.hide()
            await pilot.pause()
            assert not bar.is_open
            assert bar.query_text == ""

    @pytest.mark.asyncio
    async def test_typing_posts_changed_and_enter_posts_navigate(self) -> None:
        async with _SearchHost().run_test(size=_TERMINAL) as pilot:
            bar = pilot.app.bar
            bar.show()
            await pilot.pause()
            for ch in "abc":
                await pilot.press(ch)
            await pilot.pause()
            assert ("changed", "abc") in pilot.app.events
            await pilot.press("enter")
            await pilot.pause()
            assert ("navigate", True) in pilot.app.events

    @pytest.mark.asyncio
    async def test_escape_posts_dismissed(self) -> None:
        async with _SearchHost().run_test(size=_TERMINAL) as pilot:
            bar = pilot.app.bar
            bar.show()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert ("dismissed",) in pilot.app.events
