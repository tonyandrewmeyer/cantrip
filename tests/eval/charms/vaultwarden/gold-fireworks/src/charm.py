#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Vaultwarden Kubernetes charm."""

import datetime
import json
import logging
import secrets

import ops
import ops.pebble

logger = logging.getLogger(__name__)

CONTAINER_NAME = "vaultwarden"
SERVICE_NAME = "vaultwarden"
DATA_DIR = "/data"
BACKUP_DIR = "/data/backups"


class VaultwardenK8SCharm(ops.CharmBase):
    """Charm for Vaultwarden password manager server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container(CONTAINER_NAME)

        # Core lifecycle events
        framework.observe(self.on.vaultwarden_pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.leader_elected, self._on_leader_elected)
        framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Relation events
        framework.observe(self.on["ingress"].relation_changed, self._on_ingress_changed)
        framework.observe(self.on["ingress"].relation_broken, self._on_ingress_changed)
        framework.observe(self.on["smtp"].relation_changed, self._on_smtp_changed)
        framework.observe(self.on["smtp"].relation_broken, self._on_smtp_changed)

        # COS relation events
        framework.observe(
            self.on["metrics-endpoint"].relation_changed, self._on_cos_relation_changed
        )
        framework.observe(
            self.on["grafana-dashboard"].relation_changed, self._on_cos_relation_changed
        )

        # Actions
        framework.observe(self.on.get_admin_token_action, self._on_get_admin_token)
        framework.observe(self.on.backup_data_action, self._on_backup_data)
        framework.observe(self.on.restore_data_action, self._on_restore_data)

    # --- Event Handlers ---

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Handle pebble-ready event."""
        self._reconcile()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        self._reconcile()

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        if self.unit.is_leader():
            self._ensure_admin_token()
        self._reconcile()

    def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
        """Handle leader-elected event."""
        self._ensure_admin_token()
        self._reconcile()

    def _on_upgrade_charm(self, event: ops.UpgradeCharmEvent) -> None:
        """Handle upgrade-charm event."""
        self._reconcile()

    def _on_ingress_changed(self, event: ops.RelationEvent) -> None:
        """Handle ingress relation changes."""
        self._reconcile()

    def _on_smtp_changed(self, event: ops.RelationEvent) -> None:
        """Handle SMTP relation changes."""
        self._reconcile()

    def _on_cos_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle COS relation changes."""
        self._update_cos_relations()

    # --- Reconciliation ---

    def _reconcile(self) -> None:
        """Reconcile the charm state and update the workload."""
        if not self.container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for container")
            return

        config_error = self._validate_config()
        if config_error:
            self.unit.status = ops.BlockedStatus(config_error)
            return

        domain = self._get_domain()
        if not domain:
            self.unit.status = ops.BlockedStatus(
                "missing ingress relation or domain-override config"
            )
            return

        layer = self._build_pebble_layer()
        self.container.add_layer("vaultwarden", layer, combine=True)
        self.container.replan()

        self._update_cos_relations()

        self.unit.set_workload_version("1.30.5")
        self.unit.status = ops.ActiveStatus()

    def _validate_config(self) -> str | None:
        """Validate config options.

        Returns:
            Error message if config is invalid, None otherwise.
        """
        log_level = self.config.get("log-level", "warn")
        valid_levels = {"trace", "debug", "info", "warn", "error", "off"}
        if log_level not in valid_levels:
            return (
                f"invalid log-level '{log_level}'; "
                f"must be one of: {', '.join(sorted(valid_levels))}"
            )
        return None

    def _get_domain(self) -> str | None:
        """Get the configured domain for Vaultwarden.

        The domain-override config takes precedence over the ingress relation.
        """
        domain_override = self.config.get("domain-override", "")
        if domain_override:
            return domain_override

        ingress_relation = self.model.get_relation("ingress")
        if ingress_relation:
            if ingress_relation.app:
                url = ingress_relation.data[ingress_relation.app].get("url")
                if url:
                    return url
            for unit in ingress_relation.units:
                if unit.app != self.app:
                    url = ingress_relation.data[unit].get("url")
                    if url:
                        return url

        return None

    def _build_pebble_layer(self) -> ops.pebble.LayerDict:
        """Build the Pebble layer for Vaultwarden."""
        environment = self._build_environment()

        return {
            "summary": "Vaultwarden layer",
            "services": {
                SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Vaultwarden password manager server",
                    "command": "/vaultwarden",
                    "startup": "enabled",
                    "environment": environment,
                }
            },
        }

    def _build_environment(self) -> dict[str, str]:
        """Build the environment variables for Vaultwarden."""
        env: dict[str, str] = {
            "DATA_FOLDER": DATA_DIR,
            "SIGNUPS_ALLOWED": str(self.config.get("signups-allowed", False)).lower(),
            "INVITATIONS_ALLOWED": str(self.config.get("invitations-allowed", True)).lower(),
            "WEB_VAULT_ENABLED": str(self.config.get("web-vault-enabled", True)).lower(),
            "LOG_LEVEL": self.config.get("log-level", "warn"),
            "ENABLE_PROMETHEUS": "true",
        }

        domain = self._get_domain()
        if domain:
            env["DOMAIN"] = domain

        admin_token = self._get_admin_token()
        if admin_token:
            env["ADMIN_TOKEN"] = admin_token

        smtp_settings = self._get_smtp_settings()
        if smtp_settings:
            env.update(smtp_settings)

        return env

    def _get_smtp_settings(self) -> dict[str, str] | None:
        """Get SMTP settings from the smtp relation."""
        smtp_relation = self.model.get_relation("smtp")
        if not smtp_relation:
            return None

        data: dict[str, str] = {}
        if smtp_relation.app:
            data = dict(smtp_relation.data[smtp_relation.app])
        else:
            for unit in smtp_relation.units:
                if unit.app != self.app:
                    data = dict(smtp_relation.data[unit])
                    break

        if not data:
            return None

        settings: dict[str, str] = {}
        mappings = {
            "host": "SMTP_HOST",
            "port": "SMTP_PORT",
            "username": "SMTP_USERNAME",
            "password": "SMTP_PASSWORD",
            "from_address": "SMTP_FROM",
            "security": "SMTP_SECURITY",
        }

        for key, env_var in mappings.items():
            value = data.get(key)
            if value:
                settings[env_var] = value

        return settings if settings else None

    # --- Admin Token Secret ---

    def _ensure_admin_token(self) -> None:
        """Ensure the admin token secret exists.

        Only the leader creates the secret. The secret is stored with
        the label 'admin-token' so any unit can retrieve it.
        """
        if not self.unit.is_leader():
            return

        try:
            self.model.get_secret(label="admin-token")
            return
        except ops.SecretNotFoundError:
            pass

        token = secrets.token_urlsafe(32)
        self.app.add_secret({"admin-token": token}, label="admin-token")
        logger.info("generated new admin token secret")

    def _get_admin_token(self) -> str | None:
        """Get the admin token from the secret."""
        try:
            secret = self.model.get_secret(label="admin-token")
            content = secret.get_content()
            return content.get("admin-token")
        except ops.SecretNotFoundError:
            return None

    # --- COS Integration ---

    def _update_cos_relations(self) -> None:
        """Update COS relation data."""
        self._update_prometheus_scrape()
        self._update_grafana_dashboard()

    def _update_prometheus_scrape(self) -> None:
        """Update prometheus-scrape relation data."""
        relation = self.model.get_relation("metrics-endpoint")
        if not relation:
            return

        scrape_jobs = [
            {
                "job_name": "vaultwarden",
                "static_configs": [{"targets": ["*:80"]}],
                "metrics_path": "/metrics",
            }
        ]
        relation.data[self.app]["scrape_jobs"] = json.dumps(scrape_jobs)

    def _update_grafana_dashboard(self) -> None:
        """Update grafana-dashboard relation data."""
        relation = self.model.get_relation("grafana-dashboard")
        if not relation:
            return

        dashboard = {
            "dashboard": {
                "id": None,
                "title": "Vaultwarden",
                "tags": ["vaultwarden"],
                "timezone": "utc",
                "panels": [],
            }
        }
        relation.data[self.app]["dashboards"] = json.dumps(dashboard)

    # --- Actions ---

    def _on_get_admin_token(self, event: ops.ActionEvent) -> None:
        """Handle get-admin-token action."""
        try:
            secret = self.model.get_secret(label="admin-token")
            content = secret.get_content()
            token = content.get("admin-token")
            if token:
                event.set_results({"admin-token": token})
            else:
                event.fail("admin token not found in secret")
        except ops.SecretNotFoundError:
            event.fail("admin token secret not found")

    def _on_backup_data(self, event: ops.ActionEvent) -> None:
        """Handle backup-data action.

        Creates a tarball of the Vaultwarden data directory and returns
        the path and SHA-256 checksum.
        """
        if not self.container.can_connect():
            event.fail("container not available")
            return

        self.container.make_dir(BACKUP_DIR, make_parents=True)

        timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
        backup_path = f"{BACKUP_DIR}/backup-{timestamp}.tar.gz"

        try:
            process = self.container.exec(
                ["tar", "-czf", backup_path, "-C", DATA_DIR, "."],
                timeout=300,
            )
            process.wait()

            result = self.container.exec(["sha256sum", backup_path]).wait_output()
            sha256 = result[0].strip().split()[0]

            event.set_results(
                {
                    "backup-path": backup_path,
                    "sha256": sha256,
                }
            )
        except ops.pebble.ExecError as e:
            event.fail(f"backup failed: {e}")

    def _on_restore_data(self, event: ops.ActionEvent) -> None:
        """Handle restore-data action.

        Verifies the SHA-256 checksum, stops the Vaultwarden service,
        restores the data directory from the backup tarball, and
        restarts the service.
        """
        if not self.container.can_connect():
            event.fail("container not available")
            return

        backup_path = event.params.get("backup-path")
        expected_sha256 = event.params.get("sha256")

        if not self.container.exists(backup_path):
            event.fail(f"backup file not found: {backup_path}")
            return

        try:
            result = self.container.exec(["sha256sum", backup_path]).wait_output()
            actual_sha256 = result[0].strip().split()[0]
            if actual_sha256 != expected_sha256:
                event.fail(f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}")
                return

            temp_backup = f"/tmp/restore-{secrets.token_hex(8)}.tar.gz"
            self.container.exec(["cp", backup_path, temp_backup]).wait()

            self.container.stop(SERVICE_NAME)

            self.container.exec(["sh", "-c", f"cd {DATA_DIR} && rm -rf ..?* .[!.]* *"]).wait()

            self.container.exec(["tar", "-xzf", temp_backup, "-C", DATA_DIR]).wait()

            self.container.exec(["rm", temp_backup]).wait()

            self.container.start(SERVICE_NAME)

            event.set_results(
                {
                    "restored-from": backup_path,
                    "sha256": actual_sha256,
                }
            )
        except ops.pebble.ExecError as e:
            event.fail(f"restore failed: {e}")


if __name__ == "__main__":  # pragma: nocover
    ops.main(VaultwardenK8SCharm)
