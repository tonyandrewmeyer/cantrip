"""Tests for the event-driven watcher."""

import json
import time
from unittest import mock

import jubilant
import pytest

from cantrip.agent.watcher import (
    AppSnapshot,
    EventWatcher,
    OfferSnapshot,
    StatusSnapshot,
    UnitSnapshot,
    WatcherConfig,
    WatcherEvent,
    capture_snapshot,
    diff_snapshots,
    format_event_for_agent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    apps: dict[str, tuple[str, str, list[tuple[str, str, str, str]], frozenset[str]]]
    | None = None,
    offers: list[OfferSnapshot] | None = None,
) -> StatusSnapshot:
    """Build a StatusSnapshot from a compact dict.

    Keys are app names; values are tuples of
    ``(status, status_message, units_list, relations_set)``.
    Each unit in the list is ``(name, workload_status, workload_message, agent_status)``.
    """
    if apps is None:
        return StatusSnapshot(apps=(), offers=tuple(offers or []))
    result: list[AppSnapshot] = []
    for name, (status, msg, units_list, rels) in sorted(apps.items()):
        units = tuple(
            UnitSnapshot(
                name=uname,
                workload_status=wstatus,
                workload_message=wmsg,
                agent_status=astatus,
            )
            for uname, wstatus, wmsg, astatus in units_list
        )
        result.append(
            AppSnapshot(
                name=name,
                status=status,
                status_message=msg,
                units=units,
                relations=rels,
            )
        )
    return StatusSnapshot(apps=tuple(result), offers=tuple(offers or []))


def _offer(
    name: str = "myoffer",
    application: str = "myapp",
    endpoints: frozenset[str] = frozenset({"db:mysql"}),
    active: int = 1,
    total: int = 1,
) -> OfferSnapshot:
    """Build an OfferSnapshot with sensible defaults."""
    return OfferSnapshot(
        name=name,
        application=application,
        endpoints=endpoints,
        active_connected_count=active,
        total_connected_count=total,
    )


_EMPTY_RELS: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Snapshot diffing
# ---------------------------------------------------------------------------


class TestDiffSnapshots:
    """Tests for diff_snapshots()."""

    def test_no_change(self):
        """Identical snapshots produce no events."""
        snap = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        assert diff_snapshots(snap, snap) == []

    def test_old_none_produces_no_events(self):
        """First snapshot (old is None) produces no events."""
        snap = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        assert diff_snapshots(None, snap) == []

    def test_new_app_detected(self):
        """A new application is detected."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
                "newapp": ("waiting", "", [("newapp/0", "waiting", "", "idle")], _EMPTY_RELS),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "new_app"
        assert "newapp" in events[0].summary

    def test_removed_app_detected(self):
        """A removed application is detected."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
                "oldapp": ("active", "", [("oldapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "removed_app"
        assert "oldapp" in events[0].summary

    def test_status_change_detected(self):
        """A unit workload status change is detected."""
        old = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [("myapp/0", "waiting", "installing", "idle")],
                    _EMPTY_RELS,
                ),
            }
        )
        new = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "status_change"
        assert "waiting" in events[0].summary
        assert "active" in events[0].summary

    def test_hook_failure_detected(self):
        """A hook failure (error status) is detected."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [("myapp/0", "error", "hook failed: install", "idle")],
                    _EMPTY_RELS,
                ),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "hook_failure"
        assert "myapp/0" in events[0].summary

    def test_hook_failure_detected_via_message(self):
        """A hook failure detected via message content even with non-error status."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [("myapp/0", "blocked", "hook failed: config-changed", "idle")],
                    _EMPTY_RELS,
                ),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "hook_failure"

    def test_transient_maintenance_ignored(self):
        """Transient maintenance status is not reported as a change."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [("myapp/0", "maintenance", "installing packages", "executing")],
                    _EMPTY_RELS,
                ),
            }
        )
        events = diff_snapshots(old, new)
        assert events == []

    def test_new_relation_detected(self):
        """A new relation is detected."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [("myapp/0", "active", "", "idle")],
                    frozenset(["myapp:db-postgresql:db"]),
                ),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "new_relation"

    def test_new_unit_detected(self):
        """A new unit being added is detected."""
        old = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        new = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [
                        ("myapp/0", "active", "", "idle"),
                        ("myapp/1", "waiting", "", "allocating"),
                    ],
                    _EMPTY_RELS,
                ),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "new_unit"
        assert "myapp/1" in events[0].summary

    def test_removed_unit_detected(self):
        """A removed unit is detected."""
        old = _snap(
            {
                "myapp": (
                    "active",
                    "",
                    [
                        ("myapp/0", "active", "", "idle"),
                        ("myapp/1", "active", "", "idle"),
                    ],
                    _EMPTY_RELS,
                ),
            }
        )
        new = _snap(
            {
                "myapp": ("active", "", [("myapp/0", "active", "", "idle")], _EMPTY_RELS),
            }
        )
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "removed_unit"
        assert "myapp/1" in events[0].summary


