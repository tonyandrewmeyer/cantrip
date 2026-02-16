"""Tests for agent core."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.agent.watcher import WatcherEvent
from cantrip.llm.base import Message, Response, Role, ToolCall
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

        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "active", "error": None})()
        )

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
    async def test_max_tool_rounds_enforced(self):
        """Test that the tool loop stops after MAX_TOOL_ROUNDS."""
        tool_call = ToolCall(id="loop", name="juju_status", arguments={})

        responses = [Response(content="", tool_calls=[tool_call])] * 25
        provider = FakeProvider(responses)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "ok", "error": None})()
        )

        await agent.process_message("loop")

        assert agent._execute_tool.await_count == 20


class TestUsageRecording:
    """Tests for token usage recording."""

    @pytest.mark.asyncio
    async def test_usage_recorded_for_simple_message(self, tmp_path: Path) -> None:
        """Usage is recorded once for a simple (no tool call) exchange."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 10, "completion_tokens": 5})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("hello")

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 10
        assert total["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_usage_recorded_per_complete_call(self, tmp_path: Path) -> None:
        """Each complete() call records its own usage row."""
        tool_call = ToolCall(id="tc", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[tool_call],
                    usage={"prompt_tokens": 100, "completion_tokens": 20},
                ),
                Response(
                    content="done",
                    usage={"prompt_tokens": 200, "completion_tokens": 40},
                ),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "ok", "error": None})()
        )

        await agent.process_message("go")

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 300
        assert total["completion_tokens"] == 60

    @pytest.mark.asyncio
    async def test_usage_recorded_in_streaming(self, tmp_path: Path) -> None:
        """Usage is recorded during streaming message processing."""
        provider = FakeProvider(
            [Response(content="stream", usage={"prompt_tokens": 15, "completion_tokens": 8})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        chunks = []
        async for chunk in agent.process_message_streaming("hi"):
            chunks.append(chunk)

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 15

    @pytest.mark.asyncio
    async def test_no_store_without_charm_path(self) -> None:
        """No store is created when charm_path is not set."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 1, "completion_tokens": 1})]
        )
        agent = CantripAgent(provider=provider)

        await agent.process_message("hello")

        assert agent._store is None


class TestStoreBackedPersistence:
    """Tests for save_state / load_state with the session store."""

    def test_save_and_load_state(self, tmp_path: Path) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        agent.state.charm_name = "my-charm"
        agent.state.charm_type = "k8s"
        agent.state.add_decision("path", "12-factor", reason="Flask")
        agent.save_state()

        # Create a fresh agent pointing at the same path.
        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        assert agent2.state.charm_name == "my-charm"
        assert agent2.state.charm_type == "k8s"
        assert len(agent2.state.decisions) == 1

    def test_load_state_returns_false_when_empty(self, tmp_path: Path) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        assert agent.load_state() is False

    def test_save_state_noop_without_store(self) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        # Should not raise.
        agent.save_state()

    def test_load_state_returns_false_without_store(self) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        assert agent.load_state() is False


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
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": big_output, "error": None})()
        )

        await agent.process_message("Read big.py")

        # The tool result message should contain a virtual file pointer.
        tool_msg = agent.state.messages[2]
        assert tool_msg.role == Role.TOOL
        assert "virtual_file_read" in tool_msg.tool_results[0].content
        assert "vf_1" in tool_msg.tool_results[0].content

        # The full content should be in the virtual file store.
        vf = agent._virtual_store.get("vf_1")
        assert vf is not None
        assert len(vf.content) == 50_000

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
            # First response for the user message.
            [Response(content="short")]
            # Then a summary response during compaction.
            + [Response(content="Summary of conversation.")]
            # Then the response after compaction.
            + [Response(content="After compaction.")],
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

        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "ok", "error": None})()
        )

        await agent.process_message("Check status")

        # Compaction should have shortened the message list.
        # The virtual store should contain the history.
        files = agent._virtual_store.list_files()
        assert len(files) >= 1
        assert any(f.source == "compaction" for f in files)

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


class TestWatcherIntegration:
    """Tests for watcher integration in CantripAgent."""

    def test_start_watcher_requires_dev_model(self):
        """start_watcher returns False without a dev_model."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        assert agent.start_watcher() is False
        assert not agent.watcher_running
        assert not agent.state.watcher_enabled

    @pytest.mark.asyncio
    async def test_start_watcher_with_dev_model(self):
        """start_watcher succeeds with a dev_model set."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        result = agent.start_watcher()

        assert result is True
        assert agent.watcher_running
        assert agent.state.watcher_enabled

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_stop_watcher(self):
        """stop_watcher stops the watcher and clears the flag."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        await agent.stop_watcher()

        assert not agent.watcher_running
        assert not agent.state.watcher_enabled

    @pytest.mark.asyncio
    async def test_stop_watcher_when_not_running(self):
        """stop_watcher is a no-op when no watcher is active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        await agent.stop_watcher()

        assert not agent.watcher_running

    @pytest.mark.asyncio
    async def test_process_watcher_event_no_watcher(self):
        """process_watcher_event returns None when no watcher is active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        result = await agent.process_watcher_event()

        assert result is None

    @pytest.mark.asyncio
    async def test_process_watcher_event_empty_queue(self):
        """process_watcher_event returns None when queue is empty."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        result = await agent.process_watcher_event()

        assert result is None
        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_process_watcher_event_processes_event(self):
        """process_watcher_event dequeues and processes an event."""
        provider = FakeProvider([Response(content="I see the hook failure.")])
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        # Manually enqueue an event.
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        agent._watcher._enqueue(event)

        result = await agent.process_watcher_event()

        assert result == "I see the hook failure."
        await agent.stop_watcher()

    def test_watcher_enabled_in_system_prompt(self):
        """watcher_enabled appears in the system prompt when active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.watcher_enabled = True

        prompt = agent._build_system_prompt()

        assert "Event Watcher" in prompt
        assert "[Watcher]" in prompt

    def test_watcher_disabled_not_in_system_prompt(self):
        """Watcher section absent from system prompt when disabled."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        prompt = agent._build_system_prompt()

        assert "Event Watcher" not in prompt
