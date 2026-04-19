"""Subagent tests: concurrency."""

from typing import Any

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    ExitState,
    Subagent,
)
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_context, _make_tool

# ===================================================================
# TestConcurrentToolExecution
# ===================================================================


class TestConcurrentToolExecution:
    """Tests that tool calls within a single round execute concurrently."""

    @pytest.mark.asyncio
    async def test_tools_run_concurrently(self) -> None:
        """Multiple tool calls in one round overlap in time via asyncio.gather()."""
        import asyncio
        import time

        # Each tool sleeps briefly; sequential would take ~0.3s total,
        # concurrent should finish in ~0.1s.
        sleep_duration = 0.1
        call_times: list[float] = []

        async def _slow_execute(**kwargs: Any) -> ToolResult:  # noqa: ARG001
            call_times.append(time.monotonic())
            await asyncio.sleep(sleep_duration)
            return ToolResult(success=True, output="ok")

        tool_a = _make_tool("read_file")
        tool_a.execute = _slow_execute  # type: ignore[method-assign]
        tool_b = _make_tool("write_file")
        tool_b.execute = _slow_execute  # type: ignore[method-assign]
        tool_c = _make_tool("grep")
        tool_c.execute = _slow_execute  # type: ignore[method-assign]

        task = AgentTask(id="t", title="Multi-tool", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={}),
                        ToolCall(id="tc2", name="write_file", arguments={}),
                        ToolCall(id="tc3", name="grep", arguments={}),
                    ],
                ),
                Response(content="All done.\n\n[EXIT: completed]"),
            ],
        )
        subagent = Subagent(ctx, tools=[tool_a, tool_b, tool_c], provider=provider)

        start = time.monotonic()
        result = await subagent.run()
        elapsed = time.monotonic() - start

        assert result.exit_state == ExitState.COMPLETED
        # All three calls started at roughly the same time.
        assert len(call_times) == 3
        assert max(call_times) - min(call_times) < sleep_duration * 0.5
        # Total wall time is closer to one sleep than three sequential sleeps.
        assert elapsed < sleep_duration * 2.0

    @pytest.mark.asyncio
    async def test_concurrent_results_preserve_order(self) -> None:
        """Results from concurrent tool calls are matched to the correct tool call IDs."""
        import asyncio

        async def _execute_a(**kwargs: Any) -> ToolResult:  # noqa: ARG001
            await asyncio.sleep(0.05)
            return ToolResult(success=True, output="result-a")

        async def _execute_b(**kwargs: Any) -> ToolResult:  # noqa: ARG001
            return ToolResult(success=True, output="result-b")

        tool_a = _make_tool("read_file")
        tool_a.execute = _execute_a  # type: ignore[method-assign]
        tool_b = _make_tool("write_file")
        tool_b.execute = _execute_b  # type: ignore[method-assign]

        task = AgentTask(id="t", title="Order check", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        # Capture the tool results message sent to the provider.
        captured_messages: list[Any] = []

        class CapturingProvider(FakeProvider):
            async def complete(
                self,
                messages: Any,
                tools: Any = None,
                temperature: float = 0.7,
                max_tokens: int | None = None,
                thinking_budget: int | None = None,  # noqa: ARG002
            ) -> Response:
                captured_messages.append(list(messages))
                return await super().complete(
                    messages,
                    tools,
                    temperature,
                    max_tokens,
                )

        provider = CapturingProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-a", name="read_file", arguments={}),
                        ToolCall(id="tc-b", name="write_file", arguments={}),
                    ],
                ),
                Response(content="Done.\n\n[EXIT: completed]"),
            ],
        )
        subagent = Subagent(ctx, tools=[tool_a, tool_b], provider=provider)

        await subagent.run()

        # The second call to complete() has the tool results message.
        tool_msg = captured_messages[1][-1]
        results = tool_msg.tool_results
        assert results[0].tool_call_id == "tc-a"
        assert results[0].content == "result-a"
        assert results[1].tool_call_id == "tc-b"
        assert results[1].content == "result-b"
