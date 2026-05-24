# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Unit tests for the Flask Hello charm using ops.testing (Scenario)."""

import pytest
from charm import FlaskHelloCharm
from ops import testing


def test_install_sets_blocked_waiting_for_database(monkeypatch: pytest.MonkeyPatch):
    """After install, the charm blocks until the database relation is present."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.install", lambda: None)
    monkeypatch.setattr("charm.flask_hello.write_config", lambda **_kwargs: None)

    state_out = ctx.run(ctx.on.install(), testing.State())

    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")


def test_start_without_database_is_blocked(monkeypatch: pytest.MonkeyPatch):
    """Start with no database relation leaves the charm blocked."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.start", lambda: None)
    monkeypatch.setattr("charm.flask_hello.is_running", lambda: True)
    monkeypatch.setattr("charm.flask_hello.get_version", lambda: "1.0.0")

    state_out = ctx.run(ctx.on.start(), testing.State())

    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")


def test_database_relation_changed_starts_workload(monkeypatch: pytest.MonkeyPatch):
    """When the database relation provides a URL, the charm becomes active."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.write_config", lambda **_kwargs: None)
    monkeypatch.setattr("charm.flask_hello.start", lambda: None)
    monkeypatch.setattr("charm.flask_hello.is_running", lambda: True)
    monkeypatch.setattr("charm.flask_hello.get_version", lambda: "1.0.0")

    database = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql",
        remote_app_data={"database_url": "postgresql://user:pass@db/test"},
    )
    state_in = testing.State(relations={database})

    state_out = ctx.run(ctx.on.relation_changed(database), state_in)

    assert state_out.unit_status == testing.ActiveStatus()


def test_database_relation_broken_stops_workload(monkeypatch: pytest.MonkeyPatch):
    """When the database relation is removed, the charm blocks."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.stop", lambda: None)

    database = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql",
        remote_app_data={"database_url": "postgresql://user:pass@db/test"},
    )
    state_in = testing.State(relations={database})

    state_out = ctx.run(ctx.on.relation_broken(database), state_in)

    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")


def test_config_changed_restarts_workload(monkeypatch: pytest.MonkeyPatch):
    """Config change restarts the workload when the database is available."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.write_config", lambda **_kwargs: None)
    monkeypatch.setattr("charm.flask_hello.restart", lambda: None)
    monkeypatch.setattr("charm.flask_hello.is_running", lambda: True)
    monkeypatch.setattr("charm.flask_hello.get_version", lambda: "1.0.0")

    database = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql",
        remote_app_data={"database_url": "postgresql://user:pass@db/test"},
    )
    state_in = testing.State(
        relations={database},
        config={"log-level": "debug", "debug": True, "workers": 4},
    )

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert state_out.unit_status == testing.ActiveStatus()


def test_nginx_relation_sends_reverseproxy_config(monkeypatch: pytest.MonkeyPatch):
    """The charm publishes hostname and port to the nginx relation."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.install", lambda: None)
    monkeypatch.setattr("charm.flask_hello.write_config", lambda **_kwargs: None)

    nginx = testing.Relation(
        endpoint="nginx",
        interface="reverseproxy",
        remote_app_name="nginx",
    )
    state_in = testing.State(relations={nginx})

    state_out = ctx.run(ctx.on.relation_joined(nginx), state_in)

    nginx_out = state_out.get_relation(nginx.id)
    assert nginx_out.local_unit_data.get("port") == "5000"
    assert "hostname" in nginx_out.local_unit_data


def test_reset_counter_action_fails_without_database():
    """The reset-counter action fails when there is no database relation."""
    ctx = testing.Context(FlaskHelloCharm)

    state_out = ctx.run(ctx.on.action("reset-counter"), testing.State())

    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")


def test_reset_counter_action_succeeds_with_database(monkeypatch: pytest.MonkeyPatch):
    """The reset-counter action succeeds when the database is available."""
    ctx = testing.Context(FlaskHelloCharm)
    monkeypatch.setattr("charm.flask_hello.reset_database_counter", lambda: None)

    database = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql",
        remote_app_data={"database_url": "postgresql://user:pass@db/test"},
    )
    state_in = testing.State(relations={database})

    state_out = ctx.run(ctx.on.action("reset-counter"), state_in)

    assert state_out.unit_status == testing.ActiveStatus()
