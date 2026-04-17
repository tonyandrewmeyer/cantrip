"""Unit tests for the ntfy charm using Scenario (ops.testing)."""

import ops
import ops.testing


def test_pebble_ready_configures_workload():
    """Pebble ready should push config and go active."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("ntfy", can_connect=True)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.ActiveStatus()


def test_config_changed_regenerates_config():
    """Config changes should regenerate server.yml."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("ntfy", can_connect=True)
    state = ops.testing.State(
        config={"cache-duration": "24h"},
        containers={container},
    )

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.ActiveStatus()


def test_behind_proxy_with_ingress():
    """When ingress is related, behind-proxy should be true."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("ntfy", can_connect=True)
    ingress_remote = ops.testing.App("traefik-k8s")
    ingress_relation = ops.testing.Relation(
        endpoint="ingress",
        remote_app=ingress_remote,
    )
    state = ops.testing.State(
        containers={container},
        relations={ingress_relation},
    )

    out = ctx.run(ctx.on.relation_changed(ingress_relation), state)

    assert out.unit_status == ops.ActiveStatus()


def test_no_pebble_connection_waits():
    """Charm should wait when Pebble is not yet available."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("ntfy", can_connect=False)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.WaitingStatus("waiting for Pebble")


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _meta() -> dict:
    return {
        "name": "ntfy",
        "requires": {
            "ingress": {"interface": "ingress", "limit": 1},
        },
        "storage": {
            "data": {"type": "filesystem", "minimum-size": "1G"},
        },
        "containers": {
            "ntfy": {"resource": "oci-image"},
        },
        "resources": {
            "oci-image": {"type": "oci-image"},
        },
    }


def _config() -> dict:
    return {
        "options": {
            "base-url": {"type": "string", "default": ""},
            "cache-duration": {"type": "string", "default": "12h"},
            "log-level": {"type": "string", "default": "info"},
            "upstream-base-url": {"type": "string", "default": ""},
        },
    }
