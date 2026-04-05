#!/usr/bin/env python3
"""ntfy push notification server charm."""

import logging
import typing

import ops

logger = logging.getLogger(__name__)

# Path inside the container where Juju storage is mounted.
_DATA_MOUNT = "/var/lib/ntfy"

# ntfy expects its config at this path.
_CONFIG_PATH = "/etc/ntfy/server.yml"


class NtfyCharm(ops.CharmBase):
    """Charm for the ntfy push notification server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on["ntfy"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on["ingress"].relation_changed, self._on_ingress_changed
        )
        self.framework.observe(
            self.on["ingress"].relation_broken, self._on_ingress_broken
        )
        self.framework.observe(self.on.add_user_action, self._on_add_user)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure the workload once Pebble is available."""
        self._update_workload()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Regenerate config and restart the service."""
        self._update_workload()

    def _on_ingress_changed(self, event: ops.RelationChangedEvent) -> None:
        """Reconfigure behind-proxy when ingress is related."""
        self._update_workload()

    def _on_ingress_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Disable behind-proxy when ingress is removed."""
        self._update_workload()

    def _on_add_user(self, event: ops.ActionEvent) -> None:
        """Create a user via the ntfy CLI."""
        container = self.unit.get_container("ntfy")
        if not container.can_connect():
            event.fail("Workload container not ready.")
            return

        username = typing.cast(str, event.params.get("username", ""))
        if not username:
            event.fail("username is required")
            return

        role = typing.cast(str, event.params.get("role", "user"))
        cmd = ["ntfy", "user", "add", f"--role={role}", username]

        process = container.exec(cmd)
        try:
            stdout, _ = process.wait_output()
        except ops.pebble.ExecError as exc:
            event.fail(f"Failed to add user: {exc.stderr}")
            return

        event.set_results({"username": username, "role": role})

    # -----------------------------------------------------------------
    # Workload configuration
    # -----------------------------------------------------------------

    def _update_workload(self) -> None:
        """Push the config file and reconcile the Pebble layer."""
        container = self.unit.get_container("ntfy")
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for Pebble")
            return

        config_yaml = self._render_server_yml()
        container.push(_CONFIG_PATH, config_yaml, make_dirs=True)

        layer = ops.pebble.Layer({
            "summary": "ntfy layer",
            "services": {
                "ntfy": {
                    "override": "replace",
                    "command": "ntfy serve --config /etc/ntfy/server.yml",
                    "startup": "enabled",
                },
            },
            "checks": {
                "ntfy-health": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:80/v1/health"},
                },
            },
        })
        container.add_layer("ntfy", layer, combine=True)
        container.autostart()
        self.unit.status = ops.ActiveStatus()

    def _render_server_yml(self) -> str:
        """Generate the ntfy server.yml from charm config and relations."""
        has_ingress = self.model.get_relation("ingress") is not None

        lines = [
            f"base-url: \"{self.config.get('base-url', '')}\"",
            "listen-http: \":80\"",
            f"cache-file: \"{_DATA_MOUNT}/cache.db\"",
            f"cache-duration: \"{self.config.get('cache-duration', '12h')}\"",
            f"auth-file: \"{_DATA_MOUNT}/auth.db\"",
            "auth-default-access: \"deny-all\"",
            f"attachment-cache-dir: \"{_DATA_MOUNT}/attachments\"",
            f"log-level: \"{self.config.get('log-level', 'info')}\"",
            f"behind-proxy: {str(has_ingress).lower()}",
            "enable-metrics: true",
        ]

        upstream = self.config.get("upstream-base-url")
        if upstream:
            lines.append(f"upstream-base-url: \"{upstream}\"")

        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ops.main(NtfyCharm)
