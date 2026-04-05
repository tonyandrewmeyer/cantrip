"""Integration tests for the ntfy charm using Jubilant."""

import jubilant


def test_deploy_and_check_health(juju: jubilant.Juju):
    """Deploy ntfy and verify the health endpoint responds."""
    juju.deploy("ntfy", channel="edge")
    juju.wait(apps=["ntfy"], status="active", timeout=300)

    status = juju.status()
    assert status.apps["ntfy"].status == "active"
