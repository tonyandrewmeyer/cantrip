"""Custom status bar widget for the Cantrip TUI."""

import contextlib

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """Bottom status bar showing background task, COS health, and test summary."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }
    """

    task_label: reactive[str] = reactive("", init=False)
    cos_health: reactive[str] = reactive("", init=False)
    test_summary: reactive[str] = reactive("", init=False)
    watcher_status: reactive[str] = reactive("", init=False)

    def compose(self) -> ComposeResult:
        """Compose the status bar."""
        yield Static("", id="status-bar-content")

    def _refresh_content(self) -> None:
        """Rebuild the bar text from current reactive values."""
        segments = [
            s
            for s in (self.task_label, self.cos_health, self.test_summary, self.watcher_status)
            if s
        ]
        text = "  ".join(segments)
        with contextlib.suppress(NoMatches):
            self.query_one("#status-bar-content", Static).update(text)

    def watch_task_label(self) -> None:
        """React to task_label changes."""
        self._refresh_content()

    def watch_cos_health(self) -> None:
        """React to cos_health changes."""
        self._refresh_content()

    def watch_test_summary(self) -> None:
        """React to test_summary changes."""
        self._refresh_content()

    def watch_watcher_status(self) -> None:
        """React to watcher_status changes."""
        self._refresh_content()
