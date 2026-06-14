"""Action exerciser acceptance tool."""

import pathlib
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.acceptance._common import (
    _DESTRUCTIVE_PATTERNS,
    _generate_action_params,
    _load_charm_metadata,
)
from cantrip.agent.tools.base import Tool, ToolResult

# ---------------------------------------------------------------------------
# 17.1 Action Exerciser
# ---------------------------------------------------------------------------


class ActionExerciserTool(Tool):
    """Run every action a charm exposes and verify the results."""

    @property
    def name(self) -> str:
        return "action_exerciser"

    @property
    def description(self) -> str:
        return (
            "Run every action a deployed charm exposes against a live "
            "deployment. For each action, generate plausible parameters "
            "from the schema, execute via juju run, and report the result. "
            "Destructive-sounding actions are skipped by default."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory (for reading metadata)",
                    "default": ".",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "skip_destructive": {
                    "type": "boolean",
                    "description": "Skip destructive-sounding actions (default true)",
                    "default": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Per-action timeout in seconds (default 300)",
                    "default": 300,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        skip_destructive: bool = True,
        timeout: int = 300,
    ) -> ToolResult:
        """Exercise all actions on the deployed charm."""
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")

        charm_dir = pathlib.Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)
        actions = metadata.get("actions", {}) if metadata else {}

        if not actions:
            return ToolResult(
                success=True,
                output="# Action Exerciser Report\n\nNo actions defined — nothing to test.",
                data={"app": app, "actions_tested": 0, "actions_skipped": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        skipped: list[str] = []

        for action_name, action_spec in actions.items():
            if not isinstance(action_spec, dict):
                action_spec = {}

            # Skip destructive actions.
            if skip_destructive and _DESTRUCTIVE_PATTERNS.match(action_name):
                skipped.append(action_name)
                continue

            params = _generate_action_params(action_spec)

            # Build juju run command.
            cmd_args = ["run", f"{app}/leader", action_name, "--format", "json"]
            for k, v in params.items():
                cmd_args.append(f"{k}={v}")
            if model:
                cmd_args.extend(["--model", model])

            try:
                proc = subprocess.run(
                    ["juju"] + cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                status = "completed" if proc.returncode == 0 else "failed"
                output_text = proc.stdout[:500] if proc.stdout else proc.stderr[:500]
            except subprocess.TimeoutExpired:
                status = "timeout"
                output_text = f"Timed out after {timeout}s"

            results.append(
                {
                    "action": action_name,
                    "parameters": params,
                    "status": status,
                    "output": output_text,
                }
            )

        # Build report.
        total_ok = sum(1 for r in results if r["status"] == "completed")
        total_fail = len(results) - total_ok
        all_ok = total_fail == 0

        lines = [
            "# Action Exerciser Report",
            "",
            f"**Application:** {app}",
            f"**Actions tested:** {len(results)} ({len(skipped)} skipped as destructive)",
            "",
            "## Results",
            "",
            "| Action | Parameters | Status | Notes |",
            "|--------|-----------|--------|-------|",
        ]
        for r in results:
            param_str = ", ".join(f"{k}={v}" for k, v in r["parameters"].items()) or "—"
            note = r["output"].split("\n")[0][:80] if r["output"] else ""
            lines.append(f"| {r['action']} | {param_str} | {r['status']} | {note} |")

        if skipped:
            lines.append("")
            lines.append(f"**Skipped (destructive):** {', '.join(skipped)}")

        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** "
                f"— {total_ok} of {len(results)} actions succeeded",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{total_fail} action(s) failed",
            caption=f"{total_ok} passed, {total_fail} failed",
            data={
                "app": app,
                "actions_tested": len(results),
                "actions_skipped": len(skipped),
                "actions_passed": total_ok,
                "actions_failed": total_fail,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )
