"""Watcher cohort: subscribe, start/stop, status-bar refresh, toggle action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.agent.queue import TaskStatus
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import status as status_widgets
from cantrip.tui.widgets import statusbar as statusbar_widget
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.tui.app import CantripApp


def subscribe_events(app: CantripApp) -> None:
    """Subscribe to watcher events so the panes update even if the watcher
    starts later (e.g. once the agent provisions a model).
    """
    if not app._agent:
        return
    app._agent.event_bus.subscribe(ui_events.EventType.WATCHER_EVENT, app._on_bus_watcher_event)
    app._agent.event_bus.subscribe(
        ui_events.EventType.JUJU_STATUS_CHANGED, app._on_bus_juju_status
    )


def start_watcher(app: CantripApp) -> None:
    """Try to start the event watcher.

    If no Juju model is available yet, schedule a periodic retry so the
    watcher starts as soon as the agent provisions one.  Events are
    automatically routed to the task queue by the agent's
    ``start_watcher`` method.
    """
    if not app._agent or app._agent.watcher_running:
        return
    started = app._agent.start_watcher()
    if started:
        update_status_bar(app)
        if app._watcher_retry_timer is not None:
            app._watcher_retry_timer.stop()
            app._watcher_retry_timer = None
    elif app._watcher_retry_timer is None:
        app._watcher_retry_timer = app.set_interval(5.0, app._start_watcher)


async def stop_watcher(app: CantripApp) -> None:
    """Stop the event watcher."""
    if not app._agent:
        return
    if app._watcher_retry_timer is not None:
        app._watcher_retry_timer.stop()
        app._watcher_retry_timer = None
    await app._agent.stop_watcher()
    update_status_bar(app)


def refresh_model_panes(app: CantripApp) -> None:
    """Push the watcher's latest status snapshots into the model widget."""
    if not app._agent:
        return
    status_widget = app.query_one("#juju-status", status_widgets.MultiModelStatusWidget)
    latest = app._agent._watcher_ctl.latest_status
    if latest is not None:
        status_widget.dev_status = latest
    latest_cos = app._agent._watcher_ctl.latest_cos_status
    if latest_cos is not None:
        status_widget.cos_status = latest_cos


def on_watcher_event(app: CantripApp, event: ui_events.Event) -> None:
    """Handle a watcher event from the bus."""
    chat = app.query_one("#chat", chat_widget.ChatWidget)
    chat.add_system_message(f"[Watcher] {event.payload.get('summary', '')}")
    refresh_model_panes(app)


def on_juju_status(app: CantripApp) -> None:
    """Handle a periodic status-poll tick from the watcher."""
    refresh_model_panes(app)


def update_status_bar(app: CantripApp) -> None:
    """Update the status bar watcher indicator."""
    status_bar = app.query_one("#status-bar", statusbar_widget.StatusBar)
    if app._agent and app._agent.watcher_running:
        if app._agent.watcher_reacting:
            status_bar.watcher_status = "👁 Watching"
        else:
            status_bar.watcher_status = "👁 Watching (paused)"
    else:
        status_bar.watcher_status = ""


def refresh_subagent_status_bar(app: CantripApp) -> None:
    """Mirror the currently-active subagent phase into the status bar.

    Picks the first ACTIVE task with a live ``subagent_phase`` so
    research/build activity is visible without having to expand the
    task pane.  Cleared when no subagent is running.
    """
    from textual.css.query import NoMatches

    if not app._agent:
        return
    try:
        status_bar = app.query_one("#status-bar", statusbar_widget.StatusBar)
    except NoMatches:
        return
    for task in app._agent.work_queue.all_tasks():
        if task.status == TaskStatus.ACTIVE and task.subagent_phase:
            status_bar.subagent_label = f"⟳ {task.title} · {task.subagent_phase}"
            return
    status_bar.subagent_label = ""


def toggle_watcher(app: CantripApp) -> None:
    """Pause or resume the watcher's autonomous reactions.

    The watcher keeps observing the model either way — only whether
    detected events queue tasks for the agent changes.
    """
    if not app._agent:
        return
    reacting = app._agent.toggle_watcher_reacting()
    chat = app.query_one("#chat", chat_widget.ChatWidget)
    if reacting:
        chat.add_system_message("Watcher reactions resumed — detected events will queue tasks.")
    else:
        chat.add_system_message(
            "Watcher reactions paused — still observing the model, but events won't queue tasks."
        )
    update_status_bar(app)
