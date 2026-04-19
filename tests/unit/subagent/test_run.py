"""Subagent tests: run."""

import datetime
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    MAX_BUILD_ROUNDS,
    MAX_SUBAGENT_ROUNDS,
    ExitState,
    Subagent,
)
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import ProviderRateLimitError, Response, ToolCall
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_context, _make_tool

# ===================================================================
# TestSubagentRun
# ===================================================================


class TestSubagentRun:
    """Tests for Subagent.run() — the tool-call loop."""

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_content(self) -> None:
        provider = FakeProvider(responses=[Response(content="Task complete.")])
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        result = await subagent.run()

        assert result.text == "Task complete."

    @pytest.mark.asyncio
    async def test_one_tool_call_round(self) -> None:
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Read", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"}),
                    ],
                ),
                Response(content="Done reading."),
            ],
        )
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        result = await subagent.run()

        assert result.text == "Done reading."
        tool.execute.assert_called_once_with(path="f.py")

    @pytest.mark.asyncio
    async def test_max_rounds_stops_loop(self) -> None:
        """When the LLM keeps requesting tools, the loop stops after MAX_SUBAGENT_ROUNDS."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Loop", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        # Every response has tool calls — the loop should cap out.
        responses = [
            Response(
                content=f"round {i}",
                tool_calls=[
                    ToolCall(id=f"tc{i}", name="read_file", arguments={}),
                ],
            )
            for i in range(MAX_SUBAGENT_ROUNDS + 5)
        ]
        provider = FakeProvider(responses=responses)
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        await subagent.run()

        # The last response consumed is at round MAX_SUBAGENT_ROUNDS (0-indexed: +1 initial).
        assert provider._call_count == MAX_SUBAGENT_ROUNDS + 1

    @pytest.mark.asyncio
    async def test_uses_correct_temperature(self) -> None:
        """Verify the subagent passes temperature=0.5 to the provider."""
        recorded_temps: list[float] = []

        class RecordingProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                recorded_temps.append(temperature)
                return Response(content="done")

        provider = RecordingProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        await subagent.run()

        assert recorded_temps == [0.5]

    @pytest.mark.asyncio
    async def test_research_task_uses_light_provider(self) -> None:
        primary = FakeProvider(responses=[Response(content="primary")])
        light = FakeProvider(responses=[Response(content="light")])
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)

        subagent = Subagent(ctx, tools=[], provider=primary, light_provider=light)
        result = await subagent.run()

        assert result.text == "light"


# ===================================================================
# TestSubagentRetry
# ===================================================================


class TestSubagentRetry:
    """Tests for rate-limit retry behaviour."""

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self) -> None:
        call_count = 0

        class FlakeyProvider(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ProviderRateLimitError("rate limited")
                return Response(content="recovered")

        provider = FlakeyProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        # Patch asyncio.sleep to avoid actual delays.
        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            result = await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert result.text == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises(self) -> None:
        class AlwaysRateLimited(FakeProvider):
            async def complete(
                self,
                messages,
                tools=None,
                temperature=0.7,
                max_tokens=None,
                thinking_budget=None,  # noqa: ARG002
            ):
                raise ProviderRateLimitError("rate limited")

        provider = AlwaysRateLimited()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            with pytest.raises(ProviderRateLimitError):
                await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]


# ===================================================================
# TestSubagentToolExecution
# ===================================================================


class TestSubagentToolExecution:
    """Tests for tool execution error handling within the subagent."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        """Calling a tool not in the tool map returns an error ToolResult."""
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="nonexistent_tool", arguments={}),
                    ],
                ),
                Response(content="Handled."),
            ],
        )
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        result = await subagent.run()

        assert result.text == "Handled."

    @pytest.mark.asyncio
    async def test_type_error_returns_error_result(self) -> None:
        """A TypeError during tool execution is caught and returned as an error."""
        bad_tool = _make_tool("read_file")
        bad_tool.execute = AsyncMock(  # type: ignore[method-assign]
            side_effect=TypeError("missing required argument"),
        )

        task = AgentTask(id="t", title="Read", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={}),
                    ],
                ),
                Response(content="Error handled."),
            ],
        )
        subagent = Subagent(ctx, tools=[bad_tool], provider=provider)

        result = await subagent.run()

        assert result.text == "Error handled."


# ===================================================================
# TestMaxRoundsParameter
# ===================================================================


class TestMaxRoundsParameter:
    """Tests for the configurable max_rounds parameter."""

    @pytest.mark.asyncio
    async def test_custom_max_rounds(self) -> None:
        """Subagent respects a custom max_rounds value."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Loop", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        custom_max = 4
        responses = [
            Response(
                content=f"round {i}",
                tool_calls=[
                    ToolCall(id=f"tc{i}", name="read_file", arguments={}),
                ],
            )
            for i in range(custom_max + 5)
        ]
        provider = FakeProvider(responses=responses)
        subagent = Subagent(ctx, tools=[tool], provider=provider, max_rounds=custom_max)

        await subagent.run()

        # 1 initial call + custom_max rounds of tool-call loops.
        assert provider._call_count == custom_max + 1

    @pytest.mark.asyncio
    async def test_default_max_rounds(self) -> None:
        """Default max_rounds equals MAX_SUBAGENT_ROUNDS."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Loop", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        responses = [
            Response(
                content=f"round {i}",
                tool_calls=[
                    ToolCall(id=f"tc{i}", name="read_file", arguments={}),
                ],
            )
            for i in range(MAX_SUBAGENT_ROUNDS + 5)
        ]
        provider = FakeProvider(responses=responses)
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        await subagent.run()

        assert provider._call_count == MAX_SUBAGENT_ROUNDS + 1

    def test_build_rounds_greater_than_default(self) -> None:
        """MAX_BUILD_ROUNDS is larger than the default MAX_SUBAGENT_ROUNDS."""
        assert MAX_BUILD_ROUNDS > MAX_SUBAGENT_ROUNDS
        assert MAX_BUILD_ROUNDS == 12

    @pytest.mark.asyncio
    async def test_truncation_during_run(self) -> None:
        """Messages are truncated during the run loop when context is tight."""
        tool = _make_tool("read_file", ToolResult(success=True, output="x" * 5000))
        task = AgentTask(id="t", title="Build", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        # 3 rounds of tool calls then a final response.
        responses = [
            Response(
                content=f"round {i}",
                tool_calls=[
                    ToolCall(id=f"tc{i}", name="read_file", arguments={}),
                ],
            )
            for i in range(3)
        ]
        responses.append(Response(content="Done.\n\n[EXIT: completed]"))

        # Small context window to trigger truncation.
        provider = FakeProvider(responses=responses, context_window_tokens=2000)
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        result = await subagent.run()

        assert result.exit_state == ExitState.COMPLETED


# ===================================================================
# TestSubagentPhaseReporting
# ===================================================================


class TestSubagentPhaseReporting:
    """The subagent advertises its phase to subscribers for the TUI."""

    @pytest.mark.asyncio
    async def test_phase_sequence_during_run(self) -> None:
        """Phase moves thinking → running: <tools> → thinking → "" on exit."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Phase run", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="tc1", name="read_file", arguments={})],
                ),
                Response(content="All done.\n\n[EXIT: completed]"),
            ],
        )

        phases: list[str] = []

        def capture(changed_task: AgentTask) -> None:
            phases.append(changed_task.subagent_phase)

        subagent = Subagent(ctx, tools=[tool], provider=provider, on_phase_change=capture)
        await subagent.run()

        # First phase is "thinking", then "running: read_file" during tool
        # execution, then back to "thinking" before the follow-up LLM call,
        # and finally cleared when ``run`` completes.
        assert phases[0] == "thinking"
        assert any(p.startswith("running:") and "read_file" in p for p in phases)
        assert phases[-1] == ""

    @pytest.mark.asyncio
    async def test_started_at_set_and_cleared(self) -> None:
        """``subagent_started_at`` is set during the run and cleared on exit."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Time run", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        # The callback observes the started_at stamp *during* the run, since
        # the finally-block clears it before returning to the caller.
        snapshots: list[datetime.datetime | None] = []

        def capture(changed_task: AgentTask) -> None:
            snapshots.append(changed_task.subagent_started_at)

        provider = FakeProvider(responses=[Response(content="Fine.\n\n[EXIT: completed]")])
        subagent = Subagent(ctx, tools=[tool], provider=provider, on_phase_change=capture)
        await subagent.run()

        # At least one in-flight notification had a non-None start time.
        assert any(s is not None for s in snapshots)
        # After the run completes the field is cleared.
        assert task.subagent_started_at is None
        assert task.subagent_phase == ""

    def test_tool_phase_label_truncates_long_tool_lists(self) -> None:
        """More than 3 tool calls collapse into a "(+N)" tail."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Label", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)
        subagent = Subagent(
            ctx, tools=[tool], provider=FakeProvider(responses=[Response(content="x")])
        )

        label = subagent._tool_phase_label(["a", "b", "c", "d", "e"])
        assert "a, b, c" in label
        assert "(+2)" in label
