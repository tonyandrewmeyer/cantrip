"""Tests for agent core."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent, _infer_gaps_from_audit
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
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "ok", "error": None})()
        )

        captured: list[dict] = []
        agent.event_bus.subscribe(
            ui_events.EventType.STATUS_BAR_CHANGED,
            lambda event: captured.append(event.payload),
        )

        await agent.process_message("Pack it.")

        labels = [p.get("task_label", "") for p in captured]
        assert any("running: charmcraft_pack" in label for label in labels)
        # After the tool completes, the bar is reset to "Thinking..." so
        # the next LLM round has a neutral label.
        assert any("Thinking" in label for label in labels)

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
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "active", "error": None})()
        )

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
        agent._execute_tool = AsyncMock(
            return_value=type("R", (), {"success": True, "output": "active", "error": None})()
        )

        chunks = []
        async for chunk in agent.process_message_streaming("Show status"):
            chunks.append(chunk)

        # The joined stream must have visible separation between rounds.
        joined = "".join(chunks)
        assert "check.\n\nThe" in joined

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

    def test_start_watcher_requires_dev_model(self, monkeypatch):
        """start_watcher returns False when no dev_model is available.

        With no state.dev_model and no detectable Juju model, the
        watcher has nothing to watch and the call is a no-op.
        """
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        monkeypatch.setattr(
            "cantrip.agent.core.detect_current_juju_model",
            lambda: None,
        )

        assert agent.start_watcher() is False
        assert not agent.watcher_running
        assert not agent.state.watcher_enabled

    @pytest.mark.asyncio
    async def test_start_watcher_auto_detects_dev_model(self, monkeypatch):
        """start_watcher falls back to the current Juju model when state is empty."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        monkeypatch.setattr(
            "cantrip.agent.core.detect_current_juju_model",
            lambda: "detected-model",
        )

        result = agent.start_watcher()

        assert result is True
        assert agent.state.dev_model == "detected-model"
        assert agent.watcher_running

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_auto_detects_cos_model(self, monkeypatch):
        """start_watcher also picks up a 'cos' model when present."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        monkeypatch.setattr("cantrip.agent.core.detect_cos_juju_model", lambda: "cos")

        assert agent.start_watcher() is True
        assert agent.state.cos_model == "cos"

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_skips_cos_detection_when_already_set(self, monkeypatch):
        """cos_model already set on state is not overwritten."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.cos_model = "preset-cos"
        called = {"count": 0}

        def _spy() -> str | None:
            called["count"] += 1
            return "cos"

        monkeypatch.setattr("cantrip.agent.core.detect_cos_juju_model", _spy)
        agent.start_watcher()
        assert agent.state.cos_model == "preset-cos"
        assert called["count"] == 0

        await agent.stop_watcher()

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
    async def test_process_watcher_event_routes_to_queue(self):
        """process_watcher_event dequeues and routes to the task queue."""
        provider = FakeProvider()
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

        assert result is not None
        assert "Hook failure on myapp/0" in result
        # Task should be in the work queue.
        tasks = agent.work_queue.all_tasks()
        assert len(tasks) >= 1
        assert any("Hook failure" in t.title for t in tasks)
        await agent.stop_watcher()

    def test_route_watcher_event_creates_task(self):
        """route_watcher_event creates a DEBUG task for a hook_failure event."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category.value == "debug"
        assert task in agent.work_queue.all_tasks()

    def test_route_watcher_event_no_dev_model_returns_none(self):
        """route_watcher_event returns None without a dev_model."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        # No dev_model set.

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure",
            detail="boom",
        )
        result = agent.route_watcher_event(event)

        assert result is None
        assert len(agent.work_queue.all_tasks()) == 0

    @pytest.mark.asyncio
    async def test_start_watcher_auto_routes_events(self):
        """Events enqueued by the watcher are automatically routed to the task queue."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        events_received: list[WatcherEvent] = []
        agent.start_watcher(on_event=lambda e: events_received.append(e))

        # Simulate an event through the watcher's internal enqueue.
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        agent._watcher._enqueue(event)

        # The auto-route callback fires synchronously during _enqueue.
        tasks = agent.work_queue.all_tasks()
        assert len(tasks) >= 1
        assert any("Hook failure" in t.title for t in tasks)
        # External callback should also have fired.
        assert len(events_received) == 1
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


# ===================================================================
# TestInferGapsFromAudit
# ===================================================================


class TestInferGapsFromAudit:
    """Tests for _infer_gaps_from_audit — heuristic gap detection from audit text."""

    def test_detects_missing_tracing(self) -> None:
        text = "## Must-fix\n- Missing tracing relation (cos-tracing)"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True

    def test_detects_missing_unit_tests(self) -> None:
        text = "No unit tests found in tests/unit/"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["unit_tests"] is True

    def test_detects_deprecated_apis(self) -> None:
        text = "Uses deprecated StoredState in src/charm.py"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_detects_harness_as_deprecated(self) -> None:
        text = "Tests use Harness instead of Scenario"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_detects_fetch_libs_as_deprecated(self) -> None:
        text = "charmcraft fetch-libs import: charms.grafana_k8s — replace with PyPI"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_no_false_positives_on_clean_audit(self) -> None:
        text = "All checks passed. The charm is well-structured."
        gaps = _infer_gaps_from_audit(text)
        # Clean audit should not flag anything.
        assert not any(gaps.values())

    def test_detects_missing_readme(self) -> None:
        text = "Missing README.md file"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["readme"] is True

    def test_detects_missing_licence(self) -> None:
        text = "No licence file found"
        gaps = _infer_gaps_from_audit(text)
        assert gaps["licence"] is True


# ===================================================================
# TestHandleImprovementConfirmation
# ===================================================================


class TestHandleImprovementConfirmation:
    """Tests for CantripAgent.handle_improvement_confirmation."""

    @pytest.mark.asyncio
    async def test_generates_fix_tasks_from_audit(self, tmp_path: Path) -> None:
        """Fix tasks are generated from an audit result with gaps."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.mode = "improve"
        agent.state.charm_name = "test-charm"

        # Simulate the audit → confirm flow.
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit existing charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
        )
        audit_task.result = (
            "## Must-fix\n- Missing tracing relation\n- No unit tests found\n- Missing README.md\n"
        )
        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm improvement plan",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.DONE,
            dependencies=["audit-charm"],
        )

        agent.work_queue.add_tasks([audit_task, confirm_task])
        agent.work_queue.set_done("audit-charm", audit_task.result)

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")

        assert len(fix_tasks) > 0
        task_ids = [t.id for t in fix_tasks]
        assert any(tid.startswith("fill-observability-") for tid in task_ids)
        assert any(tid.startswith("fill-tests-") for tid in task_ids)

    @pytest.mark.asyncio
    async def test_no_tasks_when_confirm_not_found(self) -> None:
        """Returns empty list when the confirm task does not exist."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        fix_tasks = await agent.handle_improvement_confirmation("nonexistent")

        assert fix_tasks == []

    @pytest.mark.asyncio
    async def test_no_tasks_when_no_audit_result(self) -> None:
        """Returns empty list when no audit result is found."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        from cantrip.agent.queue import AgentTask, TaskCategory

        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm",
            category=TaskCategory.CONFIRM,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([confirm_task])

        fix_tasks = await agent.handle_improvement_confirmation("confirm-improvements")

        assert fix_tasks == []

    @pytest.mark.asyncio
    async def test_stores_audit_report_on_state(self, tmp_path: Path) -> None:
        """The audit report is saved to agent state."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.mode = "improve"

        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        audit_task = AgentTask(
            id="audit-charm",
            title="Audit",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
        )
        audit_text = "## Audit\nMissing tracing. Uses deprecated StoredState."
        audit_task.result = audit_text

        confirm_task = AgentTask(
            id="confirm-improvements",
            title="Confirm",
            category=TaskCategory.CONFIRM,
            dependencies=["audit-charm"],
        )
        agent.work_queue.add_tasks([audit_task, confirm_task])
        agent.work_queue.set_done("audit-charm", audit_text)

        await agent.handle_improvement_confirmation("confirm-improvements")

        assert agent.state.audit_report == audit_text