class TestOfferDiffing:
    """Tests for offer topology diffing."""

    def test_new_offer_detected(self):
        """A new offer is detected."""
        old = _snap(offers=[])
        new = _snap(offers=[_offer(name="myoffer", application="myapp")])
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "new_offer"
        assert "myoffer" in events[0].summary

    def test_removed_offer_detected(self):
        """A removed offer is detected."""
        old = _snap(offers=[_offer(name="myoffer")])
        new = _snap(offers=[])
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "removed_offer"
        assert "myoffer" in events[0].summary

    def test_offer_connection_change_detected(self):
        """A change in connection count is detected."""
        old = _snap(offers=[_offer(name="myoffer", total=1, active=1)])
        new = _snap(offers=[_offer(name="myoffer", total=3, active=2)])
        events = diff_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "offer_connection_change"
        assert "1" in events[0].summary
        assert "3" in events[0].summary

    def test_no_change_in_offers(self):
        """Identical offers produce no events."""
        offer = _offer(name="myoffer", total=2, active=1)
        snap = _snap(offers=[offer])
        assert diff_snapshots(snap, snap) == []

    def test_offer_format_includes_instructions(self):
        """Offer events include investigation instructions."""
        event = WatcherEvent(
            source="status",
            category="new_offer",
            summary="New offer: myoffer",
            detail="Offer appeared",
            app="myapp",
        )
        result = format_event_for_agent(event)
        assert "juju_list_offers" in result


class TestDatabagDiffing:
    """Tests for relation databag diffing."""

    def test_new_keys_detected(self):
        """New keys appearing in a databag are detected."""
        from cantrip.agent.watcher import DatabagSnapshot, diff_databag_snapshots

        old = DatabagSnapshot(entries=(("myapp/0", "db", "postgresql", frozenset({"host"})),))
        new = DatabagSnapshot(
            entries=(("myapp/0", "db", "postgresql", frozenset({"host", "port", "password"})),)
        )
        events = diff_databag_snapshots(old, new)
        assert len(events) == 1
        assert events[0].category == "databag_change"
        assert "port" in events[0].detail
        assert "password" in events[0].detail

    def test_removed_keys_detected(self):
        """Removed keys are detected."""
        from cantrip.agent.watcher import DatabagSnapshot, diff_databag_snapshots

        old = DatabagSnapshot(
            entries=(("myapp/0", "db", "postgresql", frozenset({"host", "port"})),)
        )
        new = DatabagSnapshot(entries=(("myapp/0", "db", "postgresql", frozenset({"host"})),))
        events = diff_databag_snapshots(old, new)
        assert len(events) == 1
        assert "removed" in events[0].detail
        assert "port" in events[0].detail

    def test_no_change_produces_no_events(self):
        """Identical databag snapshots produce no events."""
        from cantrip.agent.watcher import DatabagSnapshot, diff_databag_snapshots

        snap = DatabagSnapshot(
            entries=(("myapp/0", "db", "postgresql", frozenset({"host", "port"})),)
        )
        assert diff_databag_snapshots(snap, snap) == []

    def test_old_none_produces_no_events(self):
        """First snapshot (old is None) produces no events."""
        from cantrip.agent.watcher import DatabagSnapshot, diff_databag_snapshots

        new = DatabagSnapshot(entries=(("myapp/0", "db", "postgresql", frozenset({"host"})),))
        assert diff_databag_snapshots(None, new) == []

    def test_databag_format_includes_instructions(self):
        """Databag change events include read_relation_data instruction."""
        event = WatcherEvent(
            source="status",
            category="databag_change",
            summary="Databag change: myapp/0",
            detail="Keys changed",
            app="myapp",
            unit="myapp/0",
        )
        result = format_event_for_agent(event)
        assert "juju_read_relation_data" in result


