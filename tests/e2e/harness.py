"""Shared harness for driving the Cantrip agent through a full charm build.

The live Flask e2e test originally carried several hundred lines of
orchestration that is almost identical for every framework/profile.
Extracting it here keeps the per-framework test bodies tiny and lets the
suite cover Flask, Django, FastAPI, Go and a machine-charm path with a
single source of truth for juju model lifecycle, nudging, and polling.

The helpers assume a live ``juju`` CLI and the Cantrip agent; they do
*not* stub anything.  Tests that call into this harness must be gated on
the relevant API keys and on the controllers the harness expects.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import ProviderRateLimitError

if TYPE_CHECKING:
    from cantrip.llm.base import LLMProvider

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

MAX_FOLLOW_UPS = 12
"""Upper bound on follow-up nudges before the harness gives up."""

RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_SECONDS = 60


# ---------------------------------------------------------------------------
# Charm-spec dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CharmSpec:
    """Description of one e2e build target.

    One instance of :class:`CharmSpec` drives the whole conversation: it
    tells the harness what to seed into the workspace, what controller
    to deploy to, what resources to pass, and when to stop nudging the
    agent.
    """

    name: str
    """Human-readable identifier used in log lines and app names."""

    profile: str
    """Charmcraft ``init`` profile — e.g. ``flask-framework`` or ``machine``."""

    substrate: str
    """``"k8s"`` or ``"machine"``.  Picks the Juju controller type."""

    seed_files: dict[str, str]
    """Mapping of relative path to file contents for the workspace seed."""

    prebuilt_oci_image: str | None = None
    """Public OCI image to pass as ``oci-image`` resource.

    When set the harness tells the agent to skip rockcraft entirely and
    deploy with this image reference, which is how the Go path avoids a
    full Go toolchain build.  For flask/django/fastapi this is ``None``
    and the agent is expected to build+push a rock.
    """

    requires_active: bool = True
    """Whether the test insists on the app reaching ``active`` status.

    Set to ``False`` when the workload is a placeholder that will never
    reach active (e.g. Go with a random public image) — the test then
    only checks that ``juju deploy`` succeeded and the app is in the
    model.
    """

    acceptable_statuses: frozenset[str] = dataclasses.field(
        default_factory=lambda: frozenset({"active"})
    )
    """Statuses that count as "the charm installed and is running fine".

    The default is ``{"active"}`` — a PaaS charm with the workload deps
    in place should reach active.  Charms that need external relations
    or further config to reach active (e.g. Django with no database,
    FastAPI with no config) can widen this to ``{"active", "blocked"}``
    so the test still distinguishes "charm hook crashed" (``error``)
    from "charm is up and awaiting integration".

    Ignored when :attr:`requires_active` is ``False``.
    """

    active_timeout_seconds: int = 300
    """How long to wait for the status check when ``requires_active`` is true."""


# ---------------------------------------------------------------------------
# Workspace seeding
# ---------------------------------------------------------------------------


def seed_workspace(workspace: Path, files: dict[str, str]) -> None:
    """Write *files* into *workspace*, creating parent directories."""
    workspace.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


# ---------------------------------------------------------------------------
# Juju model lifecycle
# ---------------------------------------------------------------------------


def juju_available() -> bool:
    return shutil.which("juju") is not None


def find_controller(cloud_type: str) -> str | None:
    """Return the name of a juju controller whose cloud matches *cloud_type*.

    *cloud_type* is ``"k8s"`` for Kubernetes clouds, or ``"lxd"`` /
    ``"localhost"`` for machine clouds.  Returns ``None`` when no
    controller of that type is registered on the host.
    """
    result = subprocess.run(
        ["juju", "controllers", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    wanted = {
        "k8s": {"k8s", "kubernetes"},
        "lxd": {"lxd", "localhost"},
    }[cloud_type]
    for name, info in data.get("controllers", {}).items():
        if info.get("cloud", "") in wanted:
            return name
    return None


def create_model(cloud_type: str, label: str) -> tuple[str, str] | None:
    """Create a fresh Juju model for *cloud_type* and return ``(short, qualified)``.

    *label* is embedded in the model name to make log triage easier.
    Returns ``None`` if juju is missing or no matching controller exists.
    """
    if not juju_available():
        return None
    import jubilant

    controller = find_controller(cloud_type)
    if not controller:
        log.warning("No %s controller registered; skipping model creation", cloud_type)
        return None

    model_name = f"e2e-{label}-{int(time.time())}"
    juju = jubilant.Juju()
    try:
        juju.add_model(model_name, controller=controller)
    except (jubilant.CLIError, OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not add %s model: %s", cloud_type, exc)
        return None
    qualified = f"{controller}:{model_name}"
    log.info("Created %s model %s on %s", cloud_type, model_name, controller)
    return model_name, qualified


def destroy_models(qualified_names: list[str]) -> None:
    """Best-effort teardown of the models the harness created."""
    if not juju_available():
        return
    import jubilant

    for qualified in qualified_names:
        try:
            juju = jubilant.Juju(model=qualified)
            juju.destroy_model(
                qualified,
                force=True,
                destroy_storage=True,
                no_wait=True,
            )
            log.info("Destroyed model %s", qualified)
        except (jubilant.CLIError, OSError, subprocess.SubprocessError) as exc:
            log.warning("Failed to destroy model %s: %s", qualified, exc)


# ---------------------------------------------------------------------------
# Agent interrogation helpers
# ---------------------------------------------------------------------------


def tool_calls(agent: CantripAgent, name: str) -> list[dict]:
    """Return every argument dict for agent calls to *name* so far."""
    results: list[dict] = []
    for msg in agent.state.messages:
        for tc in msg.tool_calls:
            if tc.name == name:
                results.append(tc.arguments)
    return results


def derive_app_name(deploy_args: dict) -> str:
    app_name = deploy_args.get("app_name")
    if app_name:
        return str(app_name)
    charm_ref = deploy_args.get("charm", "unknown")
    return Path(str(charm_ref)).stem.split("_")[0]


def find_deployed_app(deploy_calls: list[dict]) -> tuple[str, str | None]:
    """Pick the most informative deploy call — one with an explicit model wins."""
    candidates = [(derive_app_name(c), c.get("model")) for c in deploy_calls]
    for app_name, model in candidates:
        if model:
            return app_name, model
    return candidates[-1] if candidates else ("unknown", None)


async def send_message(agent: CantripAgent, message: str) -> str:
    """Send *message*, retrying with exponential-ish backoff on rate limits."""
    for attempt in range(1, RATE_LIMIT_RETRIES + 1):
        try:
            return await agent.process_message(message)
        except ProviderRateLimitError:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            wait = RATE_LIMIT_BACKOFF_SECONDS * attempt
            log.warning("Rate limited; waiting %ds before retry %d", wait, attempt + 1)
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Build-progress model
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class BuildProgress:
    """Snapshot of what the agent has achieved so far on the workspace."""

    has_charm: bool
    has_rock: bool
    has_pushed: bool
    has_deploy_call: bool
    app_in_model: bool


def snapshot_progress(
    agent: CantripAgent,
    workspace: Path,
    qualified_model: str | None,
) -> BuildProgress:
    has_charm = bool(list(workspace.rglob("*.charm")))
    has_rock = bool(list(workspace.rglob("*.rock")))
    has_push = bool(tool_calls(agent, "skopeo_registry_push"))
    has_deploy = bool(tool_calls(agent, "juju_deploy"))

    app_in_model = False
    if has_deploy and qualified_model and juju_available():
        import jubilant

        try:
            juju = jubilant.Juju(model=qualified_model)
            status = juju.status()
            app_in_model = bool(status.apps)
        except (jubilant.CLIError, OSError, subprocess.SubprocessError):
            pass

    return BuildProgress(
        has_charm=has_charm,
        has_rock=has_rock,
        has_pushed=has_push,
        has_deploy_call=has_deploy,
        app_in_model=app_in_model,
    )


# ---------------------------------------------------------------------------
# Nudging
# ---------------------------------------------------------------------------


def paas_nudge(progress: BuildProgress, model_ref: str) -> str:
    """Next hint to feed a 12-factor PaaS agent that is still working."""
    if progress.has_deploy_call and not progress.has_pushed:
        return (
            "The deployment needs an OCI image in a registry. "
            "Run rockcraft_pack to build the .rock, then "
            "skopeo_registry_push to push it to localhost:32000, then "
            f"deploy with resources={{'oci-image': '<url>'}} to model '{model_ref}'."
        )
    if progress.has_charm and progress.has_pushed:
        return (
            "The charm is packed and the image is pushed. "
            f"Deploy the .charm with resources={{'oci-image': '<url>'}} to model '{model_ref}'."
        )
    if progress.has_charm and not progress.has_pushed:
        return (
            "The charm is packed but no OCI image has been pushed. "
            "Run skopeo_registry_push on the rock, then deploy with oci-image."
        )
    if progress.has_rock and not progress.has_pushed:
        return (
            "The rock is built. Push it with skopeo_registry_push, then "
            "charmcraft_pack, then deploy with the oci-image resource."
        )
    return (
        "Continue with the remaining steps: rockcraft_pack, "
        "skopeo_registry_push, charmcraft_pack, then juju_deploy with "
        "the oci-image resource."
    )


def prebuilt_image_nudge(progress: BuildProgress, image: str, model_ref: str) -> str:
    """Nudge for the Go path where we skip rockcraft entirely."""
    if progress.has_charm:
        return (
            f"The charm is packed. Deploy it to model '{model_ref}' with "
            f"resources={{'oci-image': '{image}'}} — do NOT build a rock, "
            "just use the pre-built image."
        )
    return (
        "Continue: run charmcraft_pack to produce the .charm, then "
        f"juju_deploy with resources={{'oci-image': '{image}'}} to model '{model_ref}'. "
        "Skip rockcraft_pack and skopeo_registry_push entirely."
    )


def machine_nudge(progress: BuildProgress, model_ref: str) -> str:
    """Nudge for the machine-charm path (no OCI image involved)."""
    if progress.has_charm:
        return (
            f"The charm is packed. Deploy it to the machine model '{model_ref}' "
            "with juju_deploy — no resources are required for a machine charm."
        )
    return (
        "Continue: run charmcraft_pack to produce the .charm, then "
        f"juju_deploy to the machine model '{model_ref}'. Do NOT build a rock."
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_PAAS_INITIAL_PROMPT = """\
Build a charm for the {name} application whose source is in the current directory.
This is a 12-factor {framework} app, so follow these steps in order:
1. Analyse the source with analyse_framework
2. Create the charm scaffold with charmcraft_init ({profile} profile)
3. Build the OCI image with rockcraft_pack
4. Push the rock to the local registry with skopeo_registry_push
5. Pack the charm with charmcraft_pack to produce a .charm file
6. Deploy the .charm file with juju_deploy, passing the oci-image
   resource pointing to the pushed image.{model_clause}
