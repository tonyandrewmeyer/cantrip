"""Test report aggregation tool — collects results into a structured summary."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.testing import _parse_pytest_summary

# Subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = 120


def _run_tests(charm_dir: Path, test_type: str) -> dict[str, Any]:
    """Run a test suite and return structured results.

    Returns a dict with keys: success, summary, output (truncated).
    """
    use_tox = (charm_dir / "tox.ini").exists() and shutil.which("tox") is not None
    test_dir = charm_dir / "tests" / test_type

    if use_tox:
        cmd = ["tox", "-e", test_type]
    elif test_dir.is_dir() and shutil.which("python"):
        cmd = ["python", "-m", "pytest", f"tests/{test_type}/", "-v", "--tb=short"]
    else:
        return {"success": None, "summary": {}, "output": f"No {test_type} tests found."}

    try:
        result = subprocess.run(
            cmd,
            cwd=charm_dir,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "summary": {}, "output": f"{test_type} tests timed out."}

    combined = result.stdout
    if result.stderr:
        combined += "\n" + result.stderr

    summary = _parse_pytest_summary(combined)

    # Truncate output for the report.
    output = combined
    if len(output) > 3000:
        output = output[-3000:]

    return {
        "success": result.returncode == 0,
        "summary": summary,
        "output": output,
    }


def _format_test_report(
    unit_results: dict[str, Any],
    integration_results: dict[str, Any],
    charm_name: str,
) -> str:
    """Format an aggregated test report as Markdown."""
    lines = [f"# Test Report: {charm_name}", ""]

    total_passed = 0
    total_failed = 0
    total_error = 0
    sections_run = 0

    for label, results in [
        ("Unit Tests", unit_results),
        ("Integration Tests", integration_results),
    ]:
        lines.append(f"## {label}")
        lines.append("")

        if results["success"] is None:
            lines.append("Not available.")
            lines.append("")
            continue

        sections_run += 1
        summary = results["summary"]
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        error = summary.get("error", 0)
        skipped = summary.get("skipped", 0)

        total_passed += passed
        total_failed += failed
        total_error += error

        icon = "✓" if results["success"] else "✗"
        lines.append(
            f"{icon} **{passed}** passed, **{failed}** failed, "
            f"**{error}** error, **{skipped}** skipped"
        )
        lines.append("")

        if not results["success"] and results.get("output"):
            lines.append("<details>")
            lines.append("<summary>Failure output</summary>")
            lines.append("")
            lines.append("```")
            # Show last 50 lines of output.
            output_lines = results["output"].splitlines()
            for line in output_lines[-50:]:
                lines.append(line)
            lines.append("```")
            lines.append("</details>")
            lines.append("")

    # Overall verdict.
    lines.append("## Verdict")
    lines.append("")
    if sections_run == 0:
        lines.append("No test suites were found or run.")
    elif total_failed == 0 and total_error == 0:
        lines.append(f"**PASS** — all {total_passed} tests passed.")
    else:
        lines.append(
            f"**FAIL** — {total_failed + total_error} failures/errors "
            f"out of {total_passed + total_failed + total_error} tests."
        )
    lines.append("")

    return "\n".join(lines)


class TestReportTool(Tool):
    """Tool to run all test suites and produce an aggregated report."""

    @property
    def name(self) -> str:
        return "test_report"

    @property
    def description(self) -> str:
        return (
            "Run unit and integration tests for a charm and produce an "
            "aggregated test report with pass/fail counts, failure output, "
            "and an overall verdict. Use this for a comprehensive quality "
            "check before publishing or presenting results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run tests and produce an aggregated report."""
        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        # Determine charm name from charmcraft.yaml or directory name.
        charm_name = charm_dir.name
        charmcraft = charm_dir / "charmcraft.yaml"
        if charmcraft.exists():
            try:
                import yaml

                with charmcraft.open() as f:
                    data = yaml.safe_load(f) or {}
                charm_name = data.get("name", charm_name)
            except (ImportError, Exception):  # noqa: BLE001
                pass

        unit_results = _run_tests(charm_dir, "unit")
        integration_results = _run_tests(charm_dir, "integration")

        report = _format_test_report(unit_results, integration_results, charm_name)

        total_passed = (
            unit_results["summary"].get("passed", 0)
            + integration_results["summary"].get("passed", 0)
        )
        total_failed = (
            unit_results["summary"].get("failed", 0)
            + integration_results["summary"].get("failed", 0)
            + unit_results["summary"].get("error", 0)
            + integration_results["summary"].get("error", 0)
        )

        all_passed = (
            (unit_results["success"] is None or unit_results["success"])
            and (integration_results["success"] is None or integration_results["success"])
        )

        return ToolResult(
            success=all_passed,
            output=report,
            data={
                "total_passed": total_passed,
                "total_failed": total_failed,
                "unit": unit_results["summary"],
                "integration": integration_results["summary"],
                "verdict": "pass" if all_passed else "fail",
            },
        )
