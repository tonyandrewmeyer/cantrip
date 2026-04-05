"""Integration tests for the Miniflux charm using Jubilant."""

import jubilant


def test_deploy_and_relate(juju: jubilant.Juju):
    """Deploy miniflux and postgresql, relate, and wait for active."""
    juju.deploy("miniflux", channel="edge")
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate("miniflux:postgresql", "postgresql-k8s:database")

    juju.wait(apps=["miniflux"], status="active", timeout=600)

    status = juju.status()
    assert status.apps["miniflux"].status == "active"
