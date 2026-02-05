"""Juju status widget for the TUI."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from cantrip.juju.status import AppStatus, ModelStatus


class AppBox(Static):
    """Widget representing a single application."""

    DEFAULT_CSS = """
    AppBox {
        border: solid $primary;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
    }

    AppBox.active {
        border: solid $success;
    }

    AppBox.waiting {
        border: solid $warning;
    }

    AppBox.blocked {
        border: solid $error;
    }

    AppBox .app-name {
        text-style: bold;
    }

    AppBox .status-active {
        color: $success;
    }

    AppBox .status-waiting {
        color: $warning;
    }

    AppBox .status-blocked {
        color: $error;
    }

    AppBox .status-maintenance {
        color: $primary;
    }
    """

    def __init__(self, app: AppStatus, highlight: bool = False) -> None:
        """Initialise with app status."""
        super().__init__()
        self.app = app
        self.highlight = highlight

        # Set CSS class based on status
        if app.status == "active":
            self.add_class("active")
        elif app.status in ("waiting", "unknown"):
            self.add_class("waiting")
        elif app.status in ("blocked", "error"):
            self.add_class("blocked")

    def compose(self) -> ComposeResult:
        """Compose the app box."""
        # Status indicator
        status_char = self._status_char(self.app.status)
        status_class = f"status-{self.app.status}"

        # Build content
        name_line = f"[bold]{self.app.name}[/bold]"
        if self.highlight:
            name_line += " ← you are here"

        status_line = f"[{status_class}]{status_char}[/{status_class}] {self.app.status}"
        if self.app.message:
            status_line += f": {self.app.message[:30]}"

        units_line = f"{len(self.app.units)} unit{'s' if len(self.app.units) != 1 else ''}"

        yield Static(f"{name_line}\n{status_line}\n{units_line}")

    def _status_char(self, status: str) -> str:
        """Get status indicator character."""
        return {
            "active": "●",
            "waiting": "○",
            "blocked": "◌",
            "maintenance": "◐",
            "unknown": "○",
            "error": "✗",
        }.get(status, "○")


class RelationLine(Static):
    """Widget showing a relation between apps."""

    DEFAULT_CSS = """
    RelationLine {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, relation_name: str) -> None:
        """Initialise with relation name."""
        super().__init__()
        self.relation_name = relation_name

    def compose(self) -> ComposeResult:
        """Compose the relation line."""
        yield Static(f"│ {self.relation_name}")


class JujuStatusWidget(Widget):
    """Widget displaying full Juju model status."""

    DEFAULT_CSS = """
    JujuStatusWidget {
        height: 100%;
        padding: 1;
    }

    JujuStatusWidget .model-header {
        text-style: bold;
        margin-bottom: 1;
    }

    JujuStatusWidget .no-apps {
        color: $text-muted;
        text-style: italic;
    }

    JujuStatusWidget .model-summary {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    status: reactive[ModelStatus | None] = reactive(None)
    current_app: reactive[str | None] = reactive(None)

    def __init__(
        self,
        status: ModelStatus | None = None,
        current_app: str | None = None,
        **kwargs,
    ) -> None:
        """Initialise with optional status."""
        super().__init__(**kwargs)
        self.status = status
        self.current_app = current_app

    def compose(self) -> ComposeResult:
        """Compose the status display."""
        yield Vertical(id="status-container")

    def watch_status(self, _status: ModelStatus | None) -> None:
        """React to status changes."""
        self._refresh_display()

    def watch_current_app(self, _app: str | None) -> None:
        """React to current app changes."""
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the status display."""
        results = self.query("#status-container")
        if not results:
            # Watcher fired before compose() has run.
            return
        container = results.first(Vertical)
        container.remove_children()

        if not self.status:
            container.mount(
                Static(
                    "No model connected.\n\nStart by describing what\nyou want to charm.",
                    classes="no-apps",
                )
            )
            return

        # Model header
        container.mount(
            Static(
                f"Model: {self.status.name} ({self.status.cloud})",
                classes="model-header",
            )
        )

        # Summary
        total_units = sum(len(app.units) for app in self.status.apps)
        container.mount(
            Static(
                f"Apps: {len(self.status.apps)}  Units: {total_units}",
                classes="model-summary",
            )
        )

        if not self.status.apps:
            container.mount(Static("No applications deployed.", classes="no-apps"))
            return

        # Apps with relations
        for app in self.status.apps:
            highlight = app.name == self.current_app
            container.mount(AppBox(app, highlight=highlight))

            # Show relations
            for rel_name, related_apps in app.relations.items():
                for related in related_apps:
                    container.mount(RelationLine(f"{rel_name} → {related}"))

    def update_status(self, status: ModelStatus) -> None:
        """Update the displayed status."""
        self.status = status

    def set_current_app(self, app_name: str | None) -> None:
        """Set the currently active app (highlighted)."""
        self.current_app = app_name


class MultiModelStatusWidget(Widget):
    """Widget showing status of multiple models (dev + cos)."""

    DEFAULT_CSS = """
    MultiModelStatusWidget {
        height: 100%;
    }

    MultiModelStatusWidget .model-section {
        border-bottom: solid $surface-darken-1;
        padding: 1;
        height: auto;
    }

    MultiModelStatusWidget .model-section:last-child {
        border-bottom: none;
    }

    MultiModelStatusWidget .section-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    MultiModelStatusWidget .collapsed-summary {
        color: $text-muted;
    }
    """

    dev_status: reactive[ModelStatus | None] = reactive(None)
    cos_status: reactive[ModelStatus | None] = reactive(None)
    cos_expanded: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        """Compose the multi-model display."""
        yield Vertical(
            Vertical(id="dev-section", classes="model-section"),
            Vertical(id="cos-section", classes="model-section"),
        )

    def on_mount(self) -> None:
        """Handle mount."""
        self._refresh_display()

    def watch_dev_status(self, _status: ModelStatus | None) -> None:
        """React to dev status changes."""
        self._refresh_display()

    def watch_cos_status(self, _status: ModelStatus | None) -> None:
        """React to COS status changes."""
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the display."""
        # Dev model section
        dev_section = self.query_one("#dev-section", Vertical)
        dev_section.remove_children()

        if self.dev_status:
            dev_section.mount(JujuStatusWidget(status=self.dev_status))
        else:
            dev_section.mount(Static("Dev model not connected", classes="collapsed-summary"))

        # COS model section (collapsed by default)
        cos_section = self.query_one("#cos-section", Vertical)
        cos_section.remove_children()

        cos_section.mount(Static("COS Model", classes="section-title"))

        if self.cos_status:
            if self.cos_expanded:
                cos_section.mount(JujuStatusWidget(status=self.cos_status))
            else:
                # Collapsed summary
                active_count = sum(1 for app in self.cos_status.apps if app.status == "active")
                total = len(self.cos_status.apps)
                health = "● healthy" if active_count == total else f"○ {active_count}/{total}"
                cos_section.mount(
                    Static(
                        f"Apps: {total}  {health}  (click to expand)",
                        classes="collapsed-summary",
                    )
                )
        else:
            cos_section.mount(Static("Not deployed", classes="collapsed-summary"))

    def toggle_cos_expanded(self) -> None:
        """Toggle COS section expansion."""
        self.cos_expanded = not self.cos_expanded
        self._refresh_display()
