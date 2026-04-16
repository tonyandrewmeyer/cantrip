"""Charmlint agent tool — run the standalone charm linter."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class CharmlintTool(Tool):
    """Run charmlint against a charm directory.

    This exposes the standalone charmlint linter as an agent tool,
    returning ruff-style diagnostics with rule IDs, severities, and
    fix hints.  Supports filtering by category and severity.

    Prefers the Rust binary (``charmlint-rs`` on PATH, or the in-tree
    release build) for speed, falling back to the Python library.
    """

    @property
    def name(self) -> str:
        return "charmlint"

    @property
    def description(self) -> str:
        return (
            "Lint a charm directory for best practices using charmlint. "
            "Returns diagnostics with rule IDs (COS001, TEST001, DEP001, etc.), "
            "severities (error/warning/info), and fix hints. Supports filtering "
            "by category (e.g. COS, META, TEST) and minimum severity."
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
                "select": {
                    "type": "string",
                    "description": (
                        "Comma-separated categories to check "
                        "(e.g. 'COS,META,TEST'). Empty means all."
                    ),
                },
                "ignore": {
                    "type": "string",
                    "description": (
                        "Comma-separated rule IDs or categories to skip (e.g. 'STR002,DOC')"
                    ),
                },
                "severity": {
                    "type": "string",
                    "enum": ["error", "warning", "info"],
                    "description": "Minimum severity to report (default: all)",
                },
            },
        }

    @staticmethod
    def _find_rust_binary() -> str | None:
        """Return the path to the Rust charmlint binary, or None."""
        rust_bin = shutil.which("charmlint-rs")
        if rust_bin:
            return rust_bin
        # Check the in-tree build location.
        import cantrip

        pkg_dir = Path(cantrip.__file__).resolve().parent
        candidate = pkg_dir.parent.parent / "charmlint-rs" / "target" / "release" / "charmlint"
        if candidate.is_file():
            return str(candidate)
        return None

    async def execute(
        self,
        path: str = ".",
        select: str = "",
        ignore: str = "",
        severity: str = "",
    ) -> ToolResult:
        """Run charmlint, preferring the Rust binary when available."""
        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        rust_bin = self._find_rust_binary()
        if rust_bin is not None:
            return self._execute_rust(rust_bin, charm_dir, select, ignore, severity)
        return self._execute_python(charm_dir, select, ignore, severity)

    def _execute_rust(
        self,
        binary: str,
        charm_dir: Path,
        select: str,
        ignore: str,
        severity: str,
    ) -> ToolResult:
        """Lint using the compiled Rust binary."""
        cmd = [binary, str(charm_dir), "--format", "json"]
        if select:
            cmd.extend(["--select", select])
        if ignore:
            cmd.extend(["--ignore", ignore])
        if severity:
            cmd.extend(["--severity", severity])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            return self._execute_python(charm_dir, select, ignore, severity)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="charmlint timed out")

        # Parse JSON output from the Rust binary.
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            # Fallback on unparseable output.
            return self._execute_python(charm_dir, select, ignore, severity)

        # Format text output from the parsed diagnostics.
        lines: list[str] = []
        for d in data.get("diagnostics", []):
            location = d.get("path", "")
            if d.get("line") is not None:
                location = f"{location}:{d['line']}"
            prefix = f"{location}: " if location else ""
            lines.append(f"{prefix}{d['rule_id']} {d['message']}")

        total = data.get("total", 0)
        errors = data.get("errors", 0)
        warnings = data.get("warnings", 0)
        infos = data.get("info", 0)

        if total == 0:
            lines.append("No issues found.")
        else:
            parts = []
            if errors:
                s = "s" if errors != 1 else ""
                parts.append(f"{errors} error{s}")
            if warnings:
                s = "s" if warnings != 1 else ""
                parts.append(f"{warnings} warning{s}")
            if infos:
                parts.append(f"{infos} info")
            s = "s" if total != 1 else ""
            lines.append(f"Found {total} issue{s} ({', '.join(parts)})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={**data, "backend": "rust"},
        )

    @staticmethod
    def _execute_python(
        charm_dir: Path,
        select: str,
        ignore: str,
        severity: str,
    ) -> ToolResult:
        """Lint using the Python charmlint library."""
        from charmlint import LintConfig, lint

        config = LintConfig(
            select=[s.strip() for s in select.split(",") if s.strip()],
            ignore=[s.strip() for s in ignore.split(",") if s.strip()],
        )
        if severity:
            from charmlint.models import Severity

            config.min_severity = Severity(severity)

        report = lint(charm_dir, config)

        lines: list[str] = []
        for d in report.diagnostics:
            lines.append(d.format_text(charm_dir))
        if lines:
            lines.append("")
        lines.append(report.summary_line())

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={**report.to_dict(), "backend": "python"},
        )
