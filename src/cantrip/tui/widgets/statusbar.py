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
    StatusBar.-yolo-mode {
        background: $error-darken-1;
        color: $text;
    }
    StatusBar.-paused {
        background: $warning-darken-1;
    }
    StatusBar.-blocked {
        background: $warning-darken-2;
    }
    StatusBar.-budget-limited {
        background: $error-darken-1;
        color: $text;
    }
    """

    task_label: reactive[str] = reactive("", init=False)
    subagent_label: reactive[str] = reactive("", init=False)
    cos_health: reactive[str] = reactive("", init=False)
    test_summary: reactive[str] = reactive("", init=False)
    watcher_status: reactive[str] = reactive("", init=False)
    # Phase 104: non-empty (``"[short-session]"``) when the active
    # provider runs the tight-context short-session flow, so the
    # operator knows why the conversation feels forgetful.
    short_session: reactive[str] = reactive("", init=False)
    # Phase 110: non-empty (``"[build · 11]"``) when the LLM tool slice
    # has been curated down to the active workflow phase, so the operator
    # can see what's been offered to the model this turn.
    tool_phase: reactive[str] = reactive("", init=False)
    # Phase 68.4 / 69.2: ``"plan"`` and ``"yolo"`` flip the corresponding
    # CSS class so the bar tints distinctly.  Anything else
    # (default ``"build"``) keeps the normal theme.
    mode: reactive[str] = reactive("build", init=False)
    # Phase 99.1 / 99.4: lifecycle label projected by
    # :func:`cantrip.agent.runtime.lifecycle.lifecycle_label`.  ``"running"`` is
    # the default and renders no badge; the other four
    # (``"paused"``, ``"done"``, ``"blocked"``, ``"budget-limited"``)
    # add a labelled badge plus a per-state CSS tint.
    loop_state: reactive[str] = reactive("running", init=False)

    # Phase 99.4: badge text for each lifecycle label.  Closed mapping
    # so a future label addition has to update both this table and the
    # ``LIFECYCLE_LABELS`` tuple in ``cantrip.agent.runtime.lifecycle``.
    _LIFECYCLE_BADGES = {
        "running": "",
        "paused": "PAUSED",
        "done": "DONE",
        "blocked": "BLOCKED",
        "budget-limited": "BUDGET LIMITED",
    }

    def compose(self) -> ComposeResult:
        """Compose the status bar."""
        # ``markup=False`` — the segments are data (labels like
        # ``[short-session]`` / ``[build · 11]``, file names, emoji),
        # not Textual markup, so ``[`` must not open a style tag.
        yield Static("", id="status-bar-content", markup=False)

    def _refresh_content(self) -> None:
        """Rebuild the bar text from current reactive values."""
        if self.mode == "plan":
            mode_badge = "plan mode"
        elif self.mode == "yolo":
            mode_badge = "YOLO MODE — confirmations off"
        else:
            mode_badge = ""
        loop_badge = self._LIFECYCLE_BADGES.get(self.loop_state, "")
        segments = [
            s
            for s in (
                mode_badge,
                loop_badge,
                self.short_session,
                f"[{self.tool_phase}]" if self.tool_phase else "",
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
        self.set_class(self.mode == "yolo", "-yolo-mode")
        self.set_class(self.loop_state == "paused", "-paused")
        self.set_class(self.loop_state == "blocked", "-blocked")
        self.set_class(self.loop_state == "budget-limited", "-budget-limited")

    # Every reactive triggers the same refresh — watchers generated below.


for _attr in (
    "task_label",
    "subagent_label",
    "cos_health",
    "test_summary",
    "watcher_status",
    "short_session",
    "tool_phase",
    "mode",
    "loop_state",
):
    setattr(StatusBar, f"watch_{_attr}", lambda self: self._refresh_content())
