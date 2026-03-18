"""Hook benchmark tool — measures charm hook execution times."""

import re
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Regex matching Juju debug-log hook start/stop lines.
# Format: "unit-myapp-0: HH:MM:SS DEBUG juju.worker.uniter.operation ran "install" hook (...)"
_HOOK_RAN_RE = re.compile(
    r'unit-(?P<unit>\S+): \S+ \S+ .* ran "(?P<hook>[^"]+)" hook'
    r" \((?P<duration_ms>\d+(?:\.\d+)?)ms\)"
)

# Fallback: some Juju versions log duration differently.
_HOOK_DURATION_RE = re.compile(
    r'unit-(?P<unit>\S+): .* hook "(?P<hook>[^"]+)" .* '
    r"(?P<duration>[\d.]+)\s*(?P<unit_label>ms|s)"
)

# Default threshold for flagging slow hooks (milliseconds).
_DEFAULT_THRESHOLD_MS = 5000

# Subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = 30


def _parse_hook_timings(log_output: str) -> list[dict[str, object]]:
    """Extract hook execution timings from juju debug-log output.

    Returns a list of dicts with keys: unit, hook, duration_ms.
    """
    timings: list[dict[str, object]] = []
    seen_lines: set[str] = set()

    for line in log_output.splitlines():
        if line in seen_lines:
            continue

        match = _HOOK_RAN_RE.search(line)
        if match:
            seen_lines.add(line)
            timings.append(
                {
                    "unit": match.group("unit"),
                    "hook": match.group("hook"),
                    "duration_ms": float(match.group("duration_ms")),
                }
            )
            continue

        match = _HOOK_DURATION_RE.search(line)
        if match:
            seen_lines.add(line)
            duration = float(match.group("duration"))
            if match.group("unit_label") == "s":
                duration *= 1000
            timings.append(
                {
                    "unit": match.group("unit"),
                    "hook": match.group("hook"),
                    "duration_ms": duration,
                }
            )

    return timings


def _format_benchmark_report(
    timings: list[dict[str, object]],
    threshold_ms: float,
) -> str:
    """Format a human-readable benchmark report."""
    if not timings:
        return "No hook execution timings found in the log output."

    lines = ["# Hook Benchmark Report", ""]

    # Summary statistics per hook.
    hook_stats: dict[str, list[float]] = {}
    for t in timings:
        hook = str(t["hook"])
        hook_stats.setdefault(hook, []).append(float(t["duration_ms"]))

    lines.append("## Summary")
    lines.append("")
    lines.append("| Hook | Count | Min (ms) | Max (ms) | Avg (ms) | Slow? |")
    lines.append("|------|-------|----------|----------|----------|-------|")

    slow_hooks: list[str] = []
    for hook, durations in sorted(hook_stats.items()):
        count = len(durations)
        min_d = min(durations)
        max_d = max(durations)
        avg_d = sum(durations) / count
        is_slow = max_d > threshold_ms
        if is_slow:
            slow_hooks.append(hook)
        lines.append(
            f"| {hook} | {count} | {min_d:.0f} | {max_d:.0f} | {avg_d:.0f} "
            f"| {'**YES**' if is_slow else 'no'} |"
        )

    lines.append("")

    if slow_hooks:
        lines.append(f"## Slow Hooks (>{threshold_ms:.0f} ms)")
        lines.append("")
        for hook in slow_hooks:
            durations = hook_stats[hook]
            lines.append(
                f"- **{hook}**: max {max(durations):.0f} ms (threshold {threshold_ms:.0f} ms)"
            )
        lines.append("")
    else:
        lines.append(f"All hooks executed within the {threshold_ms:.0f} ms threshold.")
        lines.append("")

    return "\n".join(lines)


class HookBenchmarkTool(Tool):
    """Tool to measure and report charm hook execution times."""

    @property
    def name(self) -> str:
        return "hook_benchmark"

    @property
    def description(self) -> str:
        return (
            "Analyse charm hook execution times from juju debug-log output. "
            "Extracts hook durations, computes statistics (min/max/avg per hook), "
            "and flags hooks exceeding a configurable threshold. Useful for "
            "identifying performance bottlenecks in charm code."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "app": {
                    "type": "string",
                    "description": "Application name to filter logs for",
                },
                "threshold_ms": {
                    "type": "number",
                    "description": (
                        "Threshold in milliseconds — hooks slower than this are "
                        "flagged (default 5000)"
                    ),
                    "default": _DEFAULT_THRESHOLD_MS,
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of debug-log lines to analyse (default 500)",
                    "default": 500,
                },
            },
        }

    async def execute(
        self,
        model: str | None = None,
        app: str | None = None,
        threshold_ms: float = _DEFAULT_THRESHOLD_MS,
        lines: int = 500,
    ) -> ToolResult:
        """Analyse hook timings from juju debug-log."""
        if not shutil.which("juju"):
            return ToolResult(
                success=False,
                output="",
                error="juju CLI not found on PATH.",
            )

        cmd = ["juju", "debug-log", "-n", str(lines), "--no-tail"]
        if model:
            cmd.extend(["--model", model])
        if app:
            cmd.extend(["--include", app])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="Timed out fetching debug logs.",
            )

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output="",
                error=f"juju debug-log failed: {result.stderr}",
            )

        timings = _parse_hook_timings(result.stdout)
        report = _format_benchmark_report(timings, threshold_ms)

        slow_hooks = [t for t in timings if float(t["duration_ms"]) > threshold_ms]

        return ToolResult(
            success=True,
            output=report,
            data={
                "total_hooks": len(timings),
                "slow_hooks": len(slow_hooks),
                "threshold_ms": threshold_ms,
                "timings": timings,
            },
        )
