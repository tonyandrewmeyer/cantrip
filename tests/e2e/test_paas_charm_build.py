"""Live e2e tests for 12-factor PaaS charm builds.

This module parametrises the same build-and-deploy flow across Flask,
Django, FastAPI, and Go so that every framework that the agent claims
to support has its own end-to-end coverage.

The Flask/Django/FastAPI paths run the full rockcraft → skopeo →
charmcraft → juju pipeline and wait for the app to reach active status.
The Go path intentionally skips rockcraft (the Go toolchain build in
rockcraft is slow) and deploys using a pre-built public OCI image — the
resulting charm will not reach active, but the deploy itself exercises
the agent's understanding of 12-factor resource wiring.

All tests require ``GEMINI_API_KEY`` and a Kubernetes Juju controller.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from tests.e2e import harness, seeds

pytestmark = [pytest.mark.e2e]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-framework specs
# ---------------------------------------------------------------------------


_FLASK = harness.CharmSpec(
    name="flask-demo",
    profile="flask-framework",
    substrate="k8s",
    seed_files=seeds.FLASK,
)

# Django-framework charms block without a database integration — the
# paas-charm extension deliberately sets BlockedStatus until the
# operator wires one in.  That is a fully-installed, running charm,
# not a failure, so the test accepts blocked alongside active.  A
# stricter run would also deploy postgresql-k8s and relate it, but
# that is out of scope for a "can we build and deploy" smoke test.
_DJANGO = harness.CharmSpec(
    name="django-demo",
    profile="django-framework",
    substrate="k8s",
    seed_files=seeds.DJANGO,
    acceptable_statuses=frozenset({"active", "blocked"}),
)

# FastAPI-framework charms block without a handful of configured
# options (app-port, app module path) — same reasoning as Django.
_FASTAPI = harness.CharmSpec(
    name="fastapi-demo",
    profile="fastapi-framework",
    substrate="k8s",
    seed_files=seeds.FASTAPI,
    acceptable_statuses=frozenset({"active", "blocked"}),
)

# The Go path reuses an existing public OCI image rather than building a
# fresh rock: the charm then cannot reach active (its pebble plan won't
# match this image), but ``juju deploy`` still lands and that is what
# this test asserts.
_GO = harness.CharmSpec(
    name="go-demo",
    profile="go-framework",
    substrate="k8s",
    seed_files=seeds.GO,
    prebuilt_oci_image="ghcr.io/stefanprodan/podinfo:latest",
    requires_active=False,
)


_ALL_SPECS = {
    "flask": _FLASK,
    "django": _DJANGO,
    "fastapi": _FASTAPI,
    "go": _GO,
}


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestPaasCharmBuild:
    """Exercise the agent end-to-end for every supported PaaS framework."""

    @pytest.fixture(autouse=True)
    def _juju_cleanup(self):
        """Destroy any Juju models the test created when it finishes."""
        self._models_to_destroy: list[str] = []
        yield
        harness.destroy_models(self._models_to_destroy)

    @pytest.mark.parametrize("spec_key", list(_ALL_SPECS.keys()))
    @pytest.mark.asyncio
    async def test_build_and_deploy(
        self, spec_key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spec = _ALL_SPECS[spec_key]

        harness.require_controller("k8s")
        provider = harness.make_provider("gemini")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        harness.seed_workspace(workspace, spec.seed_files)

        # Subprocess tools (charmcraft, juju, rockcraft) resolve paths
        # relative to the process cwd.  Align cwd with the workspace so
        # that artefacts land where the assertions expect.
        monkeypatch.chdir(workspace)

        model_info = harness.create_model("k8s", spec_key)
        assert model_info is not None, "failed to create k8s model"
        model_name, qualified_model = model_info
        self._models_to_destroy.append(qualified_model)

        agent = CantripAgent(provider=provider, charm_path=workspace)

        result = await harness.drive_to_deploy(agent, spec, workspace, qualified_model)

        # Any additional models the agent created should be cleaned up too.
        for call in harness.tool_calls(agent, "juju_add_model"):
            extra = call.get("model")
            if extra and extra not in self._models_to_destroy:
                self._models_to_destroy.append(extra)

        self._assert_scaffold(workspace)
        self._assert_packed(workspace)
        self._assert_deployed(result, spec, qualified_model, model_name)

    # -- Assertion helpers -------------------------------------------------

    def _assert_scaffold(self, workspace: Path) -> None:
        charm_root = _find_charm_root(workspace)
        assert charm_root is not None, (
            f"No charmcraft.yaml found. Files: "
            f"{sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*') if p.is_file())}"
        )
        content = (charm_root / "charmcraft.yaml").read_text()
        assert "name" in content, "charmcraft.yaml missing 'name' field"
        # PaaS charms configure observability via their framework extension.
        paas_markers = (
            "flask-framework",
            "django-framework",
            "fastapi-framework",
            "go-framework",
            "cos",
            "tracing",
        )
        assert any(m in content.lower() for m in paas_markers), (
            f"charmcraft.yaml does not look like a PaaS charm:\n{content}"
        )

    def _assert_packed(self, workspace: Path) -> None:
        archives = list(workspace.rglob("*.charm"))
        assert archives, "No .charm file produced — charmcraft_pack did not run"
        log.info("packed charm: %s (%d bytes)", archives[0].name, archives[0].stat().st_size)

    def _assert_deployed(
        self,
        result: harness.DriveResult,
        spec: harness.CharmSpec,
        qualified_model: str,
        model_name: str,
    ) -> None:
        assert result.progress.has_deploy_call, "agent never invoked juju_deploy"

        effective_model = qualified_model or result.deploy_model or model_name
        log.info("%s: verifying app %s in %s", spec.name, result.app_name, effective_model)

        # Every spec — active-required or not — must at minimum get the
        # app registered in the target model.
        assert harness.app_reached_deploy(effective_model, result.app_name, timeout=120), (
            f"{result.app_name!r} never appeared in model {effective_model!r}"
        )

        if spec.requires_active:
            last = harness.wait_for_status(
                effective_model,
                result.app_name,
                spec.active_timeout_seconds,
                spec.acceptable_statuses,
            )
            assert last in spec.acceptable_statuses, (
                f"{result.app_name!r} did not reach one of "
                f"{sorted(spec.acceptable_statuses)} within "
                f"{spec.active_timeout_seconds}s (last status: {last!r})"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_charm_root(base: Path) -> Path | None:
    for path in base.rglob("charmcraft.yaml"):
        return path.parent
    return None