# ---------------------------------------------------------------------------
# Capture snapshot
# ---------------------------------------------------------------------------


class TestCaptureSnapshot:
    """Tests for capture_snapshot()."""

    def test_captures_app_and_units(self):
        """Snapshot includes apps and their units."""
        mock_unit = mock.MagicMock()
        mock_unit.workload_status.current = "active"
        mock_unit.workload_status.message = ""
        mock_unit.juju_status.current = "idle"

        mock_app = mock.MagicMock()
        mock_app.app_status.current = "active"
        mock_app.app_status.message = ""
        mock_app.units = {"myapp/0": mock_unit}
        mock_app.relations = {}

        mock_status = mock.MagicMock(spec=jubilant.Status)
        mock_status.apps = {"myapp": mock_app}

        snapshot = capture_snapshot(mock_status)

        assert len(snapshot.apps) == 1
        assert snapshot.apps[0].name == "myapp"
        assert len(snapshot.apps[0].units) == 1
        assert snapshot.apps[0].units[0].name == "myapp/0"
        assert snapshot.apps[0].units[0].workload_status == "active"


# ---------------------------------------------------------------------------
# Deduplication and queue
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests for event deduplication."""

    def test_duplicate_suppressed_within_window(self):
        """An identical event within the dedup window is suppressed."""
        watcher = EventWatcher(dev_model="dev", config=WatcherConfig(dedup_window=300))
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="error",
            app="myapp",
            unit="myapp/0",
        )
        watcher._enqueue(event)
        watcher._enqueue(event)

        assert watcher.queue_size == 1

    def test_duplicate_passes_after_window(self):
        """An event passes after the dedup window expires."""
        watcher = EventWatcher(dev_model="dev", config=WatcherConfig(dedup_window=1))
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="error",
            app="myapp",
            unit="myapp/0",
        )
        watcher._enqueue(event)
        # Manually expire the dedup entry.
        for key in watcher._dedup:
            watcher._dedup[key] = time.time() - 2
        watcher._enqueue(event)

        assert watcher.queue_size == 2

    def test_different_keys_not_suppressed(self):
        """Events with different dedup keys are not suppressed."""
        watcher = EventWatcher(dev_model="dev", config=WatcherConfig(dedup_window=300))
        event1 = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="error",
            app="myapp",
            unit="myapp/0",
        )
        event2 = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/1",
            detail="error",
            app="myapp",
            unit="myapp/1",
        )
        watcher._enqueue(event1)
        watcher._enqueue(event2)

        assert watcher.queue_size == 2


class TestQueue:
    """Tests for the event queue."""

    @pytest.mark.asyncio
    async def test_dequeue_empty(self):
        """Dequeue on an empty queue returns None."""
        watcher = EventWatcher(dev_model="dev")
        result = await watcher.dequeue()
        assert result is None

    def test_queue_overflow_drops_event(self):
        """Events are dropped when the queue is full."""
        watcher = EventWatcher(dev_model="dev", config=WatcherConfig(max_queue=2))
        for i in range(5):
            watcher._enqueue(
                WatcherEvent(
                    source="status",
                    category="status_change",
                    summary=f"Change {i}",
                    detail=f"Detail {i}",
                )
            )
        assert watcher.queue_size == 2

    def test_on_event_callback_called(self):
        """The on_event callback is called when an event is enqueued."""
        callback = mock.MagicMock()
        watcher = EventWatcher(dev_model="dev", on_event=callback)
        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New app",
            detail="detail",
        )
        watcher._enqueue(event)

        callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_dequeue_returns_event(self):
        """Dequeue returns the oldest event."""
        watcher = EventWatcher(dev_model="dev")
        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New app",
            detail="detail",
        )
        watcher._enqueue(event)
        result = await watcher.dequeue()
        assert result is not None
        assert result.summary == "New app"

    @pytest.mark.asyncio
    async def test_has_events(self):
        """has_events reflects queue state."""
        watcher = EventWatcher(dev_model="dev")
        assert not watcher.has_events
        watcher._enqueue(
            WatcherEvent(source="status", category="new_app", summary="X", detail="Y")
        )
        assert watcher.has_events


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for EventWatcher start/stop."""

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        """Starting the watcher creates the polling tasks."""
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        watcher.start()

        assert watcher.running
        assert watcher._status_task is not None
        assert watcher._loki_task is not None

        await watcher.stop()
        assert not watcher.running

    @pytest.mark.asyncio
    async def test_start_without_cos_skips_loki(self):
        """Without a COS model, no Loki task is created."""
        watcher = EventWatcher(dev_model="dev")
        watcher.start()

        assert watcher.running
        assert watcher._status_task is not None
        assert watcher._loki_task is None

        await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        """Stopping an already-stopped watcher is a no-op."""
        watcher = EventWatcher(dev_model="dev")
        await watcher.stop()
        assert not watcher.running

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Starting an already-running watcher is a no-op."""
        watcher = EventWatcher(dev_model="dev")
        watcher.start()
        first_task = watcher._status_task
        watcher.start()
        assert watcher._status_task is first_task

        await watcher.stop()


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------


class TestStatusPolling:
    """Tests for the status polling loop."""

    @pytest.mark.asyncio
    async def test_poll_status_once_diffs(self):
        """A single status poll captures a snapshot and diffs it."""
        mock_unit = mock.MagicMock()
        mock_unit.workload_status.current = "active"
        mock_unit.workload_status.message = ""
        mock_unit.juju_status.current = "idle"

        mock_app = mock.MagicMock()
        mock_app.app_status.current = "active"
        mock_app.app_status.message = ""
        mock_app.units = {"myapp/0": mock_unit}
        mock_app.relations = {}

        mock_status = mock.MagicMock(spec=jubilant.Status)
        mock_status.apps = {"myapp": mock_app}

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.status.return_value = mock_status

        watcher = EventWatcher(dev_model="dev")

        with mock.patch("cantrip.agent.watcher.jubilant.Juju", return_value=mock_juju):
            await watcher._poll_status_once()

        # First poll sets the baseline — no events expected.
        assert watcher.queue_size == 0
        assert watcher._last_snapshot is not None

    @pytest.mark.asyncio
    async def test_poll_status_detects_change(self):
        """Two status polls with a change produce events."""
        # First poll: myapp/0 is active.
        mock_unit_1 = mock.MagicMock()
        mock_unit_1.workload_status.current = "active"
        mock_unit_1.workload_status.message = ""
        mock_unit_1.juju_status.current = "idle"

        mock_app_1 = mock.MagicMock()
        mock_app_1.app_status.current = "active"
        mock_app_1.app_status.message = ""
        mock_app_1.units = {"myapp/0": mock_unit_1}
        mock_app_1.relations = {}

        mock_status_1 = mock.MagicMock(spec=jubilant.Status)
        mock_status_1.apps = {"myapp": mock_app_1}

        # Second poll: myapp/0 is in error.
        mock_unit_2 = mock.MagicMock()
        mock_unit_2.workload_status.current = "error"
        mock_unit_2.workload_status.message = "hook failed: install"
        mock_unit_2.juju_status.current = "idle"

        mock_app_2 = mock.MagicMock()
        mock_app_2.app_status.current = "active"
        mock_app_2.app_status.message = ""
        mock_app_2.units = {"myapp/0": mock_unit_2}
        mock_app_2.relations = {}

        mock_status_2 = mock.MagicMock(spec=jubilant.Status)
        mock_status_2.apps = {"myapp": mock_app_2}

        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.status.side_effect = [mock_status_1, mock_status_2]

        watcher = EventWatcher(dev_model="dev")

        with mock.patch("cantrip.agent.watcher.jubilant.Juju", return_value=mock_juju):
            await watcher._poll_status_once()
            await watcher._poll_status_once()

        assert watcher.queue_size == 1
        event = await watcher.dequeue()
        assert event is not None
        assert event.category == "hook_failure"


# ---------------------------------------------------------------------------
# Loki polling
# ---------------------------------------------------------------------------


class TestLokiPolling:
    """Tests for the Loki polling loop."""

    @pytest.mark.asyncio
    async def test_poll_loki_parses_response(self):
        """Loki poll parses a valid response and enqueues events."""
        loki_response = {
            "data": {
                "result": [
                    {
                        "stream": {"juju_application": "myapp", "juju_unit": "myapp/0"},
                        "values": [
                            ["1700000000000000000", "ERROR: something went wrong"],
                        ],
                    }
                ]
            }
        }
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.ssh.return_value = json.dumps(loki_response)

        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ):
            await watcher._poll_loki_once()

        assert watcher.queue_size == 1
        event = await watcher.dequeue()
        assert event is not None
        assert event.category == "log_error"
        assert event.app == "myapp"

    @pytest.mark.asyncio
    async def test_poll_loki_no_cos_model(self):
        """Loki poll is a no-op without a COS model."""
        watcher = EventWatcher(dev_model="dev", cos_model=None)
        await watcher._poll_loki_once()
        assert watcher.queue_size == 0

    @pytest.mark.asyncio
    async def test_poll_loki_graceful_on_ssh_failure(self):
        """Loki poll handles SSH failure gracefully."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.ssh.side_effect = jubilant.CLIError(1, "ssh failed")

        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ):
            # Should not raise.
            await watcher._poll_loki_once()

        assert watcher.queue_size == 0

    @pytest.mark.asyncio
    async def test_poll_loki_graceful_on_no_loki(self):
        """Loki poll handles missing Loki unit gracefully."""
        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            side_effect=ValueError("No app containing 'loki'"),
        ):
            await watcher._poll_loki_once()

        assert watcher.queue_size == 0

    @pytest.mark.asyncio
    async def test_poll_loki_empty_juju_application_falls_back_to_app(self):
        """When juju_application is empty, falls back to the 'app' label."""
        loki_response = {
            "data": {
                "result": [
                    {
                        "stream": {"juju_application": "", "app": "fallback-app"},
                        "values": [
                            ["1700000000000000000", "ERROR: test"],
                        ],
                    }
                ]
            }
        }
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.ssh.return_value = json.dumps(loki_response)

        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ):
            await watcher._poll_loki_once()

        assert watcher.queue_size == 1
        event = await watcher.dequeue()
        assert event.app == "fallback-app"

    @pytest.mark.asyncio
    async def test_poll_loki_non_string_log_line(self):
        """Non-string log values are safely converted to strings."""
        loki_response = {
            "data": {
                "result": [
                    {
                        "stream": {"juju_application": "myapp"},
                        "values": [
                            ["1700000000000000000", 12345],
                        ],
                    }
                ]
            }
        }
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.ssh.return_value = json.dumps(loki_response)

        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ):
            await watcher._poll_loki_once()

        assert watcher.queue_size == 1
        event = await watcher.dequeue()
        assert "12345" in event.detail

    @pytest.mark.asyncio
    async def test_poll_loki_empty_results(self):
        """Loki poll with no results enqueues nothing."""
        mock_juju = mock.MagicMock(spec=jubilant.Juju)
        mock_juju.ssh.return_value = json.dumps({"data": {"result": []}})

        watcher = EventWatcher(dev_model="dev", cos_model="cos")

        with mock.patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(mock_juju, "loki-k8s/0"),
        ):
            await watcher._poll_loki_once()

        assert watcher.queue_size == 0


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------


