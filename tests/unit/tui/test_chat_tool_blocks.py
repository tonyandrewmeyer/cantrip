"""Tests for Phase 82 — pre/post tool block rendering in the chat widget.

The ``ChatWidget`` registers a pending block by ``tool_call_id`` and,
when the matching ``TOOL_INVOKED`` event arrives, updates the same
widget in place rather than appending a new chat line.  These tests
cover the registration / resolution paths plus the orphan scrub that
fires when a turn ends without a final event for some pending block.

Mounted via Textual's headless pilot because the chat widget's
``add_message`` queries the live ``#chat-scroll`` container.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.screens.tool_error import ToolErrorScreen
from cantrip.tui.widgets.chat import ChatWidget, MessageWidget

pytestmark = pytest.mark.tui


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


@pytest.mark.asyncio
async def test_pending_then_final_updates_in_place():
    """Pending event then matching final event yields one chat line, not two."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)

            chat.add_pending_tool_block("Packing the charm…", tool_call_id="tc-1")
            await pilot.pause()
            assert len(chat._messages) == baseline + 1
            assert "tc-1" in chat._pending_tool_blocks

            resolved = chat.add_tool_block(
                "Packed redis.charm",
                success=True,
                duration_ms=1234,
                tool_call_id="tc-1",
            )
            await pilot.pause()

            # No new line — the pending block was updated in place.
            assert len(chat._messages) == baseline + 1
            assert "tc-1" not in chat._pending_tool_blocks
            assert resolved.message.content.startswith("▸ ")
            assert "Packed redis.charm" in resolved.message.content
            assert "1234 ms" in resolved.message.content
            assert "tool-pending" not in resolved.classes


@pytest.mark.asyncio
async def test_failed_final_swaps_to_error_glyph():
    """Failed final marks the resolved block ``tool-failed`` and uses ✗."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            widget = chat.add_pending_tool_block("Packing the charm…", tool_call_id="tc-2")
            chat.add_tool_block(
                "Pack failed: missing charmcraft.yaml",
                success=False,
                tool_call_id="tc-2",
            )
            await pilot.pause()

            assert widget.message.content.startswith("✗ ")
            assert "tool-failed" in widget.classes
            assert "tool-pending" not in widget.classes


@pytest.mark.asyncio
async def test_final_without_pending_appends_new_block():
    """Final event before pending (or without pending) still surfaces in chat."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)
            chat.add_tool_block(
                "Read 47 lines from src/foo.py",
                success=True,
                tool_call_id="late",
            )
            await pilot.pause()
            assert len(chat._messages) == baseline + 1
            # No pending registration on this path.
            assert "late" not in chat._pending_tool_blocks


@pytest.mark.asyncio
async def test_final_without_id_does_not_consume_pending():
    """A final event missing ``tool_call_id`` falls through to append.

    Phase 82 is opt-in by id — older callers that never set the new
    field should get the legacy append-a-fresh-line behaviour.
    """
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_pending_tool_block("Running…", tool_call_id="tc-3")
            baseline = len(chat._messages)
            chat.add_tool_block("Done", success=True)
            await pilot.pause()
            # Two lines added in total: the pending and the unmatched final.
            assert len(chat._messages) == baseline + 1
            # Pending block is still parked — the unrelated final didn't
            # consume it.
            assert "tc-3" in chat._pending_tool_blocks


@pytest.mark.asyncio
async def test_duplicate_pending_returns_existing_widget():
    """A duplicate pending event for the same id is a no-op."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)
            first = chat.add_pending_tool_block("Running stub…", tool_call_id="tc-d")
            second = chat.add_pending_tool_block("Running stub again…", tool_call_id="tc-d")
            await pilot.pause()
            assert first is second
            assert len(chat._messages) == baseline + 1


@pytest.mark.asyncio
async def test_scrub_resolves_orphans_as_failed_cancelled():
    """Cancelled / crashed turn scrubs leftover pending blocks."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            chat.add_pending_tool_block("Running A…", tool_call_id="tc-a")
            chat.add_pending_tool_block("Running B…", tool_call_id="tc-b")
            assert len(chat._pending_tool_blocks) == 2

            scrubbed = chat.scrub_pending_tool_blocks()
            await pilot.pause()
            assert scrubbed == 2
            # Registry empty.
            assert chat._pending_tool_blocks == {}
            # Both blocks read as failed / cancelled.
            cancelled_msgs = [m for m in chat._messages if "cancelled" in m.content]
            assert len(cancelled_msgs) == 2
            for msg in cancelled_msgs:
                assert msg.content.startswith("✗ ")


@pytest.mark.asyncio
async def test_scrub_with_empty_registry_is_no_op():
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)
            scrubbed = chat.scrub_pending_tool_blocks()
            await pilot.pause()
            assert scrubbed == 0
            assert len(chat._messages) == baseline


@pytest.mark.asyncio
async def test_resolve_unknown_id_falls_back_to_append():
    """``resolve_tool_block`` with an unknown id appends a fresh block."""
    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)
            widget = chat.resolve_tool_block(
                "tc-unknown",
                "Read 47 lines from src/foo.py",
                success=True,
                duration_ms=42,
            )
            await pilot.pause()
            # Falls through to append: one new chat line.
            assert len(chat._messages) == baseline + 1
            assert chat._pending_tool_blocks == {}
            assert widget.message.content.startswith("▸ ")


