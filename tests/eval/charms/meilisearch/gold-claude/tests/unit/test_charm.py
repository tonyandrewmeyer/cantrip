"""Unit tests for the Meilisearch charm using Scenario (ops.testing)."""

import ops
import ops.testing


def test_pebble_ready_blocks_without_master_key():
    """Production mode without master-key should block."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("meilisearch", can_connect=True)
    state = ops.testing.State(
        config={"environment": "production", "master-key": ""},
        containers={container},
    )

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.BlockedStatus("master-key is required in production mode")


def test_pebble_ready_with_master_key_activates():
    """Production mode with master-key should go active."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("meilisearch", can_connect=True)
    state = ops.testing.State(
        config={
            "environment": "production",
            "master-key": "a-secure-master-key-1234",
        },
        containers={container},
    )

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.ActiveStatus()


def test_development_mode_no_key_required():
    """Development mode should not require a master-key."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("meilisearch", can_connect=True)
    state = ops.testing.State(
        config={"environment": "development", "master-key": ""},
        containers={container},
    )

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.ActiveStatus()


def test_no_pebble_connection_waits():
    """Charm should wait when Pebble is not yet available."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("meilisearch", can_connect=False)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.WaitingStatus("waiting for Pebble")


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _meta() -> dict:
    return {
        "name": "meilisearch",
        "provides": {
            "meilisearch": {"interface": "meilisearch"},
        },
        "storage": {
            "data": {"type": "filesystem", "minimum-size": "5G"},
        },
        "containers": {
            "meilisearch": {"resource": "oci-image"},
        },
        "resources": {
            "oci-image": {"type": "oci-image"},
        },
    }


def _config() -> dict:
    return {
        "options": {
            "master-key": {"type": "string", "default": ""},
            "environment": {"type": "string", "default": "production"},
            "log-level": {"type": "string", "default": "INFO"},
            "max-indexing-memory": {"type": "string", "default": ""},
            "scheduled-snapshot-interval": {"type": "int", "default": 0},
        },
    }
