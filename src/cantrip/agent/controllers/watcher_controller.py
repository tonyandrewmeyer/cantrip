"""Watcher lifecycle controller — start, stop, route, process.

Held by :class:`CantripAgent` as ``self._watcher_ctl`` and re-exposed
through thin delegators so the public surface (``watcher_running`` /
``start_watcher`` / ``stop_watcher`` / ``route_watcher_event`` /
``process_watcher_event``) keeps working unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from cantrip.agent.autodeploy import task_for_watcher_event
from cantrip.agent.tools.planning import (
    detect_cos_juju_model,
    detect_current_juju_model,
    juju_model_substrate,
)
from cantrip.agent.watcher.watcher import EventWatcher, WatcherConfig, WatcherEvent
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.agent.queue import AgentTask, WorkQueue
    from cantrip.agent.state import AgentState
    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)


class WatcherController:
    """Owns the event-watcher lifecycle and event routing.

    *ensure_store* is invoked before recording watcher events so the
    session store is initialised.  *get_store* returns the current store
    (may be ``None``).
    """

    def __init__(
        self,
        *,
        state: AgentState,
        event_bus: ui_events.EventBus,
        work_queue: WorkQueue,
        ensure_store: Callable[[], None],
        get_store: Callable[[], SessionStore | None],
    ) -> None:
        self._state = state
        self._event_bus = event_bus
        self._work_queue = work_queue
        self._ensure_store = ensure_store
        self._get_store = get_store
        self._watcher: EventWatcher | None = None

    @property
    def running(self) -> bool:
        """Whether the event watcher is currently running."""
        return self._watcher is not None and self._watcher.running

    @property
    def latest_status(self) -> object | None:
        """Most recent dev-model Juju status, or ``None``."""
        if self._watcher is None:
            return None
        return self._watcher.latest_status

    @property
    def latest_cos_status(self) -> object | None:
        """Most recent COS-model Juju status, or ``None``."""
        if self._watcher is None:
            return None
        return self._watcher.latest_cos_status

    def start(
        self,
        config: WatcherConfig | None = None,
        on_event: Callable | None = None,
    ) -> bool:
        """Create and start the event watcher.

        If ``state.dev_model`` is not set, falls back to the currently
        active Juju model (from ``juju models``), so the panes populate
        immediately when the user already has a model.  Returns ``False``
        only when no model can be detected at all — callers may retry
        later once the agent has provisioned one.  Every watcher event is
        automatically routed to the task queue before the external
        callback fires.
        """
        if self._watcher is not None and self._watcher.running:
            return True
        substrate = self._state.charm_type
        # If a previously-set dev_model belongs to the wrong substrate
        # (e.g. LXD model for a k8s charm), drop it so auto-detect can
        # pick a matching one.  When ``charm_type`` is unknown we trust
        # whatever the user/state had.
        if self._state.dev_model and substrate:
            actual = juju_model_substrate(self._state.dev_model)
            if actual is not None and actual != substrate:
                log.info(
                    "Dev model '%s' is %s but charm is %s — re-detecting",
                    self._state.dev_model,
                    actual,
                    substrate,
                )
                self._state.dev_model = None
        if not self._state.dev_model:
            detected = detect_current_juju_model(prefer_substrate=substrate)
            if detected:
                self._state.dev_model = detected
            else:
                return False
        # Auto-detect a ``cos`` model so the COS pane populates without
        # waiting for one of the narrow code paths that set
        # ``state.cos_model`` explicitly (sprint-deploy planning, etc.).
        if not self._state.cos_model:
            cos = detect_cos_juju_model()
            if cos:
                self._state.cos_model = cos

        def _auto_route(event: WatcherEvent) -> None:
            """Route the event to the task queue, then publish to the bus.

            When ``state.watcher_reacting`` is ``False`` the routing step
            is skipped — the event is still published so the UI shows it,
            but no task is queued and the agent does not act on it.
            """
            if self._state.watcher_reacting:
                self.route_event(event)
            self._event_bus.publish(
                ui_events.watcher_event(
                    source=event.source,
                    category=event.category,
                    summary=event.summary,
                    detail=getattr(event, "detail", ""),
                    app=getattr(event, "app", ""),
                    unit=getattr(event, "unit", ""),
                )
            )
            if on_event is not None:
                on_event(event)

        def _on_status_poll(model_type: str) -> None:
            """Publish a status-changed tick so UIs refresh their model panes."""
            self._event_bus.publish(
                ui_events.juju_status_changed(status_data={"model_type": model_type})
            )

        self._watcher = EventWatcher(
            dev_model=self._state.dev_model,
            cos_model=self._state.cos_model,
            config=config,
            on_event=_auto_route,
            on_status_poll=_on_status_poll,
        )
        self._watcher.start()
        self._state.watcher_enabled = True
        return True

    async def stop(self) -> None:
        """Stop the event watcher if it is running."""
        if self._watcher:
            await self._watcher.stop()
            self._watcher = None
        self._state.watcher_enabled = False

    def route_event(self, event: WatcherEvent) -> AgentTask | None:
        """Convert a watcher event into a task and add it to the work queue.

        Returns the created task, or ``None`` if the event did not map to a
        task (e.g. no dev_model or unrecognised category).
        """
        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "watcher_event",
                {
                    "category": event.category,
                    "summary": event.summary,
                },
            )

        task = task_for_watcher_event(event, self._state)
        if task is not None:
            self._work_queue.add_task(task)
        return task

    async def process_event(self) -> str | None:
        """Dequeue one watcher event and route it to the task queue.

        Returns the task title, or ``None`` if no events are pending.
        """
        if not self._watcher:
            return None
        event = await self._watcher.dequeue()
        if event is None:
            return None
        task = self.route_event(event)
        if task is not None:
            return task.title
        return None
