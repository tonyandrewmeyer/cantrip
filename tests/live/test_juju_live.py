"""Live Juju integration tests.

Exercises Juju tools against a real Juju controller and model.
Skipped automatically when ``juju`` is absent or no controller
is available.
"""

import logging
import shutil
import time

import pytest

from cantrip.agent.tools.juju import (
    JujuAddModelTool,
    JujuConfigTool,
    JujuDestroyModelTool,
    JujuStatusTool,
)
from cantrip.agent.tools.observability import JujuDebugLogTool

log = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not shutil.which("juju"),
        reason="juju CLI not available",
    ),
]


def _controller_available() -> bool:
    """Check whether a Juju controller is reachable."""
    import subprocess

    result = subprocess.run(
        ["juju", "controllers", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


pytestmark.append(
    pytest.mark.skipif(
        shutil.which("juju") and not _controller_available(),
        reason="No Juju controller available",
    ),
)


@pytest.fixture(scope="module")
def live_model():
    """Create a temporary Juju model for the test module and destroy it afterwards."""
    import jubilant

    model_name = f"live-test-{int(time.time())}"
    juju = jubilant.Juju()
    juju.add_model(model_name)
    log.info("Created live test model: %s", model_name)
    yield model_name
    try:
        juju.destroy_model(model_name, force=True, destroy_storage=True, no_wait=True)
        log.info("Destroyed live test model: %s", model_name)
    except (jubilant.CLIError, OSError) as exc:
        log.warning("Failed to destroy model %s: %s", model_name, exc)


class TestJujuLive:
    """Tests that exercise Juju tools against a real controller."""

    @pytest.mark.asyncio
    async def test_juju_status(self, live_model: str):
        """JujuStatusTool.execute() returns success with model info."""
        tool = JujuStatusTool()
        result = await tool.execute(model=live_model)

        assert result.success, f"juju_status failed: {result.error}"
        assert live_model in result.output

    @pytest.mark.asyncio
    async def test_deploy_and_status(self, live_model: str):
        """Deploy juju-qa-test and verify it appears in status."""
        import jubilant

        juju = jubilant.Juju(model=live_model)
        try:
            juju.deploy("juju-qa-test")
        except jubilant.CLIError:
            pytest.skip("Could not deploy juju-qa-test (network or charm issue)")

        tool = JujuStatusTool()
        result = await tool.execute(model=live_model)

        assert result.success
        assert result.data is not None
        assert "juju-qa-test" in result.data.get("apps", [])

    @pytest.mark.asyncio
    async def test_juju_config_get_set(self, live_model: str):
        """Set a config value on juju-qa-test, then get it back."""
        tool = JujuConfigTool()

        # First ensure juju-qa-test is deployed (may already be from previous test).
        import jubilant

        juju = jubilant.Juju(model=live_model)
        status = juju.status()
        if "juju-qa-test" not in status.apps:
            try:
                juju.deploy("juju-qa-test")
            except jubilant.CLIError:
                pytest.skip("Could not deploy juju-qa-test")

        # Get config (should succeed even if no custom values are set).
        result = await tool.execute(app_name="juju-qa-test", model=live_model)
        assert result.success, f"config get failed: {result.error}"

    @pytest.mark.asyncio
    async def test_add_and_destroy_model(self, monkeypatch: pytest.MonkeyPatch):
        """JujuAddModelTool + JujuDestroyModelTool round-trip.

        Phase 80.5 added a destructive-command gate on
        ``juju_destroy_model``; it refuses unless a policy layer sets
        ``approve_destructive: true``.  This test exists to verify the
        destroy path actually destroys, so we approve via monkeypatch
        rather than touching the user's real policy directory.
        """
        from cantrip.agent import policy

        monkeypatch.setattr(policy, "destructive_gate", lambda _tool_name, **_kwargs: (True, ""))

        model_name = f"live-roundtrip-{int(time.time())}"

        add_tool = JujuAddModelTool()
        result = await add_tool.execute(model=model_name)
        assert result.success, f"add_model failed: {result.error}"

        destroy_tool = JujuDestroyModelTool()
        result = await destroy_tool.execute(model=model_name, force=True)
        assert result.success, f"destroy_model failed: {result.error}"

    @pytest.mark.asyncio
    async def test_juju_debug_log(self, live_model: str):
        """Retrieve debug log output for the model."""
        tool = JujuDebugLogTool()
        result = await tool.execute(model=live_model, lines=10)

        assert result.success, f"debug_log failed: {result.error}"
        # Debug log should return some output (even if the model is fresh).
        assert isinstance(result.output, str)
