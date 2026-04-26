"""Live e2e test for the full research → plan → build → deploy flow.

The other e2e tests in this directory tell the agent exactly what to
do: which profile to pick, which tools to call, in what order.  This
one does not.  It hands the agent a minimal user-style prompt — "build
a charm for Redis using the public image, deploy it here" — and lets
the agent own framework detection, planning, scaffolding, packing and
deployment entirely on its own.  The point is to exercise the parts of
the agent's loop (research, skill loading, task planning) that the
prescriptive tests bypass.

**Why Redis?**  It is one of the most widely-known pieces of
infrastructure software, so the agent's training data carries
unambiguous signal for what a Redis charm should look like.  The
``redis:7-alpine`` image is under 20 MB, boots in seconds with no
config, and exposes a single listener on port 6379 — all of which
means the charm can plausibly reach ``active`` even when the agent
picks the simplest possible pebble plan.

The test is deliberately forgiving on final charm shape: it only
insists that (1) a ``.charm`` file was produced, (2) ``juju_deploy``
was called, and (3) the app appears in the target model.  It does
*not* require ``active`` — a custom-charm first attempt is less
reliable than a PaaS one and we do not want that flakiness in the
signal.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from tests.e2e import harness

pytestmark = [pytest.mark.e2e]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_MAX_TURNS = 20
"""Research + plan + build + deploy needs more turns than the prescriptive
PaaS tests, which already spell out every step.  20 is deliberately
generous so a few exploratory research turns do not exhaust the budget."""

_REDIS_IMAGE = "redis:7-alpine"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# A minimal, user-style prompt.  No mention of tool names, profiles,
# rockcraft, or step ordering — the agent has to work out the full
# plan from this sentence.
_INITIAL_PROMPT = """\
Please build and deploy a Kubernetes charm for Redis.

Use the public ``{image}`` container image for the workload — there's
no need to build your own rock.  Deploy the finished charm to the
existing Juju model ``{model}``.

That's the whole ask.  Figure out the rest."""


def _milestone_nudge(progress: harness.BuildProgress, model: str, image: str) -> str:
    """Return the next nudge — milestone-level, never tool-level.

    The goal is to catch the agent when it has obviously stalled (still
    no charm after several turns, or packed but not deployed) without
    dictating how to proceed.  Anything more prescriptive would defeat
    the point of the test.
    """
    if not progress.has_charm:
        return (
            "What's the next concrete step toward a packed .charm file?  "
            "Keep going — research, scaffold, edit, pack as needed."
        )
    if not progress.has_deploy_call:
        return (
            f"You have a packed .charm file.  Deploy it to model "
            f"``{model}`` with the ``{image}`` image as the OCI-image "
            "resource."
        )
    if not progress.app_in_model:
        return (
            f"The deploy call was made but the app has not appeared in "
            f"``{model}`` yet.  If the call failed, retry with the "
            "correct arguments; otherwise wait and re-verify."
        )
    return "The deploy has landed — stop here."


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestResearchCharmBuild:
    """End-to-end coverage of the research → plan → build → deploy path."""

    @pytest.fixture(autouse=True)
    def _juju_cleanup(self):
        self._models_to_destroy: list[str] = []
        yield
        harness.destroy_models(self._models_to_destroy)

    @pytest.mark.asyncio
    async def test_redis_from_minimal_prompt(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness.require_controller("k8s")
        provider = harness.make_provider("gemini")

        # Empty workspace on purpose — the agent has no hints from
        # seeded files.  It must decide what to do purely from the
        # user's sentence.
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        model_info = harness.create_model("k8s", "redis")
        assert model_info is not None, "failed to create k8s model"
        model_name, qualified_model = model_info
        self._models_to_destroy.append(qualified_model)

        agent = CantripAgent(provider=provider, charm_path=workspace)

        response = await harness.send_message(
            agent,
            _INITIAL_PROMPT.format(image=_REDIS_IMAGE, model=qualified_model),
        )
        log.info("turn 1: %.400s", response)

        for turn in range(2, _MAX_TURNS + 1):
            progress = harness.snapshot_progress(agent, workspace, qualified_model)
            if progress.app_in_model:
                log.info("deploy landed after turn %d", turn - 1)
                break
            nudge = _milestone_nudge(progress, qualified_model, _REDIS_IMAGE)
            response = await harness.send_message(agent, nudge)
            log.info("turn %d: %.400s", turn, response)

        # Clean up any extra models the agent spun up on its own.
        for call in harness.tool_calls(agent, "juju_add_model"):
            extra = call.get("model")
            if extra and extra not in self._models_to_destroy:
                self._models_to_destroy.append(extra)

        self._assert_charm_produced(workspace)
        self._assert_deployed(agent, qualified_model, model_name)

    # -- Assertions --------------------------------------------------------

    def _assert_charm_produced(self, workspace: pathlib.Path) -> None:
        charm_yaml = next(workspace.rglob("charmcraft.yaml"), None)
        assert charm_yaml is not None, (
            f"No charmcraft.yaml anywhere in the workspace. "
            f"Files: {sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*') if p.is_file())}"
        )
        archives = list(workspace.rglob("*.charm"))
        assert archives, "agent never packed a .charm file"

        content = charm_yaml.read_text()
        # The charm must declare the OCI image somewhere — either as a
        # resource with ``type: oci-image`` or via a PaaS framework
        # extension.  Either is acceptable for this test.
        declares_image = (
            "oci-image" in content.lower() or "containers:" in content or "-framework" in content
        )
        assert declares_image, (
            f"charmcraft.yaml does not declare an OCI image resource:\n{content}"
        )

    def _assert_deployed(self, agent: CantripAgent, qualified_model: str, model_name: str) -> None:
        deploy_calls = harness.tool_calls(agent, "juju_deploy")
        assert deploy_calls, "agent never invoked juju_deploy"

        app_name, deploy_model = harness.find_deployed_app(deploy_calls)
        effective_model = qualified_model or deploy_model or model_name

        log.info("verifying %s appears in %s", app_name, effective_model)
        assert harness.app_reached_deploy(effective_model, app_name, timeout=180), (
            f"{app_name!r} never appeared in model {effective_model!r}"
        )
