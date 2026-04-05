"""Integration tests for the Meilisearch charm using Jubilant."""

import jubilant


def test_deploy_and_health_check(juju: jubilant.Juju):
    """Deploy meilisearch with a master key and check health."""
    juju.deploy("meilisearch", channel="edge")
    juju.config("meilisearch", {"master-key": "test-key-at-least-16-bytes"})

    juju.wait(apps=["meilisearch"], status="active", timeout=300)

    status = juju.status()
    assert status.apps["meilisearch"].status == "active"
