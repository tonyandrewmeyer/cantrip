"""Environment provisioning tools via Concierge."""

import asyncio
import shutil
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


def _concierge_available() -> bool:
    """Check whether the concierge CLI is installed."""
    return shutil.which("concierge") is not None


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


async def _is_already_provisioned() -> bool:
    """Check whether concierge has already provisioned the environment.

    Runs ``concierge status`` and looks for a success indicator.  Returns
    False on any error or timeout — callers should proceed with prepare.
    """
    if not _concierge_available():
        return False
    try:
        rc, stdout, _stderr = await _run_concierge("status", timeout=30)
        return rc == 0 and "succeeded" in stdout.lower()
    except (TimeoutError, OSError):
        return False


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

        # Skip if already provisioned — concierge prepare is not fully
        # idempotent and can break the k8s cluster if run twice.
        if await _is_already_provisioned():
            rc, stdout, _stderr = await _run_concierge("status", timeout=30)
            return ToolResult(
                success=True,
                output="Environment already provisioned.\n" + stdout.strip(),
                data={"already_provisioned": True},
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
