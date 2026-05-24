# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Unit tests for the Vaultwarden charm."""

import ops.testing as testing
from charm import CONTAINER_NAME, SERVICE_NAME, VaultwardenK8SCharm


def _make_container(can_connect: bool = True) -> testing.Container:
    """Create a mock Vaultwarden container."""
    return testing.Container(
        CONTAINER_NAME,
        can_connect=can_connect,
    )


def _make_ingress_relation(url: str = "https://vaultwarden.example.com") -> testing.Relation:
    """Create a mock ingress relation."""
    return testing.Relation(
        "ingress",
        remote_app_name="traefik",
        remote_app_data={"url": url},
    )


def _make_smtp_relation(
    host: str = "smtp.example.com",
    port: str = "587",
    username: str = "user",
    password: str = "pass",
    from_address: str = "vaultwarden@example.com",
    security: str = "starttls",
) -> testing.Relation:
    """Create a mock SMTP relation."""
    return testing.Relation(
        "smtp",
        remote_app_name="smtp-relay",
        remote_app_data={
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "from_address": from_address,
            "security": security,
        },
    )


class TestPebbleReady:
    """Tests for the pebble-ready event."""

    def test_pebble_ready_without_ingress_blocked(self):
        """The charm should be blocked without an ingress relation."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        state_in = testing.State(containers={container})

        state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            "missing ingress relation or domain-override config"
        )

    def test_pebble_ready_with_ingress_active(self):
        """The charm should be active with an ingress relation."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        container_out = state_out.get_container(container.name)
        assert SERVICE_NAME in container_out.services
        assert container_out.services[SERVICE_NAME].is_running

    def test_pebble_ready_container_not_connectable(self):
        """The charm should wait if the container is not connectable."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container(can_connect=False)
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

        assert state_out.unit_status == testing.WaitingStatus("waiting for container")


class TestConfigChanged:
    """Tests for config-changed events."""

    def test_config_changed_with_ingress(self):
        """Config change should reconcile with ingress present."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.ActiveStatus()

    def test_config_changed_invalid_log_level(self):
        """Invalid log-level should block the charm."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
            config={"log-level": "invalid"},
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            "invalid log-level 'invalid'; must be one of: debug, error, info, off, trace, warn"
        )

    def test_domain_override_takes_precedence(self):
        """domain-override config should take precedence over ingress."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation(url="https://from-ingress.example.com")
        state_in = testing.State(
            containers={container},
            relations={ingress},
            config={"domain-override": "https://override.example.com"},
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["DOMAIN"] == "https://override.example.com"


class TestStart:
    """Tests for the start event."""

    def test_start_creates_admin_token_secret(self):
        """The leader should create an admin token secret on start."""
        ctx = testing.Context(VaultwardenK8SCharm)
        ctx.unit_name = "vaultwarden-k8s/0"
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
            leader=True,
        )

        state_out = ctx.run(ctx.on.start(), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        secret = state_out.get_secret(label="admin-token")
        assert secret is not None
        content = secret.tracked_content
        assert "admin-token" in content
        assert len(content["admin-token"]) > 0

    def test_start_non_leader_no_secret(self):
        """Non-leader units should not create a secret on start."""
        ctx = testing.Context(VaultwardenK8SCharm)
        ctx.unit_name = "vaultwarden-k8s/1"
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
            leader=False,
        )

        state_out = ctx.run(ctx.on.start(), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        assert state_out.get_secret(label="admin-token") is None


class TestIngressRelation:
    """Tests for ingress relation changes."""

    def test_ingress_relation_changed(self):
        """Ingress relation change should set DOMAIN in the environment."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation(url="https://vaultwarden.example.com")
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.relation_changed(ingress), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["DOMAIN"] == "https://vaultwarden.example.com"

    def test_ingress_relation_broken_blocks(self):
        """Broken ingress relation should block the charm."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.relation_broken(ingress), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            "missing ingress relation or domain-override config"
        )


