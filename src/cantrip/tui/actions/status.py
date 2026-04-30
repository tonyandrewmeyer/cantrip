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
    """Toggle model info bar visibility."""
    bar = app.query_one("#model-info", modelbar_widget.ModelInfoBar)
    bar.display = not bar.display


def show_status_panel_when_data_arrives(app: CantripApp) -> None:
    """Show the status panel when status data first arrives."""
    app.query_one("#right-panel").display = True
