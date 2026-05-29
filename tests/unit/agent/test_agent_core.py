"""Tests for ``CantripAgent`` core message-and-tool-loop behaviour."""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response, Role, ToolCall
from tests.conftest import FakeProvider


class TestCantripAgent:
    """Tests for CantripAgent."""

    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        """Test that a simple text response is returned."""
        provider = FakeProvider([Response(content="Hello there!")])
        agent = CantripAgent(provider=provider)

        result = await agent.process_message("Hi")

        assert result == "Hello there!"

    @pytest.mark.asyncio
    async def test_messages_are_accumulated(self):
        """Test that user and assistant messages are stored in state."""
        provider = FakeProvider(
            [
                Response(content="First reply"),
                Response(content="Second reply"),
            ]
        )
        agent = CantripAgent(provider=provider)

        await agent.process_message("Hello")
        await agent.process_message("Again")

        # user, assistant, user, assistant = 4 messages
        assert len(agent.state.messages) == 4
        assert agent.state.messages[0].role == Role.USER
        assert agent.state.messages[0].content == "Hello"
        assert agent.state.messages[1].role == Role.ASSISTANT
        assert agent.state.messages[1].content == "First reply"

    @pytest.mark.asyncio
    async def test_tool_call_loop(self):
        """Test that tool calls are executed and the loop continues."""
        tool_call = ToolCall(id="juju_status", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Here is the status."),
            ]
        )
        agent = CantripAgent(provider=provider)

        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="active"))

        result = await agent.process_message("Show juju status")

        assert result == "Here is the status."
        agent._execute_tool.assert_awaited_once_with("juju_status", {})

        # Messages: user, assistant (tool_calls), tool, assistant (final).
        assert len(agent.state.messages) == 4
        assert agent.state.messages[1].role == Role.ASSISTANT
        assert len(agent.state.messages[1].tool_calls) == 1
        assert agent.state.messages[2].role == Role.TOOL
        assert agent.state.messages[3].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_tool_activity_published_to_status_bar(self):
        """Main-agent tool calls surface as STATUS_BAR_CHANGED events."""
        from cantrip.ui import events as ui_events

        tool_call = ToolCall(id="charmcraft_pack", name="charmcraft_pack", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Packed."),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        captured: list[dict] = []
        agent.event_bus.subscribe(
            ui_events.EventType.STATUS_BAR_CHANGED,
            lambda event: captured.append(event.payload),
        )

        await agent.process_message("Pack it.")

        labels = [p.get("task_label", "") for p in captured]
        assert any("running: charmcraft_pack" in label for label in labels)
        # After the tool completes, the bar is reset to a themed
        # activity label (e.g. ``⟳ Conjuring...``) so the next LLM
        # round has a neutral, non-tool label.
        from cantrip.ui import flavour

        pool = flavour.think_pool()
        assert any(
            label.startswith("⟳ ") and label.endswith("...") and label[2:-3] in pool
            for label in labels
        )

    @pytest.mark.asyncio
    async def test_tool_call_failure(self):
        """Test that failed tool calls are reported correctly."""
        tool_call = ToolCall(id="unknown_tool", name="unknown_tool", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Sorry, that didn't work."),
            ]
        )
        agent = CantripAgent(provider=provider)

        result = await agent.process_message("Do something")

        assert result == "Sorry, that didn't work."
        tool_msg = agent.state.messages[2]
        assert tool_msg.role == Role.TOOL
        assert tool_msg.tool_results[0].is_error

    @pytest.mark.asyncio
    async def test_streaming_simple_response(self):
        """Test streaming returns the content."""
        provider = FakeProvider([Response(content="Streamed answer")])
        agent = CantripAgent(provider=provider)

        chunks = []
        async for chunk in agent.process_message_streaming("Hi"):
            chunks.append(chunk)

        assert "".join(chunks) == "Streamed answer"

    @pytest.mark.asyncio
    async def test_streaming_yields_chunks_incrementally(self):
        """Test that streaming yields multiple chunks, not one big blob."""
        provider = FakeProvider([Response(content="Hello world from streaming")])
        agent = CantripAgent(provider=provider)

        chunks = []
        async for chunk in agent.process_message_streaming("Hi"):
            chunks.append(chunk)

        # FakeProvider.stream() splits on spaces, so we expect multiple chunks.
        assert len(chunks) > 1
        assert "".join(chunks) == "Hello world from streaming"

    @pytest.mark.asyncio
    async def test_streaming_with_tool_calls(self):
        """Streaming yields text from both pre- and post-tool-call rounds."""
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Status is active"),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="active"))

        chunks = []
        async for chunk in agent.process_message_streaming("Show status"):
            chunks.append(chunk)

        assert "".join(chunks) == "Status is active"
        # Multiple chunks from the word-splitting in FakeProvider.stream().
        assert len(chunks) > 1
        agent._execute_tool.assert_awaited_once_with("juju_status", {})

        # Messages: user, assistant (tool_calls), tool, assistant (final).
        assert len(agent.state.messages) == 4

    @pytest.mark.asyncio
    async def test_streaming_separates_tool_call_rounds(self):
        """A separator is injected between rounds so sentences don't run together.

        Without this, if round 1 ends with "Let me check." and round 2 starts
        with "The result is X.", the streamed text collapses into
        "Let me check.The result is X." — visible in the TUI.
        """
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="Let me check.", tool_calls=[tool_call]),
                Response(content="The result is active."),
            ]
        )
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="active"))

        chunks = []
        async for chunk in agent.process_message_streaming("Show status"):
            chunks.append(chunk)

        # The joined stream must have visible separation between rounds.
        joined = "".join(chunks)
        assert "check.\n\nThe" in joined

    @pytest.mark.asyncio
    async def test_reconnect_banner_published_on_provider_disconnect(self, monkeypatch):
        """Phase 102.4: a transient ``ProviderConnectionError`` surfaces as a chat banner.

        The conversation loop's ``_complete_with_retry`` wires an
        ``on_retry`` hook into the retry layer; the hook publishes a
        ``[provider reconnect]`` system message and a ``reconnecting``
        status-bar update so the operator sees the recovery rather than
        staring at a frozen UI.
        """
        from cantrip.llm.base import ProviderConnectionError
        from cantrip.ui import events as ui_events

        # Drive ``provider.complete`` so the first call raises the
        # disconnect error and the second returns a real reply.  Skip
        # the actual asyncio.sleep so the test stays fast.
        monkeypatch.setattr(
            "cantrip.agent.policy.retry.asyncio.sleep",
            AsyncMock(return_value=None),
        )

        attempts = {"n": 0}
        recovery_response = Response(content="recovered")

        async def _flaky_complete(*_args, **_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ProviderConnectionError("snap dropped mid-stream")
            return recovery_response

        provider = FakeProvider([recovery_response])
        provider.complete = _flaky_complete  # override for test
        agent = CantripAgent(provider=provider)

        chat_messages: list[dict] = []
        status_payloads: list[dict] = []
        agent.event_bus.subscribe(
            ui_events.EventType.CHAT_MESSAGE,
            lambda event: chat_messages.append(event.payload),
        )
        agent.event_bus.subscribe(
            ui_events.EventType.STATUS_BAR_CHANGED,
            lambda event: status_payloads.append(event.payload),
        )

        result = await agent.process_message("Hi")

        assert result == "recovered"
        # A ``[provider reconnect]`` banner appears as a system chat row.
        banner_rows = [m for m in chat_messages if "[provider reconnect]" in m.get("content", "")]
        assert banner_rows, f"expected reconnect banner, got: {chat_messages}"
        assert "disconnected" in banner_rows[0]["content"]
        # And the status bar is briefly relabelled as reconnecting.
        labels = [p.get("task_label", "") for p in status_payloads]
        assert any("reconnecting" in label for label in labels)

    @pytest.mark.asyncio
    async def test_max_tool_rounds_enforced(self):
        """Test that the tool loop stops after MAX_TOOL_ROUNDS."""
        tool_call = ToolCall(id="loop", name="juju_status", arguments={})

        responses = [Response(content="", tool_calls=[tool_call])] * 25
        provider = FakeProvider(responses)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        await agent.process_message("loop")

        assert agent._execute_tool.await_count == 20

    @pytest.mark.asyncio
    async def test_pack_succeeded_resets_at_top_of_turn(self):
        """A new user turn always gets a fresh ``pack_succeeded`` flag.

        Phase 110.1 — once a charm packed in a *previous* turn, we
        still want the *next* user goal to be able to call
        ``plan_tasks`` cleanly.  The reset happens at the top of
        ``process_message`` before any inner work runs.
        """
        provider = FakeProvider([Response(content="ack")])
        agent = CantripAgent(provider=provider)
        # Simulate a successful pack in the previous turn.
        agent.state.pack_succeeded = True

        await agent.process_message("Now do something else")

        # The flag was cleared at the top of the new turn — the
        # planner gate doesn't survive across user messages.
        assert agent.state.pack_succeeded is False

    @pytest.mark.asyncio
    async def test_pack_succeeded_resets_at_top_of_streaming_turn(self):
        """Streaming variant of the per-turn reset."""
        provider = FakeProvider([Response(content="ack")])
        agent = CantripAgent(provider=provider)
        agent.state.pack_succeeded = True

        chunks: list[str] = []
        async for chunk in agent.process_message_streaming("again"):
            chunks.append(chunk)

        assert agent.state.pack_succeeded is False
