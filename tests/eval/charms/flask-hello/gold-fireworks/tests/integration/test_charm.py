# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Jubilant integration tests for the Flask Hello charm."""

import logging
import pathlib

import jubilant

logger = logging.getLogger(__name__)


def test_deploy_blocks_without_database(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm without a database and verify it blocks."""
    juju.deploy(charm.resolve(), app="flask-hello")
    # The charm should block waiting for the database relation
    juju.wait(
        lambda status: (
            status.apps["flask-hello"].units["flask-hello/0"].workload_status == "blocked"
        )
    )


def test_deploy_with_database_becomes_active(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm with PostgreSQL and verify it becomes active."""
    juju.deploy(charm.resolve(), app="flask-hello")
    juju.deploy("postgresql", app="postgresql", channel="14/stable")
    juju.relate("flask-hello:database", "postgresql:database")
    juju.wait(jubilant.all_active)


def test_reset_counter_action(charm: pathlib.Path, juju: jubilant.Juju):
    """Test the reset-counter action when the database is available."""
    juju.deploy(charm.resolve(), app="flask-hello")
    juju.deploy("postgresql", app="postgresql", channel="14/stable")
    juju.relate("flask-hello:database", "postgresql:database")
    juju.wait(jubilant.all_active)

    result = juju.run("flask-hello/0", "reset-counter")
    assert result.return_code == 0
    assert "counter reset successfully" in str(result.results)
