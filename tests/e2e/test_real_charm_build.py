"""Real end-to-end test: build, pack, and deploy a charm with a live LLM.

Exercises the complete agent workflow against a real Gemini provider,
from application source through to a live Juju deployment.

This test is slow (potentially several minutes) and requires:

  - ``GEMINI_API_KEY`` environment variable
  - ``charmcraft``, ``juju``, and supporting tools installed

Skipped automatically when ``GEMINI_API_KEY`` is absent.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider
from cantrip.llm.base import ProviderRateLimitError

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    ),
]

log = logging.getLogger(__name__)

# Maximum follow-up messages before declaring the conversation stuck.
_MAX_FOLLOW_UPS = 12

# Seconds to wait for the deployed charm to reach active status.
_ACTIVE_TIMEOUT_SECONDS = 300

# Rate-limit retry parameters for the outer _send_message wrapper.
# The agent core also retries internally; this provides a second safety net.
_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BACKOFF_SECONDS = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEMO_APP_PY = """\
from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return {"status": "ok", "service": "demo-api"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
"""

_DEMO_REQUIREMENTS_TXT = "flask>=3.0\n"


def _seed_flask_app(workspace: Path) -> None:
    """Create a minimal Flask application in *workspace*.

    This gives the agent something concrete to analyse, avoiding the need
    to clone from a remote repository (which may not exist yet).
    """
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "app.py").write_text(_DEMO_APP_PY)
    (workspace / "requirements.txt").write_text(_DEMO_REQUIREMENTS_TXT)


def _find_charm_root(base: Path) -> Path | None:
    """Return the first directory containing ``charmcraft.yaml`` under *base*."""
    for path in base.rglob("charmcraft.yaml"):
        return path.parent
    return None


def _extract_tool_calls(agent: CantripAgent, tool_name: str) -> list[dict]:
    """Return all argument dicts for calls to *tool_name* in the conversation."""
    results = []
    for msg in agent.state.messages:
        for tc in msg.tool_calls:
            if tc.name == tool_name:
                results.append(tc.arguments)
    return results


def _derive_app_name(deploy_args: dict) -> str:
    """Best-effort derivation of the Juju application name from deploy arguments."""
    app_name = deploy_args.get("app_name")
    if app_name:
        return app_name
    # Juju derives the app name from the charm reference.  For a local
    # .charm file the name is the stem minus architecture suffixes.
    charm_ref = deploy_args.get("charm", "unknown")
    return Path(charm_ref).stem.split("_")[0]


def _find_deployed_app(deploy_calls: list[dict]) -> tuple[str, str | None]:
    """Find the best app name and model from the deploy calls.

    Checks all deploy calls and prefers ones that target a specific model.
    Returns (app_name, model).
    """
    # Collect unique (app_name, model) pairs, preferring explicit models.
    candidates: list[tuple[str, str | None]] = []
    for call_args in deploy_calls:
        app_name = _derive_app_name(call_args)
        model = call_args.get("model")
        candidates.append((app_name, model))

    # Prefer deploys with an explicit model.
    for app_name, model in candidates:
        if model:
            return app_name, model

    # Fall back to the last deploy call.
    if candidates:
        return candidates[-1]
    return "unknown", None


async def _send_message(agent: CantripAgent, message: str) -> str:
    """Send a message to the agent, retrying on rate-limit errors."""
    for attempt in range(1, _RATE_LIMIT_RETRIES + 1):
        try:
            return await agent.process_message(message)
        except ProviderRateLimitError:
            if attempt == _RATE_LIMIT_RETRIES:
                raise
            wait = _RATE_LIMIT_BACKOFF_SECONDS * attempt
            log.warning("Rate limited — waiting %ds before retry %d", wait, attempt + 1)
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestRealCharmBuild:
    """Build a charm from a Flask app using a real LLM and verify the result."""

    @pytest.fixture(autouse=True)
    def _juju_cleanup(self):
        """Destroy any Juju models the agent created during the test."""
        self._models_to_destroy: list[str] = []
        yield
        if not shutil.which("juju"):
            return
        import jubilant

        for qualified_name in self._models_to_destroy:
            try:
                juju = jubilant.Juju(model=qualified_name)
                juju.destroy_model(
                    qualified_name,
                    force=True,
                    destroy_storage=True,
                    no_wait=True,
                )
                log.info("Destroyed model %s", qualified_name)
            except Exception as exc:
                log.warning("Failed to destroy model %s: %s", qualified_name, exc)

    def _setup_juju_model(self) -> tuple[str, str] | None:
        """Create a fresh Juju model on a Kubernetes controller.

        Flask-framework charms require Kubernetes.  This method finds a k8s
        controller and creates a model on it.

        Returns ``(short_name, qualified_name)`` or ``None`` on failure.
        The *qualified_name* includes the controller prefix
        (e.g. ``"concierge-k8s:e2e-123"``).
        """
        if not shutil.which("juju"):
            return None
        try:
            import jubilant

            k8s_controller = self._find_k8s_controller()
            if not k8s_controller:
                log.warning("No Kubernetes Juju controller found")
                return None

            model_name = f"e2e-{int(time.time())}"
            juju = jubilant.Juju()
            juju.add_model(model_name, controller=k8s_controller)
            qualified = f"{k8s_controller}:{model_name}"
            self._models_to_destroy.append(qualified)
            log.info("Created test model: %s (on %s)", model_name, k8s_controller)
            return model_name, qualified
        except Exception as exc:
            log.warning("Failed to create test model: %s", exc)
            return None

    @staticmethod
    def _find_k8s_controller() -> str | None:
        """Return the name of a Kubernetes Juju controller, or ``None``."""
        import json

        result = subprocess.run(
            ["juju", "controllers", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for name, info in data.get("controllers", {}).items():
            if info.get("cloud", "") == "k8s":
                return name
        return None

    # -----------------------------------------------------------------------
    # Main test
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_build_demo_api_charm(self, tmp_path: Path, monkeypatch):
        """Full lifecycle: analyse -> scaffold -> pack -> deploy -> active."""
        provider = create_provider("gemini")
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Seed the workspace with a minimal Flask application so the agent
        # can analyse it directly instead of cloning a remote repo.
        _seed_flask_app(workspace)

        # Subprocess-based tools (charmcraft, juju) resolve paths relative
        # to the process cwd.  Align cwd with the workspace so that
        # artefacts land where the assertions expect them.
        monkeypatch.chdir(workspace)

        # Pre-create a Juju model on a k8s controller so the agent can deploy.
        model_info = self._setup_juju_model()
        model_name = model_info[0] if model_info else None
        qualified_model = model_info[1] if model_info else None

        agent = CantripAgent(provider=provider, charm_path=workspace)

        # -- Drive the conversation ----------------------------------------
        model_instruction = ""
        if qualified_model:
            model_instruction = (
                f" Deploy to the existing Kubernetes Juju model '{qualified_model}'."
                " Do NOT create a new model — use this one."
            )

        response = await _send_message(
            agent,
            "Build a charm for the demo_api_charm Flask application "
            "whose source is in the current directory. "
            "This is a 12-factor Flask app, so follow these steps in order:\n"
            "1. Analyse the source with analyse_framework\n"
            "2. Create the charm scaffold with charmcraft_init (flask-framework profile)\n"
            "3. Build the OCI image with rockcraft_pack\n"
            "4. Push the rock to the local registry with skopeo_registry_push\n"
            "5. Pack the charm with charmcraft_pack to produce a .charm file\n"
            "6. Deploy the .charm file with juju_deploy, passing the "
            "oci-image resource pointing to the pushed image\n"
            f"{model_instruction}\n"
            "You MUST complete ALL steps including rockcraft_pack, "
            "skopeo_registry_push, and charmcraft_pack before deploying.",
        )
        log.info("Turn 1: %.500s", response)

        for turn in range(2, _MAX_FOLLOW_UPS + 2):
            has_charm = bool(list(workspace.rglob("*.charm")))
            has_deploy = bool(_extract_tool_calls(agent, "juju_deploy"))
            has_rock = bool(list(workspace.rglob("*.rock")))
            has_push = bool(_extract_tool_calls(agent, "skopeo_registry_push"))

            # Check if the deploy actually landed (app exists in the model).
            app_deployed = False
            if has_charm and has_deploy and qualified_model:
                try:
                    import jubilant

                    juju = jubilant.Juju(model=qualified_model)
                    status = juju.status()
                    app_deployed = bool(status.apps)
                except Exception:
                    pass

            if app_deployed:
                log.info("App deployed to model after turn %d.", turn - 1)
                break

            # Nudge the agent towards what's still missing.
            model_ref = qualified_model or model_name or "<model>"
            if has_deploy and not has_push:
                nudge = (
                    "The deployment failed because the OCI image was not pushed "
                    "to a registry. You must:\n"
                    "1. Run rockcraft_pack to build the .rock file (if not done)\n"
                    "2. Run skopeo_registry_push to push the rock to "
                    "localhost:32000\n"
                    "3. Then deploy with juju_deploy passing "
                    "resources={'oci-image': 'localhost:32000/<name>:latest'} "
                    f"to model '{model_ref}'."
                )
            elif has_charm and has_push:
                nudge = (
                    "The charm is packed and the image is pushed. "
                    "Please deploy the .charm file with juju_deploy, "
                    "passing resources={'oci-image': '<registry-url>'} "
                    f"to model '{model_ref}'."
                    if qualified_model
                    else "Please deploy the .charm file now."
                )
            elif has_charm and not has_push:
                nudge = (
                    "The charm is packed but the OCI image has not been pushed "
                    "to a container registry. Run skopeo_registry_push to push "
                    "the .rock file, then deploy with the oci-image resource."
                )
            elif has_rock and not has_push:
                nudge = (
                    "The rock is built. Please push it to the registry with "
                    "skopeo_registry_push, then run charmcraft_pack, "
                    "then deploy with the oci-image resource."
                )
            else:
                nudge = (
                    "Please continue with the remaining steps. "
                    "The full sequence is: rockcraft_pack, skopeo_registry_push, "
                    "charmcraft_pack, then juju_deploy with the oci-image resource."
                )

            response = await _send_message(agent, nudge)
            log.info("Turn %d: %.500s", turn, response)

        # Record any models the agent created so the fixture can clean up.
        for call_args in _extract_tool_calls(agent, "juju_add_model"):
            agent_model = call_args.get("model")
            if agent_model and agent_model not in self._models_to_destroy:
                self._models_to_destroy.append(agent_model)

        # -- Structural assertions -----------------------------------------
        charm_root = _find_charm_root(workspace)
        assert charm_root is not None, (
            "No charmcraft.yaml found under the workspace. "
            f"Files: {sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*') if p.is_file())}"
        )

        charmcraft_content = (charm_root / "charmcraft.yaml").read_text()
        log.info("charmcraft.yaml:\n%s", charmcraft_content)
        assert "name" in charmcraft_content, "charmcraft.yaml is missing a 'name' field"

        # src/charm.py (or similar) should exist and use ops.
        charm_py_files = list(charm_root.rglob("charm.py"))
        assert charm_py_files, (
            "No charm.py found in the charm tree. "
            f"Python files: {[str(p.relative_to(charm_root)) for p in charm_root.rglob('*.py')]}"
        )
        charm_py_content = charm_py_files[0].read_text()
        log.info("charm.py:\n%s", charm_py_content)
        assert "ops" in charm_py_content, "charm.py does not reference the ops framework"

        # Comparison with k8s-5-observe: the charm should have some form
        # of observability or COS integration.  For flask-framework charms
        # this is automatic via the extension; for custom charms we look
        # for explicit integrations.
        has_cos_indicators = any(
            keyword in charmcraft_content.lower()
            for keyword in (
                "cos",
                "grafana",
                "prometheus",
                "loki",
                "tracing",
                "observability",
                "flask-framework",
            )
        )
        if not has_cos_indicators:
            log.warning(
                "charmcraft.yaml has no obvious COS/observability references. "
                "The charm may lack observability support."
            )

        # -- Pack assertion -------------------------------------------------
        charm_archives = list(workspace.rglob("*.charm"))
        assert charm_archives, "No .charm file produced — packing failed"
        log.info(
            "Packed charm: %s (%d bytes)",
            charm_archives[0].name,
            charm_archives[0].stat().st_size,
        )

        # -- Deployment assertion -------------------------------------------
        if not shutil.which("juju"):
            pytest.skip("juju CLI not available — deployment checks skipped")

        deploy_calls = _extract_tool_calls(agent, "juju_deploy")
        assert deploy_calls, "The agent did not attempt to deploy the charm"

        app_name, deploy_model = _find_deployed_app(deploy_calls)
        # Use the pre-created qualified model for jubilant status checks.
        # The agent uses the short name; we need the controller prefix.
        effective_model = qualified_model or deploy_model or model_name
        log.info(
            "Waiting for %s to reach active (model=%s, timeout=%ds) ...",
            app_name,
            effective_model,
            _ACTIVE_TIMEOUT_SECONDS,
        )

        import jubilant

        deadline = time.monotonic() + _ACTIVE_TIMEOUT_SECONDS
        last_status = "unknown"
        while time.monotonic() < deadline:
            try:
                juju = jubilant.Juju(model=effective_model)
                status = juju.status()
                if app_name in status.apps:
                    app_status = status.apps[app_name].app_status.current or "unknown"
                    last_status = app_status
                    if app_status == "active":
                        break
                    log.debug("Current status of %s: %s", app_name, app_status)
            except Exception as exc:
                log.debug("juju status poll error: %s", exc)
            time.sleep(10)

        assert last_status == "active", (
            f"Charm {app_name!r} did not reach active status within "
            f"{_ACTIVE_TIMEOUT_SECONDS}s (last status: {last_status!r})"
        )
        log.info("Charm %s is active!", app_name)
