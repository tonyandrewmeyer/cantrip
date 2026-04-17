"""Relation detail modal screen for Cantrip TUI."""

import functools
import json
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static
from textual.worker import Worker, WorkerState

# Timeout for juju show-unit subprocess (seconds).
_SUBPROCESS_TIMEOUT = 15


class RelationDetailScreen(ModalScreen):
    """Modal screen showing relation databag contents.

    Fetches databag data via ``juju show-unit`` and displays provider
    and requirer databag keys and values side by side.
    """

    DEFAULT_CSS = """
    RelationDetailScreen {
        align: center middle;
    }

    #relation-container {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #relation-title {
        width: 100%;
        height: 1;
        padding-bottom: 1;
    }

    .title-text {
        text-style: bold;
        width: 1fr;
    }

    .title-hint {
        color: $text-muted;
        width: auto;
    }

    #relation-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #relation-output {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        unit_name: str,
        endpoint: str,
        related_app: str,
        model: str | None = None,
    ) -> None:
        """Initialise with relation details."""
        super().__init__()
        self._unit_name = unit_name
        self._endpoint = endpoint
        self._related_app = related_app
        self._model = model

    def compose(self) -> ComposeResult:
        """Compose the relation detail layout."""
        with Center(), Vertical(id="relation-container"):
            with Horizontal(id="relation-title"):
                yield Static(
                    f"Relation: {self._endpoint} ↔ {self._related_app}",
                    classes="title-text",
                )
                yield Static("[Esc Close]", classes="title-hint")
            yield RichLog(id="relation-output", wrap=True)
            yield Static(
                "[r] Refresh  [Esc] Close",
                id="relation-footer",
            )

    def on_mount(self) -> None:
        """Fetch relation data on mount."""
        self._fetch_data()

    def action_refresh(self) -> None:
        """Refresh the relation data."""
        self._fetch_data()

    def _fetch_data(self) -> None:
        """Kick off a background worker to fetch relation databag data."""
        output = self.query_one("#relation-output", RichLog)
        output.clear()

        if not self._model:
            output.write("No development model connected.")
            return

        output.write("[dim]Fetching relation data…[/dim]")
        self.run_worker(
            functools.partial(self._fetch_data_blocking, self._unit_name, self._model),
            name="fetch_relation",
            exclusive=True,
            thread=True,
        )

    @staticmethod
    def _fetch_data_blocking(unit_name: str, model: str) -> str:
        """Run ``juju show-unit`` in a thread (called via ``run_worker``)."""
        cmd = [
            "juju",
            "show-unit",
            unit_name,
            "--model",
            model,
            "--format",
            "json",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except FileNotFoundError:
            return json.dumps({"error": "juju CLI not found. Is it installed?"})
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Timed out fetching relation data."})

        if result.returncode != 0:
            return json.dumps({"error": result.stderr or "unknown error"})

        return result.stdout

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle the fetch_relation worker completing."""
        if event.worker.name != "fetch_relation":
            return
        if event.worker.state != WorkerState.SUCCESS:
            return

        raw = event.worker.result
        output = self.query_one("#relation-output", RichLog)
        output.clear()

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            output.write("Could not parse juju show-unit output.")
            return

        if "error" in data:
            output.write(f"Error: {data['error']}")
            return

        self._render_relation_data(data)

    def _render_relation_data(self, data: dict) -> None:
        """Render parsed ``juju show-unit`` JSON into the RichLog."""
        output = self.query_one("#relation-output", RichLog)

        unit_info = data.get(self._unit_name, {})
        relations = unit_info.get("relation-info", [])

        # Find the matching relation.
        matched = False
        for rel in relations:
            if rel.get("endpoint") != self._endpoint:
                continue

            output.write(f"[bold]Endpoint:[/bold] {self._endpoint}")
            output.write(f"[bold]Relation ID:[/bold] {rel.get('relation-id', '?')}")
            output.write("")

            # Local application data.
            local_data = rel.get("application-data", {})
            if local_data:
                output.write(f"[bold]{self._unit_name.rsplit('/', 1)[0]} (local):[/bold]")
                for k, v in sorted(local_data.items()):
                    output.write(f"  {k}: {v}")
                output.write("")

            # Related unit data.
            related_units = rel.get("related-units", {})
            if related_units:
                output.write(f"[bold]{self._related_app} (remote):[/bold]")
                for ru_name, ru_info in sorted(related_units.items()):
                    output.write(f"  [dim]{ru_name}:[/dim]")
                    for k, v in sorted(ru_info.get("data", {}).items()):
                        output.write(f"    {k}: {v}")
                output.write("")

            # Highlight asymmetries.
            local_keys = set(local_data.keys())
            remote_keys: set[str] = set()
            for ru_info in related_units.values():
                remote_keys.update(ru_info.get("data", {}).keys())

            only_local = local_keys - remote_keys
            only_remote = remote_keys - local_keys
            if only_local or only_remote:
                output.write("[bold]Asymmetries:[/bold]")
                if only_local:
                    output.write(f"  Only in local: {', '.join(sorted(only_local))}")
                if only_remote:
                    output.write(f"  Only in remote: {', '.join(sorted(only_remote))}")

            matched = True

        if not matched:
            output.write(f"No relation data found for endpoint '{self._endpoint}'.")
