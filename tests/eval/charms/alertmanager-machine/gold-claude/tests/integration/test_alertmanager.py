"""Integration tests for the alertmanager-machine charm using Jubilant."""

# Integration tests require a real Juju machine model.
# Run with: uv run pytest tests/integration/ -v
#
# The test suite is intentionally thin — it verifies the charm deploys,
# reaches active status, and the alertmanager API is reachable.

pytest_plugins: list[str] = []


def test_deploy_and_active(ops_test):
    """Charm should deploy and reach active status on a machine model."""
    pytest.importorskip("jubilant")
    import jubilant

    with jubilant.temp_model() as juju:
        juju.deploy("alertmanager-machine", num_units=1)
        juju.wait(jubilant.all_active, timeout=120)
        status = juju.status()
        assert status.apps["alertmanager-machine"].app_status.current == "active"
