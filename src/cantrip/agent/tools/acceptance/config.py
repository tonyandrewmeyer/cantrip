"""Config variation / under-load acceptance tools."""

import contextlib
import pathlib
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools import juju_subprocess
from cantrip.agent.tools.acceptance._common import (
    _generate_test_value,
    _load_charm_metadata,
)
from cantrip.agent.tools.base import Tool, ToolResult

# ---------------------------------------------------------------------------
# 17.4 Config Variation Testing
# ---------------------------------------------------------------------------


class ConfigVariationTool(Tool):
    """Set each config option to a non-default value and verify the charm settles."""

    @property
    def name(self) -> str:
        return "config_variation_test"

    @property
    def description(self) -> str:
        return (
            "Test charm config options by setting each to a non-default "
            "value, waiting for the charm to settle, then resetting to the "
            "original. Reports which options caused errors or had no visible "
            "effect."
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
                "skip_options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Config option names to skip",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": ("Seconds to wait for settle after each change (default 120)"),
                    "default": 120,
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        model: str | None = None,
        skip_options: list[str] | None = None,
        timeout: int = 120,
    ) -> ToolResult:
        """Test each config option with a non-default value."""
        if not shutil.which("juju"):
            return ToolResult(success=False, output="", error="juju CLI not found on PATH.")
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        skip = set(skip_options or [])
        charm_dir = pathlib.Path(path).resolve()
        metadata = _load_charm_metadata(charm_dir)
        config_opts = metadata.get("config", {}).get("options", {}) if metadata else {}

        if not config_opts:
            return ToolResult(
                success=True,
                output="# Config Variation Test Report\n\nNo config options — nothing to test.",
                data={"app": app, "options_tested": 0, "results": []},
            )

        results: list[dict[str, Any]] = []
        skipped_names: list[str] = []

        for opt_name, opt_spec in config_opts.items():
            if not isinstance(opt_spec, dict):
                continue
            if opt_name in skip:
                skipped_names.append(opt_name)
                continue

            # Skip risky path/directory options.
            if any(kw in opt_name.lower() for kw in ("path", "dir", "directory", "mount")):
                skipped_names.append(opt_name)
                continue

            opt_type = opt_spec.get("type", "string")
            default = opt_spec.get("default")
            test_value = _generate_test_value(opt_type, default)

            if test_value is None:
                skipped_names.append(opt_name)
                continue

            # Set the config value.
            try:
                set_result = juju_subprocess.run_juju(
                    ["config", app, f"{opt_name}={test_value}"], model
                )
                if set_result.returncode != 0:
                    results.append(
                        {
                            "option": opt_name,
                            "type": opt_type,
                            "test_value": test_value,
                            "settled_ok": False,
                            "notes": f"Set failed: {set_result.stderr[:200]}",
                        }
                    )
                    continue
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "option": opt_name,
                        "type": opt_type,
                        "test_value": test_value,
                        "settled_ok": False,
                        "notes": "Set command timed out",
                    }
                )
                continue

            # Wait for settle.
            settled = juju_subprocess.wait_for_app(app, model, timeout)

            results.append(
                {
                    "option": opt_name,
                    "type": opt_type,
                    "test_value": test_value,
                    "settled_ok": settled,
                    "notes": "Settled to active/idle" if settled else "Did not settle",
                }
            )

            # Reset to default.
            try:
                juju_subprocess.run_juju(["config", app, "--reset", opt_name], model)
                juju_subprocess.wait_for_app(app, model, timeout)
            except subprocess.TimeoutExpired:
                pass

        tested = list(results)
        passed = sum(1 for r in tested if r["settled_ok"])
        failed = len(tested) - passed
        all_ok = failed == 0

        lines = [
            "# Config Variation Test Report",
            "",
            f"**Application:** {app}",
            f"**Options tested:** {len(tested)} ({len(skipped_names)} skipped)",
            "",
            "## Results",
            "",
            "| Option | Type | Test Value | Settled OK | Notes |",
            "|--------|------|-----------|-----------|-------|",
        ]
        for r in results:
            settled_str = "yes" if r["settled_ok"] else "NO"
            lines.append(
                f"| {r['option']} | {r['type']} | {r['test_value']} "
                f"| {settled_str} | {r['notes']} |"
            )

        if skipped_names:
            lines.extend(["", f"**Skipped:** {', '.join(skipped_names)}"])

        lines.extend(
            [
                "",
                "## Verdict",
                "",
                f"**{'PASS' if all_ok else 'FAIL'}** "
                f"— {passed} of {len(tested)} options settled correctly",
                "",
            ]
        )

        return ToolResult(
            success=all_ok,
            output="\n".join(lines),
            error=None if all_ok else f"{failed} config option(s) caused issues",
            caption=f"{passed} passed, {failed} failed",
            data={
                "app": app,
                "options_tested": len(tested),
                "options_passed": passed,
                "options_failed": failed,
                "results": results,
                "verdict": "pass" if all_ok else "fail",
            },
        )


