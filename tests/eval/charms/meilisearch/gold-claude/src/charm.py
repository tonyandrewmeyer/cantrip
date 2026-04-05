#!/usr/bin/env python3
"""Meilisearch full-text search engine charm."""

import json
import logging
import typing

import ops

logger = logging.getLogger(__name__)

# Mount point for Juju storage inside the workload container.
_DATA_MOUNT = "/var/lib/meilisearch"


class MeilisearchCharm(ops.CharmBase):
    """Charm for the Meilisearch search engine."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(
            self.on["meilisearch"].pebble_ready, self._on_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.create_snapshot_action, self._on_create_snapshot)
        self.framework.observe(self.on.create_dump_action, self._on_create_dump)
        self.framework.observe(self.on.get_keys_action, self._on_get_keys)

        # Relation for client charms to discover the search endpoint.
        self.framework.observe(
            self.on["meilisearch"].relation_joined, self._on_client_joined
        )

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure the workload once Pebble is available."""
        self._update_workload()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """React to configuration changes."""
        self._update_workload()

    def _on_client_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Publish connection details to client charms."""
        if not self.unit.is_leader():
            return
        master_key = typing.cast(str, self.config.get("master-key", ""))
        event.relation.data[self.app].update({
            "host": self.app.name,
            "port": "7700",
            "master-key": master_key,
        })

    def _on_create_snapshot(self, event: ops.ActionEvent) -> None:
        """Trigger a snapshot via the Meilisearch API."""
        result = self._api_post("/snapshots")
        if result is None:
            event.fail("Could not reach Meilisearch API.")
            return
        event.set_results({"task": result})

    def _on_create_dump(self, event: ops.ActionEvent) -> None:
        """Trigger a dump via the Meilisearch API."""
        result = self._api_post("/dumps")
        if result is None:
            event.fail("Could not reach Meilisearch API.")
            return
        event.set_results({"task": result})

    def _on_get_keys(self, event: ops.ActionEvent) -> None:
        """List API keys via the Meilisearch API."""
        result = self._api_get("/keys")
        if result is None:
            event.fail("Could not reach Meilisearch API.")
            return
        event.set_results({"keys": result})

    # -----------------------------------------------------------------
    # Workload configuration
    # -----------------------------------------------------------------

    def _update_workload(self) -> None:
        """Reconcile the Pebble layer with current configuration."""
        container = self.unit.get_container("meilisearch")
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for Pebble")
            return

        master_key = typing.cast(str, self.config.get("master-key", ""))
        environment = typing.cast(str, self.config.get("environment", "production"))

        if environment == "production" and not master_key:
            self.unit.status = ops.BlockedStatus(
                "master-key is required in production mode"
            )
            return

        env = {
            "MEILI_DB_PATH": f"{_DATA_MOUNT}/data.ms",
            "MEILI_HTTP_ADDR": "0.0.0.0:7700",
            "MEILI_ENV": environment,
            "MEILI_LOG_LEVEL": typing.cast(
                str, self.config.get("log-level", "INFO")
            ),
            "MEILI_SNAPSHOT_DIR": f"{_DATA_MOUNT}/snapshots",
            "MEILI_DUMP_DIR": f"{_DATA_MOUNT}/dumps",
            "MEILI_NO_ANALYTICS": "true",
        }

        if master_key:
            env["MEILI_MASTER_KEY"] = master_key

        max_mem = self.config.get("max-indexing-memory")
        if max_mem:
            env["MEILI_MAX_INDEXING_MEMORY"] = typing.cast(str, max_mem)

        snap_interval = self.config.get("scheduled-snapshot-interval", 0)
        if snap_interval:
            env["MEILI_SCHEDULE_SNAPSHOT"] = str(snap_interval)

        layer = ops.pebble.Layer({
            "summary": "meilisearch layer",
            "services": {
                "meilisearch": {
                    "override": "replace",
                    "command": "/bin/meilisearch",
                    "startup": "enabled",
                    "environment": env,
                },
            },
            "checks": {
                "meilisearch-health": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:7700/health"},
                },
            },
        })
        container.add_layer("meilisearch", layer, combine=True)
        container.autostart()
        self.unit.status = ops.ActiveStatus()

    # -----------------------------------------------------------------
    # API helpers
    # -----------------------------------------------------------------

    def _api_post(self, path: str) -> str | None:
        """POST to the Meilisearch API via the workload container."""
        container = self.unit.get_container("meilisearch")
        if not container.can_connect():
            return None

        master_key = typing.cast(str, self.config.get("master-key", ""))
        headers = f"-H 'Authorization: Bearer {master_key}'" if master_key else ""
        cmd = ["sh", "-c", f"curl -s -X POST {headers} http://localhost:7700{path}"]

        process = container.exec(cmd)
        try:
            stdout, _ = process.wait_output()
            return stdout.strip()
        except ops.pebble.ExecError:
            return None

    def _api_get(self, path: str) -> str | None:
        """GET from the Meilisearch API via the workload container."""
        container = self.unit.get_container("meilisearch")
        if not container.can_connect():
            return None

        master_key = typing.cast(str, self.config.get("master-key", ""))
        headers = f"-H 'Authorization: Bearer {master_key}'" if master_key else ""
        cmd = ["sh", "-c", f"curl -s {headers} http://localhost:7700{path}"]

        process = container.exec(cmd)
        try:
            stdout, _ = process.wait_output()
            return stdout.strip()
        except ops.pebble.ExecError:
            return None


if __name__ == "__main__":
    ops.main(MeilisearchCharm)
