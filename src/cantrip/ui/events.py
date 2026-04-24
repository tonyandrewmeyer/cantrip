"""Async publish/subscribe event bus for UI updates.

Both the Textual TUI and the aiohttp web UI subscribe to a single
``EventBus`` instance so that agent-layer code only needs to publish
once and every consumer receives the update.
"""

import asyncio
import contextlib
import enum
import json
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class EventType(enum.StrEnum):
    """All event types emitted by the agent layer."""

    TASK_UPDATED = "task_updated"
    TASKS_SNAPSHOT = "tasks_snapshot"
    CHAT_MESSAGE = "chat_message"
    THINKING_CHANGED = "thinking_changed"
    JUJU_STATUS_CHANGED = "juju_status_changed"
    WATCHER_EVENT = "watcher_event"
    STATUS_BAR_CHANGED = "status_bar_changed"
    PREFLIGHT_UPDATED = "preflight_updated"
    MEMORY_WRITTEN = "memory_written"
    MEMORY_RECALLED = "memory_recalled"
    MCP_ELICITATION_REQUEST = "mcp_elicitation_request"
    TOOL_INVOKED = "tool_invoked"


@dataclass(frozen=True)
class Event:
    """An immutable, JSON-serialisable UI event.

    The *payload* must contain only JSON-serialisable values.  Factory
    functions below enforce this by building payloads from primitive types.
    """

    type: EventType
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialise for WebSocket transport."""
        return json.dumps(
            {"type": self.type.value, "data": self.payload, "timestamp": self.timestamp}
        )


# Subscriber callback — may be sync or async.
Subscriber = Callable[["Event"], None] | Callable[["Event"], Coroutine[Any, Any, None]]


class EventBus:
    """Async publish/subscribe bus for UI events.

    Thread-safe publishing: ``publish()`` can be called from any thread.
    When a bound event loop exists and the caller is on a different thread,
    delivery is scheduled via ``call_soon_threadsafe``.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[Subscriber]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to an event loop for cross-thread delivery."""
        self._loop = loop

    def subscribe(
        self,
        event_type: EventType | None,
        callback: Subscriber,
    ) -> None:
        """Register *callback* for events of *event_type*.

        Pass ``None`` as the event type to receive all events (wildcard).
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(
        self,
        event_type: EventType | None,
        callback: Subscriber,
    ) -> None:
        """Remove a previously registered subscription."""
        subs = self._subscribers.get(event_type, [])
        with contextlib.suppress(ValueError):
            subs.remove(callback)

    def publish(self, event: Event) -> None:
        """Publish *event* to all matching subscribers.

        If a bound event loop exists and the caller is on a different
        thread, delivery is scheduled via ``call_soon_threadsafe``.
        Otherwise delivery happens synchronously.
        """
        if self._loop is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not self._loop:
                self._loop.call_soon_threadsafe(self._deliver, event)
                return
        self._deliver(event)

    def _deliver(self, event: Event) -> None:
        """Invoke subscribers for the event's type and wildcard."""
        for sub_list in (
            self._subscribers.get(event.type, []),
            self._subscribers.get(None, []),
        ):
            for callback in list(sub_list):
                try:
                    result = callback(event)
                    if asyncio.iscoroutine(result):
                        asyncio.ensure_future(result)
                except (  # noqa: PERF203
                    TypeError,
                    AttributeError,
                    KeyError,
                    ValueError,
                    RuntimeError,
                    OSError,
                ):
                    log.exception("Error in event subscriber for %s", event.type)


# ---------------------------------------------------------------------------
# Factory functions — build Event instances with validated payloads.
# ---------------------------------------------------------------------------


def task_updated(
    *,
    task_id: str,
    title: str,
    status: str,
    category: str,
    description: str = "",
    result: str | None = None,
    blocked_reason: str | None = None,
    worktree_path: str | None = None,
    subagent_phase: str = "",
    subagent_started_at: str | None = None,
) -> Event:
    """Build a ``TASK_UPDATED`` event."""
    return Event(
        type=EventType.TASK_UPDATED,
        payload={
            "id": task_id,
            "title": title,
            "status": status,
            "category": category,
            "description": description,
            "result": result,
            "blocked_reason": blocked_reason,
            "worktree_path": worktree_path,
            "subagent_phase": subagent_phase,
            "subagent_started_at": subagent_started_at,
        },
    )


def task_updated_from_task(task: Any) -> Event:
    """Build a ``TASK_UPDATED`` event from an ``AgentTask`` object.

    Accepts ``Any`` to avoid importing ``AgentTask`` (which lives in
    the agent layer) and keeping the dependency direction clean.
    """
    started = getattr(task, "subagent_started_at", None)
    return task_updated(
        task_id=task.id,
        title=task.title,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        category=task.category.value if hasattr(task.category, "value") else str(task.category),
        description=task.description,
        result=task.result,
        blocked_reason=task.blocked_reason,
        worktree_path=getattr(task, "worktree_path", None),
        subagent_phase=getattr(task, "subagent_phase", "") or "",
        subagent_started_at=started.isoformat() if started is not None else None,
    )


