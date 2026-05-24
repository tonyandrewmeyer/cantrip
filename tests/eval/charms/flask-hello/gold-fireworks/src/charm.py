#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Flask Hello charm — a machine charm for a simple Flask web application.

Install layout (see ``flask_hello`` helper module for the implementation):

* App and virtualenv: ``/srv/flask-hello/`` and ``/srv/flask-hello/venv``.
* App dependencies installed via ``pip install -r requirements-app.txt`` into
  the venv after ``apt-get install python3-venv python3-pip``.
* Config file: ``/etc/flask-hello/config.env`` (DATABASE_URL etc.).
* Service: managed by ``systemd`` as ``flask-hello.service`` on port 5000.
"""

import logging
import os

import flask_hello
import ops

logger = logging.getLogger(__name__)

DATABASE_URL_KEY = "database_url"


class FlaskHelloCharm(ops.CharmBase):
    """Charm the Flask Hello application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Lifecycle events
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.update_status, self._on_update_status)

        # Config events
        framework.observe(self.on.config_changed, self._on_config_changed)

        # Relation events
        framework.observe(self.on.postgresql_relation_changed, self._on_database_relation_changed)
        framework.observe(self.on.postgresql_relation_broken, self._on_database_relation_broken)
        framework.observe(self.on.nginx_route_relation_joined, self._on_nginx_relation_joined)
        framework.observe(self.on.nginx_route_relation_changed, self._on_nginx_relation_changed)
        framework.observe(self.on.nginx_route_relation_broken, self._on_nginx_relation_broken)

        # Action events
        framework.observe(self.on.reset_counter_action, self._on_reset_counter)

    # ------------------------------------------------------------------
    # Lifecycle handlers
    # ------------------------------------------------------------------

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install the workload on the machine."""
        self.unit.status = ops.MaintenanceStatus("installing workload")
        try:
            flask_hello.install()
            self._write_config()
            self.unit.status = ops.BlockedStatus("waiting for database relation")
        except Exception as exc:
            logger.exception("Installation failed: %s", exc)
            self.unit.status = ops.BlockedStatus(f"install failed: {exc}")

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        if not self._has_database():
            self.unit.status = ops.BlockedStatus("waiting for database relation")
            return

        self.unit.status = ops.MaintenanceStatus("starting workload")
        try:
            self._start_or_restart_service()
            version = flask_hello.get_version()
            if version is not None:
                self.unit.set_workload_version(version)
            self.unit.status = ops.ActiveStatus()
        except Exception as exc:
            logger.exception("Start failed: %s", exc)
            self.unit.status = ops.BlockedStatus(f"start failed: {exc}")

    def _on_stop(self, event: ops.StopEvent) -> None:
        """Handle stop event."""
        try:
            flask_hello.stop()
        except Exception:
            logger.exception("Stop failed; continuing.")

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Periodic status check."""
        if not self._has_database():
            self.unit.status = ops.BlockedStatus("waiting for database relation")
            return

        if not flask_hello.is_running():
            self.unit.status = ops.MaintenanceStatus("workload not running; restarting")
            try:
                self._start_or_restart_service()
                self.unit.status = ops.ActiveStatus()
            except Exception as exc:
                logger.exception("Restart failed: %s", exc)
                self.unit.status = ops.BlockedStatus(f"restart failed: {exc}")
        else:
            self.unit.status = ops.ActiveStatus()

    # ------------------------------------------------------------------
    # Config handlers
    # ------------------------------------------------------------------

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """React to configuration changes."""
        if not self._has_database():
            self.unit.status = ops.BlockedStatus("waiting for database relation")
            return

        self.unit.status = ops.MaintenanceStatus("applying configuration")
        try:
            self._write_config()
            self._start_or_restart_service()
            self.unit.status = ops.ActiveStatus()
        except Exception as exc:
            logger.exception("Config change failed: %s", exc)
            self.unit.status = ops.BlockedStatus(f"config failed: {exc}")

    # ------------------------------------------------------------------
    # Database relation handlers
    # ------------------------------------------------------------------

    def _on_database_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle database relation data changes."""
        if not self._has_database():
            self.unit.status = ops.BlockedStatus("waiting for database relation")
            return

        self.unit.status = ops.MaintenanceStatus("database connected; starting workload")
        try:
            self._write_config()
            self._start_or_restart_service()
            version = flask_hello.get_version()
            if version is not None:
                self.unit.set_workload_version(version)
            self.unit.status = ops.ActiveStatus()
        except Exception as exc:
            logger.exception("Database setup failed: %s", exc)
            self.unit.status = ops.BlockedStatus(f"database setup failed: {exc}")

    def _on_database_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle database relation removal."""
        try:
            flask_hello.stop()
        except Exception:
            logger.exception("Stop on database broken failed; continuing.")
        self.unit.status = ops.BlockedStatus("waiting for database relation")

    # ------------------------------------------------------------------
    # Nginx (reverseproxy) relation handlers
    # ------------------------------------------------------------------

    def _on_nginx_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Send reverse-proxy configuration to nginx when the relation forms."""
        self._send_nginx_config(event.relation)

    def _on_nginx_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Re-send nginx config if the relation data changes."""
        self._send_nginx_config(event.relation)

    def _on_nginx_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle nginx relation removal."""
        logger.info("Nginx reverse-proxy relation removed.")

    def _send_nginx_config(self, relation: ops.Relation) -> None:
        """Publish reverse-proxy configuration to the nginx relation."""
        relation.data[self.unit]["hostname"] = str(
            self.model.get_binding(relation).network.bind_address or "127.0.0.1"
        )
        relation.data[self.unit]["port"] = "5000"

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_reset_counter(self, event: ops.ActionEvent) -> None:
        """Reset the page-view counter in the database."""
        if not self._has_database():
            event.fail("No database relation available.")
            return

        try:
            # Set DATABASE_URL in the environment so psycopg2 can connect
            db_url = self._get_database_url()
            if db_url:
                os.environ["DATABASE_URL"] = db_url
            flask_hello.reset_database_counter()
            event.set_results({"result": "counter reset successfully"})
        except Exception as exc:
            logger.exception("Reset counter failed: %s", exc)
            event.fail(f"Failed to reset counter: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_database(self) -> bool:
        """Return True if a database relation with a valid URL is present."""
        return self._get_database_url() is not None

    def _get_database_url(self) -> str | None:
        """Extract DATABASE_URL from the postgresql_client relation data."""
        relation = self.model.get_relation("postgresql")
        if relation is None:
            return None

        # Try to read from the remote application databag
        for unit in relation.units:
            data = relation.data[unit]
            url = data.get("database_url") or data.get("connection_string")
            if url:
                return url

        # Also check application-level data
        app_data = relation.data.get(relation.app)
        if app_data:
            url = app_data.get("database_url") or app_data.get("connection_string")
            if url:
                return url

        return None

    def _write_config(self) -> None:
        """Write the workload configuration file."""
        db_url = self._get_database_url()
        log_level = self.config.get("log-level", "info")
        debug = bool(self.config.get("debug", False))
        workers = int(self.config.get("workers", 2))
        flask_hello.write_config(
            database_url=db_url,
            log_level=log_level,
            debug=debug,
            workers=workers,
        )

    def _start_or_restart_service(self) -> None:
        """Start or restart the systemd service."""
        if flask_hello.is_running():
            flask_hello.restart()
        else:
            flask_hello.start()


if __name__ == "__main__":  # pragma: nocover
    ops.main(FlaskHelloCharm)
