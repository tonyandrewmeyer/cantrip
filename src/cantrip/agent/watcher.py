"""Event-driven watcher for Juju model changes.

Monitors a development model for hook failures, status changes, new relations,
and application-level log errors. Events are queued for the agent to process
autonomously.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

import jubilant

from cantrip.agent.tools.observability import _find_cos_unit

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitSnapshot:
    """Lightweight snapshot of a single unit's state."""

    name: str
    workload_status: str
    workload_message: str
    agent_status: str


@dataclass(frozen=True)
class AppSnapshot:
    """Lightweight snapshot of an application's state."""

    name: str
    status: str
    status_message: str
    units: tuple[UnitSnapshot, ...]
    relations: frozenset[str]


@dataclass(frozen=True)
class StatusSnapshot:
    """Lightweight snapshot of the full model status."""

    apps: tuple[AppSnapshot, ...]


@dataclass
class WatcherEvent:
    """An event detected by the watcher."""

    source: str  # "status" or "loki"
    category: str  # "hook_failure", "status_change", "new_app", etc.
    summary: str
    detail: str
    app: str | None = None
    unit: str | None = None
    timestamp: float = field(default_factory=time.time)
    dedup_key: str = ""

    def __post_init__(self) -> None:
        """Generate a dedup key if not provided."""
        if not self.dedup_key:
            raw = f"{self.source}:{self.category}:{self.app}:{self.unit}:{self.summary}"
            self.dedup_key = hashlib.md5(raw.encode()).hexdigest()  # noqa: S324


@dataclass
class WatcherConfig:
    """Configuration for the EventWatcher polling intervals and limits."""

    status_interval: float = 10.0  # seconds between status polls
    loki_interval: float = 15.0  # seconds between Loki polls
    dedup_window: float = 300.0  # seconds to suppress duplicate events
    max_queue: int = 50  # maximum queued events before dropping


# ---------------------------------------------------------------------------
# Snapshot capture and diffing
# ---------------------------------------------------------------------------


def capture_snapshot(status: jubilant.Status) -> StatusSnapshot:
    """Build a lightweight snapshot from a Jubilant status object."""
    apps: list[AppSnapshot] = []
    for app_name, app in sorted(status.apps.items()):
        units: list[UnitSnapshot] = []
        for unit_name, unit in sorted(app.units.items()):
            units.append(
                UnitSnapshot(
                    name=unit_name,
                    workload_status=unit.workload_status.current,
                    workload_message=unit.workload_status.message,
                    agent_status=unit.juju_status.current,
                )
            )

        # Collect relation endpoint names for topology diffing.
        relation_names: set[str] = set()
        for endpoint, rels in app.relations.items():
            for rel_app in rels:
                relation_names.add(f"{app_name}:{endpoint}-{rel_app.related_app}")

        apps.append(
            AppSnapshot(
                name=app_name,
                status=app.app_status.current,
                status_message=app.app_status.message,
                units=tuple(units),
                relations=frozenset(relation_names),
            )
        )
    return StatusSnapshot(apps=tuple(apps))


