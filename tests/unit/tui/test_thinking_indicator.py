"""Tests for Phase 108.7 — on-brand thinking indicator.

Replaces Textual's stock ``LoadingIndicator`` with a single-line
braille-spinner-plus-flavour-verb widget.  These tests exercise the
widget directly (verb + spinner shape) and through the
:meth:`ChatWidget.show_thinking` / :meth:`ChatWidget.hide_thinking`
public surface so the wiring stays honest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets.chat import ChatWidget, ThinkingIndicator
from cantrip.ui import flavour

pytestmark = pytest.mark.tui


def _mock_agent() -> MagicMock:
    """Build a minimal mock agent so ``CantripApp`` can mount cleanly."""
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
    no_preview = MagicMock()
    no_preview.exists = False
    agent.preview_session = MagicMock(return_value=no_preview)
    agent.transcript_tail = MagicMock(return_value=[])
    agent.archive_session = MagicMock(return_value=None)
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


def test_indicator_picks_a_verb_from_the_pool():
    """The constructor draws the verb from ``flavour.pick_activity_label``."""
    indicator = ThinkingIndicator()
    assert indicator.verb in flavour.think_pool()


def test_indicator_respects_category_pool():
    """A ``BUILD`` indicator picks from the build-flavoured pool."""
    indicator = ThinkingIndicator(category=flavour.ActivityCategory.BUILD)
    assert indicator.verb in flavour.category_pool(flavour.ActivityCategory.BUILD)


def _rendered(indicator: ThinkingIndicator) -> str:
    """Snapshot the widget's current Static content as a string.

    ``Static.render()`` returns the renderable Textual would draw —
    a string here because :meth:`ThinkingIndicator._refresh` calls
    ``self.update()`` with a plain markup string.
    """
    return str(indicator.render())


def test_first_frame_renders_in_correct_shape():
    """Initial render is ``<spinner>  <verb>…`` (two-space gutter, ellipsis)."""
    indicator = ThinkingIndicator()
    indicator._refresh()
    rendered = _rendered(indicator)
    # First spinner frame plus the picked verb.
    assert rendered.startswith(ThinkingIndicator._SPINNER_FRAMES[0])
    assert indicator.verb in rendered
    assert rendered.endswith("…")


def test_tick_advances_the_spinner_frame():
    """``_tick`` cycles to the next spinner frame and rerenders."""
    indicator = ThinkingIndicator()
    indicator._refresh()
    first = _rendered(indicator)
    indicator._tick()
    second = _rendered(indicator)
    # Different glyph between consecutive renders.
    assert first[:1] != second[:1]


def test_tick_wraps_at_the_end_of_the_pattern():
    """After ``len(frames)`` ticks the indicator returns to the first glyph."""
    indicator = ThinkingIndicator()
    indicator._refresh()
    starting_glyph = _rendered(indicator)[:1]
    for _ in range(len(ThinkingIndicator._SPINNER_FRAMES)):
        indicator._tick()
    assert _rendered(indicator)[:1] == starting_glyph


@pytest.mark.asyncio
async def test_show_thinking_mounts_thinking_indicator():
    """``ChatWidget.show_thinking`` replaces the legacy LoadingIndicator."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.show_thinking()
            await pilot.pause()
            indicators = chat.query(ThinkingIndicator)
            assert len(indicators) == 1
            assert indicators.first().id == "thinking-indicator"


@pytest.mark.asyncio
async def test_hide_thinking_removes_the_indicator():
    """``hide_thinking`` clears every mounted ``ThinkingIndicator``."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.show_thinking()
            await pilot.pause()
            assert len(chat.query(ThinkingIndicator)) == 1

            chat.hide_thinking()
            await pilot.pause()
            assert len(chat.query(ThinkingIndicator)) == 0


@pytest.mark.asyncio
async def test_show_thinking_twice_keeps_only_one_indicator():
    """A second ``show_thinking`` call replaces the first indicator in place."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.show_thinking()
            await pilot.pause()
            chat.show_thinking()
            await pilot.pause()
            assert len(chat.query(ThinkingIndicator)) == 1
