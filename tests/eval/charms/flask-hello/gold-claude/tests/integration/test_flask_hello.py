"""Integration tests for the flask-hello charm using Jubilant."""

# Integration tests require a real Juju machine model with PostgreSQL.
# Run with: uv run pytest tests/integration/ -v

pytest_plugins: list[str] = []


def test_deploy_with_postgresql(ops_test):
    """Charm should go active once the postgresql relation is satisfied."""
    pytest.importorskip("jubilant")
    import jubilant

    with jubilant.temp_model() as juju:
        juju.deploy("flask-hello", num_units=1)
        juju.deploy("postgresql", num_units=1)
        juju.integrate("flask-hello:postgresql", "postgresql:database")
        juju.wait(jubilant.all_active, timeout=300)
        status = juju.status()
        assert status.apps["flask-hello"].app_status.current == "active"
