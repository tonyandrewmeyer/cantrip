"""Phase 107: tool-call failure cap.

Pins the autonomous-loop bail-out shape so a model that keeps
emitting the same failing tool call doesn't burn minutes (or
hours) before the operator notices.  The cap fires after N
consecutive same-(tool, args) failures; the active work-queue
task is flipped to BLOCKED so Phase 106's exit path takes over.
"""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response, Role, ToolCall
from cantrip.ui import events as ui_events
from tests.conftest import FakeProvider


class TestToolFailureCap:
    """Phase 107 — same-(tool, args) failure cap."""

    @pytest.mark.asyncio
    async def test_loop_bails_after_cap_failures(self):
        """Same failing tool call N times in a row exits the loop."""
        # Provider emits the same write_file call on every turn.  The
        # tool always fails.  With the default cap of 5, the loop
        # should bail somewhere around turn 5 — long before the
        # MAX_TOOL_ROUNDS of 20 fires.
        failing_call = ToolCall(
            id="wf",
            name="write_file",
            arguments={"path": "tests/test_charm.py", "content": ""},
        )
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 30)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="content empty")
        )

        await agent.process_message("Do the thing")

        cap = agent.state.tool_failure_cap
        # The streak counter should be at least cap (could be exactly
        # cap if the loop bailed precisely at the threshold; never
        # more than cap+1 because the cap-check fires after each
        # turn's tool calls).
        assert agent.state.consecutive_tool_failures >= cap
        # MAX_TOOL_ROUNDS is 20 — if the cap didn't fire, _execute_tool
        # would have run 20 times.  Cap should keep us well below that.
        assert agent._execute_tool.call_count <= cap + 1

    @pytest.mark.asyncio
    async def test_success_resets_streak(self):
        """A successful tool call clears the failure streak."""
        # Three failing calls then one success: the streak should be
        # back to 0 and the agent should NOT bail.
        failing_call = ToolCall(id="wf", name="write_file", arguments={"path": "x.py"})
        success_call = ToolCall(id="rf", name="read_file", arguments={"path": "y.py"})
        responses = [
            Response(content="", tool_calls=[failing_call]),
            Response(content="", tool_calls=[failing_call]),
            Response(content="", tool_calls=[failing_call]),
            Response(content="", tool_calls=[success_call]),
            Response(content="done"),
        ]
        provider = FakeProvider(responses)
        agent = CantripAgent(provider=provider)

        async def fake_execute(name, _args):
            if name == "write_file":
                return ToolResult(success=False, output="", error="boom")
            return ToolResult(success=True, output="content")

        agent._execute_tool = fake_execute

        result = await agent.process_message("Do it")

        assert result == "done"
        assert agent.state.consecutive_tool_failures == 0
        assert agent.state.last_failed_tool_signature is None

    @pytest.mark.asyncio
    async def test_different_args_resets_streak(self):
        """Same tool but different arguments doesn't compound the streak."""
        # Three failing write_file calls but each with a *different*
        # path.  Streak should never get past 1 because each call has
        # a fresh signature.
        responses = [
            Response(
                content="",
                tool_calls=[ToolCall(id="a", name="write_file", arguments={"path": "a.py"})],
            ),
            Response(
                content="",
                tool_calls=[ToolCall(id="b", name="write_file", arguments={"path": "b.py"})],
            ),
            Response(
                content="",
                tool_calls=[ToolCall(id="c", name="write_file", arguments={"path": "c.py"})],
            ),
            Response(content="ok"),
        ]
        provider = FakeProvider(responses)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        result = await agent.process_message("Try things")

        assert result == "ok"
        # Streak only reaches 1 because each new path starts fresh.
        assert agent.state.consecutive_tool_failures == 1

    @pytest.mark.asyncio
    async def test_active_task_marked_blocked(self):
        """Cap fire flips the active work-queue task to BLOCKED."""
        failing_call = ToolCall(id="wf", name="write_file", arguments={"path": "x.py"})
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 30)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        # Seed an active task so Phase 107's _mark_active_task_blocked
        # has a target.  Without this the cap still fires and the loop
        # exits, but no task transitions (covered by the first test).
        task = AgentTask(
            id="t1",
            title="Try writing things",
            category=TaskCategory.BUILD,
            status=TaskStatus.ACTIVE,
        )
        agent._work_queue.add_tasks([task])
        agent._work_queue.set_active(task.id)

        await agent.process_message("Do it")

        # The task should now be BLOCKED with a reason mentioning the
        # tool name and the failure count.
        refreshed = agent._work_queue.get_task("t1")
        assert refreshed.status == TaskStatus.BLOCKED
        assert "write_file" in (refreshed.blocked_reason or "")
        assert str(agent.state.tool_failure_cap) in (refreshed.blocked_reason or "")

    @pytest.mark.asyncio
    async def test_env_var_tunes_cap(self, monkeypatch):
        """``CANTRIP_TOOL_FAILURE_CAP`` overrides the default cap."""
        monkeypatch.setenv("CANTRIP_TOOL_FAILURE_CAP", "2")
        failing_call = ToolCall(id="wf", name="write_file", arguments={"path": "x.py"})
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 10)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        assert agent.state.tool_failure_cap == 2

        await agent.process_message("Do it")

        # Cap of 2 means the loop bails after 2 same-call failures.
        # That's at most 3 _execute_tool calls (the 3rd is the one
        # that trips the cap; the cap-check happens *after* each
        # turn's tool calls so the loop will bail before turn 4).
        assert agent._execute_tool.call_count <= 3

    @pytest.mark.asyncio
    async def test_invalid_env_var_falls_back_to_default(self, monkeypatch):
        """Garbage in ``CANTRIP_TOOL_FAILURE_CAP`` is ignored."""
        monkeypatch.setenv("CANTRIP_TOOL_FAILURE_CAP", "not-a-number")
        agent = CantripAgent(provider=FakeProvider())
        # 5 is the documented default.
        assert agent.state.tool_failure_cap == 5

    @pytest.mark.asyncio
    async def test_pre_cap_warning_injected_one_round_early(self):
        """Phase 107.3: one round before the cap, nudge the model to change tack."""
        failing_call = ToolCall(
            id="wf", name="write_file", arguments={"path": "x.py", "content": ""}
        )
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 30)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        chat_events: list = []
        agent.event_bus.subscribe(ui_events.EventType.CHAT_MESSAGE, chat_events.append)

        await agent.process_message("Do it")

        # Exactly one warning, injected as a SYSTEM message when the
        # streak reached cap - 1 (frontier providers don't collapse
        # history, so it stays in the working set).
        warnings = [
            m for m in agent.state.messages if m.role == Role.SYSTEM and "BLOCKED" in m.content
        ]
        assert len(warnings) == 1
        assert "write_file" in warnings[0].content
        # ...and it was mirrored to the chat UI as a system message.
        sys_chats = [
            e
            for e in chat_events
            if e.payload.get("role") == "system" and "write_file" in e.payload.get("content", "")
        ]
        assert len(sys_chats) == 1

    @pytest.mark.asyncio
    async def test_pre_cap_warning_skipped_when_cap_is_one(self, monkeypatch):
        """A cap of 1 leaves no room for a warning round — none is injected."""
        monkeypatch.setenv("CANTRIP_TOOL_FAILURE_CAP", "1")
        failing_call = ToolCall(id="wf", name="write_file", arguments={"path": "x.py"})
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 10)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        await agent.process_message("Do it")

        assert not [
            m for m in agent.state.messages if m.role == Role.SYSTEM and "BLOCKED" in m.content
        ]

    @pytest.mark.asyncio
    async def test_retry_streak_surfaces_status_badge(self):
        """Phase 107.4: a streak of 2+ publishes a 'tool retrying (n/cap)' label."""
        failing_call = ToolCall(id="wf", name="write_file", arguments={"path": "x.py"})
        provider = FakeProvider([Response(content="", tool_calls=[failing_call])] * 30)
        agent = CantripAgent(provider=provider)
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=False, output="", error="boom")
        )

        labels: list[str] = []
        agent.event_bus.subscribe(
            ui_events.EventType.STATUS_BAR_CHANGED,
            lambda e: labels.append(e.payload.get("task_label", "")),
        )

        await agent.process_message("Do it")

        retry_labels = [label for label in labels if "tool retrying" in label]
        assert retry_labels
        cap = agent.state.tool_failure_cap
        assert any(f"(2/{cap})" in label for label in retry_labels)
