"""Tests for :class:`ExecutorController`.

The controller is a thin lifecycle wrapper around
:class:`BackgroundExecutor`, but it owns several closures (subagent
tool-invoked forwarders, budget / rate-limit forwarders, checkpoint
purge) that are wired into the executor at ``start()`` time.  The
tests below patch out the real ``BackgroundExecutor``, capture the
kwargs the controller passes, and exercise each closure directly.
``_forward_permission_auto_approved`` is a regular method so it is
called directly.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.controllers.executor_controller import ExecutorController
from cantrip.agent.queue import AgentTask, TaskCategory, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.tools import ToolResult
from cantrip.llm.base import Role
from cantrip.ui import events as ui_events
from tests.conftest import FakeProvider


def _make_controller(
    state: AgentState | None = None,
) -> tuple[ExecutorController, ui_events.EventBus, MagicMock, MagicMock]:
    """Build an :class:`ExecutorController` with capturing callbacks."""
    bus = ui_events.EventBus()
    publish_tool_invoked = MagicMock()
    publish_tool_invoked_pending = MagicMock()
    ctl = ExecutorController(
        state=state or AgentState(),
        event_bus=bus,
        publish_tool_invoked=publish_tool_invoked,
        publish_tool_invoked_pending=publish_tool_invoked_pending,
    )
    return ctl, bus, publish_tool_invoked, publish_tool_invoked_pending


def _start_with_mock_executor(
    ctl: ExecutorController,
    *,
    store: object | None = None,
    max_concurrency: int | None = None,
) -> tuple[MagicMock, dict[str, Any]]:
    """Start *ctl* with a patched ``BackgroundExecutor`` and return the kwargs."""
    fake_exec = MagicMock()
    fake_exec.running = False
    with patch(
        "cantrip.agent.controllers.executor_controller.BackgroundExecutor",
        return_value=fake_exec,
    ) as cls:
        ctl.start(
            queue=WorkQueue(),
            tools=[],
            provider=FakeProvider(),
            store=store,  # type: ignore[arg-type]
            light_provider=None,
            hook_runner=MagicMock(),
            ensure_store=lambda: None,
            max_concurrency=max_concurrency,
        )
    return fake_exec, cls.call_args.kwargs


# ---------------------------------------------------------------------------
# Simple lifecycle pass-throughs (running / pause / resume / set_yolo)
# ---------------------------------------------------------------------------


class TestPassThroughs:
    """``running`` / ``pause`` / ``resume`` / ``set_yolo`` delegators."""

    def test_running_false_when_no_executor(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        assert ctl.running is False

    def test_running_true_when_executor_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.running = True
        ctl._executor = fake
        assert ctl.running is True

    def test_pause_forwards_when_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.running = True
        ctl._executor = fake
        ctl.pause()
        fake.pause.assert_called_once()

    def test_pause_noop_when_not_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.running = False
        ctl._executor = fake
        ctl.pause()
        fake.pause.assert_not_called()

    def test_pause_noop_when_no_executor(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        ctl.pause()  # must not raise

    def test_resume_forwards_when_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.running = True
        ctl._executor = fake
        ctl.resume()
        fake.resume.assert_called_once()

    def test_resume_noop_when_not_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.running = False
        ctl._executor = fake
        ctl.resume()
        fake.resume.assert_not_called()

    def test_set_yolo_forwards_when_executor_present(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        ctl._executor = fake
        ctl.set_yolo(True)
        fake.set_yolo.assert_called_once_with(True)

    def test_set_yolo_noop_without_executor(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        ctl.set_yolo(True)  # must not raise


# ---------------------------------------------------------------------------
# start() — early return, max_concurrency, yolo handoff, callback wiring
# ---------------------------------------------------------------------------


class TestStart:
    """``start()`` entry-point: idempotency, kwargs, yolo handoff."""

    def test_start_is_noop_when_already_running(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        existing = MagicMock()
        existing.running = True
        ctl._executor = existing
        with patch("cantrip.agent.controllers.executor_controller.BackgroundExecutor") as cls:
            ctl.start(
                queue=WorkQueue(),
                tools=[],
                provider=FakeProvider(),
                store=None,
                light_provider=None,
                hook_runner=MagicMock(),
                ensure_store=lambda: None,
            )
        cls.assert_not_called()

    def test_start_calls_ensure_store(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        ensure_called = MagicMock()
        with patch("cantrip.agent.controllers.executor_controller.BackgroundExecutor") as cls:
            cls.return_value.running = False
            ctl.start(
                queue=WorkQueue(),
                tools=[],
                provider=FakeProvider(),
                store=None,
                light_provider=None,
                hook_runner=MagicMock(),
                ensure_store=ensure_called,
            )
        ensure_called.assert_called_once()

    def test_start_threads_max_concurrency(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl, max_concurrency=7)
        assert kwargs["max_concurrency"] == 7

    def test_start_omits_max_concurrency_by_default(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl)
        assert "max_concurrency" not in kwargs

    def test_start_propagates_yolo_when_already_set(self) -> None:
        state = AgentState()
        state.yolo_mode = True
        ctl, _bus, _pti, _ptip = _make_controller(state=state)
        fake_exec, _kwargs = _start_with_mock_executor(ctl)
        fake_exec.set_yolo.assert_called_once_with(True)

    def test_start_does_not_set_yolo_when_off(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake_exec, _kwargs = _start_with_mock_executor(ctl)
        fake_exec.set_yolo.assert_not_called()

    def test_start_registers_auto_approve_callback(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake_exec, _kwargs = _start_with_mock_executor(ctl)
        fake_exec.permission_manager.set_on_auto_approve.assert_called_once_with(
            ctl._forward_permission_auto_approved
        )

    def test_start_invokes_executor_start(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        fake_exec, _kwargs = _start_with_mock_executor(ctl)
        fake_exec.start.assert_called_once()

    def test_queue_callback_publishes_task_updated(self) -> None:
        ctl, bus, _pti, _ptip = _make_controller()
        captured: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.TASK_UPDATED, captured.append)

        queue = WorkQueue()
        fake_exec = MagicMock()
        fake_exec.running = False
        with patch(
            "cantrip.agent.controllers.executor_controller.BackgroundExecutor",
            return_value=fake_exec,
        ):
            ctl.start(
                queue=queue,
                tools=[],
                provider=FakeProvider(),
                store=None,
                light_provider=None,
                hook_runner=MagicMock(),
                ensure_store=lambda: None,
            )

        task = AgentTask(id="t9", title="x", category=TaskCategory.BUILD)
        queue._on_task_changed(task)
        assert len(captured) == 1
        assert captured[0].payload["id"] == "t9"


# ---------------------------------------------------------------------------
# Closures wired into start(): on_task_done, tool_invoked forwarders,
# budget_exceeded, rate_limited.
# ---------------------------------------------------------------------------


class TestPurgeTaskCheckpoints:
    """``on_task_done`` closure that purges step checkpoints."""

    def test_no_store_skips_purge(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl, store=None)
        with patch("cantrip.agent.runtime.durability.CheckpointStore") as cls:
            kwargs["on_task_done"](AgentTask(id="t1", title="x", category=TaskCategory.BUILD))
        cls.assert_not_called()

    def test_calls_checkpoint_store_when_store_present(self) -> None:
        store = MagicMock()
        ctl, _bus, _pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl, store=store)
        with patch("cantrip.agent.runtime.durability.CheckpointStore") as cls:
            instance = cls.return_value
            kwargs["on_task_done"](AgentTask(id="abc", title="x", category=TaskCategory.BUILD))
        cls.assert_called_once_with(store)
        instance.on_task_done.assert_called_once_with("abc")

    def test_swallows_sqlite_errors(self) -> None:
        store = MagicMock()
        ctl, _bus, _pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl, store=store)
        with patch("cantrip.agent.runtime.durability.CheckpointStore") as cls:
            cls.return_value.on_task_done.side_effect = sqlite3.Error("db gone")
            # Must not raise.
            kwargs["on_task_done"](AgentTask(id="abc", title="x", category=TaskCategory.BUILD))


class TestSubagentToolForwarders:
    """``on_tool_invoked`` and ``on_tool_invoked_pending`` closures."""

    def test_tool_invoked_tags_source_and_forwards_kwargs(self) -> None:
        ctl, _bus, pti, _ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl)
        result = ToolResult(success=True, output="ok")
        kwargs["on_tool_invoked"](
            "read_file",
            {"path": "x"},
            result,
            123,
            "call-1",
        )
        pti.assert_called_once_with(
            "read_file",
            {"path": "x"},
            result,
            source="subagent",
            duration_ms=123,
            tool_call_id="call-1",
        )

    def test_tool_invoked_pending_tags_source_and_forwards(self) -> None:
        ctl, _bus, _pti, ptip = _make_controller()
        _exec, kwargs = _start_with_mock_executor(ctl)
        kwargs["on_tool_invoked_pending"](
            "edit_file",
            {"path": "y"},
            "call-2",
        )
        ptip.assert_called_once_with(
            "edit_file",
            {"path": "y"},
            source="subagent",
            tool_call_id="call-2",
        )


class TestBudgetAndRateLimitForwarders:
    """``on_budget_exceeded`` and ``on_rate_limited`` closures."""

    def test_budget_exceeded_appends_message_and_publishes_two_events(self) -> None:
        state = AgentState()
        ctl, bus, _pti, _ptip = _make_controller(state=state)
        budget_events: list[ui_events.Event] = []
        chat_events: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.GOAL_BUDGET_EXCEEDED, budget_events.append)
        bus.subscribe(ui_events.EventType.CHAT_MESSAGE, chat_events.append)

        _exec, kwargs = _start_with_mock_executor(ctl)
        task = AgentTask(id="t-b", title="x", category=TaskCategory.BUILD)
        kwargs["on_budget_exceeded"](task, "iteration cap reached")

        assert len(state.messages) == 1
        assert state.messages[0].role is Role.SYSTEM
        assert state.messages[0].content == "iteration cap reached"
        assert len(budget_events) == 1
        assert budget_events[0].payload == {
            "task_id": "t-b",
            "reason": "iteration cap reached",
        }
        assert len(chat_events) == 1
        assert chat_events[0].payload["role"] == "system"
        assert chat_events[0].payload["content"] == "iteration cap reached"

    def test_rate_limited_appends_message_and_publishes_two_events(self) -> None:
        state = AgentState()
        ctl, bus, _pti, _ptip = _make_controller(state=state)
        rate_events: list[ui_events.Event] = []
        chat_events: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.POLICY_RATE_LIMITED, rate_events.append)
        bus.subscribe(ui_events.EventType.CHAT_MESSAGE, chat_events.append)

        _exec, kwargs = _start_with_mock_executor(ctl)
        task = AgentTask(id="t-r", title="x", category=TaskCategory.BUILD)
        kwargs["on_rate_limited"](task, 12, 10, "default")

        assert len(state.messages) == 1
        assert state.messages[0].role is Role.SYSTEM
        assert "12 tool calls" in state.messages[0].content
        assert "cap: 10" in state.messages[0].content
        assert "'default'" in state.messages[0].content
        assert len(rate_events) == 1
        assert rate_events[0].payload == {
            "task_id": "t-r",
            "tool_calls_made": 12,
            "cap": 10,
            "policy_name": "default",
        }
        assert len(chat_events) == 1
        assert chat_events[0].payload["role"] == "system"


# ---------------------------------------------------------------------------
# stop() — async path
# ---------------------------------------------------------------------------


class TestStop:
    """``stop()`` clears the executor reference."""

    @pytest.mark.asyncio
    async def test_stop_awaits_executor_and_clears(self) -> None:
        from unittest.mock import AsyncMock

        ctl, _bus, _pti, _ptip = _make_controller()
        fake = MagicMock()
        fake.stop = AsyncMock()
        ctl._executor = fake
        await ctl.stop()
        fake.stop.assert_awaited_once()
        assert ctl._executor is None

    @pytest.mark.asyncio
    async def test_stop_noop_without_executor(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        await ctl.stop()  # must not raise
        assert ctl._executor is None


# ---------------------------------------------------------------------------
# _forward_permission_auto_approved
# ---------------------------------------------------------------------------


class _Request:
    """Minimal stand-in for ``PermissionAskRequest``."""

    def __init__(
        self,
        *,
        request_id: str | None = "req-1",
        tool_name: str = "shell",
        reason: str = "yolo bypass",
        command: str | None = "ls",
    ) -> None:
        self.request_id = request_id
        self.tool_name = tool_name
        self.reason = reason
        self.command = command


class TestForwardPermissionAutoApproved:
    """``_forward_permission_auto_approved`` builds the PA event safely."""

    def test_publishes_well_formed_request(self) -> None:
        ctl, bus, _pti, _ptip = _make_controller()
        captured: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.PERMISSION_AUTO_APPROVED, captured.append)

        ctl._forward_permission_auto_approved(_Request())

        assert len(captured) == 1
        payload = captured[0].payload
        assert payload["tool_name"] == "shell"
        assert payload["reason"] == "yolo bypass"
        assert payload["request_id"] == "req-1"
        assert payload["command"] == "ls"

    def test_drops_non_string_request_id_and_command(self) -> None:
        ctl, bus, _pti, _ptip = _make_controller()
        captured: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.PERMISSION_AUTO_APPROVED, captured.append)

        # ``request_id`` and ``command`` are intentionally non-strings; the
        # forwarder coerces both to ``None`` rather than crashing on the way
        # to the event bus.
        ctl._forward_permission_auto_approved(
            _Request(request_id=42, command=object())  # type: ignore[arg-type]
        )

        assert len(captured) == 1
        payload = captured[0].payload
        assert payload["request_id"] is None
        assert payload["command"] is None

    def test_handles_missing_attributes(self) -> None:
        ctl, bus, _pti, _ptip = _make_controller()
        captured: list[ui_events.Event] = []
        bus.subscribe(ui_events.EventType.PERMISSION_AUTO_APPROVED, captured.append)

        # ``object()`` has no ``tool_name`` / ``reason`` etc.; defensive
        # ``getattr`` defaults keep the publish call alive.
        ctl._forward_permission_auto_approved(object())

        assert len(captured) == 1
        payload = captured[0].payload
        assert payload["tool_name"] == ""
        assert payload["reason"] == ""
        assert payload["request_id"] is None
        assert payload["command"] is None

    def test_swallows_publish_errors(self) -> None:
        ctl, _bus, _pti, _ptip = _make_controller()
        # A broken bus that raises is the realistic failure mode the
        # ``except`` block exists for.
        ctl._event_bus = MagicMock()
        ctl._event_bus.publish.side_effect = RuntimeError("bus closed")
        # Must not raise.
        ctl._forward_permission_auto_approved(_Request())
