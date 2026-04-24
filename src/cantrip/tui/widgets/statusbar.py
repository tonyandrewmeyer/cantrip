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
    StatusBar.-plan-mode {
        background: $warning-darken-2;
    }
    """

    task_label: reactive[str] = reactive("", init=False)
    subagent_label: reactive[str] = reactive("", init=False)
    cos_health: reactive[str] = reactive("", init=False)
    test_summary: reactive[str] = reactive("", init=False)
    watcher_status: reactive[str] = reactive("", init=False)
    # Phase 68.4: ``"plan"`` means the read-only gate is active and the
    # ``-plan-mode`` CSS class is set so the bar tints distinctly.
    # Any other value (default: ``"build"``) keeps the normal theme.
    mode: reactive[str] = reactive("build", init=False)

    def compose(self) -> ComposeResult:
        """Compose the status bar."""
        yield Static("", id="status-bar-content")

    def _refresh_content(self) -> None:
        """Rebuild the bar text from current reactive values."""
        mode_badge = "plan mode" if self.mode == "plan" else ""
        segments = [
            s
            for s in (
                mode_badge,
                self.task_label,
                self.subagent_label,
                self.cos_health,
                self.test_summary,
                self.watcher_status,
            )
            if s
        ]
        text = "  ".join(segments)
        with contextlib.suppress(NoMatches):
            self.query_one("#status-bar-content", Static).update(text)
        self.set_class(self.mode == "plan", "-plan-mode")

    # Every reactive triggers the same refresh — watchers generated below.


for _attr in (
    "task_label",
    "subagent_label",
    "cos_health",
    "test_summary",
    "watcher_status",
    "mode",
):
    setattr(StatusBar, f"watch_{_attr}", lambda self: self._refresh_content())
