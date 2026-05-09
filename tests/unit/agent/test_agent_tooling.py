"""Tests for ``CantripAgent`` tool-result capture, image forwarding, and events."""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Image, Response, Role, ToolCall
from cantrip.ui import events as ui_events
from tests.conftest import FakeProvider


class TestTestResultsCapture:
    """Tests for _capture_test_results integration in the agent loop."""

    @pytest.mark.asyncio
    async def test_run_charm_tests_sets_state(self):
        """Running run_charm_tests populates state.test_results."""
        tool_call = ToolCall(id="tc1", name="run_charm_tests", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Tests done."),
            ]
        )
        agent = CantripAgent(provider=provider)

        agent._execute_tool = AsyncMock(
            return_value=ToolResult(
                success=True,
                output="5 passed",
                data={"summary": {"passed": 5, "failed": 0, "error": 0, "skipped": 1}},
            )
        )

        await agent.process_message("Run tests")

        assert agent.state.test_results is not None
        assert agent.state.test_results.passed == 5
        assert agent.state.test_results.skipped == 1
        assert agent.state.test_results.failed == 0

    @pytest.mark.asyncio
    async def test_charm_validate_sets_state(self):
        """Running charm_validate with nested test data populates state.test_results."""
        tool_call = ToolCall(id="tc1", name="charm_validate", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Validation done."),
            ]
        )
        agent = CantripAgent(provider=provider)

        agent._execute_tool = AsyncMock(
            return_value=ToolResult(
                success=True,
                output="ok",
                data={"tests": {"summary": {"passed": 3, "failed": 1, "error": 0, "skipped": 0}}},
            )
        )

        await agent.process_message("Validate charm")

        assert agent.state.test_results is not None
        assert agent.state.test_results.passed == 3
        assert agent.state.test_results.failed == 1

    @pytest.mark.asyncio
    async def test_unrelated_tool_does_not_set_state(self):
        """A tool that is not in _TEST_RESULT_TOOLS leaves test_results as None."""
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Status ok."),
            ]
        )
        agent = CantripAgent(provider=provider)

        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=True, output="active/idle")
        )

        await agent.process_message("Show status")

        assert agent.state.test_results is None

    @pytest.mark.asyncio
    async def test_empty_summary_does_not_set_state(self):
        """An empty summary dict from run_charm_tests leaves test_results as None."""
        tool_call = ToolCall(id="tc1", name="run_charm_tests", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="No results."),
            ]
        )
        agent = CantripAgent(provider=provider)

        agent._execute_tool = AsyncMock(
            return_value=ToolResult(
                success=True,
                output="no tests found",
                data={"summary": {}},
            )
        )

        await agent.process_message("Run tests")

        assert agent.state.test_results is None


class TestToolResultImageForwarding:
    """Phase 48.2b: images flow agent ToolResult → llm.ToolResult → TOOL msg."""

    @pytest.mark.asyncio
    async def test_images_propagate_into_tool_message(self):
        """A tool that returns images produces a TOOL message carrying them."""
        tool_call = ToolCall(id="tc1", name="grafana_screenshot", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Looked at the panel."),
            ]
        )
        agent = CantripAgent(provider=provider)

        img = Image(data=b"\x89PNGdiagnostic", mime="image/png")
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(
                success=True,
                output="Rendered latency panel.",
                images=[img],
            )
        )

        await agent.process_message("Render the latency panel.")

        tool_msgs = [m for m in agent.state.messages if m.role == Role.TOOL]
        assert tool_msgs, "no TOOL message recorded"
        [llm_tr] = tool_msgs[-1].tool_results
        assert len(llm_tr.images) == 1
        assert llm_tr.images[0].mime == "image/png"
        assert llm_tr.images[0].data == b"\x89PNGdiagnostic"


class TestToolInvokedEvent:
    """Phase 75: each main-agent tool call publishes a TOOL_INVOKED event."""

    @pytest.mark.asyncio
    async def test_tool_call_emits_tool_invoked_event(self):
        """``process_message`` emits a TOOL_INVOKED event with the right payload."""
        tool_call = ToolCall(id="tc1", name="read_file", arguments={"path": "src/foo.py"})
        provider = FakeProvider(
            [
                Response(content="Let me check:", tool_calls=[tool_call]),
                Response(content="All good."),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="47 lines"))

        received: list[ui_events.Event] = []
        agent.event_bus.subscribe(ui_events.EventType.TOOL_INVOKED, received.append)

        await agent.process_message("show me the file")

        assert len(received) == 1
        payload = received[0].payload
        assert payload["tool_name"] == "read_file"
        assert payload["success"] is True
        assert payload["source"] == "main"
        # Caption falls back to the verb-target formatter (Phase 108.5).
        assert payload["caption"] == "read src/foo.py"
        # Duration is measured, non-negative.
        assert isinstance(payload["duration_ms"], int)
        assert payload["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_failed_tool_call_emits_with_success_false(self):
        tool_call = ToolCall(id="tc1", name="run_command", arguments={"command": "false"})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="That didn't work."),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="exit 1")
        )

        received: list = []
        agent.event_bus.subscribe(ui_events.EventType.TOOL_INVOKED, received.append)

        await agent.process_message("run something")

        assert len(received) == 1
        assert received[0].payload["success"] is False

    @pytest.mark.asyncio
    async def test_pending_event_precedes_invoked_with_matching_id(self):
        """Phase 82: TOOL_INVOKED_PENDING fires before TOOL_INVOKED with
        the same ``tool_call_id`` so renderers can update in place."""
        tool_call = ToolCall(id="tc-pending", name="read_file", arguments={"path": "x"})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="ok"),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        events_seen: list[ui_events.Event] = []
        agent.event_bus.subscribe(ui_events.EventType.TOOL_INVOKED_PENDING, events_seen.append)
        agent.event_bus.subscribe(ui_events.EventType.TOOL_INVOKED, events_seen.append)

        await agent.process_message("read it")

        types = [e.type for e in events_seen]
        assert types == [
            ui_events.EventType.TOOL_INVOKED_PENDING,
            ui_events.EventType.TOOL_INVOKED,
        ]
        assert events_seen[0].payload["tool_call_id"] == "tc-pending"
        assert events_seen[1].payload["tool_call_id"] == "tc-pending"
        # The pending caption is a present-continuous "doing now"
        # form ending in a horizontal ellipsis.  ReadFileTool
        # overrides intro_caption to "Reading x…"; without an
        # override the synthesised fallback would be
        # "Running tool(arg=value)…" — both end in ``…``.
        assert events_seen[0].payload["caption"].endswith("…")
        # The final caption is the post-call summary, not the
        # pre-call form, so the two must differ.
        assert events_seen[0].payload["caption"] != events_seen[1].payload["caption"]

    @pytest.mark.asyncio
    async def test_explicit_caption_wins_over_fallback(self):
        """A tool setting ``ToolResult.caption`` overrides the formulaic fallback."""
        tool_call = ToolCall(id="tc1", name="read_file", arguments={"path": "src/foo.py"})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Done."),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(
                success=True,
                output="",
                caption="Read 47 lines from src/foo.py",
            )
        )

        received: list = []
        agent.event_bus.subscribe(ui_events.EventType.TOOL_INVOKED, received.append)
        await agent.process_message("read it")
        assert received[0].payload["caption"] == "Read 47 lines from src/foo.py"
