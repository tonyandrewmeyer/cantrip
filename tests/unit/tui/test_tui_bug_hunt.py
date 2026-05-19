"""Ad-hoc Pilot probe — drives the TUI through every F-key and feeds
markup-hazardous chat input, looking for crashes / markup errors.

Lives alongside the regular TUI tests but is named ``_bug_hunt`` so its
purpose is obvious if something here starts failing — it isn't a
behaviour contract, it's a fuzz-style smoke-driver.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cantrip.tui.app import CantripApp
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _patched_with_watcher_off() -> tuple[object, object]:
    """``_patch_app`` plus the watcher mocks F5 needs to round-trip cleanly.

    F5 (``action_toggle_watcher``) flips ``agent.toggle_watcher_reacting``
    and refreshes the status bar; give it a concrete bool so the chat
    notice and status glyph are deterministic rather than driven off an
    auto-mocked truthy MagicMock.

    Also pin ``state.charm_path`` to ``None`` so the F9 transcript action
    short-circuits — otherwise an auto-mocked MagicMock is passed to
    :class:`TranscriptScreen` and ``sqlite3.connect(str(magicmock))``
    creates a real database file in the cwd named after the mock's repr.
    """
    p1, p2, agent = _patch_app()
    agent.watcher_running = False
    agent.watcher_reacting = True
    agent.toggle_watcher_reacting = lambda: False
    agent.stop_watcher = AsyncMock()
    agent.state.charm_path = None
    return p1, p2


@pytest.mark.parametrize(
    "key",
    ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9"],
)
async def test_each_f_key_does_not_crash(key: str) -> None:
    """Every documented F-key keybinding must mount cleanly."""
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            await pilot.press(key)
            await pilot.pause()
            # Esc/F1 etc. each open their own screen; pop back to base.
            await pilot.press("escape")
            await pilot.pause()


async def test_markup_hazardous_chat_input_does_not_crash() -> None:
    """Square-bracket text that looks like Textual markup must not crash the app.

    Mirrors ``be7f0d6 fix: TUI markup crash and unhandled transient provider
    errors`` (prior bug-hunt commit).  Probes for regressions in the same
    family with novel shapes the original fix may not have covered.
    """
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            from textual.widgets import Input

            inp = pilot.app.query_one(Input)
            for content in [
                "[bold]hi[/bold]",
                "[/notatag]",
                "Plain [ unmatched",
                "Nested [a [b [c]]]",
                "[#ff0000 on #00ff00]styled[/]",
                "Backticks `[code]` inside",
            ]:
                inp.value = content
                await pilot.press("enter")
                await pilot.pause()


async def test_slash_command_dispatch_does_not_crash() -> None:
    """Typing ``/help`` and pressing enter should dispatch without exploding."""
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            from textual.widgets import Input

            inp = pilot.app.query_one(Input)
            inp.value = "/help"
            await pilot.press("enter")
            await pilot.pause()


async def test_rapid_key_sequence_does_not_crash() -> None:
    """Hammer F1/F2/F3 in fast succession — hunts async ordering bugs."""
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            for key in ["f2", "f2", "f1", "escape", "f3", "escape", "f9", "escape"]:
                await pilot.press(key)
            await pilot.pause()


# ---------------------------------------------------------------------------
# Control-key bindings
# ---------------------------------------------------------------------------


async def test_ctrl_l_clears_chat() -> None:
    """``ctrl+l`` removes posted messages from the chat widget."""
    from cantrip.tui.widgets.chat import ChatMessage, ChatWidget, MessageRole

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            # Seed three messages so "did anything actually clear?" is observable.
            for i in range(3):
                chat.add_message(ChatMessage(role=MessageRole.USER, content=f"msg {i}"))
            await pilot.pause()
            assert len(chat._messages) >= 3

            await pilot.press("ctrl+l")
            await pilot.pause()
            assert len(chat._messages) == 0


async def test_ctrl_f_opens_search_bar() -> None:
    """``ctrl+f`` reveals the chat-search bar (priority-bound, so it
    fires even while the input has focus)."""
    from cantrip.tui.widgets.chat import ChatWidget, SearchBar

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            bar = chat.query_one(SearchBar)
            # Search bar is hidden on mount.
            assert bar.display is False

            await pilot.press("ctrl+f")
            await pilot.pause()
            assert bar.display is True


async def test_ctrl_c_with_no_running_worker_does_not_crash() -> None:
    """``ctrl+c`` iterates ``self.workers`` and only acts on a running
    ``agent_response`` worker — pressing it on a fresh app must be a
    benign no-op rather than crashing or shutting the app down.
    """
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            await pilot.press("ctrl+c")
            await pilot.pause()
            # App still alive — query a known widget, which would raise
            # NoMatches if the DOM had been torn down.
            from textual.widgets import Input

            assert pilot.app.query_one(Input) is not None


async def test_escape_with_no_running_worker_does_not_crash() -> None:
    """``escape`` is bound to ``cancel_agent`` (alias for ``ctrl+c``).
    On a base screen with no worker, it should be a no-op.
    """
    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()
            from textual.widgets import Input

            assert pilot.app.query_one(Input) is not None


# ---------------------------------------------------------------------------
# Screen-stacking behaviour
# ---------------------------------------------------------------------------


async def test_consecutive_modal_open_close_returns_to_base() -> None:
    """F1 → escape → F3 → escape exercises modal entry/exit twice and
    must land back on the base screen with the input still focusable.

    Tightens the parametrized F-key smoke test from "didn't crash" to
    "actually returned to base", which would catch a bug where a
    screen failed to dismiss and the next F-key opened a *second*
    layer the user couldn't escape from.
    """
    from textual.widgets import Input

    from cantrip.tui.screens.help import HelpScreen
    from cantrip.tui.screens.logs import LogScreen

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            base_screen_id = id(pilot.app.screen)

            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(pilot.app.screen, HelpScreen)

            await pilot.press("escape")
            await pilot.pause()
            assert id(pilot.app.screen) == base_screen_id

            await pilot.press("f3")
            await pilot.pause()
            assert isinstance(pilot.app.screen, LogScreen)

            await pilot.press("escape")
            await pilot.pause()
            assert id(pilot.app.screen) == base_screen_id
            assert pilot.app.query_one(Input) is not None


async def test_double_f1_does_not_stack_help_screens() -> None:
    """Pressing F1 twice in a row should not push two HelpScreens —
    a stacked modal is poor UX and a real bug surface (the second
    escape would only pop the inner one and confuse the user).
    """
    from cantrip.tui.screens.help import HelpScreen

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            await pilot.press("f1")
            await pilot.pause()
            assert isinstance(pilot.app.screen, HelpScreen)

            await pilot.press("f1")
            await pilot.pause()
            # Should still be the same single HelpScreen instance.
            stack_depth = sum(1 for s in pilot.app.screen_stack if isinstance(s, HelpScreen))
            assert stack_depth == 1, f"F1 stacked {stack_depth} HelpScreens — should be idempotent"


# ---------------------------------------------------------------------------
# Slash-command edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "/",  # bare slash
        "//double",  # double slash
        "/totally_made_up_command_xyz",  # unknown slash command
        "/  ",  # slash plus whitespace only
        "/help extra unexpected args",  # known command with bonus args
    ],
)
async def test_malformed_slash_does_not_crash(raw: str) -> None:
    """Slash-command dispatch must not crash on degenerate input.

    The dispatcher splits on whitespace and looks up the verb;
    edge cases (empty verb, unknown verb, bonus args on a known
    verb) should produce a clean error message rather than a
    traceback in the chat.
    """
    from textual.widgets import Input

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            inp = pilot.app.query_one(Input)
            inp.value = raw
            await pilot.press("enter")
            await pilot.pause()
            # App still alive and input is empty (submission cleared it).
            assert pilot.app.query_one(Input).value == ""


# ---------------------------------------------------------------------------
# Focus / interaction edge cases
# ---------------------------------------------------------------------------


async def test_input_focus_survives_modal_close() -> None:
    """After F1 (open Help) → escape, the chat input must regain focus.

    A modal that doesn't restore focus on dismiss leaves the user
    typing into the void (or worse, into a now-focused widget that
    intercepts their keypresses).
    """
    from textual.widgets import Input

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            inp = pilot.app.query_one(Input)
            assert inp.has_focus  # the app starts with input focused

            await pilot.press("f1")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            # Same input widget still focused after the modal closes.
            assert pilot.app.query_one(Input).has_focus


async def test_typing_in_input_then_modal_open_does_not_lose_text() -> None:
    """Typing partial input then opening a modal (F1) and dismissing
    it must preserve the typed text — losing in-progress text on a
    modal flicker is a real-world UX regression.
    """
    from textual.widgets import Input

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            inp = pilot.app.query_one(Input)
            inp.value = "half-typed thought "
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert pilot.app.query_one(Input).value == "half-typed thought "


async def test_extreme_whitespace_input_does_not_submit_empty_message() -> None:
    """Pressing enter on whitespace-only input must not produce a
    user message in the chat — the agent has nothing to respond to
    and we'd burn a turn for nothing.
    """
    from textual.widgets import Input

    from cantrip.tui.widgets.chat import ChatWidget

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            initial_count = len(chat._messages)

            inp = pilot.app.query_one(Input)
            for whitespace_only in ("   ", "\t\t", "  \n  ", ""):
                inp.value = whitespace_only
                await pilot.press("enter")
                await pilot.pause()
            assert len(chat._messages) == initial_count, (
                "whitespace-only submissions reached the chat widget"
            )


async def test_extremely_long_input_does_not_crash() -> None:
    """A pasted multi-kB blob in the input field must not crash the
    submission path or markup renderer.
    """
    from textual.widgets import Input

    p1, p2 = _patched_with_watcher_off()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            inp = pilot.app.query_one(Input)
            # 8 kB of mixed content: text + markup-hazardous brackets
            # at every 200 chars to also exercise the markup escape.
            chunk = "x" * 200 + "[bold]y[/]"
            inp.value = chunk * 40  # ~8 kB
            await pilot.press("enter")
            await pilot.pause()
            # App still alive.
            assert pilot.app.query_one(Input) is not None
