#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Meilisearch Kubernetes charm."""

import logging

import meilisearch
import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

logger = logging.getLogger(__name__)

SERVICE_NAME = "meilisearch"
MEILI_PORT = 7700
MEILI_DB_PATH = "/meili_data"
MEILI_SNAPSHOT_PATH = "/meili_snapshots"
MEILI_DUMP_PATH = "/meili_dumps"


class MeilisearchK8SCharm(ops.CharmBase):
    """Charm for Meilisearch on Kubernetes."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container("meilisearch")

        # Observe core lifecycle events
        framework.observe(self.on.meilisearch.pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.stop, self._on_stop)

        # Actions
        framework.observe(self.on.create_snapshot_action, self._on_create_snapshot_action)
        framework.observe(self.on.create_dump_action, self._on_create_dump_action)
        framework.observe(self.on.get_keys_action, self._on_get_keys_action)

        # COS integrations
        self._log_forwarder = LogForwarder(self, relation_name="logging")
        self._metrics_provider = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "metrics_path": "/metrics",
                    "static_configs": [{"targets": [f"*:{MEILI_PORT}"]}],
                }
            ],
            relation_name="metrics-endpoint",
        )
        self._grafana_dashboard = GrafanaDashboardProvider(self, relation_name="grafana-dashboard")

        # Client relation
        framework.observe(
            self.on["meilisearch-client"].relation_changed,
            self._on_meilisearch_client_relation_changed,
        )
        framework.observe(
            self.on["meilisearch-client"].relation_departed,
            self._on_meilisearch_client_relation_departed,
        )

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Handle pebble-ready event."""
        self.unit.status = ops.MaintenanceStatus("starting workload")
        self._configure_workload()
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        if not self.container.can_connect():
            event.defer()
            return

        self.unit.status = ops.MaintenanceStatus("reconfiguring workload")
        self._configure_workload()
        self.unit.status = ops.ActiveStatus()

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Handle update-status event."""
        if not self.container.can_connect():
            return

        if not meilisearch.is_healthy(self.container, MEILI_PORT):
            self.unit.status = ops.BlockedStatus("workload not healthy")
            return

        version = meilisearch.get_version(self.container, MEILI_PORT)
        if version is not None:
            self.unit.set_workload_version(version)

        self.unit.status = ops.ActiveStatus()

    def _on_stop(self, event: ops.StopEvent) -> None:
        """Handle stop event."""
        self.unit.status = ops.MaintenanceStatus("stopping workload")

    def _configure_workload(self) -> None:
        """Configure and start the Meilisearch workload."""
        if not self.container.can_connect():
            logger.warning("container not ready, skipping workload configuration")
            return

        env = self._build_environment()
        layer: ops.pebble.LayerDict = {
            "services": {
                SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Meilisearch full-text search engine",
                    "command": "/bin/meilisearch",
                    "startup": "enabled",
                    "environment": env,
                    "on-check-failure": {"meilisearch-ready": "restart"},
                }
            },
            "checks": {
                "meilisearch-ready": {
                    "override": "replace",
                    "period": "10s",
                    "threshold": 3,
                    "http": {
                        "url": f"http://localhost:{MEILI_PORT}/health",
                    },
                }
            },
        }
        self.container.add_layer("meilisearch", layer, combine=True)
        self.container.replan()

    def _build_environment(self) -> dict[str, str]:
        """Build the environment variables for Meilisearch."""
        env: dict[str, str] = {
            "MEILI_HTTP_ADDR": f"0.0.0.0:{MEILI_PORT}",
            "MEILI_DB_PATH": MEILI_DB_PATH,
            "MEILI_ENV": self.config["environment"],
            "MEILI_LOG_LEVEL": self.config["log-level"],
        }

        master_key = self.config["master-key"]
        if master_key:
            env["MEILI_MASTER_KEY"] = master_key

        max_memory = self.config["max-indexing-memory"]
        if max_memory > 0:
            env["MEILI_MAX_INDEXING_MEMORY"] = str(max_memory)

        snapshot_interval = self.config["scheduled-snapshot-interval"]
        if snapshot_interval > 0:
            env["MEILI_SCHEDULE_SNAPSHOT"] = "true"
            env["MEILI_SNAPSHOT_INTERVAL_SEC"] = str(snapshot_interval)
            env["MEILI_SNAPSHOT_DIR"] = MEILI_SNAPSHOT_PATH

        return env

    def _on_create_snapshot_action(self, event: ops.ActionEvent) -> None:
        """Handle create-snapshot action."""
        if not self.container.can_connect():
            event.fail("container not ready")
            return

        master_key = self.config["master-key"]
        if not master_key:
            event.fail("master-key must be configured to create snapshots")
            return

        event.log("Creating Meilisearch snapshot...")
        try:
            result = meilisearch.create_snapshot(self.container, MEILI_PORT, master_key)
            event.set_results({"result": result})
        except Exception as e:
            logger.exception("snapshot creation failed")
            event.fail(f"failed to create snapshot: {e}")

    def _on_create_dump_action(self, event: ops.ActionEvent) -> None:
        """Handle create-dump action."""
        if not self.container.can_connect():
            event.fail("container not ready")
            return

        master_key = self.config["master-key"]
        if not master_key:
            event.fail("master-key must be configured to create dumps")
            return

        event.log("Creating Meilisearch dump...")
        try:
            result = meilisearch.create_dump(self.container, MEILI_PORT, master_key)
            event.set_results({"result": result})
        except Exception as e:
            logger.exception("dump creation failed")
            event.fail(f"failed to create dump: {e}")

    def _on_get_keys_action(self, event: ops.ActionEvent) -> None:
        """Handle get-keys action."""
        if not self.container.can_connect():
            event.fail("container not ready")
            return

        master_key = self.config["master-key"]
        if not master_key:
            event.fail("master-key must be configured to retrieve keys")
            return

        event.log("Fetching Meilisearch API keys...")
        try:
            keys = meilisearch.get_keys(self.container, MEILI_PORT, master_key)
            event.set_results({"keys": keys})
        except Exception as e:
            logger.exception("key retrieval failed")
            event.fail(f"failed to retrieve keys: {e}")

    def _on_meilisearch_client_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle client relation changed."""
        self._update_client_relation_data(event.relation)

    def _on_meilisearch_client_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle client relation departed."""
        if event.relation:
            event.relation.data[self.app].clear()

    def _update_client_relation_data(self, relation: ops.Relation) -> None:
        """Update relation data with connection info for clients."""
        if not self.unit.is_leader():
            return

        host = self.app.name
        master_key = self.config["master-key"]
        relation.data[self.app].update(
            {
                "host": host,
                "port": str(MEILI_PORT),
                "api-key": master_key,
            }
        )


if __name__ == "__main__":  # pragma: nocover
    ops.main(MeilisearchK8SCharm)
