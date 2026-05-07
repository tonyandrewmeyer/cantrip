"""Branch-coverage backfill for ``cantrip.agent.watcher``.

The base ``test_watcher.py`` covers the diff helpers, dedup, and queue
mechanics.  This file fills the remaining branches:

- ``capture_snapshot`` relation-loop and offer-loop bodies
- ``capture_databag_snapshot`` show-unit success path and per-unit
  show-unit failure handling
- ``EventWatcher.latest_cos_status`` accessor
- Polling loops: status / COS-status / Loki exception arms,
  ``_poll_status_once`` databag path, ``_poll_cos_status_once`` happy
  path, ``_poll_loki_once`` JSON-decode failure / undersized entries.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import jubilant
import pytest

from cantrip.agent.watcher import (
    DatabagSnapshot,
    EventWatcher,
    WatcherConfig,
    capture_databag_snapshot,
    capture_snapshot,
)


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# capture_snapshot — relation + offer bodies
# ---------------------------------------------------------------------------


class TestCaptureSnapshotRelationsAndOffers:
    """Covers the relation-loop and offer-loop branches."""

    def test_relations_are_recorded(self) -> None:
        rel_partner = MagicMock()
        rel_partner.related_app = "postgres"

        unit = MagicMock()
        unit.workload_status.current = "active"
        unit.workload_status.message = ""
        unit.juju_status.current = "idle"

        app = MagicMock()
        app.app_status.current = "active"
        app.app_status.message = ""
        app.units = {"my/0": unit}
        app.relations = {"db": [rel_partner]}

        status = MagicMock(spec=jubilant.Status)
        status.apps = {"my": app}

        snapshot = capture_snapshot(status)
        assert "my:db-postgres" in snapshot.apps[0].relations

    def test_offers_are_recorded(self) -> None:
        ep = MagicMock()
        ep.name = "grafana-dashboard"
        ep.interface = "grafana_dashboard"

        ep_no_iface = MagicMock()
        ep_no_iface.name = "ingress"
        ep_no_iface.interface = ""

        offer = MagicMock()
        offer.application_name = "grafana"
        offer.endpoints = {"grafana-dashboard": ep, "ingress": ep_no_iface}
        offer.active_connected_count = 2
        offer.total_connected_count = 3

        status = MagicMock(spec=jubilant.Status)
        status.apps = {}
        status.offers = {"cos.grafana": offer}

        snapshot = capture_snapshot(status)
        assert len(snapshot.offers) == 1
        offer_snap = snapshot.offers[0]
        assert "grafana-dashboard:grafana_dashboard" in offer_snap.endpoints
        # No-interface endpoint falls back to the bare name.
        assert "ingress" in offer_snap.endpoints
        assert offer_snap.active_connected_count == 2
        assert offer_snap.total_connected_count == 3


# ---------------------------------------------------------------------------
# capture_databag_snapshot — success and per-unit failure paths
# ---------------------------------------------------------------------------


class TestCaptureDatabagSuccess:
    """Drive ``capture_databag_snapshot`` through both shell-out steps."""

    def test_records_relation_databag_keys(self) -> None:
        # First call: ``juju status`` lists the units.
        # Subsequent calls: ``juju show-unit`` per app.
        status_payload = json.dumps(
            {
                "applications": {
                    "my": {"units": {"my/0": {}}},
                }
            }
        )
        show_unit_payload = json.dumps(
            {
                "my/0": {
                    "relation-info": [
                        {
                            "endpoint": "db",
                            "related-units": {
                                "pg/0": {
                                    "name": "pg/0",
                                    "data": {
                                        "username": "u",
                                        "password": "p",
                                    },
                                }
                            },
                        }
                    ]
                }
            }
        )

        with patch(
            "subprocess.run",
            side_effect=[
                _proc(returncode=0, stdout=status_payload),
                _proc(returncode=0, stdout=show_unit_payload),
            ],
        ):
            snapshot = capture_databag_snapshot("dev")

        assert len(snapshot.entries) == 1
        unit_name, endpoint, related_app, keys = snapshot.entries[0]
        assert unit_name == "my/0"
        assert endpoint == "db"
        assert related_app == "pg"
        assert keys == frozenset({"username", "password"})

    def test_show_unit_returncode_failure_skips_app(self) -> None:
        status_payload = json.dumps({"applications": {"my": {"units": {"my/0": {}}}}})
        with patch(
            "subprocess.run",
            side_effect=[
                _proc(returncode=0, stdout=status_payload),
                _proc(returncode=1, stderr="show-unit failed"),
            ],
        ):
            snapshot = capture_databag_snapshot("dev")
        assert snapshot == DatabagSnapshot()

    def test_show_unit_subprocess_error_skips_app(self) -> None:
        status_payload = json.dumps({"applications": {"my": {"units": {"my/0": {}}}}})
        import subprocess as _subprocess

        # First subprocess.run returns the status; the second raises.
        call_count = {"n": 0}

        def _mock_run(*_args: object, **_kwargs: object) -> MagicMock:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _proc(returncode=0, stdout=status_payload)
            raise _subprocess.TimeoutExpired(cmd="juju", timeout=15)

        with patch("subprocess.run", side_effect=_mock_run):
            snapshot = capture_databag_snapshot("dev")
        assert snapshot == DatabagSnapshot()

    def test_skips_apps_with_no_units(self) -> None:
        status_payload = json.dumps({"applications": {"my": {"units": {}}}})
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout=status_payload),
        ):
            snapshot = capture_databag_snapshot("dev")
        assert snapshot == DatabagSnapshot()


# ---------------------------------------------------------------------------
# EventWatcher properties
# ---------------------------------------------------------------------------


class TestLatestCosStatus:
    """Accessor for ``latest_cos_status``."""

    def test_default_none(self) -> None:
        assert EventWatcher(dev_model="dev").latest_cos_status is None

    def test_returns_set_value(self) -> None:
        w = EventWatcher(dev_model="dev")
        sentinel = MagicMock()
        w._latest_cos_status = sentinel
        assert w.latest_cos_status is sentinel


# ---------------------------------------------------------------------------
# Polling loops — exception arms and once-method bodies
# ---------------------------------------------------------------------------


class TestPollStatusOnce:
    """Exercise ``_poll_status_once`` body branches."""

    @pytest.mark.asyncio
    async def test_status_poll_publishes_callback(self) -> None:
        called: list[str] = []
        watcher = EventWatcher(dev_model="dev", on_status_poll=called.append)

        fake_status = MagicMock(spec=jubilant.Status)
        fake_status.apps = {}
        fake_status.offers = {}

        with (
            patch("cantrip.agent.watcher.jubilant.Juju") as juju_cls,
            patch(
                "cantrip.agent.watcher.diff_snapshots",
                return_value=[],
            ),
        ):
            juju = juju_cls.return_value
            juju.status.return_value = fake_status
            await watcher._poll_status_once()
        assert called == ["dev"]
        assert watcher.latest_status is fake_status

    @pytest.mark.asyncio
    async def test_status_poll_with_databag_snapshot(self) -> None:
        config = WatcherConfig(snapshot_databags=True)
        watcher = EventWatcher(dev_model="dev", config=config)

        fake_status = MagicMock(spec=jubilant.Status)
        fake_status.apps = {}
        fake_status.offers = {}

        with (
            patch("cantrip.agent.watcher.jubilant.Juju") as juju_cls,
            patch("cantrip.agent.watcher.diff_snapshots", return_value=[]),
            patch(
                "cantrip.agent.watcher.capture_databag_snapshot",
                return_value=DatabagSnapshot(),
            ),
            patch(
                "cantrip.agent.watcher.diff_databag_snapshots",
                return_value=[],
            ),
        ):
            juju_cls.return_value.status.return_value = fake_status
            await watcher._poll_status_once()
        assert watcher._last_databag is not None

    @pytest.mark.asyncio
    async def test_status_poll_databag_oserror_swallowed(self) -> None:
        config = WatcherConfig(snapshot_databags=True)
        watcher = EventWatcher(dev_model="dev", config=config)

        fake_status = MagicMock(spec=jubilant.Status)
        fake_status.apps = {}
        fake_status.offers = {}

        with (
            patch("cantrip.agent.watcher.jubilant.Juju") as juju_cls,
            patch("cantrip.agent.watcher.diff_snapshots", return_value=[]),
            patch(
                "cantrip.agent.watcher.capture_databag_snapshot",
                side_effect=OSError("eperm"),
            ),
        ):
            juju_cls.return_value.status.return_value = fake_status
            await watcher._poll_status_once()  # must not raise


class TestStatusOnceDatabagEnqueue:
    """``_poll_status_once`` databag enqueue branch."""

    @pytest.mark.asyncio
    async def test_databag_event_is_enqueued(self) -> None:
        from cantrip.agent.watcher import WatcherEvent

        config = WatcherConfig(snapshot_databags=True)
        watcher = EventWatcher(dev_model="dev", config=config)

        fake_status = MagicMock(spec=jubilant.Status)
        fake_status.apps = {}
        fake_status.offers = {}

        databag_event = WatcherEvent(
            source="watcher",
            category="databag_change",
            summary="databag changed",
            detail="",
        )

        with (
            patch("cantrip.agent.watcher.jubilant.Juju") as juju_cls,
            patch("cantrip.agent.watcher.diff_snapshots", return_value=[]),
            patch(
                "cantrip.agent.watcher.capture_databag_snapshot",
                return_value=DatabagSnapshot(),
            ),
            patch(
                "cantrip.agent.watcher.diff_databag_snapshots",
                return_value=[databag_event],
            ),
        ):
            juju_cls.return_value.status.return_value = fake_status
            await watcher._poll_status_once()
        assert watcher.queue_size == 1


class TestLoopCancellation:
    """All three polling loops re-raise asyncio.CancelledError."""

    @pytest.mark.asyncio
    async def test_status_loop_cancellation_propagates(self) -> None:
        watcher = EventWatcher(dev_model="dev")
        watcher._running = True

        async def _cancel() -> None:
            raise asyncio.CancelledError

        with (
            patch.object(watcher, "_poll_status_once", side_effect=_cancel),
            pytest.raises(asyncio.CancelledError),
        ):
            await watcher._poll_status_loop()

    @pytest.mark.asyncio
    async def test_cos_status_loop_cancellation_propagates(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        watcher._running = True

        async def _cancel() -> None:
            raise asyncio.CancelledError

        with (
            patch.object(watcher, "_poll_cos_status_once", side_effect=_cancel),
            pytest.raises(asyncio.CancelledError),
        ):
            await watcher._poll_cos_status_loop()

    @pytest.mark.asyncio
    async def test_loki_loop_cancellation_propagates(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        watcher._running = True

        async def _cancel() -> None:
            raise asyncio.CancelledError

        with (
            patch.object(watcher, "_poll_loki_once", side_effect=_cancel),
            pytest.raises(asyncio.CancelledError),
        ):
            await watcher._poll_loki_loop()


class TestCaptureDatabagStatusFailure:
    """``capture_databag_snapshot`` returns empty when status rc != 0."""

    def test_status_returncode_failure(self) -> None:
        with patch("subprocess.run", return_value=_proc(returncode=1, stderr="auth fail")):
            assert capture_databag_snapshot("dev") == DatabagSnapshot()


class TestPollStatusLoopExceptions:
    """``_poll_status_loop`` swallows jubilant / OS / Timeout errors."""

    @pytest.mark.asyncio
    async def test_loop_swallows_clierror(self) -> None:
        watcher = EventWatcher(dev_model="dev")
        watcher._running = True

        async def _raise_then_stop() -> None:
            watcher._running = False
            raise jubilant.CLIError(returncode=1, cmd="juju", output="", stderr="boom")

        with (
            patch.object(watcher, "_poll_status_once", side_effect=_raise_then_stop),
            patch(
                "cantrip.agent.watcher.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            # The loop body runs once: the once() raises CLIError (covered),
            # the except arm logs (covered), the sleep is awaited, and the
            # while condition reads False so the loop exits.
            await watcher._poll_status_loop()


class TestPollCosStatusOnce:
    """COS status poll fires the on_status_poll hook."""

    @pytest.mark.asyncio
    async def test_cos_status_poll_publishes_callback(self) -> None:
        called: list[str] = []
        watcher = EventWatcher(dev_model="dev", cos_model="cos", on_status_poll=called.append)
        fake_status = MagicMock()
        with patch("cantrip.agent.watcher.jubilant.Juju") as juju_cls:
            juju_cls.return_value.status.return_value = fake_status
            await watcher._poll_cos_status_once()
        assert called == ["cos"]
        assert watcher.latest_cos_status is fake_status


class TestPollCosStatusLoopExceptions:
    """``_poll_cos_status_loop`` swallows jubilant / OS / Timeout errors."""

    @pytest.mark.asyncio
    async def test_loop_swallows_oserror(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        watcher._running = True

        async def _raise_then_stop() -> None:
            watcher._running = False
            raise OSError("eperm")

        with (
            patch.object(watcher, "_poll_cos_status_once", side_effect=_raise_then_stop),
            patch("cantrip.agent.watcher.asyncio.sleep", new_callable=AsyncMock),
        ):
            await watcher._poll_cos_status_loop()


class TestPollLokiLoopExceptions:
    """``_poll_loki_loop`` swallows OS / Timeout / ValueError."""

    @pytest.mark.asyncio
    async def test_loop_swallows_value_error(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        watcher._running = True

        async def _raise_then_stop() -> None:
            watcher._running = False
            raise ValueError("bad")

        with (
            patch.object(watcher, "_poll_loki_once", side_effect=_raise_then_stop),
            patch("cantrip.agent.watcher.asyncio.sleep", new_callable=AsyncMock),
        ):
            await watcher._poll_loki_loop()


class TestPollLokiOnce:
    """``_poll_loki_once`` malformed-response and undersized-entry paths."""

    @pytest.mark.asyncio
    async def test_no_cos_model_returns_immediately(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model=None)
        # Should not call _find_cos_unit because cos_model is None.
        with patch("cantrip.agent.watcher._find_cos_unit") as find:
            await watcher._poll_loki_once()
        find.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_json_logs_and_returns(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        juju = MagicMock()
        juju.ssh.return_value = "not json"
        with patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(juju, "loki/0"),
        ):
            await watcher._poll_loki_once()
        # No event was enqueued because JSON parsing failed.
        assert watcher.queue_size == 0

    @pytest.mark.asyncio
    async def test_entry_shorter_than_two_is_skipped(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        juju = MagicMock()
        juju.ssh.return_value = json.dumps(
            {
                "data": {
                    "result": [
                        {
                            "stream": {
                                "juju_application": "myapp",
                                "juju_unit": "myapp/0",
                            },
                            # Each "values" entry must be ``[ts, message]``;
                            # a 1-tuple is malformed and must be skipped without
                            # crashing.
                            "values": [["only-ts"], ["123", "real log line"]],
                        }
                    ]
                }
            }
        )
        with patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(juju, "loki/0"),
        ):
            await watcher._poll_loki_once()
        # Only the well-formed entry made it through to the queue.
        assert watcher.queue_size == 1

    @pytest.mark.asyncio
    async def test_loki_unit_not_found(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        with patch(
            "cantrip.agent.watcher._find_cos_unit",
            side_effect=ValueError("not found"),
        ):
            await watcher._poll_loki_once()
        assert watcher.queue_size == 0

    @pytest.mark.asyncio
    async def test_ssh_clierror(self) -> None:
        watcher = EventWatcher(dev_model="dev", cos_model="cos")
        juju = MagicMock()
        juju.ssh.side_effect = jubilant.CLIError(
            returncode=1, cmd="ssh", output="", stderr="ssh died"
        )
        with patch(
            "cantrip.agent.watcher._find_cos_unit",
            return_value=(juju, "loki/0"),
        ):
            await watcher._poll_loki_once()
        assert watcher.queue_size == 0