You MUST complete ALL steps including rockcraft_pack, skopeo_registry_push,
and charmcraft_pack before deploying."""


_PREBUILT_IMAGE_PROMPT = """\
Build a charm for the {name} application whose source is in the current directory.
This is a 12-factor {framework} app. To keep the test quick we will skip the rock
build and reuse an existing public OCI image.

Follow these steps:
1. Analyse the source with analyse_framework
2. Create the charm scaffold with charmcraft_init ({profile} profile)
3. Pack the charm with charmcraft_pack to produce a .charm file
4. Deploy the .charm with juju_deploy, passing
   resources={{'oci-image': '{image}'}}.{model_clause}

Do NOT call rockcraft_pack or skopeo_registry_push — the image already
exists in a public registry."""


_MACHINE_PROMPT = """\
Build a machine charm for the {name} workload whose source is in the current directory.
This is a traditional (non-12-factor) charm deployed on an LXD/machine substrate.

Follow these steps:
1. Analyse the source with analyse_framework
2. Create the charm scaffold with charmcraft_init ({profile} profile)
3. Pack the charm with charmcraft_pack to produce a .charm file
4. Deploy the .charm with juju_deploy.{model_clause}

Do NOT build an OCI image — machine charms don't need one."""


def initial_prompt(spec: CharmSpec, qualified_model: str | None) -> str:
    model_clause = (
        f" Deploy to the existing model '{qualified_model}'. "
        "Do NOT create a new model — use this one."
        if qualified_model
        else ""
    )
    framework = spec.profile.removesuffix("-framework")
    ctx = {
        "name": spec.name,
        "profile": spec.profile,
        "framework": framework,
        "model_clause": model_clause,
        "image": spec.prebuilt_oci_image or "",
    }
    if spec.substrate == "machine":
        return _MACHINE_PROMPT.format(**ctx)
    if spec.prebuilt_oci_image:
        return _PREBUILT_IMAGE_PROMPT.format(**ctx)
    return _PAAS_INITIAL_PROMPT.format(**ctx)


