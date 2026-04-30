"""Chat-pane action handlers (clear, search, cancel)."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.widgets import Input

from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import statusbar as statusbar_widget

if TYPE_CHECKING:
    from cantrip.tui.app import CantripApp


def clear_chat(app: CantripApp) -> None:
    """Clear chat history."""
    chat = app.query_one("#chat", chat_widget.ChatWidget)
    chat.clear()


def open_search(app: CantripApp) -> None:
    """Open the chat search bar."""
    chat = app.query_one("#chat", chat_widget.ChatWidget)
    chat.open_search()


def search_closed(app: CantripApp, event: chat_widget.ChatWidget.SearchClosed) -> None:
    """Return focus to the chat input when the search bar closes."""
    from textual.css.query import NoMatches

    event.stop()
    with contextlib.suppress(NoMatches):
        app.query_one("#chat-input", Input).focus()


def cancel_agent(app: CantripApp) -> None:
    """Cancel the running agent response worker."""
    for worker in app.workers:
        if worker.name == "agent_response" and worker.is_running:
            worker.cancel()
            app.query_one("#status-bar", statusbar_widget.StatusBar).task_label = "⏹ Cancelling..."
            return
