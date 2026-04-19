"""Live e2e test for the non-PaaS (machine) charm path.

Flask/Django/FastAPI/Go all travel through the 12-factor extension.
This test covers the *other* supported build path — a plain ops charm
scaffolded via the ``machine`` profile and deployed to an LXD
controller.  No rockcraft, no OCI image, no skopeo.

Requires ``GEMINI_API_KEY`` and a localhost/LXD Juju controller.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from tests.e2e import harness, seeds

pytestmark = [pytest.mark.e2e]

log = logging.getLogger(__name__)


# LXD container provisioning is substantially slower than a k8s pod.
# Do not insist on "active" — the test verifies the agent drove the
# build-and-deploy lifecycle correctly.  Reaching active is an extra
# property of the LXD environment, not of the agent under test.
_MACHINE_SPEC = harness.CharmSpec(
    name="hello-machine",
    profile="machine",
    substrate="machine",
    seed_files=seeds.MACHINE,
    requires_active=False,
)


class TestMachineCharmBuild:
    """End-to-end build+deploy of a custom (non-12-factor) machine charm."""

    @pytest.fixture(autouse=True)
    def _juju_cleanup(self):
        self._models_to_destroy: list[str] = []
        yield
        harness.destroy_models(self._models_to_destroy)

    @pytest.mark.asyncio
    async def test_build_and_deploy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        harness.require_controller("lxd")
        provider = harness.make_provider("gemini")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        harness.seed_workspace(workspace, _MACHINE_SPEC.seed_files)
        monkeypatch.chdir(workspace)

        model_info = harness.create_model("lxd", "machine")
        assert model_info is not None, "failed to create lxd model"
        model_name, qualified_model = model_info
        self._models_to_destroy.append(qualified_model)

        agent = CantripAgent(provider=provider, charm_path=workspace)

        result = await harness.drive_to_deploy(agent, _MACHINE_SPEC, workspace, qualified_model)

        for call in harness.tool_calls(agent, "juju_add_model"):
            extra = call.get("model")
            if extra and extra not in self._models_to_destroy:
                self._models_to_destroy.append(extra)

        self._assert_machine_scaffold(workspace)
        self._assert_packed(workspace)
        self._assert_deployed(result, qualified_model, model_name)

    # -- Assertion helpers -------------------------------------------------

    def _assert_machine_scaffold(self, workspace: Path) -> None:
        charm_root = _find_charm_root(workspace)
        assert charm_root is not None, "No charmcraft.yaml in workspace"

        content = (charm_root / "charmcraft.yaml").read_text()
        assert "name" in content, "charmcraft.yaml missing 'name' field"
        # A machine charm should not have pulled in a PaaS extension.
        assert "-framework" not in content, (
            "Machine charm should not use a 12-factor framework extension — "
            f"charmcraft.yaml:\n{content}"
        )

        charm_py = list(charm_root.rglob("charm.py"))
        assert charm_py, (
            "No charm.py in scaffold — machine profile should generate one; "
            f"files: {[str(p.relative_to(charm_root)) for p in charm_root.rglob('*.py')]}"
        )
        assert "ops" in charm_py[0].read_text(), "charm.py does not import ops"

    def _assert_packed(self, workspace: Path) -> None:
        archives = list(workspace.rglob("*.charm"))
        assert archives, "No .charm file produced — charmcraft_pack did not run"

    def _assert_deployed(
        self,
        result: harness.DriveResult,
        qualified_model: str,
        model_name: str,
    ) -> None:
        assert result.progress.has_deploy_call, "agent never invoked juju_deploy"
        effective_model = qualified_model or result.deploy_model or model_name
        assert harness.app_reached_deploy(effective_model, result.app_name, timeout=180), (
            f"{result.app_name!r} never appeared in model {effective_model!r}"
        )


def _find_charm_root(base: Path) -> Path | None:
    for path in base.rglob("charmcraft.yaml"):
        return path.parent
    return None