# ---------------------------------------------------------------------------
# 17.5 Config Under Load
# ---------------------------------------------------------------------------


class ConfigUnderLoadTool(Tool):
    """Change a config option while probing a health endpoint for downtime."""

    @property
    def name(self) -> str:
        return "config_under_load_test"

    @property
    def description(self) -> str:
        return (
            "Change a config option while periodically probing a health "
            "endpoint, and report whether there was downtime or errors "
            "during the reconfiguration. Tests that config changes are "
            "applied gracefully without service interruption."
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
                "config_key": {
                    "type": "string",
                    "description": "Config option to change",
                },
                "config_value": {
                    "type": "string",
                    "description": "New value to set",
                },
                "health_url": {
                    "type": "string",
                    "description": (
                        "Health endpoint URL to probe (e.g. http://<unit-ip>:8080/health)"
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
                "probe_count": {
                    "type": "integer",
                    "description": "Number of health probes to send (default 10)",
                    "default": 10,
                },
                "probe_interval": {
                    "type": "number",
                    "description": "Seconds between probes (default 3)",
                    "default": 3,
                },
            },
            "required": ["app", "config_key", "config_value", "health_url"],
        }

    async def execute(
        self,
        app: str,
        config_key: str,
        config_value: str,
        health_url: str,
        model: str | None = None,
        probe_count: int = 10,
        probe_interval: float = 3,
    ) -> ToolResult:
        """Apply a config change while probing a health endpoint."""
        if not shutil.which("juju"):
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found.",
            )

        import asyncio
        import time

        probes: list[dict[str, Any]] = []
        errors = 0

        async def _probe_loop() -> None:
            nonlocal errors
            for i in range(probe_count):
                t0 = time.monotonic()
                try:
                    result = subprocess.run(
                        ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", health_url],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    elapsed = time.monotonic() - t0
                    status = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
                    ok = 200 <= status < 400
                    if not ok:
                        errors += 1
                    probes.append(
                        {
                            "probe": i + 1,
                            "status": status,
                            "elapsed_ms": round(elapsed * 1000),
                            "ok": ok,
                        }
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
                    errors += 1
                    probes.append(
                        {
                            "probe": i + 1,
                            "status": 0,
                            "elapsed_ms": 0,
                            "ok": False,
                        }
                    )
                await asyncio.sleep(probe_interval)

        async def _apply_config() -> None:
            # Wait for a few probes to establish baseline, then apply.
            await asyncio.sleep(probe_interval * 2)
            cmd = ["juju", "config", app, f"{config_key}={config_value}"]
            if model:
                cmd.extend(["--model", model])
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=juju_subprocess.JUJU_SUBPROCESS_TIMEOUT,
            )

        # Run probes and config change concurrently.
        await asyncio.gather(_probe_loop(), _apply_config())

        # Reset config.
        reset_cmd = ["juju", "config", app, "--reset", config_key]
        if model:
            reset_cmd.extend(["--model", model])
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                reset_cmd,
                capture_output=True,
                text=True,
                timeout=juju_subprocess.JUJU_SUBPROCESS_TIMEOUT,
            )

        verdict = "PASS" if errors == 0 else "FAIL"
        lines = [
            "# Config Under Load Test",
            "",
            f"**Application:** {app}",
            f"**Config change:** {config_key}={config_value}",
            f"**Health endpoint:** {health_url}",
            f"**Probes:** {probe_count} at {probe_interval}s intervals",
            "",
            "## Results",
            "",
            f"**Errors during reconfiguration:** {errors}/{probe_count}",
            "",
            "| Probe | Status | Time (ms) | OK |",
            "|-------|--------|-----------|----|",
        ]
        for p in probes:
            lines.append(
                f"| {p['probe']} | {p['status']} | {p['elapsed_ms']} | "
                f"{'yes' if p['ok'] else 'NO'} |"
            )
        lines.extend(["", f"**Verdict: {verdict}**", ""])

        return ToolResult(
            success=errors == 0,
            output="\n".join(lines),
            error=None if errors == 0 else f"{errors} probe(s) failed during config change",
            caption=f"{probe_count - errors} ok, {errors} errored",
            data={
                "app": app,
                "config_key": config_key,
                "config_value": config_value,
                "probes": probes,
                "errors": errors,
                "verdict": verdict.lower(),
            },
        )
