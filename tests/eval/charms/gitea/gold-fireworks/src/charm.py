#!/usr/bin/env python3
# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Gitea Kubernetes charm.

A charm for deploying Gitea — a lightweight self-hosted Git service — on
Kubernetes.  Supports PostgreSQL, Redis, ingress, SMTP, S3 object storage,
COS observability, and a suite of operational actions.
"""

from __future__ import annotations

import logging
import secrets
import string

import gitea
import ops
import ops.pebble

logger = logging.getLogger(__name__)

CONTAINER_NAME = "gitea"
SERVICE_NAME = "gitea"
CONFIG_PATH = "/data/gitea/conf/app.ini"
DATA_PATH = "/data"

# Relation interface keys expected in databags
POSTGRESQL_KEYS = {"dbname", "host", "port", "user", "password"}
REDIS_KEYS = {"url", "hostname", "port"}
INGRESS_KEYS = {"url"}
SMTP_KEYS = {"host", "port", "user", "password", "auth_identity", "from_address"}
S3_KEYS = {"bucket", "endpoint", "access-key", "secret-key", "path", "region"}


class GiteaK8SCharm(ops.CharmBase):
    """Charm the Gitea application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.container = self.unit.get_container(CONTAINER_NAME)

        # Core lifecycle
        framework.observe(self.on.gitea.pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)

        # Storage
        framework.observe(self.on.data_storage_attached, self._on_storage_attached)
        framework.observe(self.on.config_storage_attached, self._on_storage_attached)

        # Relations — requires
        framework.observe(self.on.database_relation_changed, self._on_database_relation_changed)
        framework.observe(self.on.database_relation_broken, self._on_database_relation_broken)
        framework.observe(self.on.cache_relation_changed, self._on_cache_relation_changed)
        framework.observe(self.on.cache_relation_broken, self._on_cache_relation_broken)
        framework.observe(self.on.ingress_relation_changed, self._on_ingress_relation_changed)
        framework.observe(self.on.ingress_relation_broken, self._on_ingress_relation_broken)
        framework.observe(self.on.smtp_relation_changed, self._on_smtp_relation_changed)
        framework.observe(self.on.smtp_relation_broken, self._on_smtp_relation_broken)
        framework.observe(
            self.on.object_storage_relation_changed, self._on_object_storage_relation_changed
        )
        framework.observe(
            self.on.object_storage_relation_broken, self._on_object_storage_relation_broken
        )

        # COS provides
        framework.observe(self.on.metrics_endpoint_relation_joined, self._on_cos_relation)
        framework.observe(self.on.metrics_endpoint_relation_changed, self._on_cos_relation)
        framework.observe(self.on.grafana_dashboard_relation_joined, self._on_cos_relation)
        framework.observe(self.on.grafana_dashboard_relation_changed, self._on_cos_relation)
        framework.observe(self.on.logging_relation_joined, self._on_cos_relation)
        framework.observe(self.on.logging_relation_changed, self._on_cos_relation)

        # Actions
        framework.observe(self.on.create_admin_action, self._on_create_admin_action)
        framework.observe(
            self.on.change_admin_password_action, self._on_change_admin_password_action
        )
        framework.observe(self.on.run_housekeeping_action, self._on_run_housekeeping_action)
        framework.observe(self.on.backup_data_action, self._on_backup_data_action)
        framework.observe(self.on.restore_data_action, self._on_restore_data_action)

    # ------------------------------------------------------------------
    # Lifecycle handlers
    # ------------------------------------------------------------------

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Handle pebble-ready event."""
        self._reconcile(event)

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        self._reconcile(event)

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Handle update-status event."""
        self._reconcile(event)

    def _on_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        """Handle storage-attached event."""
        self._reconcile(event)

    # ------------------------------------------------------------------
    # Relation handlers
    # ------------------------------------------------------------------

    def _on_database_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle database relation changes."""
        self._reconcile(event)

    def _on_database_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle database relation broken."""
        self._reconcile(event)

    def _on_cache_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle cache (redis) relation changes."""
        self._reconcile(event)

    def _on_cache_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle cache relation broken."""
        self._reconcile(event)

    def _on_ingress_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle ingress relation changes."""
        self._reconcile(event)

    def _on_ingress_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle ingress relation broken."""
        self._reconcile(event)

    def _on_smtp_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle SMTP relation changes."""
        self._reconcile(event)

    def _on_smtp_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle SMTP relation broken."""
        self._reconcile(event)

    def _on_object_storage_relation_changed(self, event: ops.RelationEvent) -> None:
        """Handle object-storage (S3) relation changes."""
        self._reconcile(event)

    def _on_object_storage_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle object-storage relation broken."""
        self._reconcile(event)

    def _on_cos_relation(self, event: ops.RelationEvent) -> None:
        """Handle COS relation events (metrics, dashboards, logging)."""
        if not self.container.can_connect():
            return
        self._publish_cos_data(event)

    def _publish_cos_data(self, event: ops.RelationEvent) -> None:
        """Publish COS relation data to the remote application."""
        relation = event.relation
        endpoint = event.relation.name

        if endpoint == "metrics-endpoint":
            # Publish scrape job for Prometheus
            metrics_token = self._get_or_create_metrics_token()
            relation.data[self.app]["jobs"] = (
                '[{"job_name": "gitea", "static_configs": '
                '[{"targets": ["*:3000"]}], "metrics_path": "/metrics", '
                f'"bearer_token": "{metrics_token}"}}]'
            )
        elif endpoint == "grafana-dashboard":
            # Dashboard is shipped as a file in the charm; relation data
            # just signals availability.  The Grafana charm picks up the
            # dashboard from the relation content.
            relation.data[self.app]["dashboards"] = "gitea"
        elif endpoint == "logging":
            # Publish Loki push endpoint configuration
            relation.data[self.app]["metadata"] = (
                '{"model": "' + self.model.name + '", '
                '"application": "' + self.app.name + '", '
                '"unit": "' + self.unit.name + '"}'
            )

    # ------------------------------------------------------------------
    # Reconcile
    # ------------------------------------------------------------------

    def _reconcile(self, event: ops.EventBase) -> None:
        """Reconcile charm state and workload configuration.

        This is the central reconciliation loop that evaluates all
        dependencies and either starts / reconfigures the workload or
        sets an appropriate blocked / waiting status.
        """
        if not self.container.can_connect():
            self.unit.status = ops.WaitingStatus("waiting for Pebble")
            event.defer()
            return

        # Ensure storage directories exist
        self._ensure_directories()

        # Check required database relation
        db_data = self._get_database_data()
        if not db_data:
            self.unit.status = ops.BlockedStatus("database relation required")
            return

        # Generate and write app.ini
        config = self._generate_config(db_data)
        self._write_config(config)

        # Build Pebble layer
        layer = self._build_pebble_layer()
        self.container.add_layer("gitea", layer, combine=True)

        # Manage services
        services = self.container.get_services(SERVICE_NAME)
        if SERVICE_NAME not in services or not services[SERVICE_NAME].is_running():
            self.container.replan()

        # Set status based on optional relations
        cache_data = self._get_cache_data()
        if not cache_data:
            self.unit.status = ops.MaintenanceStatus("running with degraded session storage")
        else:
            self.unit.status = ops.ActiveStatus()

        # Update workload version
        version = gitea.get_version(self.container)
        if version:
            self.unit.set_workload_version(version)

    def _ensure_directories(self) -> None:
        """Ensure required directories exist in the workload container."""
        for path in ["/data/gitea/conf", "/data/gitea/log", "/data/git/repositories"]:
            self.container.make_dir(path, make_parents=True)

    def _write_config(self, config: str) -> None:
        """Write the Gitea configuration file."""
        self.container.push(CONFIG_PATH, config, make_dirs=True)

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------

    def _generate_config(self, db_data: dict[str, str]) -> str:
        """Generate the app.ini configuration file."""
        cfg = self.model.config

        lines: list[str] = [
            "; Gitea configuration — generated by Juju charm",
            "[server]",
            f"APP_NAME = {cfg.get('app-name', 'Gitea')}",
            "HTTP_PORT = 3000",
            "ROOT_URL = http://localhost:3000/",
            "DISABLE_SSH = true",
        ]

        # Ingress URL
        ingress_url = self._get_ingress_url()
        if ingress_url:
            lines[-1] = f"ROOT_URL = {ingress_url}"

        lines.extend(
            [
                "",
                "[database]",
                "DB_TYPE = postgres",
                f"HOST = {db_data.get('host', 'localhost')}:{db_data.get('port', '5432')}",
                f"NAME = {db_data.get('dbname', 'gitea')}",
                f"USER = {db_data.get('user', 'gitea')}",
                f"PASSWD = {db_data.get('password', '')}",
                "SCHEMA = public",
            ]
        )

        # Cache / session (Redis)
        cache_data = self._get_cache_data()
        if cache_data:
            redis_url = cache_data.get("url", "")
            if not redis_url:
                host = cache_data.get("hostname", cache_data.get("host", "localhost"))
                port = cache_data.get("port", "6379")
                redis_url = f"redis://{host}:{port}"
            lines.extend(
                [
                    "",
                    "[cache]",
                    "ADAPTER = redis",
                    f"HOST = {redis_url}",
                    "",
                    "[session]",
                    "PROVIDER = redis",
                    f"PROVIDER_CONFIG = {redis_url}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "[cache]",
                    "ADAPTER = memory",
                    "",
                    "[session]",
                    "PROVIDER = memory",
                ]
            )

        # Mailer (SMTP)
        smtp_data = self._get_smtp_data()
        if smtp_data:
            lines.extend(
                [
                    "",
                    "[mailer]",
                    "ENABLED = true",
                    f"SMTP_ADDR = {smtp_data.get('host', 'localhost')}:{smtp_data.get('port', '25')}",
                    f"FROM = {smtp_data.get('from_address', smtp_data.get('from', 'gitea@localhost'))}",
                ]
            )
            if smtp_data.get("user"):
                lines.append(f"USER = {smtp_data['user']}")
            if smtp_data.get("password"):
                lines.append(f"PASSWD = {smtp_data['password']}")
        else:
            lines.extend(
                [
                    "",
                    "[mailer]",
                    "ENABLED = false",
                ]
            )

        # Object storage (S3 / MinIO)
        s3_data = self._get_object_storage_data()
        if s3_data:
            endpoint = s3_data.get("endpoint", "")
            bucket = s3_data.get("bucket", "gitea")
            access_key = s3_data.get("access-key", "")
            secret_key = s3_data.get("secret-key", "")
            region = s3_data.get("region", "us-east-1")
            path_style = "true" if s3_data.get("path", "false").lower() == "true" else "false"  # noqa: F841 - Fireworks declared but never used; kept for caller compat.

            lines.extend(
                [
                    "",
                    "[lfs]",
                    "STORAGE_TYPE = minio",
                    f"MINIO_ENDPOINT = {endpoint}",
                    f"MINIO_BUCKET = {bucket}-lfs",
                    f"MINIO_ACCESS_KEY_ID = {access_key}",
                    f"MINIO_SECRET_ACCESS_KEY = {secret_key}",
                    f"MINIO_LOCATION = {region}",
                    "MINIO_USE_SSL = false",
                    "",
                    "[attachment]",
                    "STORAGE_TYPE = minio",
                    f"MINIO_ENDPOINT = {endpoint}",
                    f"MINIO_BUCKET = {bucket}-attachments",
                    f"MINIO_ACCESS_KEY_ID = {access_key}",
                    f"MINIO_SECRET_ACCESS_KEY = {secret_key}",
                    f"MINIO_LOCATION = {region}",
                    "MINIO_USE_SSL = false",
                    "",
                    "[packages]",
                    "STORAGE_TYPE = minio",
                    f"MINIO_ENDPOINT = {endpoint}",
                    f"MINIO_BUCKET = {bucket}-packages",
                    f"MINIO_ACCESS_KEY_ID = {access_key}",
                    f"MINIO_SECRET_ACCESS_KEY = {secret_key}",
                    f"MINIO_LOCATION = {region}",
                    "MINIO_USE_SSL = false",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "[lfs]",
                    "STORAGE_TYPE = local",
                    f"PATH = {DATA_PATH}/lfs",
                    "",
                    "[attachment]",
                    "STORAGE_TYPE = local",
                    f"PATH = {DATA_PATH}/attachments",
                    "",
                    "[packages]",
                    "STORAGE_TYPE = local",
                    f"PATH = {DATA_PATH}/packages",
                ]
            )

        # Metrics endpoint (COS)
        metrics_token = self._get_or_create_metrics_token()
        lines.extend(
            [
                "",
                "[metrics]",
                "ENABLED = true",
                f"TOKEN = {metrics_token}",
            ]
        )

        # Logging
        log_level = cfg.get("log-level", "Info")
        lines.extend(
            [
                "",
                "[log]",
                f"LEVEL = {log_level}",
                "MODE = console",
                "ROOT_PATH = /data/gitea/log",
            ]
        )

        # Security / operational settings
        lines.extend(
            [
                "",
                "[security]",
                f"DISABLE_GIT_HOOKS = {str(cfg.get('disable-git-hooks', True)).lower()}",
                f"ALLOW_ONLY_EXTERNAL_REGISTRATION = {str(cfg.get('allow-only-external-registration', True)).lower()}",
            ]
        )

        # Repository defaults
        lines.extend(
            [
                "",
                "[repository]",
                f"DEFAULT_PRIVATE = {str(cfg.get('default-private-repos', True)).lower()}",
            ]
        )

        # Mirror cron
        cron_expr = cfg.get("cron-update-mirrors", "@every 10m")
        lines.extend(
            [
                "",
                "[cron.update_mirrors]",
                "SCHEDULE = @every 10m",
                f"UPDATE_SETTING = {cron_expr}",
            ]
        )

        # Basic paths
        lines.extend(
            [
                "",
                "[repository]",
                f"ROOT = {DATA_PATH}/git/repositories",
                "",
                "[lfs]",
                f"PATH = {DATA_PATH}/lfs",
            ]
        )

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Pebble layer
    # ------------------------------------------------------------------

    def _build_pebble_layer(self) -> ops.pebble.LayerDict:
        """Build the Pebble layer for the Gitea workload."""
        return {
            "summary": "Gitea layer",
            "services": {
                SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Gitea self-hosted Git service",
                    "command": "/usr/local/bin/gitea web -c /data/gitea/conf/app.ini",
                    "startup": "enabled",
                    "environment": {
                        "GITEA_WORK_DIR": "/data",
                        "HOME": "/data",
                    },
                }
            },
            "checks": {
                "gitea-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {
                        "url": "http://localhost:3000/api/healthz",
                    },
                }
            },
        }

    # ------------------------------------------------------------------
    # Relation data helpers
    # ------------------------------------------------------------------

    def _get_database_data(self) -> dict[str, str] | None:
        """Fetch PostgreSQL connection details from the database relation."""
        relation = self.model.get_relation("database")
        if not relation:
            return None
        for unit in relation.units:
            data = relation.data[unit]
            if all(k in data for k in ("dbname", "host", "port", "user", "password")):
                return {
                    "dbname": data.get("dbname", ""),
                    "host": data.get("host", ""),
                    "port": data.get("port", "5432"),
                    "user": data.get("user", ""),
                    "password": data.get("password", ""),
                }
        # Fallback: try application data (newer postgresql_client)
        app_data = relation.data.get(relation.app, {})
        if app_data and all(k in app_data for k in ("dbname", "host", "port", "user", "password")):
            return {
                "dbname": app_data.get("dbname", ""),
                "host": app_data.get("host", ""),
                "port": app_data.get("port", "5432"),
                "user": app_data.get("user", ""),
                "password": app_data.get("password", ""),
            }
        return None

    def _get_cache_data(self) -> dict[str, str] | None:
        """Fetch Redis connection details from the cache relation."""
        relation = self.model.get_relation("cache")
        if not relation:
            return None
        for unit in relation.units:
            data = relation.data[unit]
            if data.get("url") or (data.get("hostname") and data.get("port")):
                return {
                    "url": data.get("url", ""),
                    "hostname": data.get("hostname", data.get("host", "")),
                    "port": data.get("port", "6379"),
                }
        app_data = relation.data.get(relation.app, {})
        if app_data:
            return {
                "url": app_data.get("url", ""),
                "hostname": app_data.get("hostname", app_data.get("host", "")),
                "port": app_data.get("port", "6379"),
            }
        return None

    def _get_ingress_url(self) -> str | None:
        """Fetch ingress URL from the ingress relation."""
        relation = self.model.get_relation("ingress")
        if not relation:
            return None
        for unit in relation.units:
            data = relation.data[unit]
            if "url" in data:
                return data["url"]
        app_data = relation.data.get(relation.app, {})
        return app_data.get("url")

    def _get_smtp_data(self) -> dict[str, str] | None:
        """Fetch SMTP details from the smtp relation."""
        relation = self.model.get_relation("smtp")
        if not relation:
            return None
        for unit in relation.units:
            data = relation.data[unit]
            if data.get("host"):
                return {
                    "host": data.get("host", ""),
                    "port": data.get("port", "25"),
                    "user": data.get("user", ""),
                    "password": data.get("password", ""),
                    "from_address": data.get("from_address", data.get("from", "")),
                    "auth_identity": data.get("auth_identity", ""),
                }
        app_data = relation.data.get(relation.app, {})
        if app_data and app_data.get("host"):
            return {
                "host": app_data.get("host", ""),
                "port": app_data.get("port", "25"),
                "user": app_data.get("user", ""),
                "password": app_data.get("password", ""),
                "from_address": app_data.get("from_address", app_data.get("from", "")),
                "auth_identity": app_data.get("auth_identity", ""),
            }
        return None

    def _get_object_storage_data(self) -> dict[str, str] | None:
        """Fetch S3 details from the object-storage relation."""
        relation = self.model.get_relation("object-storage")
        if not relation:
            return None
        for unit in relation.units:
            data = relation.data[unit]
            if data.get("bucket") and data.get("endpoint"):
                return {
                    "bucket": data.get("bucket", ""),
                    "endpoint": data.get("endpoint", ""),
                    "access-key": data.get("access-key", data.get("access_key", "")),
                    "secret-key": data.get("secret-key", data.get("secret_key", "")),
                    "path": data.get("path", "false"),
                    "region": data.get("region", "us-east-1"),
                }
        app_data = relation.data.get(relation.app, {})
        if app_data and app_data.get("bucket") and app_data.get("endpoint"):
            return {
                "bucket": app_data.get("bucket", ""),
                "endpoint": app_data.get("endpoint", ""),
                "access-key": app_data.get("access-key", app_data.get("access_key", "")),
                "secret-key": app_data.get("secret-key", app_data.get("secret_key", "")),
                "path": app_data.get("path", "false"),
                "region": app_data.get("region", "us-east-1"),
            }
        return None

    # ------------------------------------------------------------------
    # Metrics token (stored in peer data or generated)
    # ------------------------------------------------------------------

    def _get_or_create_metrics_token(self) -> str:
        """Return the bearer token for the /metrics endpoint."""
        peer_relation = self.model.get_relation("gitea-peers")
        if peer_relation:
            token = peer_relation.data[self.app].get("metrics-token")
            if token:
                return token
            token = self._generate_random_password()
            peer_relation.data[self.app]["metrics-token"] = token
            return token
        # No peer relation — generate per-unit (not ideal but functional)
        token = self._generate_random_password()
        return token

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_create_admin_action(self, event: ops.ActionEvent) -> None:
        """Create a new Gitea admin user."""
        if not self.container.can_connect():
            event.fail("Pbble not ready")
            return

        username = event.params["username"]
        email = event.params["email"]
        random_password = event.params.get("random-password", True)

        if random_password:
            password = self._generate_random_password()
        else:
            event.fail(
                "random-password=false is not supported via action; set random-password=true"
            )
            return

        cmd = [
            "/usr/local/bin/gitea",
            "admin",
            "user",
            "create",
            "--username",
            username,
            "--email",
            email,
            "--password",
            password,
            "--admin",
            "--config",
            CONFIG_PATH,
        ]

        try:
            proc = self.container.exec(
                cmd, environment={"GITEA_WORK_DIR": "/data", "HOME": "/data"}
            )
            proc.wait_output()
            event.set_results({"password": password})
        except ops.pebble.ExecError as e:
            logger.error("create-admin failed: %s", e)
            event.fail(f"Failed to create admin: {e}")

    def _on_change_admin_password_action(self, event: ops.ActionEvent) -> None:
        """Change an existing Gitea admin user's password."""
        if not self.container.can_connect():
            event.fail("Pebble not ready")
            return

        username = event.params["username"]
        random_password = event.params.get("random-password", True)
        explicit_password = event.params.get("password", "")

        if random_password:
            password = self._generate_random_password()
        elif explicit_password:
            password = explicit_password
        else:
            event.fail("Either random-password=true or an explicit password is required")
            return

        cmd = [
            "/usr/local/bin/gitea",
            "admin",
            "user",
            "change-password",
            "--username",
            username,
            "--password",
            password,
            "--config",
            CONFIG_PATH,
        ]

        try:
            proc = self.container.exec(
                cmd, environment={"GITEA_WORK_DIR": "/data", "HOME": "/data"}
            )
            proc.wait_output()
            event.set_results({"password": password})
        except ops.pebble.ExecError as e:
            logger.error("change-admin-password failed: %s", e)
            event.fail(f"Failed to change password: {e}")

    def _on_run_housekeeping_action(self, event: ops.ActionEvent) -> None:
        """Run Gitea housekeeping tasks."""
        if not self.container.can_connect():
            event.fail("Pebble not ready")
            return

        env = {"GITEA_WORK_DIR": "/data", "HOME": "/data"}
        results: dict[str, str] = {}

        # 1. Flush queues
        try:
            proc = self.container.exec(
                ["/usr/local/bin/gitea", "manager", "flush-queues", "--config", CONFIG_PATH],
                environment=env,
            )
            proc.wait_output()
            results["flush-queues"] = "ok"
        except ops.pebble.ExecError as e:
            logger.warning("flush-queues failed: %s", e)
            results["flush-queues"] = f"failed: {e}"

        # 2. Clean archived repos older than 720h (30 days)
        try:
            proc = self.container.exec(
                [
                    "/usr/local/bin/gitea",
                    "admin",
                    "repo-archive-cleanup",
                    "--older-than",
                    "720h",
                    "--config",
                    CONFIG_PATH,
                ],
                environment=env,
            )
            proc.wait_output()
            results["repo-archive-cleanup"] = "ok"
        except ops.pebble.ExecError as e:
            logger.warning("repo-archive-cleanup failed: %s", e)
            results["repo-archive-cleanup"] = f"failed: {e}"

        # 3. Git GC sweep across all repositories
        try:
            proc = self.container.exec(
                [
                    "/bin/sh",
                    "-c",
                    f"find {DATA_PATH}/git/repositories -type d -name '*.git' -exec git -C {{}} gc \\;",
                ],
                environment=env,
            )
            proc.wait_output()
            results["git-gc"] = "ok"
        except ops.pebble.ExecError as e:
            logger.warning("git-gc failed: %s", e)
            results["git-gc"] = f"failed: {e}"

        event.set_results(results)

    def _on_backup_data_action(self, event: ops.ActionEvent) -> None:
        """Backup Gitea data using gitea dump."""
        if not self.container.can_connect():
            event.fail("Pebble not ready")
            return

        timestamp = self._timestamp()
        archive_name = f"gitea-backup-{timestamp}.tar.gz"
        archive_path = f"{DATA_PATH}/backups/{archive_name}"

        # Ensure backup directory exists
        self.container.make_dir(f"{DATA_PATH}/backups", make_parents=True)

        env = {"GITEA_WORK_DIR": "/data", "HOME": "/data"}
        cmd = [
            "/usr/local/bin/gitea",
            "dump",
            "--config",
            CONFIG_PATH,
            "--file",
            archive_path,
            "--type",
            "tar.gz",
        ]

        try:
            proc = self.container.exec(cmd, environment=env)
            stdout, stderr = proc.wait_output()
            logger.info("backup output: %s", stdout)

            # Compute SHA-256
            sha_proc = self.container.exec(
                ["sha256sum", archive_path],
                environment=env,
            )
            sha_stdout, _ = sha_proc.wait_output()
            sha256 = sha_stdout.split()[0]

            event.set_results(
                {
                    "archive-path": archive_path,
                    "sha256": sha256,
                }
            )
        except ops.pebble.ExecError as e:
            logger.error("backup-data failed: %s", e)
            event.fail(f"Backup failed: {e}")

    def _on_restore_data_action(self, event: ops.ActionEvent) -> None:
        """Restore Gitea from a backup archive."""
        if not self.container.can_connect():
            event.fail("Pebble not ready")
            return

        # Refuse if database relation is detached
        if not self._get_database_data():
            event.fail("Database relation is detached; restore refused")
            return

        archive_path = event.params["archive-path"]
        expected_sha256 = event.params["sha256"]

        # Verify SHA-256
        try:
            sha_proc = self.container.exec(["sha256sum", archive_path])
            sha_stdout, _ = sha_proc.wait_output()
            actual_sha256 = sha_stdout.split()[0]
            if actual_sha256 != expected_sha256:
                event.fail(f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}")
                return
        except ops.pebble.ExecError as e:
            event.fail(f"Failed to verify archive: {e}")
            return

        env = {"GITEA_WORK_DIR": "/data", "HOME": "/data"}

        # Stop Pebble services
        try:
            self.container.stop(SERVICE_NAME)
        except ops.pebble.APIError as e:
            logger.warning("Failed to stop service (may already be stopped): %s", e)

        # Unpack archive
        try:
            # gitea dump tar.gz contains the data directory contents
            proc = self.container.exec(
                ["tar", "-xzf", archive_path, "-C", DATA_PATH],
                environment=env,
            )
            proc.wait_output()
        except ops.pebble.ExecError as e:
            logger.error("Failed to unpack archive: %s", e)
            # Try to restart service before failing
            try:  # noqa: SIM105 - kept as written by Fireworks for legibility.
                self.container.start(SERVICE_NAME)
            except ops.pebble.APIError:
                pass
            event.fail(f"Failed to unpack archive: {e}")
            return

        # Restart services
        try:
            self.container.start(SERVICE_NAME)
        except ops.pebble.APIError as e:
            event.fail(f"Failed to restart service: {e}")
            return

        event.set_results(
            {
                "restored-from": archive_path,
                "sha256-verified": expected_sha256,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_random_password(length: int = 24) -> str:
        """Generate a cryptographically secure random password."""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_+="
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def _timestamp() -> str:
        """Return an ISO-8601-ish timestamp string."""
        import datetime

        return datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")


if __name__ == "__main__":  # pragma: nocover
    ops.main(GiteaK8SCharm)
