#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Alertmanager machine charm.

This charm installs Prometheus Alertmanager from the Snap Store, manages its
systemd service, generates configuration from charm options, supports HA
clustering via a peer relation, and integrates with the Canonical Observability
Stack (COS).
"""

import logging

import alertmanager
import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

logger = logging.getLogger(__name__)

ALERTMANAGER_PORT = 9093
METRICS_PATH = "/metrics"


class AlertmanagerCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        # COS integrations
        self._metrics_provider = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "metrics_path": METRICS_PATH,
                    "static_configs": [{"targets": [f"*:{ALERTMANAGER_PORT}"]}],
                }
            ],
        )
        self._grafana_provider = GrafanaDashboardProvider(
            self,
            dashboards_path="./src/grafana_dashboards",
        )
        self._log_consumer = LogProxyConsumer(
            self,
            relation_name="logging",
            log_files=["/var/snap/alertmanager/common/logs/alertmanager.log"],
        )

        # Event observers
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(
            self.on.replicas_relation_changed,
            self._on_replicas_changed,
        )
        framework.observe(
            self.on.replicas_relation_departed,
            self._on_replicas_changed,
        )
        framework.observe(
            self.on.alerting_relation_joined,
            self._on_alerting_relation_joined,
        )
        framework.observe(
            self.on.send_test_alert_action,
            self._on_send_test_alert_action,
        )

    # ------------------------------------------------------------------ #
    #  Lifecycle hooks
    # ------------------------------------------------------------------ #

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install Alertmanager from the Snap Store."""
        self.unit.status = ops.MaintenanceStatus("installing alertmanager snap")
        try:
            alertmanager.install()
        except Exception as e:
            logger.exception("Failed to install alertmanager snap")
            self.unit.status = ops.BlockedStatus(f"install failed: {e}")
            return
        self.unit.status = ops.MaintenanceStatus("alertmanager installed")

    def _on_start(self, event: ops.StartEvent) -> None:
        """Start Alertmanager and open the service port."""
        self.unit.status = ops.MaintenanceStatus("starting alertmanager")
        self._configure_alertmanager()
        version = alertmanager.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.open_port("tcp", ALERTMANAGER_PORT)
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Regenerate configuration and reload the service."""
        self.unit.status = ops.MaintenanceStatus("reconfiguring alertmanager")
        self._configure_alertmanager()
        self.unit.status = ops.ActiveStatus()

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Update workload version and verify service health."""
        version = alertmanager.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        if not alertmanager.is_service_active():
            self.unit.status = ops.BlockedStatus("alertmanager service is not running")
            return
        self.unit.status = ops.ActiveStatus()

    # ------------------------------------------------------------------ #
    #  Peer / HA clustering
    # ------------------------------------------------------------------ #

    def _on_replicas_changed(self, event: ops.EventBase) -> None:
        """Regenerate cluster peers when the peer relation changes."""
        self.unit.status = ops.MaintenanceStatus("updating cluster peers")
        self._configure_alertmanager()
        self.unit.status = ops.ActiveStatus()

    def _peer_addresses(self) -> list[str] | None:
        """Return a list of peer cluster addresses from the replicas relation."""
        relation = self.model.get_relation("replicas")
        if relation is None:
            return None
        addresses: list[str] = []
        for unit in relation.units:
            if unit == self.unit:
                continue
            addr = relation.data[unit].get("private-address")
            if addr:
                addresses.append(f"{addr}:{ALERTMANAGER_PORT}")
        return addresses if addresses else None

    def _set_peer_data(self) -> None:
        """Publish this unit's address into the peer relation databag."""
        relation = self.model.get_relation("replicas")
        if relation is None:
            return
        relation.data[self.unit]["private-address"] = str(
            self.model.get_binding(relation).network.bind_address
        )

    # ------------------------------------------------------------------ #
    #  Alerting relation (provides)
    # ------------------------------------------------------------------ #

    def _on_alerting_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Publish this Alertmanager's API URL to Prometheus."""
        bind_address = self.model.get_binding(event.relation).network.bind_address
        if bind_address is None:
            event.defer()
            return
        url = f"http://{bind_address}:{ALERTMANAGER_PORT}"
        event.relation.data[self.app]["alertmanager_url"] = url

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #

    def _on_send_test_alert_action(self, event: ops.ActionEvent) -> None:
        """Send a synthetic test alert to the local Alertmanager."""
        if not alertmanager.is_service_active():
            event.fail("Alertmanager service is not active")
            return
        try:
            alertmanager.send_test_alert()
            event.set_results({"result": "Test alert sent successfully"})
        except Exception as e:
            logger.exception("Failed to send test alert")
            event.fail(f"Failed to send test alert: {e}")

    # ------------------------------------------------------------------ #
    #  Configuration helpers
    # ------------------------------------------------------------------ #

    def _configure_alertmanager(self) -> None:
        """Write alertmanager.yml and (re)start the service."""
        self._set_peer_data()
        resolve_timeout = self.config.get("resolve-timeout", "5m")
        log_level = self.config.get("log-level", "info")
        smtp_smarthost = self.config.get("smtp-smarthost", "")
        smtp_from = self.config.get("smtp-from", "")
        peers = self._peer_addresses()

        alertmanager.write_and_reload(
            resolve_timeout=resolve_timeout,
            log_level=log_level,
            smtp_smarthost=smtp_smarthost,
            smtp_from=smtp_from,
            peer_addresses=peers,
        )


if __name__ == "__main__":  # pragma: nocover
    ops.main(AlertmanagerCharm)
