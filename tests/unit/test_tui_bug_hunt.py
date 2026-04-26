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
from tests.unit.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _patched_with_watcher_off() -> tuple[object, object]:
    """``_patch_app`` plus the watcher mocks F5 needs to round-trip cleanly.

    The shared helper auto-mocks every agent attribute as a truthy MagicMock,
    so ``agent.watcher_running`` reads truthy and ``action_toggle_watcher``
    routes to the *stop* path on the very first F5 — but ``stop_watcher`` is
    plain MagicMock, not awaitable.  Hard-set both here so F5 exercises the
    realistic start-path on a fresh app.

    Also pin ``state.charm_path`` to ``None`` so the F9 transcript action
    short-circuits — otherwise an auto-mocked MagicMock is passed to
    :class:`TranscriptScreen` and ``sqlite3.connect(str(magicmock))``
    creates a real database file in the cwd named after the mock's repr.
    """
    p1, p2, agent = _patch_app()
    agent.watcher_running = False
    agent.stop_watcher = AsyncMock()
    agent.start_watcher = lambda: True
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
