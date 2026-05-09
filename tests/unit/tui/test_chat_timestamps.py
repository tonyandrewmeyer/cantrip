"""Tests for Phase 108.6 — timestamp visual rhythm.

The chat used to render ``[HH:MM]`` on every message, which read as
a logfile in busy sessions.  ``ChatWidget`` now suppresses the
timestamp on tool / shell rows always, and on conversational rows
that land within ``_TIMESTAMP_GAP_SECONDS`` of the last shown
timestamp.  These tests pin the policy.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets.chat import (
    ChatMessage,
    ChatWidget,
    MessageRole,
    MessageWidget,
)

pytestmark = pytest.mark.tui


def _mock_agent() -> MagicMock:
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
    return (
        patch("cantrip.tui.app.create_provider", return_value=MagicMock()),
        patch("cantrip.tui.app.CantripAgent", return_value=_mock_agent()),
    )


def _msg(
    role: MessageRole,
    content: str = "hi",
    *,
    when: datetime.datetime | None = None,
) -> ChatMessage:
    """Build a ChatMessage at *when* (now if omitted)."""
    timestamp = when or datetime.datetime.now()
    return ChatMessage(role=role, content=content, timestamp=timestamp)


def _rendered(widget: MessageWidget) -> str:
    """Snapshot the widget's current Static body as a string."""
    return str(widget._render_body())


# ---------------------------------------------------------------------------
# Pure-policy tests (decision logic, no Pilot mount needed)
# ---------------------------------------------------------------------------


def test_first_eligible_message_shows_timestamp():
    """First USER message in a session always carries ``[HH:MM]``."""
    chat = ChatWidget()
    decision = chat._should_show_timestamp(_msg(MessageRole.USER))
    assert decision is True


def test_tool_role_never_shows_timestamp():
    """Tool blocks are continuous with the assistant turn above them."""
    chat = ChatWidget()
    decision = chat._should_show_timestamp(_msg(MessageRole.TOOL))
    assert decision is False


def test_shell_role_never_shows_timestamp():
    """Ctrl-X shell rows behave like tool rows."""
    chat = ChatWidget()
    decision = chat._should_show_timestamp(_msg(MessageRole.SHELL))
    assert decision is False


def test_rapid_followup_within_gap_is_suppressed():
    """A second eligible row inside the gap window does not re-show ``[HH:MM]``."""
    chat = ChatWidget()
    base = datetime.datetime(2026, 5, 10, 14, 23, 0)
    chat._last_timestamp_at = base
    follow = _msg(MessageRole.ASSISTANT, when=base + datetime.timedelta(seconds=30))
    assert chat._should_show_timestamp(follow) is False


def test_followup_after_gap_re_anchors():
    """A row past ``_TIMESTAMP_GAP_SECONDS`` re-shows the timestamp."""
    chat = ChatWidget()
    base = datetime.datetime(2026, 5, 10, 14, 23, 0)
    chat._last_timestamp_at = base
    later = _msg(
        MessageRole.ASSISTANT,
        when=base + datetime.timedelta(seconds=ChatWidget._TIMESTAMP_GAP_SECONDS),
    )
    assert chat._should_show_timestamp(later) is True


def test_followup_just_before_gap_still_suppressed():
    """A row one second before the gap boundary stays suppressed."""
    chat = ChatWidget()
    base = datetime.datetime(2026, 5, 10, 14, 23, 0)
    chat._last_timestamp_at = base
    nearly = _msg(
        MessageRole.ASSISTANT,
        when=base + datetime.timedelta(seconds=ChatWidget._TIMESTAMP_GAP_SECONDS - 1),
    )
    assert chat._should_show_timestamp(nearly) is False


# ---------------------------------------------------------------------------
# MessageWidget rendering — ``show_timestamp`` flag controls the chip
# ---------------------------------------------------------------------------


def test_message_widget_renders_timestamp_by_default():
    """Backward compat: omitting ``show_timestamp`` keeps the chip."""
    msg = _msg(
        MessageRole.USER,
        when=datetime.datetime(2026, 5, 10, 14, 23, 0),
    )
    rendered = _rendered(MessageWidget(msg))
    assert "[14:23]" in rendered


def test_message_widget_suppresses_timestamp_when_flagged():
    """``show_timestamp=False`` drops the ``[HH:MM]`` chip."""
    msg = _msg(
        MessageRole.USER,
        when=datetime.datetime(2026, 5, 10, 14, 23, 0),
    )
    rendered = _rendered(MessageWidget(msg, show_timestamp=False))
    assert "[14:23]" not in rendered
    # Role glyph (``> `` for user) still appears.
    assert "> " in rendered


# ---------------------------------------------------------------------------
# End-to-end: ChatWidget mounted under a Pilot drives the policy correctly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_resets_the_timestamp_anchor():
    """After Ctrl+L the next first message shows its timestamp again."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_user_message("first")
            assert chat._last_timestamp_at is not None
            chat.clear()
            assert chat._last_timestamp_at is None


@pytest.mark.asyncio
async def test_burst_session_shows_one_timestamp():
    """A user message + assistant reply + tool block within ms = one chip."""
    p1, p2 = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            user_widget = chat.add_user_message("build a flask charm")
            assistant_widget = chat.add_assistant_message("on it")
            tool_widget = chat.add_tool_block(
                "read pyproject.toml",
                success=True,
            )
            await pilot.pause()
            # The first widget shows its timestamp; the others do not.
            assert "[" in _rendered(user_widget)
            assistant_render = _rendered(assistant_widget)
            assert "[" not in assistant_render or ":" not in assistant_render
            tool_render = _rendered(tool_widget)
            # Tool rendering still includes the ``[dim]`` markup
            # *around* its glyph; what we want is no ``[HH:MM]`` chip.
            # The chip pattern is exactly ``[<digits>:<digits>]``.
            import re

            assert not re.search(r"\[\d{2}:\d{2}\]", assistant_render)
            assert not re.search(r"\[\d{2}:\d{2}\]", tool_render)
