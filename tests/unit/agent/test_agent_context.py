"""Tests for ``CantripAgent`` context-window management integration."""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Message, Response, Role, ToolCall
from tests.conftest import FakeProvider


class TestContextManagement:
    """Tests for context window management integration."""

    @pytest.mark.asyncio
    async def test_large_tool_result_is_virtualised(self):
        """A large tool result is replaced with a virtual file pointer."""
        tool_call = ToolCall(id="tc1", name="read_file", arguments={"path": "big.py"})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Done."),
            ]
        )
        agent = CantripAgent(provider=provider)

        # Return a large result (>10k tokens = >40k chars).
        big_output = "X" * 50_000
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output=big_output))

        await agent.process_message("Read big.py")

        # The tool result message should contain a virtual file pointer.
        tool_msg = agent.state.messages[2]
        assert tool_msg.role == Role.TOOL
        assert "virtual_file_read" in tool_msg.tool_results[0].content
        assert "vf_1" in tool_msg.tool_results[0].content

        # The full content should be in the virtual file store.
        # The stored content includes the <tool_result> delimiter wrapping.
        vf = agent._virtual_store.get("vf_1")
        assert vf is not None
        assert "X" * 50_000 in vf.content

    @pytest.mark.asyncio
    async def test_budget_message_not_stored_in_state(self):
        """The budget message is transient and not persisted in state.messages."""
        provider = FakeProvider([Response(content="Hello!")])
        agent = CantripAgent(provider=provider)

        await agent.process_message("Hi")

        # Only user + assistant should be in state — no budget message.
        assert len(agent.state.messages) == 2
        for msg in agent.state.messages:
            assert "[Context Budget]" not in msg.content

    @pytest.mark.asyncio
    async def test_compaction_triggers_at_threshold(self):
        """Compaction triggers when token usage exceeds the threshold."""
        # Use a tiny context window so compaction triggers easily.
        # FakeProvider count_tokens uses chars//4, and compaction threshold is 80%.
        # Context window = 200 tokens → threshold at 160 tokens → 640 chars.
        provider = FakeProvider(
            [
                # First response for the user message.
                Response(content="short"),
                # Then a summary response during compaction.
                Response(content="Summary of conversation."),
                # Then the response after compaction.
                Response(content="After compaction."),
            ],
            context_window_tokens=200,
        )
        agent = CantripAgent(provider=provider)

        # Manually inject enough messages to exceed the threshold.
        for _i in range(10):
            agent.state.messages.append(Message(role=Role.USER, content="A" * 80))
            agent.state.messages.append(Message(role=Role.ASSISTANT, content="B" * 80))

        # Trigger compaction indirectly by injecting a tool call round.
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        # Replace provider responses: tool_call response, then compaction summary, then final.
        provider._responses = [
            Response(content="", tool_calls=[tool_call]),
            Response(content="Compaction summary."),
            Response(content="After compaction."),
        ]
        provider._call_count = 0

        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        await agent.process_message("Check status")

        # Compaction should have shortened the message list.
        # The virtual store should contain the history.
        files = agent._virtual_store.list_files()
        assert len(files) >= 1
        assert any(f.source == "compaction" for f in files)

    @pytest.mark.asyncio
    async def test_compaction_emits_started_and_completed_events(self):
        """Phase 78.3: compaction brackets the work with UI events.

        Without the events, users see a multi-second pause while the
        summary LLM turn runs with no explanation.  The event pair
        complements the ``pre_compact`` / ``post_compact`` hooks
        (which fire but don't reach the bus) so chat panes can show
        an inline indicator.
        """
        from cantrip.ui.events import EventType

        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Compaction summary."),
                Response(content="After compaction."),
            ],
            context_window_tokens=200,
        )
        agent = CantripAgent(provider=provider)
        events: list = []
        agent.event_bus.subscribe(None, lambda e: events.append(e))

        # Pre-load the context past the 80% threshold so the tool
        # round-trip trips compaction.
        for _ in range(10):
            agent.state.messages.append(Message(role=Role.USER, content="A" * 80))
            agent.state.messages.append(Message(role=Role.ASSISTANT, content="B" * 80))

        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        await agent.process_message("Check status")

        started = [e for e in events if e.type == EventType.COMPACTION_STARTED]
        completed = [e for e in events if e.type == EventType.COMPACTION_COMPLETED]
        assert len(started) == 1
        assert len(completed) == 1
        # Started fires first and carries the pre-compaction token count.
        assert events.index(started[0]) < events.index(completed[0])
        assert started[0].payload["tokens_before"] > 0
        assert started[0].payload["source"] == "main"
        # Completed carries the token counts and kind.
        assert completed[0].payload["tokens_before"] == started[0].payload["tokens_before"]
        assert completed[0].payload["kind"] in {"compact", "emergency"}
        assert "tokens_after" in completed[0].payload

    def test_virtual_file_tools_are_registered(self):
        """Virtual file tools are included in the tool list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        tool_names = {t.name for t in agent._tools}

        assert "virtual_file_read" in tool_names
        assert "virtual_file_search" in tool_names

    def test_run_charm_tests_tool_is_registered(self):
        """The run_charm_tests tool is included in the tool list."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        tool_names = {t.name for t in agent._tools}

        assert "run_charm_tests" in tool_names
