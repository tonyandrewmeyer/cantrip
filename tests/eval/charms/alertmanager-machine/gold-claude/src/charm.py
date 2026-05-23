#!/usr/bin/env python3
"""Prometheus Alertmanager machine charm."""

import logging
import pathlib
import subprocess
import typing

import ops

logger = logging.getLogger(__name__)

_CONFIG_DIR = pathlib.Path("/etc/alertmanager")
_CONFIG_PATH = _CONFIG_DIR / "alertmanager.yml"
_SERVICE = "snap.alertmanager.alertmanager"
_PORT = 9093


class AlertmanagerCharm(ops.CharmBase):
    """Charm for Prometheus Alertmanager on a machine substrate."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on["alerting"].relation_joined, self._on_alerting_joined)
        self.framework.observe(self.on["replicas"].relation_changed, self._on_replicas_changed)
        self.framework.observe(self.on.send_test_alert_action, self._on_send_test_alert)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install the alertmanager snap."""
        self.unit.status = ops.MaintenanceStatus("installing alertmanager")
        try:
            subprocess.run(
                ["snap", "install", "alertmanager", "--channel=stable"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("snap install failed: %s", exc.stderr)
            self.unit.status = ops.BlockedStatus("failed to install alertmanager snap")
            return
        self.unit.open_port("tcp", _PORT)
        self._write_config()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Regenerate config and restart the service on config changes."""
        self._write_config()
        self._restart_service()

    def _on_start(self, event: ops.StartEvent) -> None:
        """Start the service and go active."""
        self._restart_service()

    def _on_alerting_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Publish this unit's alertmanager endpoint to Prometheus."""
        if not self.unit.is_leader():
            return
        addr = self._bind_address()
        event.relation.data[self.app].update(
            {
                "alertmanager_url": f"http://{addr}:{_PORT}",
            }
        )

    def _on_replicas_changed(self, event: ops.RelationChangedEvent) -> None:
        """Regenerate config when cluster membership changes."""
        self._write_config()
        self._restart_service()

    def _on_send_test_alert(self, event: ops.ActionEvent) -> None:
        """POST a synthetic alert to the local Alertmanager API."""
        addr = self._bind_address()
        labels = typing.cast(dict, event.params.get("labels", {}))
        payload_labels = {"alertname": "CanTripTestAlert", "severity": "info"} | labels
        label_str = ",".join(f'"{k}":"{v}"' for k, v in payload_labels.items())
        payload = f'[{{"labels":{{{label_str}}}}}]'
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    payload,
                    f"http://{addr}:{_PORT}/api/v2/alerts",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            event.set_results({"result": result.stdout.strip() or "alert sent"})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            event.fail(f"Failed to send test alert: {exc}")

    # -----------------------------------------------------------------
    # Configuration helpers
    # -----------------------------------------------------------------

    def _write_config(self) -> None:
        """Write alertmanager.yml from charm config and peer data."""
        resolve_timeout = typing.cast(str, self.config.get("resolve-timeout", "5m"))
        log_level = typing.cast(str, self.config.get("log-level", "info"))
        smtp_host = typing.cast(str, self.config.get("smtp-smarthost", ""))
        smtp_from = typing.cast(str, self.config.get("smtp-from", ""))

        peers = self._cluster_peers()
        cluster_section = ""
        if peers:
            peer_addrs = "\n".join(f"  - {p}:9094" for p in peers)
            cluster_section = f"cluster:\n  peers:\n{peer_addrs}\n"

        smtp_section = ""
        if smtp_host:
            smtp_section = (
                f"  smtp_smarthost: '{smtp_host}'\n"
                f"  smtp_from: '{smtp_from}'\n"
            )

        config = f"""global:
  resolve_timeout: {resolve_timeout}
{smtp_section}
route:
  receiver: 'default'
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h

receivers:
  - name: 'default'

{cluster_section}"""

        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(config)
        logger.info("wrote alertmanager config (log-level=%s)", log_level)

    def _restart_service(self) -> None:
        """Restart the alertmanager systemd service."""
        try:
            subprocess.run(
                ["systemctl", "restart", _SERVICE],
                check=True,
                capture_output=True,
            )
            self.unit.status = ops.ActiveStatus()
        except subprocess.CalledProcessError as exc:
            logger.error("systemd restart failed: %s", exc.stderr)
            self.unit.status = ops.BlockedStatus("alertmanager failed to start")

    def _cluster_peers(self) -> list[str]:
        """Return the addresses of peer units for HA clustering."""
        rel = self.model.get_relation("replicas")
        if rel is None:
            return []
        addrs = []
        for unit in rel.units:
            addr = rel.data[unit].get("private-address", "")
            if addr and addr != self._bind_address():
                addrs.append(addr)
        return addrs

    def _bind_address(self) -> str:
        """Return this unit's bind address."""
        binding = self.model.get_binding("alerting")
        if binding is None:
            return "127.0.0.1"
        return str(binding.network.bind_address)


if __name__ == "__main__":
    ops.main(AlertmanagerCharm)