def diff_snapshots(
    old: StatusSnapshot | None,
    new: StatusSnapshot,
) -> list[WatcherEvent]:
    """Compare two status snapshots and return detected events.

    Detects:
    - New applications added to the model
    - Applications removed from the model
    - Unit workload status changes (excluding transient ``maintenance``)
    - Hook failures (unit enters ``error`` status or message contains "hook failed")
    - New relations between applications
    - Units added or removed from an application
    """
    if old is None:
        return []

    events: list[WatcherEvent] = []
    old_apps = {a.name: a for a in old.apps}
    new_apps = {a.name: a for a in new.apps}

    # New apps.
    for name in sorted(set(new_apps) - set(old_apps)):
        events.append(
            WatcherEvent(
                source="status",
                category="new_app",
                summary=f"New application: {name}",
                detail=f"Application '{name}' appeared in the model.",
                app=name,
            )
        )

    # Removed apps.
    for name in sorted(set(old_apps) - set(new_apps)):
        events.append(
            WatcherEvent(
                source="status",
                category="removed_app",
                summary=f"Application removed: {name}",
                detail=f"Application '{name}' is no longer in the model.",
                app=name,
            )
        )

    # Compare apps that exist in both snapshots.
    for name in sorted(set(old_apps) & set(new_apps)):
        old_app = old_apps[name]
        new_app = new_apps[name]

        # New relations.
        new_rels = new_app.relations - old_app.relations
        for rel in sorted(new_rels):
            events.append(
                WatcherEvent(
                    source="status",
                    category="new_relation",
                    summary=f"New relation: {rel}",
                    detail=f"Relation '{rel}' was added involving '{name}'.",
                    app=name,
                )
            )

        # Diff units.
        old_units = {u.name: u for u in old_app.units}
        new_units = {u.name: u for u in new_app.units}

        # New units.
        for uname in sorted(set(new_units) - set(old_units)):
            events.append(
                WatcherEvent(
                    source="status",
                    category="new_unit",
                    summary=f"New unit: {uname}",
                    detail=f"Unit '{uname}' was added to '{name}'.",
                    app=name,
                    unit=uname,
                )
            )

        # Removed units.
        for uname in sorted(set(old_units) - set(new_units)):
            events.append(
                WatcherEvent(
                    source="status",
                    category="removed_unit",
                    summary=f"Unit removed: {uname}",
                    detail=f"Unit '{uname}' was removed from '{name}'.",
                    app=name,
                    unit=uname,
                )
            )

        # Status changes for existing units.
        for uname in sorted(set(old_units) & set(new_units)):
            old_unit = old_units[uname]
            new_unit = new_units[uname]

            if old_unit.workload_status == new_unit.workload_status:
                continue

            # Ignore transient maintenance status — normal during hook execution.
            if new_unit.workload_status == "maintenance":
                continue

            # Hook failure detection.
            is_hook_failure = (
                new_unit.workload_status == "error"
                or "hook failed" in new_unit.workload_message.lower()
            )

            if is_hook_failure:
                events.append(
                    WatcherEvent(
                        source="status",
                        category="hook_failure",
                        summary=f"Hook failure on {uname}",
                        detail=(
                            f"Unit '{uname}' entered error state: {new_unit.workload_message}"
                        ),
                        app=name,
                        unit=uname,
                    )
                )
            else:
                events.append(
                    WatcherEvent(
                        source="status",
                        category="status_change",
                        summary=(
                            f"{uname}: {old_unit.workload_status} -> {new_unit.workload_status}"
                        ),
                        detail=(
                            f"Unit '{uname}' changed from "
                            f"'{old_unit.workload_status}' to "
                            f"'{new_unit.workload_status}'"
                            f"{': ' + new_unit.workload_message if new_unit.workload_message else ''}"
                        ),
                        app=name,
                        unit=uname,
                    )
                )

    return events


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------


_EVENT_INSTRUCTIONS: dict[str, list[str]] = {
    "hook_failure": [
        "Please investigate this hook failure:",
        "1. Check `juju_debug_log` for the error traceback",
        "2. If COS is available, query `loki_query` for related log entries",
        "3. Diagnose the root cause and suggest or apply a fix",
    ],
    "new_relation": [
        "A new relation was detected. Please:",
        "1. Check `juju_status` to see the current state",
        "2. Verify the relation is expected and properly configured",
        "3. Report the relation status to the user",
    ],
    "log_error": [
        "An error was found in the application logs:",
        "1. Query `loki_query` for more context around this error",
        "2. Check `juju_debug_log` for related hook activity",
        "3. Diagnose the root cause and suggest or apply a fix",
    ],
}

# Topology changes share the same instructions.
for _cat in ("new_app", "removed_app", "new_unit", "removed_unit"):
    _EVENT_INSTRUCTIONS[_cat] = [
        "A topology change was detected. Please:",
        "1. Check `juju_status` to see the current model state",
        "2. Report the change to the user",
    ]