def follow_up_prompt(spec: CharmSpec, progress: BuildProgress, qualified_model: str | None) -> str:
    model_ref = qualified_model or "<model>"
    if spec.substrate == "machine":
        return machine_nudge(progress, model_ref)
    if spec.prebuilt_oci_image:
        return prebuilt_image_nudge(progress, spec.prebuilt_oci_image, model_ref)
    return paas_nudge(progress, model_ref)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DriveResult:
    turns_taken: int
    progress: BuildProgress
    app_name: str
    deploy_model: str | None


async def drive_to_deploy(
    agent: CantripAgent,
    spec: CharmSpec,
    workspace: Path,
    qualified_model: str | None,
    *,
    max_follow_ups: int = MAX_FOLLOW_UPS,
    turn_hook: Callable[[int, str], Awaitable[None]] | None = None,
) -> DriveResult:
    """Run the agent until it has deployed the charm (or hit the nudge cap)."""
    prompt = initial_prompt(spec, qualified_model)
    response = await send_message(agent, prompt)
    log.info("[%s] turn 1: %.400s", spec.name, response)
    if turn_hook:
        await turn_hook(1, response)

    for turn in range(2, max_follow_ups + 2):
        progress = snapshot_progress(agent, workspace, qualified_model)
        if progress.app_in_model:
            log.info("[%s] deploy landed after turn %d", spec.name, turn - 1)
            break

        nudge = follow_up_prompt(spec, progress, qualified_model)
        response = await send_message(agent, nudge)
        log.info("[%s] turn %d: %.400s", spec.name, turn, response)
        if turn_hook:
            await turn_hook(turn, response)
    else:
        turn = max_follow_ups + 1

    progress = snapshot_progress(agent, workspace, qualified_model)

    deploy_calls = tool_calls(agent, "juju_deploy")
    if deploy_calls:
        app_name, deploy_model = find_deployed_app(deploy_calls)
    else:
        app_name, deploy_model = "unknown", None

    return DriveResult(
        turns_taken=turn,
        progress=progress,
        app_name=app_name,
        deploy_model=deploy_model,
    )


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------


