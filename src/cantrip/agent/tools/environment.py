"""Environment provisioning tools via Concierge."""

import asyncio
import json
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Cloud names that indicate a Kubernetes substrate.  Duplicated from
# ``preflight`` rather than imported, because ``preflight`` imports from
# this module — cross-importing would create a cycle.
_K8S_CLOUDS = frozenset({"k8s", "microk8s", "kubernetes", "canonical-k8s"})


def _concierge_available() -> bool:
    """Check whether the concierge CLI is installed."""
    return shutil.which("concierge") is not None


def _concierge_already_running() -> bool:
    """Check whether a ``concierge`` process is currently running.

    Two concurrent ``concierge prepare`` invocations can leave the
    environment in a broken state (half-bootstrapped cluster, lock files
    held, etc.), so callers use this as a hard guardrail before
    launching a new one.  Uses ``pgrep -x`` which matches only exact
    basenames via ``/proc/*/comm``, so it won't false-match this
    process or other commands that happen to contain the substring.
    Returns ``False`` when ``pgrep`` is unavailable — better to let the
    caller proceed than to refuse to run at all.
    """
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return False
    try:
        result = subprocess.run(
            [pgrep, "-x", "concierge"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # pgrep exits 0 when matches exist, 1 when none found, >=2 on error.
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


async def _run_concierge(*args: str, timeout: int = 600) -> tuple[int, str, str]:
    """Run a concierge command with sudo.

    Returns a tuple of (return_code, stdout, stderr).
    """
    proc = await asyncio.create_subprocess_exec(
        "sudo",
        "concierge",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout.decode(), stderr.decode()


def _list_healthy_controllers() -> list[dict]:
    """Return controllers from ``juju controllers --format=json``, or [] on failure.

    Each entry is the raw dict as returned by Juju, which includes the
    ``cloud`` field used for preset matching.
    """
    juju = shutil.which("juju")
    if not juju:
        return []
    try:
        result = subprocess.run(
            [juju, "controllers", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        controllers = data.get("controllers", {}) or {}
        return [{"name": name, **(info or {})} for name, info in controllers.items()]
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return []


def _juju_controller_healthy() -> bool:
    """Check whether a Juju controller is already accessible.

    Runs ``juju controllers`` (cheap, no model required) and returns True
    if it exits cleanly and lists at least one controller.  This is a
    faster, more reliable signal than ``concierge status`` because it
    works regardless of how Juju was set up.
    """
    return len(_list_healthy_controllers()) > 0


def _controller_matches_preset(preset: str, cloud: str) -> bool:
    """Does a controller with *cloud* satisfy *preset*?

    ``k8s`` preset needs a K8s-family cloud; ``machine`` preset needs
    anything else (LXD, MAAS, OpenStack, EC2 — all fine).
    """
    if preset == "k8s":
        return cloud in _K8S_CLOUDS
    if preset == "machine":
        return bool(cloud) and cloud not in _K8S_CLOUDS
    # Unknown preset — don't claim a match; caller can decide.
    return False


def _healthy_controller_matches_preset(preset: str | None) -> tuple[bool, str | None]:
    """Return ``(matches, mismatch_cloud)`` for the requested preset.

    - No preset given and any controller exists → ``(True, None)`` (legacy).
    - A healthy controller matches the preset → ``(True, None)``.
    - Healthy controller(s) exist but none match → ``(False, <cloud>)``
      where ``<cloud>`` is the first existing cloud, for a clear error.
    - No controllers at all → ``(False, None)`` — caller should proceed
      with concierge.
    """
    controllers = _list_healthy_controllers()
    if not controllers:
        return False, None
    if preset is None:
        return True, None
    for ctrl in controllers:
        if _controller_matches_preset(preset, ctrl.get("cloud", "")):
            return True, None
    # Controllers exist but none match — return the first cloud as a hint.
    return False, controllers[0].get("cloud") or None


async def _is_already_provisioned(preset: str | None = None) -> tuple[bool, str | None]:
    """Check whether the environment is already usable.

    Returns ``(provisioned, mismatch_cloud)``:

    - ``provisioned=True`` when a healthy controller matches the requested
      preset (or any healthy controller exists if *preset* is ``None``).
    - ``provisioned=False, mismatch_cloud=<cloud>`` when controllers
      exist but none match the requested preset — callers must NOT run
      concierge, because doing so can break the existing controller.
    - ``(False, None)`` when no controller exists; callers should
      proceed with ``concierge prepare``.

    Falls back to ``concierge status`` when the ``juju`` CLI is missing —
    concierge status doesn't expose cloud reliably, so ``mismatch_cloud``
    stays ``None`` in that branch.
    """
    # Fast path: if Juju is working, don't touch concierge.
    matches, mismatch = _healthy_controller_matches_preset(preset)
    if matches:
        return True, None
    if mismatch is not None:
        return False, mismatch
    if not _concierge_available():
        return False, None
    try:
        rc, stdout, _stderr = await _run_concierge("status", timeout=30)
        return (rc == 0 and "succeeded" in stdout.lower()), None
    except (TimeoutError, OSError):
        return False, None


class ConciergePrepareTool(Tool):
    """Tool to provision a development environment via Concierge."""

    @property
    def name(self) -> str:
        return "concierge_prepare"

    @property
    def description(self) -> str:
        return (
            "Provision a charm development environment using Concierge. "
            "Installs Juju, a cloud substrate (LXD or Canonical K8s), and "
            "bootstraps a controller. Use 'machine' for LXD or 'k8s' for Kubernetes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "preset": {
                    "type": "string",
                    "enum": ["machine", "k8s"],
                    "description": "Environment preset: 'machine' for LXD, 'k8s' for Kubernetes",
                },
            },
            "required": ["preset"],
        }

    async def execute(self, preset: str) -> ToolResult:
        """Provision the environment with Concierge."""
        if not _concierge_available():
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Concierge is not installed. "
                    "Install it with: sudo snap install concierge --channel latest/edge"
                ),
            )

        # Refuse to launch if another concierge process is already running —
        # two concurrent `concierge prepare` calls can leave the environment
        # in a half-bootstrapped state with broken locks.
        if _concierge_already_running():
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Another concierge process is already running. "
                    "Wait for it to finish before starting a new one "
                    "(check with `pgrep -a concierge`)."
                ),
                data={"concierge_running": True},
            )

        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        provisioned, mismatch_cloud = await _is_already_provisioned(preset)
        if provisioned:
            status_output = ""
            try:
                _rc, stdout, _stderr = await _run_concierge("status", timeout=30)
                status_output = stdout.strip()
            except (TimeoutError, OSError, FileNotFoundError):
                pass
            return ToolResult(
                success=True,
                output="Environment already provisioned.\n" + status_output,
                data={"already_provisioned": True},
            )

        # Controller exists but on the wrong substrate — refuse to run
        # concierge, because it might destroy the existing controller.
        if mismatch_cloud is not None:
            required = "Kubernetes" if preset == "k8s" else "IAAS (LXD/MAAS/etc.)"
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"A healthy Juju controller on cloud '{mismatch_cloud}' "
                    f"already exists, but preset '{preset}' needs a {required} "
                    "controller. Destroy the existing controller with "
                    "`juju destroy-controller <name>` or pick a matching preset."
                ),
                data={
                    "mismatch_cloud": mismatch_cloud,
                    "requested_preset": preset,
                },
            )

        # Run the prepare command.
        try:
            rc, stdout, stderr = await _run_concierge(
                "prepare",
                "--preset",
                preset,
                timeout=600,
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="Concierge prepare timed out after 600 seconds.",
            )

        if rc != 0:
            return ToolResult(
                success=False,
                output=stdout,
                error=f"Concierge prepare failed (exit {rc}): {stderr.strip()}",
            )

        return ToolResult(
            success=True,
            output=f"Environment provisioned with preset '{preset}'.\n{stdout.strip()}",
            data={"preset": preset},
        )


class ConciergeStatusTool(Tool):
    """Tool to check the current Concierge environment status."""

    @property
    def name(self) -> str:
        return "concierge_status"

    @property
    def description(self) -> str:
        return "Check the current state of the Concierge-provisioned development environment."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self) -> ToolResult:
        """Check concierge status."""
        if not _concierge_available():
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Concierge is not installed. "
                    "Install it with: sudo snap install concierge --channel latest/edge"
                ),
            )

        try:
            rc, stdout, stderr = await _run_concierge("status", timeout=30)
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="Concierge status timed out after 30 seconds.",
            )

        if rc != 0:
            return ToolResult(
                success=False,
                output=stdout,
                error=f"Concierge status failed (exit {rc}): {stderr.strip()}",
            )

        return ToolResult(
            success=True,
            output=stdout.strip(),
        )
