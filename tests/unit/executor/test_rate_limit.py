"""Executor tests: Phase 80.3 per-goal rate limit gate."""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.support.wait import wait_for_task_status
from tests.unit.executor.conftest import _make_tool


@pytest.fixture
def store(tmp_path: pathlib.Path) -> SessionStore:
    db = tmp_path / ".cantrip"
    s = SessionStore(db)
    s.open()
    s.save_session(AgentState(charm_name="x", charm_path=tmp_path))
    return s


def _install_rate_limit(tmp_path: pathlib.Path, cap: int) -> pathlib.Path:
    """Write a per-charm policy file that sets ``max_calls_per_request``.

    Returns the ``charm_path`` to hand to ``AgentState``.  Using a
    per-charm file (rather than the user config dir) keeps the test
    deterministic regardless of ``$HOME``.
    """
    (tmp_path / "cantrip.policies.yaml").write_text(
        f"name: test-rate-cap\nmax_calls_per_request: {cap}\n"
    )
    return tmp_path


class TestRateLimitCap:
    """Executor reads ``max_calls_per_request`` from the composed stack."""

    def test_no_policy_file_means_no_cap(self, tmp_path: pathlib.Path) -> None:
        state = AgentState(charm_path=tmp_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )
        assert executor._rate_limit_cap is None

    def test_per_charm_file_sets_cap(self, tmp_path: pathlib.Path) -> None:
        charm_path = _install_rate_limit(tmp_path, 50)
        state = AgentState(charm_path=charm_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )
        assert executor._rate_limit_cap == 50


class TestCounterIncrementsViaCallback:
    """The wrapped ``on_tool_invoked`` bumps the counter for non-MCP calls."""

    def _make(self, tmp_path: pathlib.Path, cap: int | None = None) -> BackgroundExecutor:
        charm_path = _install_rate_limit(tmp_path, cap) if cap is not None else tmp_path
        state = AgentState(charm_path=charm_path)
        return BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )

    def test_non_mcp_call_increments(self, tmp_path: pathlib.Path) -> None:
        executor = self._make(tmp_path, cap=5)
        assert executor._tool_calls_made == 0
        # ``_on_tool_invoked`` is the wrapped callback the subagent
        # would have called.
        executor._on_tool_invoked(
            "read_file", {}, ToolResult(success=True, output=""), 10, "call-1"
        )
        assert executor._tool_calls_made == 1

    def test_mcp_call_does_not_increment(self, tmp_path: pathlib.Path) -> None:
        executor = self._make(tmp_path, cap=5)
        executor._on_tool_invoked(
            "mcp__grafana__query",
            {},
            ToolResult(success=True, output=""),
            10,
            "call-1",
        )
        assert executor._tool_calls_made == 0

    def test_counter_bumped_even_without_cap(self, tmp_path: pathlib.Path) -> None:
        """No cap means no gate, but the counter still runs — lets
        future tooling surface "calls made so far" even before a cap
        is introduced."""
        executor = self._make(tmp_path, cap=None)
        executor._on_tool_invoked(
            "read_file", {}, ToolResult(success=True, output=""), 10, "call-1"
        )
        assert executor._tool_calls_made == 1

    def test_inner_callback_still_fires(self, tmp_path: pathlib.Path) -> None:
        """The user's original ``on_tool_invoked`` must still be called.

        Otherwise the rate-limit wrapper would accidentally swallow
        the UI event and TOOL_INVOKED would never reach the chat.
        """
        captured: list[tuple[str, int, str]] = []
        state = AgentState(charm_path=tmp_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            on_tool_invoked=lambda name, _args, _result, ms, tcid: captured.append(
                (name, ms, tcid)
            ),
        )
        executor._on_tool_invoked(
            "read_file", {}, ToolResult(success=True, output=""), 17, "call-a"
        )
        executor._on_tool_invoked(
            "mcp__grafana__query",
            {},
            ToolResult(success=True, output=""),
            22,
            "call-b",
        )
        assert captured == [
            ("read_file", 17, "call-a"),
            ("mcp__grafana__query", 22, "call-b"),
        ]


class TestRateLimitGate:
    """``_check_rate_limit`` trips when the counter hits the cap."""

    def test_gate_clear_below_cap(self, tmp_path: pathlib.Path) -> None:
        charm_path = _install_rate_limit(tmp_path, 5)
        state = AgentState(charm_path=charm_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )
        executor._tool_calls_made = 4
        assert executor._check_rate_limit() is None

    def test_gate_trips_at_cap(self, tmp_path: pathlib.Path) -> None:
        charm_path = _install_rate_limit(tmp_path, 5)
        state = AgentState(charm_path=charm_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )
        executor._tool_calls_made = 5
        trip = executor._check_rate_limit()
        assert trip == (5, 5)

    def test_gate_never_trips_without_cap(self, tmp_path: pathlib.Path) -> None:
        state = AgentState(charm_path=tmp_path)
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
        )
        executor._tool_calls_made = 1_000_000
        assert executor._check_rate_limit() is None


class TestRateLimitBlocksSpawn:
    """End-to-end: a tripped rate limit blocks the task and fires the callback."""

    @pytest.mark.asyncio
    async def test_rate_limited_task_blocks(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        charm_path = _install_rate_limit(tmp_path, 1)
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        state = AgentState(charm_path=charm_path)
        triggered: list[tuple[str, int, int, str]] = []

        executor = BackgroundExecutor(
            queue=queue,
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=store,
            on_rate_limited=lambda t, count, cap, policy: triggered.append(
                (t.id, count, cap, policy)
            ),
        )
        # Pre-load the counter so the very first spawn trips.
        executor._tool_calls_made = 2

        executor.start()
        try:
            await wait_for_task_status(task, TaskStatus.BLOCKED)
        finally:
            await executor.stop()

        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason is not None
        assert "rate limit" in task.blocked_reason.lower()
        assert len(triggered) == 1
        assert triggered[0][0] == "t1"
        assert triggered[0][1] == 2  # count
        assert triggered[0][2] == 1  # cap
        assert "test-rate-cap" in triggered[0][3]

    @pytest.mark.asyncio
    async def test_raising_counter_below_cap_runs_task(
        self, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        """Lowering the counter (e.g. after the operator clears state)
        lets a previously blocked task proceed."""
        charm_path = _install_rate_limit(tmp_path, 5)
        queue = WorkQueue()
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        state = AgentState(charm_path=charm_path)

        executor = BackgroundExecutor(
            queue=queue,
            tools=[_make_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=state,
            store=store,
        )
        executor._tool_calls_made = 5  # At cap.

        executor.start()
        try:
            await wait_for_task_status(task, TaskStatus.BLOCKED)
        except TimeoutError:
            await executor.stop()
            raise

        # Clear the counter (simulating operator-initiated "reset
        # the rate window" — the /budget --clear analogue for rate
        # limits is a future follow-up).  Also move the task back
        # to pending so the executor picks it up.
        executor._tool_calls_made = 0
        queue.set_pending(task.id)

        try:
            await wait_for_task_status(task, TaskStatus.DONE, timeout=5.0)
        finally:
            await executor.stop()

        assert task.status == TaskStatus.DONE