class TestSMTPRelation:
    """Tests for SMTP relation changes."""

    def test_smtp_relation_sets_env_vars(self):
        """SMTP relation should set SMTP_* environment variables."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        smtp = _make_smtp_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress, smtp},
        )

        state_out = ctx.run(ctx.on.relation_changed(smtp), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["SMTP_HOST"] == "smtp.example.com"
        assert env["SMTP_PORT"] == "587"
        assert env["SMTP_USERNAME"] == "user"
        assert env["SMTP_PASSWORD"] == "pass"
        assert env["SMTP_FROM"] == "vaultwarden@example.com"
        assert env["SMTP_SECURITY"] == "starttls"

    def test_smtp_relation_broken_removes_env(self):
        """Broken SMTP relation should remove SMTP_* environment variables."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        smtp = _make_smtp_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress, smtp},
        )

        state_out = ctx.run(ctx.on.relation_broken(smtp), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert "SMTP_HOST" not in env
        assert "SMTP_PORT" not in env


class TestEnvironment:
    """Tests for the rendered environment."""

    def test_default_environment(self):
        """The default environment should have correct values."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["DATA_FOLDER"] == "/data"
        assert env["SIGNUPS_ALLOWED"] == "false"
        assert env["INVITATIONS_ALLOWED"] == "true"
        assert env["WEB_VAULT_ENABLED"] == "true"
        assert env["LOG_LEVEL"] == "warn"
        assert env["ENABLE_PROMETHEUS"] == "true"
        assert env["DOMAIN"] == "https://vaultwarden.example.com"

    def test_config_options_in_environment(self):
        """Config options should be reflected in the environment."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
            config={
                "signups-allowed": True,
                "invitations-allowed": False,
                "web-vault-enabled": False,
                "log-level": "debug",
            },
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["SIGNUPS_ALLOWED"] == "true"
        assert env["INVITATIONS_ALLOWED"] == "false"
        assert env["WEB_VAULT_ENABLED"] == "false"
        assert env["LOG_LEVEL"] == "debug"

    def test_admin_token_in_environment(self):
        """Admin token should be present in the environment when secret exists."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        secret = testing.Secret(
            {"admin-token": "test-token-12345"},
            label="admin-token",
            owner="app",
        )
        state_in = testing.State(
            containers={container},
            relations={ingress},
            secrets={secret},
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        container_out = state_out.get_container(container.name)
        env = container_out.services[SERVICE_NAME].environment
        assert env["ADMIN_TOKEN"] == "test-token-12345"


class TestActions:
    """Tests for charm actions."""

    def test_get_admin_token(self):
        """get-admin-token action should return the token."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        secret = testing.Secret(
            {"admin-token": "my-secret-token"},
            label="admin-token",
            owner="app",
        )
        state_in = testing.State(
            containers={container},
            relations={ingress},
            secrets={secret},
        )

        action_output = ctx.run_action("get-admin-token", state_in)

        assert action_output.success
        assert action_output.results["admin-token"] == "my-secret-token"

    def test_get_admin_token_missing_secret(self):
        """get-admin-token action should fail when secret is missing."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        action_output = ctx.run_action("get-admin-token", state_in)

        assert not action_output.success
        assert "admin token secret not found" in action_output.failure

    def test_backup_data(self):
        """backup-data action should create a tarball and return checksum."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        action_output = ctx.run_action("backup-data", state_in)

        assert action_output.success
        assert "backup-path" in action_output.results
        assert "sha256" in action_output.results
        assert action_output.results["backup-path"].endswith(".tar.gz")
        assert len(action_output.results["sha256"]) == 64

    def test_restore_data(self):
        """restore-data action should verify checksum and restore data."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        action_output = ctx.run_action(
            "restore-data",
            state_in,
            params={
                "backup-path": "/data/backups/backup-20240101-000000.tar.gz",
                "sha256": "a" * 64,
            },
        )

        assert action_output.success
        assert "restored-from" in action_output.results

    def test_restore_data_checksum_mismatch(self):
        """restore-data action should fail on checksum mismatch."""
        ctx = testing.Context(VaultwardenK8SCharm)
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
        )

        action_output = ctx.run_action(
            "restore-data",
            state_in,
            params={
                "backup-path": "/data/backups/backup-20240101-000000.tar.gz",
                "sha256": "b" * 64,
            },
        )

        assert not action_output.success
        assert "SHA-256 mismatch" in action_output.failure


class TestLeaderElected:
    """Tests for leader-elected event."""

    def test_leader_elected_creates_secret(self):
        """Leader elected should create admin token secret."""
        ctx = testing.Context(VaultwardenK8SCharm)
        ctx.unit_name = "vaultwarden-k8s/0"
        container = _make_container()
        ingress = _make_ingress_relation()
        state_in = testing.State(
            containers={container},
            relations={ingress},
            leader=True,
        )

        state_out = ctx.run(ctx.on.leader_elected(), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        secret = state_out.get_secret(label="admin-token")
        assert secret is not None
