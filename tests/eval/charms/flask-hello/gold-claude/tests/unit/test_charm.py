"""Unit tests for the flask-hello charm using Scenario (ops.testing).

Machine charms manage processes via subprocess; tests patch subprocess.run
and filesystem helpers rather than touching the real OS.
"""

import unittest.mock

import ops
import ops.testing
from src.charm import FlaskHelloCharm


def _make_postgresql_relation() -> ops.testing.Relation:
    """Return a postgresql relation with canned connection data."""
    remote_app = ops.testing.App("postgresql")
    return ops.testing.Relation(
        endpoint="postgresql",
        remote_app=remote_app,
        remote_app_data={
            "endpoints": "10.0.0.1:5432",
            "username": "flaskhello",
            "password": "s3cr3t",
            "database": "flaskhello",
        },
    )


def test_postgresql_changed_goes_active():
    """Unit should go active when a valid postgresql relation is present."""
    ctx = ops.testing.Context(FlaskHelloCharm)
    rel = _make_postgresql_relation()
    state = ops.testing.State(relations={rel})

    with (
        unittest.mock.patch("src.charm.subprocess.run") as mock_run,
        unittest.mock.patch("src.charm._CONFIG_DIR") as mock_dir,
        unittest.mock.patch("src.charm._CONFIG_ENV") as mock_env,
    ):
        mock_dir.mkdir = unittest.mock.MagicMock()
        mock_env.write_text = unittest.mock.MagicMock()
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)

        out = ctx.run(ctx.on.relation_changed(rel), state)

    assert out.unit_status == ops.ActiveStatus()


def test_blocked_without_postgresql():
    """Config-changed should leave the unit blocked without a db relation."""
    ctx = ops.testing.Context(FlaskHelloCharm)
    state = ops.testing.State()

    with unittest.mock.patch("src.charm.subprocess.run"):
        out = ctx.run(ctx.on.config_changed(), state)

    assert isinstance(out.unit_status, ops.BlockedStatus)


def test_postgresql_broken_stops_service():
    """Removing the postgresql relation should block the unit."""
    ctx = ops.testing.Context(FlaskHelloCharm)
    rel = _make_postgresql_relation()
    state = ops.testing.State(relations={rel})

    with unittest.mock.patch("src.charm.subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)
        out = ctx.run(ctx.on.relation_broken(rel), state)

    assert isinstance(out.unit_status, ops.BlockedStatus)


def test_install_opens_port():
    """Install event should open TCP port 5000."""
    ctx = ops.testing.Context(FlaskHelloCharm)
    state = ops.testing.State()

    with (
        unittest.mock.patch("src.charm.subprocess.run") as mock_run,
        unittest.mock.patch("src.charm._APP_DIR") as mock_app_dir,
        unittest.mock.patch("src.charm._CONFIG_DIR") as mock_cfg_dir,
        unittest.mock.patch("pathlib.Path.write_text"),
        unittest.mock.patch("pathlib.Path.mkdir"),
    ):
        mock_app_dir.mkdir = unittest.mock.MagicMock()
        mock_cfg_dir.mkdir = unittest.mock.MagicMock()
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)

        out = ctx.run(ctx.on.install(), state)

    assert ops.Port("tcp", 5000) in out.opened_ports
