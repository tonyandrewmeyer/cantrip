"""Charmlint agent tool — run the standalone charm linter."""

from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from charmlint import LintConfig, lint


class CharmlintTool(Tool):
    """Run charmlint against a charm directory.

    This exposes the standalone charmlint linter as an agent tool,
    returning ruff-style diagnostics with rule IDs, severities, and
    fix hints.  Supports filtering by category and severity.
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

    async def execute(
        self,
        path: str = ".",
        select: str = "",
        ignore: str = "",
        severity: str = "",
    ) -> ToolResult:
        """Run charmlint and return diagnostics."""
        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        config = LintConfig(
            select=[s.strip() for s in select.split(",") if s.strip()],
            ignore=[s.strip() for s in ignore.split(",") if s.strip()],
        )
        if severity:
            from charmlint.models import Severity

            config.min_severity = Severity(severity)

        report = lint(charm_dir, config)

        # Format as text output.
        lines: list[str] = []
        for d in report.diagnostics:
            lines.append(d.format_text(charm_dir))
        if lines:
            lines.append("")
        lines.append(report.summary_line())

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=report.to_dict(),
        )