def tasks_snapshot(tasks: list[dict[str, Any]]) -> Event:
    """Build a ``TASKS_SNAPSHOT`` event with the full task list."""
    return Event(type=EventType.TASKS_SNAPSHOT, payload={"tasks": tasks})


def chat_message(*, role: str, content: str) -> Event:
    """Build a ``CHAT_MESSAGE`` event."""
    return Event(
        type=EventType.CHAT_MESSAGE,
        payload={"role": role, "content": content},
    )


def thinking_changed(*, active: bool) -> Event:
    """Build a ``THINKING_CHANGED`` event."""
    return Event(
        type=EventType.THINKING_CHANGED,
        payload={"active": active},
    )


def juju_status_changed(*, status_data: dict[str, Any]) -> Event:
    """Build a ``JUJU_STATUS_CHANGED`` event."""
    return Event(
        type=EventType.JUJU_STATUS_CHANGED,
        payload=status_data,
    )


def watcher_event(
    *,
    source: str,
    category: str,
    summary: str,
    detail: str = "",
    app: str = "",
    unit: str = "",
) -> Event:
    """Build a ``WATCHER_EVENT`` event."""
    return Event(
        type=EventType.WATCHER_EVENT,
        payload={
            "source": source,
            "category": category,
            "summary": summary,
            "detail": detail,
            "app": app,
            "unit": unit,
        },
    )


def status_bar_changed(**fields: str) -> Event:
    """Build a ``STATUS_BAR_CHANGED`` event.

    Accepts any combination of ``task_label``, ``cos_health``,
    ``test_summary``, and ``watcher_status``.
    """
    return Event(type=EventType.STATUS_BAR_CHANGED, payload=fields)


def preflight_updated(
    *,
    group_index: int,
    item_index: int,
    status: str,
) -> Event:
    """Build a ``PREFLIGHT_UPDATED`` event."""
    return Event(
        type=EventType.PREFLIGHT_UPDATED,
        payload={
            "group_index": group_index,
            "item_index": item_index,
            "status": status,
        },
    )


def memory_written(
    *,
    title: str,
    scope: str,
    kind: str,
    source: str,
    reasoning: str = "",
) -> Event:
    """Build a ``MEMORY_WRITTEN`` event.

    Emitted when the auto-writer persists a memory or when a memory tool
    creates one — UIs render this as an inline "Wrote memory: …" notice.
    """
    return Event(
        type=EventType.MEMORY_WRITTEN,
        payload={
            "title": title,
            "scope": scope,
            "kind": kind,
            "source": source,
            "reasoning": reasoning,
        },
    )


def memory_recalled(
    *,
    title: str,
    scope: str,
    kind: str,
) -> Event:
    """Build a ``MEMORY_RECALLED`` event.

    Emitted when an agent or tool reads a memory by title — UIs render
    this as an inline "Recalled memory: …" notice so users see what
    durable context the agent is leaning on.
    """
    return Event(
        type=EventType.MEMORY_RECALLED,
        payload={"title": title, "scope": scope, "kind": kind},
    )


def tool_invoked(
    *,
    tool_name: str,
    caption: str,
    success: bool,
    duration_ms: int | None = None,
    source: str = "main",
) -> Event:
    """Build a ``TOOL_INVOKED`` event.

    Emitted from every tool-call boundary (main-agent synchronous
    loop, main-agent streaming loop, subagent gather path) so the
    chat surfaces can render a compact "the agent just did X" block
    between messages.  ``source`` is one of ``main`` / ``main-stream``
    / ``subagent`` so subscribers that care about context (a test
    harness recording only main-agent calls, say) can filter.
    ``duration_ms`` is optional — ``None`` means "not measured" rather
    than "zero".
    """
    return Event(
        type=EventType.TOOL_INVOKED,
        payload={
            "tool_name": tool_name,
            "caption": caption,
            "success": success,
            "duration_ms": duration_ms,
            "source": source,
        },
    )


def mcp_elicitation_request(
    *,
    request_id: str,
    server_name: str,
    mode: str,
    message: str,
    requested_schema: dict[str, Any] | None = None,
    url: str | None = None,
) -> Event:
    """Build a ``MCP_ELICITATION_REQUEST`` event.

    Emitted when an MCP server asks the user for structured input
    mid-tool-call.  UIs render the prompt and call
    ``agent.complete_elicitation(request_id, action, content)`` once
    the user has answered.
    """
    return Event(
        type=EventType.MCP_ELICITATION_REQUEST,
        payload={
            "request_id": request_id,
            "server_name": server_name,
            "mode": mode,
            "message": message,
            "requested_schema": requested_schema,
            "url": url,
        },
    )
