"""Upgrade testing tool — verifies charm upgrades between revisions."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools import juju_subprocess
from cantrip.agent.tools.base import Tool, ToolResult

# Wait timeout for units to settle after upgrade (seconds).
_SETTLE_TIMEOUT = 300


def _get_app_status(
    app: str,
    model: str | None,
) -> dict[str, Any]:
    """Get structured status for an application."""
    result = juju_subprocess.run_juju(["status", "--format", "json", app], model)
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
        return data.get("applications", {}).get(app, {})
    except (ValueError, KeyError):
        return {}


def _check_hook_failures(app: str, model: str | None, lines: int = 100) -> list[str]:
    """Check debug-log for hook failures during upgrade."""
    try:
        result = juju_subprocess.run_juju(
            ["debug-log", "-n", str(lines), "--no-tail", "--include", app],
            model,
        )
    except (FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    failures = []
    for line in result.stdout.splitlines():
        if "hook failed" in line.lower() or "error" in line.lower():
            failures.append(line.strip())
    return failures[-20:]  # Keep last 20 for brevity.


class UpgradeTestTool(Tool):
    """Tool to test charm upgrade paths between revisions."""

    @property
    def name(self) -> str:
        return "upgrade_test"

    @property
    def description(self) -> str:
        return (
            "Test a charm upgrade by refreshing a deployed application with a "
            "new charm file and verifying it returns to active/idle without "
            "regressions. Reports pre-upgrade status, post-upgrade status, "
            "hook failures during upgrade, and an overall pass/fail verdict."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to upgrade",
                },
                "charm_path": {
                    "type": "string",
                    "description": (
                        "Path to the new .charm file to refresh with "
                        "(e.g. './my-charm_amd64.charm')"
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "resources": {
                    "type": "object",
                    "description": (
                        "Optional resources to attach during refresh "
                        "(e.g. {'oci-image': 'registry/image:tag'})"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": ("Seconds to wait for recovery after upgrade (default 300)"),
                    "default": _SETTLE_TIMEOUT,
                },
            },
            "required": ["app", "charm_path"],
        }

    async def execute(
        self,
        app: str = "",
        charm_path: str = "",
        model: str | None = None,
        resources: dict[str, str] | None = None,
        timeout: int = _SETTLE_TIMEOUT,
    ) -> ToolResult:
        """Test a charm upgrade."""
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

        charm_file = Path(charm_path)
        if not charm_file.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Charm file not found: {charm_path}",
            )

        report_lines = [
            "# Upgrade Test Report",
            "",
            f"**Application:** {app}",
            f"**Charm file:** {charm_path}",
            "",
        ]

        # Step 1: capture pre-upgrade status.
        report_lines.append("## Pre-Upgrade Status")
        report_lines.append("")

        pre_status = _get_app_status(app, model)
        if not pre_status:
            return ToolResult(
                success=False,
                output="\n".join(report_lines),
                error=f"Application '{app}' not found or not deployed.",
            )

        pre_app_status = pre_status.get("application-status", {})
        pre_units = pre_status.get("units", {})
        report_lines.append(f"- App status: {pre_app_status.get('current', '?')}")
        report_lines.append(f"- Units: {len(pre_units)}")
        for unit_name, unit_data in pre_units.items():
            ws = unit_data.get("workload-status", {})
            report_lines.append(f"  - {unit_name}: {ws.get('current', '?')}")
        report_lines.append("")

        # Step 2: perform upgrade (juju refresh).
        report_lines.append("## Upgrade")
        report_lines.append("")

        refresh_cmd = ["refresh", app, "--path", str(charm_file)]
        if resources:
            for res_name, res_value in resources.items():
                refresh_cmd.extend(["--resource", f"{res_name}={res_value}"])

        try:
            refresh_result = juju_subprocess.run_juju(refresh_cmd, model)
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="\n".join(report_lines),
                error="juju refresh timed out.",
            )

        if refresh_result.returncode != 0:
            report_lines.append(f"Refresh failed: {refresh_result.stderr}")
            return ToolResult(
                success=False,
                output="\n".join(report_lines),
                error=f"juju refresh failed: {refresh_result.stderr}",
            )

        report_lines.append("Refresh command succeeded.")
        report_lines.append("")

        # Step 3: wait for recovery.
        report_lines.append("## Post-Upgrade Recovery")
        report_lines.append("")

        recovered = juju_subprocess.wait_for_app(app, model, timeout)
        report_lines.append(f"Recovery: **{'SUCCESS' if recovered else 'FAILED'}**")
        report_lines.append("")

        # Step 4: capture post-upgrade status.
        report_lines.append("## Post-Upgrade Status")
        report_lines.append("")

        post_status = _get_app_status(app, model)
        post_app_status = post_status.get("application-status", {})
        post_units = post_status.get("units", {})
        report_lines.append(f"- App status: {post_app_status.get('current', '?')}")
        report_lines.append(f"- Units: {len(post_units)}")
        for unit_name, unit_data in post_units.items():
            ws = unit_data.get("workload-status", {})
            report_lines.append(f"  - {unit_name}: {ws.get('current', '?')}")
        report_lines.append("")

        # Step 5: check for hook failures during upgrade.
        hook_failures = _check_hook_failures(app, model)
        if hook_failures:
            report_lines.append("## Hook Failures During Upgrade")
            report_lines.append("")
            for line in hook_failures:
                report_lines.append(f"  {line}")
            report_lines.append("")

        # Step 6: compare pre/post status.
        report_lines.append("## Comparison")
        report_lines.append("")

        pre_current = pre_app_status.get("current", "unknown")
        post_current = post_app_status.get("current", "unknown")
        status_regressed = pre_current == "active" and post_current != "active"
        units_changed = len(pre_units) != len(post_units)

        if status_regressed:
            report_lines.append(
                f"**REGRESSION**: status changed from {pre_current} to {post_current}"
            )
        elif not recovered:
            report_lines.append("**FAILED**: application did not recover to active/idle")
        else:
            report_lines.append("No regressions detected.")

        if units_changed:
            report_lines.append(f"Unit count changed: {len(pre_units)} → {len(post_units)}")
        report_lines.append("")

        # Verdict.
        all_ok = recovered and not status_regressed
        report_lines.append("## Verdict")
        report_lines.append("")
        report_lines.append(f"**{'PASS' if all_ok else 'FAIL'}**")
        report_lines.append("")

        return ToolResult(
            success=all_ok,
            output="\n".join(report_lines),
            error=None if all_ok else "Upgrade test failed — see report",
            caption=f"upgrade {app}: {'PASS' if all_ok else 'FAIL'}",
            data={
                "app": app,
                "pre_status": pre_current,
                "post_status": post_current,
                "recovered": recovered,
                "status_regressed": status_regressed,
                "hook_failures": len(hook_failures),
                "verdict": "pass" if all_ok else "fail",
            },
        )
