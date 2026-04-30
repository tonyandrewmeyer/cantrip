"""Executor lifecycle controller — start, stop, pause, resume, callbacks.

Held by :class:`CantripAgent` as ``self._executor_ctl`` and re-exposed
through thin delegators so the public surface (``executor_running`` /
``start_executor`` / ``stop_executor``) keeps working unchanged.  The
callback wiring that forwards subagent events to the shared event bus
lives here rather than in ``core.py``, keeping the god class focused
on message processing.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask
from cantrip.agent.tools import ToolResult
from cantrip.llm.base import Message, Role
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from collections.abc import Callable

    from cantrip.agent.queue import WorkQueue
    from cantrip.agent.state import AgentState
    from cantrip.agent.store import SessionStore
    from cantrip.agent.tools import Tool
    from cantrip.hooks import HookRunner
    from cantrip.llm.base import LLMProvider

log = logging.getLogger(__name__)


class ExecutorController:
    """Owns the background executor lifecycle and its event-bus callbacks.

    *publish_tool_invoked* and *publish_tool_invoked_pending* are callables
    provided by the agent to forward subagent tool calls to the chat
    surfaces.  *event_bus* is the shared UI event bus.
    """

    def __init__(
        self,
        *,
        state: AgentState,
        event_bus: ui_events.EventBus,
        publish_tool_invoked: Callable[..., None],
        publish_tool_invoked_pending: Callable[..., None],
    ) -> None:
        self._state = state
        self._event_bus = event_bus
        self._publish_tool_invoked = publish_tool_invoked
        self._publish_tool_invoked_pending = publish_tool_invoked_pending
        self._executor: BackgroundExecutor | None = None

    @property
    def running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor is not None and self._executor.running

    def pause(self) -> None:
        """Pause the background executor while handling a user message."""
        if self._executor and self._executor.running:
            self._executor.pause()

    def resume(self) -> None:
        """Resume the background executor after handling a user message."""
        if self._executor and self._executor.running:
            self._executor.resume()

    def start(
        self,
        *,
        queue: WorkQueue,
        tools: list[Tool],
        provider: LLMProvider,
        store: SessionStore | None,
        light_provider: LLMProvider | None,
        hook_runner: HookRunner,
        ensure_store: Callable[[], None],
        max_concurrency: int | None = None,
    ) -> None:
        """Create and start the background executor.

        Every task mutation is published to the shared ``event_bus`` so
        that both UIs receive updates.  *max_concurrency* controls how
        many subagent tasks run in parallel (default 3).
        """
        if self._executor is not None and self._executor.running:
            return
        ensure_store()

        def _notify_bus(task: AgentTask) -> None:
            self._event_bus.publish(ui_events.task_updated_from_task(task))

        queue._on_task_changed = _notify_bus

        # Phase 52.1: purge a task's step checkpoints on successful
        # completion so a long-running session doesn't leak rows.
        # Failed / blocked tasks keep their checkpoints so 52.3's
        # resume path can reuse them.  Honours
        # ``$CANTRIP_KEEP_CHECKPOINTS`` via
        # :meth:`CheckpointStore.on_task_done` for debugging.
        def _purge_task_checkpoints(task: AgentTask) -> None:
            if store is None:
                return
            from cantrip.agent.durability import CheckpointStore

            try:
                CheckpointStore(store).on_task_done(task.id)
            except sqlite3.Error:
                log.debug(
                    "Failed to purge step checkpoints for task %s",
                    task.id,
                    exc_info=True,
                )

        # Phase 75: forward subagent tool calls to the chat surfaces
        # via the shared event bus.  Mirrors the main-agent emission in
        # ``_publish_tool_invoked`` but tagged ``source="subagent"`` so
        # subscribers can tell where each call came from.
        def _forward_subagent_tool_invoked(
            tool_name: str,
            arguments: dict[str, Any],
            result: ToolResult,
            duration_ms: int,
            tool_call_id: str,
        ) -> None:
            self._publish_tool_invoked(
                tool_name,
                arguments,
                result,
                source="subagent",
                duration_ms=duration_ms,
                tool_call_id=tool_call_id,
            )

        # Phase 82: forward subagent "running now" events so the chat
        # renders a pending block before each subagent tool returns —
        # mirrors the main-agent pre-dispatch emission above.
        def _forward_subagent_tool_invoked_pending(
            tool_name: str,
            arguments: dict[str, Any],
            tool_call_id: str,
        ) -> None:
            self._publish_tool_invoked_pending(
                tool_name,
                arguments,
                source="subagent",
                tool_call_id=tool_call_id,
            )

        # Phase 55.3: forward goal-budget trips to both the transcript
        # (as a SYSTEM chat message) and the shared event bus so TUI
        # and Web show the stop in-band rather than leaving the user
        # to work out why the queue stalled.
        def _forward_budget_exceeded(task: AgentTask, reason: str) -> None:
            self._state.messages.append(Message(role=Role.SYSTEM, content=reason))
            self._event_bus.publish(ui_events.goal_budget_exceeded(task_id=task.id, reason=reason))
            self._event_bus.publish(ui_events.chat_message(role="system", content=reason))

        # Phase 80.3: same shape for per-goal rate-limit trips.  Fires
        # a ``POLICY_RATE_LIMITED`` event carrying count / cap / the
        # composed-policy-name so observability consumers can
        # distinguish rate-limit stops from goal-budget stops.
        def _forward_rate_limited(task: AgentTask, count: int, cap: int, policy_name: str) -> None:
            reason = (
                f"Policy rate limit exceeded: {count} tool calls "
                f"(cap: {cap}) under policy {policy_name!r}."
            )
            self._state.messages.append(Message(role=Role.SYSTEM, content=reason))
            self._event_bus.publish(
                ui_events.policy_rate_limited(
                    task_id=task.id,
                    tool_calls_made=count,
                    cap=cap,
                    policy_name=policy_name,
                )
            )
            self._event_bus.publish(ui_events.chat_message(role="system", content=reason))

        kwargs: dict[str, object] = {
            "queue": queue,
            "tools": tools,
            "provider": provider,
            "state": self._state,
            "store": store,
            "light_provider": light_provider,
            "hook_runner": hook_runner,
            "on_task_done": _purge_task_checkpoints,
            "on_tool_invoked": _forward_subagent_tool_invoked,
            "on_tool_invoked_pending": _forward_subagent_tool_invoked_pending,
            "on_budget_exceeded": _forward_budget_exceeded,
            "on_rate_limited": _forward_rate_limited,
        }
        if max_concurrency is not None:
            kwargs["max_concurrency"] = max_concurrency
        self._executor = BackgroundExecutor(**kwargs)
        # Phase 69.2: forward auto-approvals to the event bus so the
        # transcript and any UI surface can render the audit line.
        self._executor.permission_manager.set_on_auto_approve(
            self._forward_permission_auto_approved
        )
        # If the session started with --yolo already set on state,
        # push it onto the freshly-built manager so subagents pick it
        # up from the first dispatch.
        if self._state.yolo_mode:
            self._executor.set_yolo(True)
        self._executor.start()

    async def stop(self) -> None:
        """Stop the background executor if it is running."""
        if self._executor:
            await self._executor.stop()
            self._executor = None

    def set_yolo(self, enabled: bool) -> None:
        """Forward yolo-mode toggle to the executor's permission manager."""
        if self._executor:
            self._executor.set_yolo(enabled)

    def _forward_permission_auto_approved(self, request: object) -> None:
        """Phase 69.2: publish a ``permission_auto_approved`` UI event.

        Receives a :class:`PermissionAskRequest` from the executor's
        manager every time yolo mode turns an ``ask`` into an
        auto-approval.  Defensive attribute access so a malformed
        payload can't break the dispatch loop — worst case the event
        is dropped.
        """
        request_id = getattr(request, "request_id", None)
        tool_name = getattr(request, "tool_name", "")
        reason = getattr(request, "reason", "")
        command = getattr(request, "command", None)
        try:
            self._event_bus.publish(
                ui_events.permission_auto_approved(
                    tool_name=str(tool_name),
                    reason=str(reason),
                    request_id=request_id if isinstance(request_id, str) else None,
                    command=command if isinstance(command, str) else None,
                )
            )
        except (TypeError, ValueError, RuntimeError, AttributeError):
            log.debug("permission_auto_approved publish failed", exc_info=True)