class TestFormatEventForAgent:
    """Tests for format_event_for_agent()."""

    def test_hook_failure_format(self):
        """Hook failure events include investigation instructions."""
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        result = format_event_for_agent(event)

        assert "[Watcher]" in result
        assert "Hook failure on myapp/0" in result
        assert "juju_debug_log" in result
        assert "loki_query" in result

    def test_new_relation_format(self):
        """New relation events include verification instructions."""
        event = WatcherEvent(
            source="status",
            category="new_relation",
            summary="New relation: myapp:db-postgresql:db",
            detail="Relation was added",
            app="myapp",
        )
        result = format_event_for_agent(event)

        assert "[Watcher]" in result
        assert "juju_status" in result
        assert "relation" in result.lower()

    def test_log_error_format(self):
        """Log error events include Loki investigation instructions."""
        event = WatcherEvent(
            source="loki",
            category="log_error",
            summary="Log error in myapp",
            detail="ERROR: connection refused",
            app="myapp",
            unit="myapp/0",
        )
        result = format_event_for_agent(event)

        assert "[Watcher]" in result
        assert "loki_query" in result
        assert "juju_debug_log" in result

    def test_status_change_format(self):
        """Status change events include investigation instructions."""
        event = WatcherEvent(
            source="status",
            category="status_change",
            summary="myapp/0: waiting -> active",
            detail="Status changed",
            app="myapp",
            unit="myapp/0",
        )
        result = format_event_for_agent(event)

        assert "[Watcher]" in result
        assert "juju_status" in result

    def test_topology_change_format(self):
        """Topology change events (new/removed app/unit) include instructions."""
        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New application: newapp",
            detail="Application appeared",
            app="newapp",
        )
        result = format_event_for_agent(event)

        assert "[Watcher]" in result
        assert "topology" in result.lower()

    def test_format_includes_metadata(self):
        """Formatted events include source, category, app, and unit metadata."""
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure",
            detail="error details",
            app="myapp",
            unit="myapp/0",
        )
        result = format_event_for_agent(event)

        assert "**Source:** status" in result
        assert "**Category:** hook_failure" in result
        assert "**Application:** myapp" in result
        assert "**Unit:** myapp/0" in result


