"""Status panel and model-bar toggle handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.tui.widgets import filetree as filetree_widget
from cantrip.tui.widgets import modelbar as modelbar_widget

if TYPE_CHECKING:
    from cantrip.tui.app import CantripApp


def toggle_status(app: CantripApp) -> None:
    """Toggle status panel visibility."""
    right_panel = app.query_one("#right-panel")
    right_panel.display = not right_panel.display


def toggle_files(app: CantripApp) -> None:
    """Toggle charm file tree visibility."""
    tree = app.query_one("#charm-files", filetree_widget.CharmTreeWidget)
    tree.display = not tree.display


def toggle_model_info(app: CantripApp) -> None:
    """Toggle the model info bar between compact and expanded.

    Phase 108.4: the bar is *always* visible — F7 used to hard-hide
    it, but the new contract is "compact one-liner by default,
    flip to the rich two-line breakdown on demand".  Hiding the bar
    entirely was rare enough that the simpler two-state contract
    earns its keep; the compact line still surfaces the
    glance-and-go signals (model, context %, session cost).
    """
    bar = app.query_one("#model-info", modelbar_widget.ModelInfoBar)
    bar.expanded = not bar.expanded


def show_status_panel_when_data_arrives(app: CantripApp) -> None:
    """Show the status panel when status data first arrives."""
    app.query_one("#right-panel").display = True