_DEFAULT_INSTRUCTIONS = [
    "Please investigate this change:",
    "1. Check `juju_status` for the current state",
    "2. Use observability tools if needed to understand the cause",
    "3. Report findings to the user",
]


def format_event_for_agent(event: WatcherEvent) -> str:
    """Format a WatcherEvent into a structured message for the LLM.

    The message uses a ``[Watcher]`` prefix so the agent can distinguish
    watcher-injected messages from user input.
    """
    lines = [
        f"[Watcher] {event.summary}",
        "",
        f"**Source:** {event.source}",
        f"**Category:** {event.category}",
    ]
    if event.app:
        lines.append(f"**Application:** {event.app}")
    if event.unit:
        lines.append(f"**Unit:** {event.unit}")
    lines.append("")
    lines.append(event.detail)
    lines.append("")

    instructions = _EVENT_INSTRUCTIONS.get(event.category, _DEFAULT_INSTRUCTIONS)
    lines.extend(instructions)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EventWatcher
# ---------------------------------------------------------------------------


class EventWatcher:
    """Watches a development Juju model for events and queues them for the agent.

    The watcher only activates when ``state.dev_model`` is set. It runs two
    concurrent polling loops:

    - **Status polling** — diffs ``juju status`` snapshots every N seconds
    - **Loki polling** — queries Loki for error logs every N seconds (only
      when ``state.cos_model`` is set)

    Events are deduplicated within a configurable time window and placed on
    an asyncio queue for the agent to consume.
    """

    def __init__(
        self,
        dev_model: str,
        cos_model: str | None = None,
        config: WatcherConfig | None = None,
        on_event: Callable[[WatcherEvent], None] | None = None,
    ) -> None:
        self._dev_model = dev_model
        self._cos_model = cos_model
        self._config = config or WatcherConfig()
        self._on_event = on_event

        self._queue: asyncio.Queue[WatcherEvent] = asyncio.Queue(
            maxsize=self._config.max_queue,
        )
        self._dedup: dict[str, float] = {}
        self._last_snapshot: StatusSnapshot | None = None
        self._latest_status: jubilant.Status | None = None

        self._status_task: asyncio.Task | None = None
        self._loki_task: asyncio.Task | None = None
        self._running = False

    # -- Lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the watcher is currently running."""
        return self._running

    @property
    def latest_status(self) -> "jubilant.Status | None":
        """The most recent Juju status snapshot, or ``None`` if never polled."""
        return self._latest_status

    def start(self) -> None:
        """Start the polling loops as asyncio tasks."""
        if self._running:
            return
        self._running = True
        self._status_task = asyncio.create_task(self._poll_status_loop())
        if self._cos_model:
            self._loki_task = asyncio.create_task(self._poll_loki_loop())
        log.info(
            "Watcher started (model=%s, cos=%s)",
            self._dev_model,
            self._cos_model or "none",
        )

    async def stop(self) -> None:
        """Stop all polling loops and drain the queue."""
        if not self._running:
            return
        self._running = False
        if self._status_task:
            self._status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._status_task
            self._status_task = None
        if self._loki_task:
            self._loki_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loki_task
            self._loki_task = None
        log.info("Watcher stopped")

    # -- Queue access --------------------------------------------------------

    @property
    def has_events(self) -> bool:
        """Whether there are events waiting in the queue."""
        return not self._queue.empty()

    @property
    def queue_size(self) -> int:
        """Number of events currently in the queue."""
        return self._queue.qsize()

    async def dequeue(self) -> WatcherEvent | None:
        """Remove and return the next event, or ``None`` if the queue is empty."""
        if self._queue.empty():
            return None
        return self._queue.get_nowait()

    # -- Deduplication -------------------------------------------------------

    def _is_duplicate(self, event: WatcherEvent) -> bool:
        """Check whether an event is a duplicate within the dedup window."""
        now = time.time()
        # Prune expired entries lazily.
        expired = [k for k, t in self._dedup.items() if now - t > self._config.dedup_window]
        for k in expired:
            del self._dedup[k]

        if event.dedup_key in self._dedup:
            return True
        self._dedup[event.dedup_key] = now
        return False

    def _enqueue(self, event: WatcherEvent) -> None:
        """Enqueue an event if it is not a duplicate, dropping if the queue is full."""
        if self._is_duplicate(event):
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("Watcher event queue full — dropping event: %s", event.summary)
            return
        if self._on_event:
            self._on_event(event)

    # -- Status polling ------------------------------------------------------

    async def _poll_status_loop(self) -> None:
        """Poll ``juju status`` at the configured interval."""
        while self._running:
            try:
                await self._poll_status_once()
            except asyncio.CancelledError:
                raise
            except (jubilant.CLIError, OSError, TimeoutError) as exc:
                log.warning("Error polling juju status: %s", exc)
            await asyncio.sleep(self._config.status_interval)

    async def _poll_status_once(self) -> None:
        """Run a single status poll and diff against the previous snapshot."""
        loop = asyncio.get_running_loop()
        juju = jubilant.Juju(model=self._dev_model)
        status = await loop.run_in_executor(None, juju.status)
        self._latest_status = status
        snapshot = capture_snapshot(status)
        events = diff_snapshots(self._last_snapshot, snapshot)
        self._last_snapshot = snapshot
        for event in events:
            self._enqueue(event)

    # -- Loki polling --------------------------------------------------------

    async def _poll_loki_loop(self) -> None:
        """Poll Loki for error logs at the configured interval."""
        while self._running:
            try:
                await self._poll_loki_once()
            except asyncio.CancelledError:
                raise
            except (OSError, TimeoutError, ValueError) as exc:
                log.warning("Error polling Loki: %s", exc)
            await asyncio.sleep(self._config.loki_interval)

    async def _poll_loki_once(self) -> None:
        """Run a single Loki query for errors in the dev model."""
        if not self._cos_model:
            return

        loop = asyncio.get_running_loop()

        try:
            juju, unit_name = await loop.run_in_executor(
                None,
                _find_cos_unit,
                self._cos_model,
                "loki",
            )
        except ValueError:
            log.debug("Loki not found in COS model '%s' — skipping poll", self._cos_model)
            return

        # Query for errors in the dev model, slightly larger than the poll interval
        # to avoid gaps.
        query = f'{{juju_model="{self._dev_model}"}} |~ "(?i)(error|traceback|hook failed)"'
        # Time window: 20s (slightly larger than the 15s interval).
        window_seconds = int(self._config.loki_interval) + 5
        params = {
            "query": query,
            "limit": "20",
            "start": f"now-{window_seconds}s",
            "end": "now",
        }
        url = f"http://localhost:3100/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"

        python_script = (
            "import urllib.request, json, sys; "
            f"req = urllib.request.Request('{url}'); "
            "resp = urllib.request.urlopen(req, timeout=10); "
            "print(resp.read().decode())"
        )

        try:
            result = await loop.run_in_executor(
                None,
                juju.ssh,
                unit_name,
                f'python3 -c "{python_script}"',
            )
        except jubilant.CLIError:
            log.debug("SSH to Loki unit failed — skipping poll")
            return

        try:
            data = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            log.debug("Malformed JSON from Loki — skipping poll")
            return

        streams = data.get("data", {}).get("result", [])
        for stream in streams:
            labels = stream.get("stream", {})
            app_name = labels.get("juju_application") or labels.get("app", "")
            unit_name_label = labels.get("juju_unit", "")
            for entry in stream.get("values", []):
                if len(entry) < 2:
                    continue
                log_line = str(entry[1])
                self._enqueue(
                    WatcherEvent(
                        source="loki",
                        category="log_error",
                        summary=f"Log error in {app_name or 'unknown'}",
                        detail=log_line[:500],
                        app=app_name or None,
                        unit=unit_name_label or None,
                    )
                )
