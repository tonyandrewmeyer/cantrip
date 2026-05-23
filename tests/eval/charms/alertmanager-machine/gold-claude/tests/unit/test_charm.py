"""Unit tests for the alertmanager-machine charm using Scenario (ops.testing).

Machine charms don't use Pebble containers, so the tests drive the event
handlers directly and verify status transitions and subprocess calls.
"""

import unittest.mock

import ops
import ops.testing
from src.charm import AlertmanagerCharm


def test_config_changed_writes_config_and_goes_active():
    """Config-changed should regenerate config and mark the unit active."""
    ctx = ops.testing.Context(AlertmanagerCharm)
    state = ops.testing.State(config={"resolve-timeout": "3m", "log-level": "debug"})

    with (
        unittest.mock.patch("src.charm.subprocess.run") as mock_run,
        unittest.mock.patch("src.charm._CONFIG_DIR") as mock_dir,
        unittest.mock.patch("src.charm._CONFIG_PATH") as mock_path,
    ):
        mock_dir.mkdir = unittest.mock.MagicMock()
        mock_path.write_text = unittest.mock.MagicMock()
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)

        out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.ActiveStatus()


def test_install_opens_port():
    """Install event should open TCP port 9093."""
    ctx = ops.testing.Context(AlertmanagerCharm)
    state = ops.testing.State()

    with (
        unittest.mock.patch("src.charm.subprocess.run") as mock_run,
        unittest.mock.patch("src.charm._CONFIG_DIR") as mock_dir,
        unittest.mock.patch("src.charm._CONFIG_PATH") as mock_path,
    ):
        mock_dir.mkdir = unittest.mock.MagicMock()
        mock_path.write_text = unittest.mock.MagicMock()
        mock_run.return_value = unittest.mock.MagicMock(returncode=0)

        out = ctx.run(ctx.on.install(), state)

    assert ops.Port("tcp", 9093) in out.opened_ports


def test_install_blocked_when_snap_fails():
    """A failing snap install should leave the unit in BlockedStatus."""
    import subprocess

    ctx = ops.testing.Context(AlertmanagerCharm)
    state = ops.testing.State()

    with unittest.mock.patch("src.charm.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "snap", stderr=b"error")
        out = ctx.run(ctx.on.install(), state)

    assert isinstance(out.unit_status, ops.BlockedStatus)
