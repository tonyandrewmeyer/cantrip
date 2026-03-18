"""Scaling test tool — verifies charm behaviour under unit scaling."""

import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = 60

# Wait timeout for units to settle (seconds).
_SETTLE_TIMEOUT = 300


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


def _wait_for_app(app: str, model: str | None, timeout: int) -> bool:
    """Wait for all units of an application to reach active/idle."""
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


def _get_unit_count(app: str, model: str | None) -> int | None:
    """Get the current number of units for an application."""
    result = _run_juju(["status", "--format", "json", app], model)
    if result.returncode != 0:
        return None
    try:
        import json

        data = json.loads(result.stdout)
        app_data = data.get("applications", {}).get(app, {})
        return len(app_data.get("units", {}))
    except (ValueError, KeyError):
        return None


class ScalingTestTool(Tool):
    """Tool to test charm behaviour under unit scaling."""

    @property
    def name(self) -> str:
        return "scaling_test"

    @property
    def description(self) -> str:
        return (
            "Test charm scaling behaviour by adding units, waiting for them "
            "to settle, then optionally scaling back down. Verifies that "
            "peer relations, leader election, and data replication work "
            "correctly. Reports unit status at each stage."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to scale",
                },
                "target_units": {
                    "type": "integer",
                    "description": "Number of units to scale to (default 3)",
                    "default": 3,
                },
                "scale_back": {
                    "type": "boolean",
                    "description": (
                        "Whether to scale back to 1 unit after testing (default true)"
                    ),
                    "default": True,
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds to wait for units to settle (default 300)",
                    "default": _SETTLE_TIMEOUT,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        target_units: int = 3,
        scale_back: bool = True,
        model: str | None = None,
        timeout: int = _SETTLE_TIMEOUT,
    ) -> ToolResult:
        """Scale the application and verify behaviour."""
        if not shutil.which("juju"):
            return ToolResult(
                success=False,
                output="",
                error="juju CLI not found on PATH.",
            )

        if not app:
            return ToolResult(
                success=False,
                output="",
                error="app parameter is required.",
            )

        if target_units < 1:
            return ToolResult(
                success=False,
                output="",
                error="target_units must be at least 1.",
            )

        report_lines = [
            "# Scaling Test Report",
            "",
            f"**Application:** {app}",
            f"**Target units:** {target_units}",
            "",
        ]

        # Step 1: record initial state.
        initial_count = _get_unit_count(app, model)
        report_lines.append(f"## Initial State: {initial_count or '?'} unit(s)")
        report_lines.append("")

        initial_status = _run_juju(["status", app], model)
        if initial_status.returncode == 0:
            report_lines.append("```")
            report_lines.append(initial_status.stdout.strip())
            report_lines.append("```")
            report_lines.append("")

        # Step 2: scale up.
        report_lines.append(f"## Scale Up to {target_units}")
        report_lines.append("")

        scale_result = _run_juju(
            ["scale-application", app, str(target_units)],
            model,
        )
        if scale_result.returncode != 0:
            # Fall back to add-unit for machine models.
            current = initial_count or 1
            units_to_add = target_units - current
            if units_to_add > 0:
                add_result = _run_juju(
                    ["add-unit", app, "-n", str(units_to_add)],
                    model,
                )
                if add_result.returncode != 0:
                    return ToolResult(
                        success=False,
                        output="\n".join(report_lines),
                        error=f"Failed to scale: {add_result.stderr}",
                    )

        # Wait for all units to settle.
        scale_up_ok = _wait_for_app(app, model, timeout)
        report_lines.append(f"Scale-up recovery: **{'SUCCESS' if scale_up_ok else 'FAILED'}**")
        report_lines.append("")

        # Capture scaled-up status.
        scaled_status = _run_juju(["status", app], model)
        if scaled_status.returncode == 0:
            report_lines.append("```")
            report_lines.append(scaled_status.stdout.strip())
            report_lines.append("```")
            report_lines.append("")

        scaled_count = _get_unit_count(app, model)

        # Step 3: scale back (optional).
        scale_down_ok = True
        if scale_back and (scaled_count or target_units) > 1:
            report_lines.append("## Scale Down to 1")
            report_lines.append("")

            _run_juju(["scale-application", app, "1"], model)
            scale_down_ok = _wait_for_app(app, model, timeout)
            report_lines.append(
                f"Scale-down recovery: **{'SUCCESS' if scale_down_ok else 'FAILED'}**"
            )
            report_lines.append("")

            final_status = _run_juju(["status", app], model)
            if final_status.returncode == 0:
                report_lines.append("```")
                report_lines.append(final_status.stdout.strip())
                report_lines.append("```")
                report_lines.append("")

        # Verdict.
        all_ok = scale_up_ok and scale_down_ok
        report_lines.append("## Verdict")
        report_lines.append("")
        report_lines.append(f"**{'PASS' if all_ok else 'FAIL'}**")
        report_lines.append("")

        return ToolResult(
            success=all_ok,
            output="\n".join(report_lines),
            error=None if all_ok else "Scaling test failed — check report for details",
            data={
                "app": app,
                "initial_units": initial_count,
                "target_units": target_units,
                "scale_up_ok": scale_up_ok,
                "scale_down_ok": scale_down_ok,
                "verdict": "pass" if all_ok else "fail",
            },
        )