@pytest.mark.asyncio
async def test_bus_pending_then_final_updates_in_place():
    """Routing through the TUI bus handlers yields one block per call."""
    from cantrip.ui import events as ui_events

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)

            pending = ui_events.tool_invoked_pending(
                tool_name="charmcraft_pack",
                caption="Packing the charm…",
                tool_call_id="tc-bus",
            )
            pilot.app._on_bus_tool_invoked_pending(pending)
            await pilot.pause()
            assert "tc-bus" in chat._pending_tool_blocks
            assert len(chat._messages) == baseline + 1

            final = ui_events.tool_invoked(
                tool_name="charmcraft_pack",
                caption="Packed redis.charm",
                success=True,
                duration_ms=2340,
                tool_call_id="tc-bus",
            )
            pilot.app._on_bus_tool_invoked(final)
            await pilot.pause()

            # Same line, in-place update.
            assert len(chat._messages) == baseline + 1
            assert "tc-bus" not in chat._pending_tool_blocks
            assert "Packed redis.charm" in chat._messages[-1].content


@pytest.mark.asyncio
async def test_bus_pending_without_id_is_dropped():
    """Pending event with no usable id is ignored — no orphan spinner."""
    from cantrip.ui import events as ui_events

    p1, p2, _ = _patch_app()
    with p1, p2:
        async with CantripApp().run_test() as pilot:
            chat = pilot.app.query_one("#chat", ChatWidget)
            baseline = len(chat._messages)

            # Forge a pending event with an empty id by reaching into
            # the payload — the factory enforces a non-empty id, so this
            # exercises the renderer's defensive drop.
            event = ui_events.Event(
                type=ui_events.EventType.TOOL_INVOKED_PENDING,
                payload={
                    "tool_name": "x",
                    "caption": "Running x…",
                    "tool_call_id": "",
                    "source": "main",
                },
            )
            pilot.app._on_bus_tool_invoked_pending(event)
            await pilot.pause()
            # No new message, no registry entry.
            assert len(chat._messages) == baseline
            assert chat._pending_tool_blocks == {}


class TestFailedToolBlockDetail:
    """A failed tool block carries a clickable failure drill-down."""

    @pytest.mark.asyncio
    async def test_failed_block_with_detail_is_marked_clickable(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "Pack failed: missing charmcraft.yaml",
                    success=False,
                    detail="charmcraft pack\nerror: charmcraft.yaml not found",
                )
                await pilot.pause()
                assert (
                    widget.tool_error_detail == "charmcraft pack\nerror: charmcraft.yaml not found"
                )
                assert widget.tool_error_caption == "Pack failed: missing charmcraft.yaml"
                assert "tool-failed-detail" in widget.classes
                assert "(details)" in widget.message.content

    @pytest.mark.asyncio
    async def test_failed_block_without_detail_is_not_clickable(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block("Pack failed", success=False)
                await pilot.pause()
                assert widget.tool_error_detail is None
                assert "tool-failed-detail" not in widget.classes
                assert "(details)" not in widget.message.content

    @pytest.mark.asyncio
    async def test_success_block_ignores_detail(self):
        """A successful call never becomes clickable even if ``detail`` slips through."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block("Done", success=True, detail="ignored")
                await pilot.pause()
                assert widget.tool_error_detail is None
                assert "tool-failed-detail" not in widget.classes
                assert "(details)" not in widget.message.content

    @pytest.mark.asyncio
    async def test_resolved_failed_block_carries_detail(self):
        """Resolving a pending block as failed wires the drill-down too."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                chat.add_pending_tool_block("Packing…", tool_call_id="tc-fail")
                widget = chat.add_tool_block(
                    "Pack failed",
                    success=False,
                    tool_call_id="tc-fail",
                    detail="boom",
                )
                await pilot.pause()
                assert widget.tool_error_detail == "boom"
                assert "tool-failed-detail" in widget.classes

    @pytest.mark.asyncio
    async def test_click_opens_failure_modal(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block(
                    "Pack failed",
                    success=False,
                    detail="error: charmcraft.yaml not found",
                )
                await pilot.pause()
                widget.on_click(MagicMock())
                await pilot.pause()
                assert isinstance(pilot.app.screen, ToolErrorScreen)

    @pytest.mark.asyncio
    async def test_click_without_detail_does_not_open_modal(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", ChatWidget)
                widget = chat.add_tool_block("Pack failed", success=False)
                await pilot.pause()
                top_before = type(pilot.app.screen)
                widget.on_click(MagicMock())
                await pilot.pause()
                assert type(pilot.app.screen) is top_before

    @pytest.mark.asyncio
    async def test_bus_failure_event_attaches_detail(self):
        from cantrip.ui import events as ui_events

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                event = ui_events.tool_invoked(
                    tool_name="run_command",
                    caption="run make check",
                    success=False,
                    detail="exit 1\n\n5 failed",
                    tool_call_id="tc-bus-fail",
                )
                pilot.app._on_bus_tool_invoked(event)
                await pilot.pause()
                failed = next(
                    w for w in pilot.app.query(MessageWidget) if "tool-failed" in w.classes
                )
                assert failed.tool_error_detail == "exit 1\n\n5 failed"
                assert "(details)" in failed.message.content


class TestToolErrorScreen:
    """The modal that surfaces a failed tool's full error and output."""

    @pytest.mark.asyncio
    async def test_renders_caption_and_detail(self):
        from textual.widgets import RichLog

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.push_screen(ToolErrorScreen("Pack failed", "line one\nline two"))
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, ToolErrorScreen)
                assert screen._caption == "Pack failed"
                log = screen.query_one("#tool-error-output", RichLog)
                assert log.lines  # detail text was written

    @pytest.mark.asyncio
    async def test_empty_detail_shows_placeholder(self):
        from textual.widgets import RichLog

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.push_screen(ToolErrorScreen("", "   "))
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, ToolErrorScreen)
                log = screen.query_one("#tool-error-output", RichLog)
                assert log.lines
