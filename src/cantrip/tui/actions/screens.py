"""Screen-switching action handlers (help, debug, logs, graph, transcript)."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from cantrip.tui.widgets import status as status_widgets

if TYPE_CHECKING:
    from cantrip.tui.app import CantripApp


def show_help(app: CantripApp) -> None:
    """Push the help screen."""
    from cantrip.tui.screens import help as help_screen

    app.push_screen(help_screen.HelpScreen())


def show_debug(app: CantripApp) -> None:
    """Push the trace/debug screen."""
    from cantrip.agent import cos_endpoints
    from cantrip.tui.screens import traces as traces_screen

    cos_model = app._agent.state.cos_model if app._agent else None
    status = app._agent._watcher_ctl.latest_cos_status if app._agent else None
    endpoints = cos_endpoints.derive_endpoints(status)
    app.push_screen(traces_screen.TraceScreen(cos_model=cos_model, endpoints=endpoints))


def show_logs(app: CantripApp) -> None:
    """Push the log viewer screen."""
    from cantrip.tui.screens import logs as logs_screen

    dev_model = app._agent.state.dev_model if app._agent else None
    cos_model = app._agent.state.cos_model if app._agent else None
    app.push_screen(logs_screen.LogScreen(dev_model=dev_model, cos_model=cos_model))


def show_graph(app: CantripApp) -> None:
    """Push the integration graph screen."""
    from cantrip.tui.screens import graph as graph_screen

    status_widget = app.query_one("#juju-status", status_widgets.MultiModelStatusWidget)
    current_app = app._agent.state.charm_name if app._agent else None
    dev_model = app._agent.state.dev_model if app._agent else None
    cos_model = app._agent.state.cos_model if app._agent else None
    app.push_screen(
        graph_screen.GraphScreen(
            status=status_widget.dev_status,
            current_app=current_app,
            model=dev_model,
            cos_status=status_widget.cos_status,
            cos_model=cos_model,
        )
    )


def show_transcript(app: CantripApp) -> None:
    """Push the session transcript screen."""
    from cantrip.tui.screens import transcript as transcript_screen

    db_path: pathlib.Path | None = None
    if app._agent and app._agent.state.charm_path:
        candidate = app._agent.state.charm_path / ".cantrip"
        if candidate.exists():
            db_path = candidate
    app.push_screen(transcript_screen.TranscriptScreen(db_path=db_path))


def open_relation_detail(app: CantripApp, event: status_widgets.RelationLine.Selected) -> None:
    """Open the relation detail screen when a relation line is clicked."""
    from cantrip.tui.screens import relation as relation_screen

    dev_model = app._agent.state.dev_model if app._agent else None
    app.push_screen(
        relation_screen.RelationDetailScreen(
            unit_name=event.unit_name,
            endpoint=event.endpoint,
            related_app=event.related_app,
            model=dev_model,
        )
    )