def wait_for_active(model: str, app_name: str, timeout: int) -> str:
    """Poll ``juju status`` until *app_name* is active or *timeout* elapses.

    Thin wrapper around :func:`wait_for_status` that keeps the
    traditional "active is the only success" contract for callers that
    predate the generalised settled-status check.
    """
    return wait_for_status(model, app_name, timeout, frozenset({"active"}))


def wait_for_status(
    model: str,
    app_name: str,
    timeout: int,
    acceptable: frozenset[str],
) -> str:
    """Poll until *app_name* enters any status in *acceptable* or *timeout* elapses.

    Returns the last observed status.  Callers compare against their
    own set — e.g. ``{"active"}`` for strict tests or
    ``{"active", "blocked"}`` for charms that need external relations
    to reach active.  The ``blocked`` path is crucial for PaaS charms
    with minimal seeds (Django without a database, FastAPI without
    required config): the install hook succeeded and the charm is
    running — it is waiting for the operator's next action rather than
    crashing.
    """
    import jubilant

    deadline = time.monotonic() + timeout
    last = "unknown"
    while time.monotonic() < deadline:
        try:
            juju = jubilant.Juju(model=model)
            status = juju.status()
            if app_name in status.apps:
                current = status.apps[app_name].app_status.current or "unknown"
                last = current
                if current in acceptable:
                    return current
        except (jubilant.CLIError, OSError, subprocess.SubprocessError) as exc:
            log.debug("juju status poll error: %s", exc)
        time.sleep(10)
    return last


def app_reached_deploy(model: str, app_name: str, timeout: int = 60) -> bool:
    """Return ``True`` if *app_name* appears in *model* within *timeout* seconds."""
    import jubilant

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            juju = jubilant.Juju(model=model)
            status = juju.status()
            if app_name in status.apps:
                return True
        except (jubilant.CLIError, OSError, subprocess.SubprocessError):
            pass
        time.sleep(5)
    return False


# ---------------------------------------------------------------------------
# Skip-reason helper
# ---------------------------------------------------------------------------


def require_controller(cloud_type: str) -> None:
    """Skip the current test unless a controller of *cloud_type* is present."""
    if not juju_available():
        pytest.skip("juju CLI not installed")
    if find_controller(cloud_type) is None:
        pytest.skip(f"no {cloud_type} juju controller registered")


# ---------------------------------------------------------------------------
# Provider factory used by tests
# ---------------------------------------------------------------------------


_PROVIDER_ENV_VAR = "CANTRIP_E2E_PROVIDER"
"""Environment override for the e2e provider.

When set, this takes precedence over the ``name`` argument passed to
:func:`make_provider` — handy for running the same test against a
different provider without editing code.  Useful when a daily quota on
one provider is exhausted and we want to keep running on another.
"""


def make_provider(name: str) -> LLMProvider:
    """Instantiate a provider by name, skipping the test if keys are missing.

    The concrete provider can be overridden per-run by setting the
    ``CANTRIP_E2E_PROVIDER`` environment variable to ``gemini`` or
    ``claude`` — tests themselves don't need to know which one.
    """
    import os

    from cantrip.llm import create_provider

    resolved = os.environ.get(_PROVIDER_ENV_VAR) or name
    env_map = {
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    env = env_map.get(resolved)
    if env is None:
        pytest.skip(f"unknown e2e provider: {resolved!r}")
    if not os.environ.get(env):
        pytest.skip(f"{env} not set (resolved provider: {resolved})")
    return create_provider(resolved)
