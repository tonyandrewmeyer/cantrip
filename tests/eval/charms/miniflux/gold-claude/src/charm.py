#!/usr/bin/env python3
"""Miniflux RSS reader charm."""

import logging
import typing

import ops

logger = logging.getLogger(__name__)


class MinifluxCharm(ops.CharmBase):
    """Charm for the Miniflux RSS feed reader."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on["miniflux"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on["postgresql"].relation_changed, self._on_postgresql_changed
        )
        self.framework.observe(
            self.on["postgresql"].relation_broken, self._on_postgresql_broken
        )
        self.framework.observe(self.on.create_admin_action, self._on_create_admin)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure the workload once Pebble is available."""
        self._update_workload()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """React to charm configuration changes."""
        self._update_workload()

    def _on_postgresql_changed(self, event: ops.RelationChangedEvent) -> None:
        """React to database relation data becoming available."""
        self._update_workload()

    def _on_postgresql_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle database relation removal."""
        self.unit.status = ops.BlockedStatus("waiting for postgresql relation")

    def _on_create_admin(self, event: ops.ActionEvent) -> None:
        """Create an admin user inside the running workload."""
        container = self.unit.get_container("miniflux")
        if not container.can_connect():
            event.fail("Workload container not ready.")
            return

        db_url = self._database_url()
        if not db_url:
            event.fail("No database connection available.")
            return

        username = typing.cast(str, event.params.get("username", "admin"))
        password = typing.cast(str, event.params.get("password", ""))
        if not password:
            event.fail("password is required")
            return

        env = {"DATABASE_URL": db_url, "CREATE_ADMIN": "1",
               "ADMIN_USERNAME": username, "ADMIN_PASSWORD": password}
        process = container.exec(["/usr/bin/miniflux", "-create-admin"], environment=env)
        try:
            stdout, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            event.fail(f"Failed to create admin: {exc.stderr}")
            return

        event.set_results({"username": username, "result": stdout.strip()})

    # -----------------------------------------------------------------
    # Workload configuration
    # -----------------------------------------------------------------

    def _update_workload(self) -> None:
        """Reconcile the Pebble layer with current config and relations."""
        container = self.unit.get_container("miniflux")
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for Pebble")
            return

        db_url = self._database_url()
        if not db_url:
            self.unit.status = ops.BlockedStatus("waiting for postgresql relation")
            return

        env = {
            "DATABASE_URL": db_url,
            "RUN_MIGRATIONS": "1",
            "LISTEN_ADDR": "0.0.0.0:8080",
            "POLLING_FREQUENCY": str(self.config.get("polling-frequency", 60)),
            "WORKER_POOL_SIZE": str(self.config.get("worker-pool-size", 16)),
        }
        base_url = self.config.get("base-url")
        if base_url:
            env["BASE_URL"] = typing.cast(str, base_url)

        layer = ops.pebble.Layer({
            "summary": "miniflux layer",
            "services": {
                "miniflux": {
                    "override": "replace",
                    "command": "/usr/bin/miniflux",
                    "startup": "enabled",
                    "environment": env,
                },
            },
            "checks": {
                "miniflux-health": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:8080/healthcheck"},
                },
            },
        })
        container.add_layer("miniflux", layer, combine=True)
        container.autostart()
        self.unit.status = ops.ActiveStatus()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _database_url(self) -> str | None:
        """Build a PostgreSQL connection string from relation data."""
        rel = self.model.get_relation("postgresql")
        if rel is None:
            return None
        data = rel.data.get(rel.app)
        if not data:
            return None
        endpoints = data.get("endpoints", "")
        username = data.get("username", "")
        password = data.get("password", "")
        database = data.get("database", "")
        if not all([endpoints, username, password, database]):
            return None
        host_port = endpoints.split(",")[0]
        return f"postgresql://{username}:{password}@{host_port}/{database}"


if __name__ == "__main__":
    ops.main(MinifluxCharm)
