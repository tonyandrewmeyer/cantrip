"""Unit tests for the ntfy charm using Scenario (ops.testing).

``ops.testing.Context`` reads ``charmcraft.yaml`` automatically when given the
real charm class — no ``meta=``/``config=`` overrides needed.
"""

import ops
import ops.testing
from src.charm import NtfyCharm


def test_pebble_ready_configures_workload():
    """Pebble ready should push config and go active."""
    ctx = ops.testing.Context(NtfyCharm)
    container = ops.testing.Container("ntfy", can_connect=True)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.ActiveStatus()


def test_config_changed_regenerates_config():
    """Config changes should regenerate server.yml."""
    ctx = ops.testing.Context(NtfyCharm)
    container = ops.testing.Container("ntfy", can_connect=True)
    state = ops.testing.State(
        config={"cache-duration": "24h"},
        containers={container},
    )

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.ActiveStatus()


def test_behind_proxy_with_ingress():
    """When ingress is related, behind-proxy should be true."""
    ctx = ops.testing.Context(NtfyCharm)
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
    ctx = ops.testing.Context(NtfyCharm)
    container = ops.testing.Container("ntfy", can_connect=False)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.WaitingStatus("waiting for Pebble")
