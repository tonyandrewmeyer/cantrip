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
        on_cache_usage: Callable[[int, int], None] | None = None,
    ) -> None:
        self._state = state
        self._event_bus = event_bus
        self._publish_tool_invoked = publish_tool_invoked
        self._publish_tool_invoked_pending = publish_tool_invoked_pending
        # Forwarded to the executor so subagent prompt-cache tokens reach
        # the agent's session-level accumulators (see ``_record_usage``).
        self._on_cache_usage = on_cache_usage
        self._executor: BackgroundExecutor | None = None
        # Phase 99.1: ``/pause`` and ``/resume`` set this flag so the
        # transient pause/resume around each chat turn doesn't accidentally
        # un-pause an autonomous loop the user explicitly stopped.
        self._user_paused = False

    @property
    def running(self) -> bool:
        """Whether the background executor is currently running."""
        return self._executor is not None and self._executor.running

    @property
    def user_paused(self) -> bool:
        """Whether the user has paused the autonomous loop via ``/pause``."""
        return self._user_paused

    def pause(self) -> None:
        """Pause the background executor while handling a user message."""
        if self._executor and self._executor.running:
            self._executor.pause()

    def resume(self) -> None:
        """Resume the background executor after handling a user message.

        Skips when the user has paused the loop via ``/pause`` so that
        typing a chat message doesn't silently restart autonomous work
        the user explicitly stopped.
        """
        if self._user_paused:
            return
        if self._executor and self._executor.running:
            self._executor.resume()

    def user_pause(self) -> bool:
        """Phase 99.1: pause the autonomous loop on user request.

        Sticky across chat turns — unlike :meth:`pause`, the conversation
        loop's transient :meth:`resume` is a no-op while this flag is set.
        Returns ``True`` when the call changed state, ``False`` when the
        loop was already user-paused.
        """
        if self._user_paused:
            return False
        self._user_paused = True
        if self._executor and self._executor.running:
            self._executor.pause()
        return True

    def user_resume(self) -> bool:
        """Phase 99.1: resume the autonomous loop on user request.

        Returns ``True`` when the call changed state, ``False`` when the
        loop was not user-paused.
        """
        if not self._user_paused:
            return False
        self._user_paused = False
        if self._executor and self._executor.running:
            self._executor.resume()
        return True

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
            # Phase 99.4: keep the lifecycle badge in sync with queue
            # transitions.  A task moving to BLOCKED with a budget
            # reason flips the projection to ``budget-limited``; a
            # queue draining empty flips it to ``done``.  The Web UI
            # pulls this off the same ``status_bar_changed`` event the
            # TUI already listens to.
            from cantrip.agent.lifecycle import lifecycle_label

            label = lifecycle_label(
                user_paused=self._user_paused,
                tasks=queue.all_tasks(),
            )
            self._event_bus.publish(ui_events.status_bar_changed(loop_state=label))

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
            "on_cache_usage": self._on_cache_usage,
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
        # Phase 99.1: honour a pre-existing ``/pause`` if one fired
        # before the executor came up — ``start()`` resets ``_paused``
        # to ``False`` so we re-apply the user-pause here.
        if self._user_paused:
            self._executor.pause()

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