# ---------------------------------------------------------------------------
# WatcherEvent dataclass
# ---------------------------------------------------------------------------


class TestWatcherEvent:
    """Tests for the WatcherEvent dataclass."""

    def test_dedup_key_auto_generated(self):
        """dedup_key is auto-generated from event fields."""
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="failure",
            detail="detail",
            app="myapp",
            unit="myapp/0",
        )
        assert event.dedup_key != ""
        assert len(event.dedup_key) == 32  # MD5 hex digest

    def test_dedup_key_deterministic(self):
        """Same event fields produce the same dedup key."""
        kwargs = {
            "source": "status",
            "category": "hook_failure",
            "summary": "failure",
            "detail": "detail",
            "app": "myapp",
            "unit": "myapp/0",
        }
        event1 = WatcherEvent(**kwargs)
        event2 = WatcherEvent(**kwargs)
        assert event1.dedup_key == event2.dedup_key

    def test_explicit_dedup_key_preserved(self):
        """An explicitly provided dedup_key is not overwritten."""
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="failure",
            detail="detail",
            dedup_key="custom-key",
        )
        assert event.dedup_key == "custom-key"

    def test_timestamp_auto_set(self):
        """Timestamp is auto-set to current time."""
        before = time.time()
        event = WatcherEvent(source="status", category="test", summary="test", detail="test")
        after = time.time()
        assert before <= event.timestamp <= after
