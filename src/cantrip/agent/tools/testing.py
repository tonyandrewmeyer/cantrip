"""Charm test runner tool."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeouts per test type (seconds).
_TIMEOUTS = {"unit": 120, "integration": 900}

# If output exceeds this many characters, truncate to the last N lines.
_MAX_OUTPUT_CHARS = 5000
_TAIL_LINES = 200

# Regex matching the pytest summary line, e.g. "3 passed, 1 failed, 2 error".
_SUMMARY_RE = re.compile(
    r"(?:=+)?\s*"
    r"(?:(?P<failed>\d+) failed)?"
    r"[, ]*(?:(?P<passed>\d+) passed)?"
    r"[, ]*(?:(?P<error>\d+) error)?"
    r"[, ]*(?:(?P<skipped>\d+) skipped)?"
)


def _parse_pytest_summary(output: str) -> dict[str, int]:
    """Extract passed/failed/error/skipped counts from pytest output.

    Scans the output for the pytest summary line (e.g.
    ``=== 3 passed, 1 failed in 0.5s ===``) and returns a dict of counts.
    Returns an empty dict if no summary line is found.
    """
    # Pytest prints a final summary line starting with "=" characters.
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("="):
            continue
        # Try all patterns: "X failed", "X passed", "X error", "X skipped".
        counts: dict[str, int] = {}
        for key in ("passed", "failed", "error", "skipped"):
            match = re.search(rf"(\d+) {key}", stripped)
            if match:
                counts[key] = int(match.group(1))
        if counts:
            return counts
    return {}


def _truncate_output(output: str) -> str:
    """Truncate output to the last ``_TAIL_LINES`` lines if it exceeds the threshold."""
    if len(output) <= _MAX_OUTPUT_CHARS:
        return output
    lines = output.splitlines()
    tail = lines[-_TAIL_LINES:]
    return f"[...truncated — showing last {_TAIL_LINES} lines...]\n" + "\n".join(tail)


def _build_pytest_target(test_dir: Path, pattern: str | None) -> list[str]:
    """Build the pytest positional arguments from an optional pattern.

    Supports three forms:
    - ``None`` → run the whole test directory
    - ``"test_deploy"`` → run a specific file (``tests/<type>/test_deploy.py``)
    - ``"test_deploy::test_foo"`` → run a specific test function
    - anything containing spaces or boolean operators → passed to ``-k``
    """
    if pattern is None:
        return [str(test_dir) + "/"]

    # A -k expression: contains spaces or boolean keywords.
    if " " in pattern or " or " in pattern or " and " in pattern:
        return [str(test_dir) + "/", "-k", pattern]

    # File::function form.
    if "::" in pattern:
        file_part, rest = pattern.split("::", 1)
        file_part = file_part.removesuffix(".py")
        candidate = test_dir / f"{file_part}.py"
        if candidate.exists():
            return [f"{candidate}::{rest}"]
        # Fall back to -k if the file doesn't exist.
        return [str(test_dir) + "/", "-k", rest]

    # Plain name — try as a file first, then fall back to -k.
    candidate = test_dir / f"{pattern}.py"
    if candidate.exists():
        return [str(candidate)]
    candidate = test_dir / pattern
    if candidate.exists():
        return [str(candidate)]
    return [str(test_dir) + "/", "-k", pattern]


class RunCharmTestsTool(Tool):
    """Tool to run unit or integration tests for a charm."""

    @property
    def name(self) -> str:
        return "run_charm_tests"

    @property
    def description(self) -> str:
        return (
            "Run unit or integration tests for a charm. "
            "Prefers tox if available, otherwise falls back to pytest. "
            "Returns test output and a parsed summary of pass/fail counts. "
            "Use the optional pattern parameter to run a specific test file "
            "or test function (e.g. 'test_deploy' or 'test_relations::test_db')."
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
                "test_type": {
                    "type": "string",
                    "description": "Type of tests to run",
                    "enum": ["unit", "integration"],
                    "default": "unit",
                },
                "pattern": {
                    "type": "string",
                    "description": (
                        "Optional filter to run specific tests. Can be a file name "
                        "(e.g. 'test_deploy'), a file::function pattern "
                        "(e.g. 'test_relations::test_db_connect'), or a pytest -k "
                        "expression (e.g. 'deploy or relation'). Only used with the "
                        "pytest runner — ignored when tox is used."
                    ),
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        test_type: str = "unit",
        pattern: str | None = None,
    ) -> ToolResult:
        """Run charm tests using tox or pytest."""
        charm_path = Path(path).resolve()
        if not charm_path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        timeout = _TIMEOUTS.get(test_type, _TIMEOUTS["unit"])

        # Prefer tox if tox.ini exists and tox is on PATH — but fall back to
        # pytest when a pattern is given so we can target specific tests.
        use_tox = (
            (charm_path / "tox.ini").exists()
            and shutil.which("tox") is not None
            and pattern is None
        )

        if use_tox:
            cmd = ["tox", "-e", test_type]
            runner = "tox"
        else:
            # Fall back to pytest.
            if not shutil.which("python"):
                return ToolResult(
                    success=False,
                    output="",
                    error="Neither tox nor python found on PATH.",
                )
            test_dir = charm_path / "tests" / test_type
            if not test_dir.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Test directory not found: tests/{test_type}/",
                )
            cmd = ["python", "-m", "pytest", "-v", "--tb=short"]
            cmd.extend(_build_pytest_target(test_dir, pattern))
            runner = "pytest"

        try:
            result = subprocess.run(
                cmd,
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Tests timed out after {timeout}s",
            )

        combined = result.stdout
        if result.stderr:
            combined += "\n" + result.stderr

        summary = _parse_pytest_summary(combined)
        output = _truncate_output(combined)

        success = result.returncode == 0
        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Tests failed (exit code {result.returncode})",
            data={"summary": summary, "runner": runner},
        )
