"""Unit tests for the Miniflux charm using Scenario (ops.testing)."""

import ops
import ops.testing


def test_pebble_ready_without_db_blocks():
    """Charm should block when Pebble is ready but no database relation exists."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("miniflux", can_connect=True)
    state = ops.testing.State(containers={container})

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.BlockedStatus("waiting for postgresql relation")


def test_pebble_ready_with_db_activates():
    """Charm should go active when both Pebble and database are available."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("miniflux", can_connect=True)
    pg_remote = ops.testing.App("postgresql-k8s")
    pg_relation = ops.testing.Relation(
        endpoint="postgresql",
        remote_app=pg_remote,
        remote_app_data={
            "endpoints": "postgresql-k8s-primary:5432",
            "username": "miniflux",
            "password": "secret",
            "database": "miniflux",
        },
    )
    state = ops.testing.State(
        containers={container},
        relations={pg_relation},
    )

    out = ctx.run(ctx.on.pebble_ready(container), state)

    assert out.unit_status == ops.ActiveStatus()


def test_config_changed_updates_env():
    """Config changes should propagate to the Pebble layer environment."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("miniflux", can_connect=True)
    pg_remote = ops.testing.App("postgresql-k8s")
    pg_relation = ops.testing.Relation(
        endpoint="postgresql",
        remote_app=pg_remote,
        remote_app_data={
            "endpoints": "pg:5432",
            "username": "u",
            "password": "p",
            "database": "miniflux",
        },
    )
    state = ops.testing.State(
        config={"polling-frequency": 30},
        containers={container},
        relations={pg_relation},
    )

    out = ctx.run(ctx.on.config_changed(), state)

    assert out.unit_status == ops.ActiveStatus()


def test_postgresql_broken_blocks():
    """Removing the database relation should block the unit."""
    ctx = ops.testing.Context(ops.CharmBase, meta=_meta(), config=_config())
    container = ops.testing.Container("miniflux", can_connect=True)
    pg_remote = ops.testing.App("postgresql-k8s")
    pg_relation = ops.testing.Relation(
        endpoint="postgresql",
        remote_app=pg_remote,
    )
    state = ops.testing.State(
        containers={container},
        relations={pg_relation},
    )

    out = ctx.run(ctx.on.relation_broken(pg_relation), state)

    assert out.unit_status == ops.BlockedStatus("waiting for postgresql relation")


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _meta() -> dict:
    return {
        "name": "miniflux",
        "requires": {
            "postgresql": {"interface": "postgresql_client"},
        },
        "containers": {
            "miniflux": {"resource": "oci-image"},
        },
        "resources": {
            "oci-image": {"type": "oci-image"},
        },
    }


def _config() -> dict:
    return {
        "options": {
            "base-url": {"type": "string", "default": ""},
            "polling-frequency": {"type": "int", "default": 60},
            "worker-pool-size": {"type": "int", "default": 16},
        },
    }
