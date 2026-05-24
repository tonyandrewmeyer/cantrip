#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Charm the ntfy push notification server."""

import logging
import time
from pathlib import Path

import ntfy
import ops
import yaml

logger = logging.getLogger(__name__)

SERVICE_NAME = "ntfy"
CONFIG_PATH = "/etc/ntfy/server.yml"
CACHE_DIR = "/var/cache/ntfy"
ATTACHMENTS_DIR = "/var/lib/ntfy/attachments"
CACHE_FILE = f"{CACHE_DIR}/cache.db"
AUTH_FILE = f"{CACHE_DIR}/auth.db"


class NtfyK8SCharm(ops.CharmBase):
    """Charm the ntfy push notification server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container("ntfy")

        framework.observe(self.on["ntfy"].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on["ingress"].relation_changed, self._on_ingress_changed)
        framework.observe(self.on["ingress"].relation_broken, self._on_ingress_changed)

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Handle pebble-ready event."""
        self._reconcile(event)

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle config-changed event."""
        self._reconcile(event)

    def _on_ingress_changed(self, event: ops.RelationEvent):
        """Handle ingress relation changes."""
        self._reconcile(event)

    def _reconcile(self, event: ops.EventBase):
        """Reconcile charm state and workload configuration."""
        if not self.container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for container")
            event.defer()
            return

        self.unit.status = ops.MaintenanceStatus("configuring workload")

        self._write_config()
        self._ensure_directories()
        self._add_pebble_layer()
        self.container.replan()

        self._wait_for_ready()
        version = ntfy.get_version(self.container)
        if version is not None:
            self.unit.set_workload_version(version)

        self.unit.status = ops.ActiveStatus()

    def _write_config(self):
        """Generate the ntfy server configuration file."""
        config = self._build_ntfy_config()
        config_yaml = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)
        self.container.push(CONFIG_PATH, config_yaml, make_dirs=True)
        logger.info("wrote ntfy config to %s", CONFIG_PATH)

    def _build_ntfy_config(self) -> dict:
        """Build the ntfy server configuration dictionary."""
        base_url = self.config.get("base-url", "")
        cache_duration = self.config.get("cache-duration", "12h")
        log_level = self.config.get("log-level", "info")
        auth_default_access = self.config.get("auth-default-access", "deny-all")
        enable_metrics = self.config.get("enable-metrics", False)

        config: dict = {
            "base-url": base_url,
            "listen-http": ":80",
            "cache-file": CACHE_FILE,
            "auth-file": AUTH_FILE,
            "auth-default-access": auth_default_access,
            "attachment-cache-dir": ATTACHMENTS_DIR,
            "cache-duration": cache_duration,
            "log-level": log_level,
            "behind-proxy": self._has_ingress(),
        }

        if enable_metrics:
            config["enable-metrics"] = True

        return config

    def _has_ingress(self) -> bool:
        """Return True if an ingress relation is established."""
        relation = self.model.get_relation("ingress")
        if relation is None:
            return False
        return len(relation.units) > 0

    def _ensure_directories(self):
        """Ensure required directories exist in the workload container."""
        for directory in (CACHE_DIR, ATTACHMENTS_DIR):
            path = Path(directory)
            self.container.make_dir(str(path), make_parents=True, permissions=0o755)

    def _add_pebble_layer(self):
        """Add the Pebble layer for the ntfy service."""
        layer: ops.pebble.LayerDict = {
            "services": {
                SERVICE_NAME: {
                    "override": "replace",
                    "summary": "ntfy push notification server",
                    "command": "ntfy serve",
                    "startup": "enabled",
                    "environment": {},
                }
            },
            "checks": {
                "ntfy-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {
                        "url": "http://localhost:80/v1/health",
                    },
                },
            },
        }
        self.container.add_layer("ntfy", layer, combine=True)

    def _wait_for_ready(self) -> None:
        """Wait for the workload to be ready to use."""
        for _ in range(10):
            if self._is_ready():
                return
            time.sleep(2)
        logger.error("the workload was not ready within the expected time")

    def _is_ready(self) -> bool:
        """Check whether the workload is ready to use."""
        for name, service_info in self.container.get_services().items():
            if not service_info.is_running():
                logger.info("service '%s' is not running", name)
                return False
        checks = self.container.get_checks(level=ops.pebble.CheckLevel.READY)
        for check_info in checks.values():
            if check_info.status != ops.pebble.CheckStatus.UP:
                return False
        return True


if __name__ == "__main__":  # pragma: nocover
    ops.main(NtfyK8SCharm)
