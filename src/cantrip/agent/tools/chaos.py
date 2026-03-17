"""Chaos testing tool — disrupts a deployed charm and verifies recovery."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = 60

# Wait timeout after disruption (seconds).
_RECOVERY_TIMEOUT = 300

# Supported disruption types.
_DISRUPTIONS = frozenset({
    "kill-unit",
    "remove-relation",
    "scale-down",
    "config-reset",
})


def _run_juju(args: list[str], model: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a juju command and return the result."""
    cmd = ["juju"] + args
    if model:
        cmd.extend(["--model", model])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )


class ChaosTestTool(Tool):
    """Tool to perform chaos testing on a deployed charm."""

    @property
    def name(self) -> str:
        return "chaos_test"

    @property
    def description(self) -> str:
        return (
            "Perform a chaos test on a deployed charm: disrupt the deployment "
            "(kill a unit, remove a relation, scale down, or reset config) "
            "then wait for recovery and report whether the charm returns to "
            "active/idle. Useful for verifying resilience and recovery logic."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to test",
                },
                "disruption": {
                    "type": "string",
                    "description": (
                        "Type of disruption: kill-unit (remove a unit), "
                        "remove-relation (break a relation), scale-down "
                        "(reduce to 0 then restore), config-reset (set config "
                        "to defaults)"
                    ),
                    "enum": sorted(_DISRUPTIONS),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "relation": {
                    "type": "string",
                    "description": (
                        "Relation endpoint to remove (required for "
                        "remove-relation disruption, e.g. 'myapp:db postgres:db')"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Seconds to wait for recovery (default 300)"
                    ),
                    "default": _RECOVERY_TIMEOUT,
                },
            },
            "required": ["app", "disruption"],
        }

    async def execute(
        self,
        app: str = "",
        disruption: str = "",
        model: str | None = None,
        relation: str | None = None,
        timeout: int = _RECOVERY_TIMEOUT,
    ) -> ToolResult:
        """Run a chaos test: disrupt then verify recovery."""
        if not shutil.which("juju"):
            return ToolResult(
                success=False,
                output="",
                error="juju CLI not found on PATH.",
            )

        if not app:
            return ToolResult(
                success=False, output="", error="app parameter is required.",
            )

        if disruption not in _DISRUPTIONS:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown disruption type: {disruption}. "
                       f"Choose from: {', '.join(sorted(_DISRUPTIONS))}",
            )

        # Step 1: capture pre-disruption status.
        pre_status = _run_juju(["status", "--format", "json", app], model)
        if pre_status.returncode != 0:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to get status: {pre_status.stderr}",
            )

        # Step 2: perform disruption.
        disruption_output = self._disrupt(app, disruption, model, relation)
        if disruption_output.startswith("Error:"):
            return ToolResult(
                success=False,
                output="",
                error=disruption_output,
            )

        # Step 3: wait for recovery.
        recovery = self._wait_for_recovery(app, model, timeout)

        # Step 4: capture post-recovery status.
        post_status = _run_juju(["status", app], model)

        report_lines = [
            "# Chaos Test Report",
            "",
            f"**Application:** {app}",
            f"**Disruption:** {disruption}",
            f"**Recovery:** {'SUCCESS' if recovery else 'FAILED'}",
            "",
            "## Disruption",
            "",
            disruption_output,
            "",
            "## Post-Recovery Status",
            "",
            "```",
            post_status.stdout.strip() if post_status.returncode == 0 else "Failed to get status",
            "```",
            "",
        ]

        return ToolResult(
            success=recovery,
            output="\n".join(report_lines),
            error=None if recovery else "Charm did not recover to active/idle",
            data={
                "app": app,
                "disruption": disruption,
                "recovered": recovery,
            },
        )

    @staticmethod
    def _disrupt(
        app: str,
        disruption: str,
        model: str | None,
        relation: str | None,
    ) -> str:
        """Perform the disruption and return a description of what was done."""
        try:
            if disruption == "kill-unit":
                result = _run_juju(["remove-unit", f"{app}/0", "--no-prompt"], model)
                if result.returncode != 0:
                    return f"Error: failed to remove unit: {result.stderr}"
                return f"Removed unit {app}/0."

            if disruption == "remove-relation":
                if not relation:
                    return "Error: relation parameter required for remove-relation."
                parts = relation.split()
                result = _run_juju(["remove-relation", *parts], model)
                if result.returncode != 0:
                    return f"Error: failed to remove relation: {result.stderr}"
                return f"Removed relation: {relation}."

            if disruption == "scale-down":
                result = _run_juju(["scale-application", app, "0"], model)
                if result.returncode != 0:
                    # Fall back to remove-unit for machine models.
                    result = _run_juju(["remove-unit", f"{app}/0", "--no-prompt"], model)
                    if result.returncode != 0:
                        return f"Error: failed to scale down: {result.stderr}"
                # Restore to 1 unit.
                restore = _run_juju(["scale-application", app, "1"], model)
                if restore.returncode != 0:
                    _run_juju(["add-unit", app], model)
                return f"Scaled {app} down to 0, then back to 1."

            if disruption == "config-reset":
                result = _run_juju(["config", app, "--reset", "--all"], model)
                if result.returncode != 0:
                    return f"Error: failed to reset config: {result.stderr}"
                return f"Reset all config options for {app} to defaults."

        except subprocess.TimeoutExpired:
            return f"Error: disruption timed out ({disruption})."

        return f"Error: unhandled disruption type {disruption}."

    @staticmethod
    def _wait_for_recovery(
        app: str,
        model: str | None,
        timeout: int,
    ) -> bool:
        """Wait for the application to return to active/idle."""
        cmd = ["juju", "wait-for", "application", app, "--timeout", f"{timeout}s"]
        if model:
            cmd.extend(["--model", model])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
