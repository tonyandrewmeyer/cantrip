"""Acceptance report consolidation tool."""

import pathlib
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# ---------------------------------------------------------------------------
# 17.6 Acceptance Report
# ---------------------------------------------------------------------------


class AcceptanceReportTool(Tool):
    """Consolidate acceptance test results into ACCEPTANCE.md."""

    @property
    def name(self) -> str:
        return "acceptance_report"

    @property
    def description(self) -> str:
        return (
            "Consolidate acceptance test results from the individual tools "
            "(action exerciser, relation smoke tests, endpoint probes, config "
            "variation) into a single ACCEPTANCE.md report in the charm directory."
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
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "actions": {
                    "type": "string",
                    "description": "Markdown output from action_exerciser",
                    "default": "",
                },
                "relations": {
                    "type": "string",
                    "description": "Markdown output from relation_smoke_test",
                    "default": "",
                },
                "endpoints": {
                    "type": "string",
                    "description": "Markdown output from workload_endpoint_test",
                    "default": "",
                },
                "config": {
                    "type": "string",
                    "description": "Markdown output from config_variation_test",
                    "default": "",
                },
                "lifecycle": {
                    "type": "string",
                    "description": ("Markdown output from scaling_test / upgrade_test"),
                    "default": "",
                },
            },
            "required": ["app"],
        }

    async def execute(
        self,
        app: str = "",
        path: str = ".",
        actions: str = "",
        relations: str = "",
        endpoints: str = "",
        config: str = "",
        lifecycle: str = "",
    ) -> ToolResult:
        """Write ACCEPTANCE.md consolidating all acceptance test sections."""
        if not app:
            return ToolResult(success=False, output="", error="app parameter is required.")

        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {path}")

        sections = [
            f"# Acceptance Test Report — {app}",
            "",
            "This report summarises the acceptance tests performed against "
            f"the deployed **{app}** charm.",
            "",
        ]

        section_count = 0
        section_summaries: list[str] = []

        if actions:
            sections.extend(["---", "", actions, ""])
            section_count += 1
            section_summaries.append("actions exercised")
        if relations:
            sections.extend(["---", "", relations, ""])
            section_count += 1
            section_summaries.append("relations tested")
        if endpoints:
            sections.extend(["---", "", endpoints, ""])
            section_count += 1
            section_summaries.append("endpoints probed")
        if config:
            sections.extend(["---", "", config, ""])
            section_count += 1
            section_summaries.append("config options varied")
        if lifecycle:
            sections.extend(["---", "", lifecycle, ""])
            section_count += 1
            section_summaries.append("lifecycle operations checked")

        if section_count == 0:
            return ToolResult(
                success=False,
                output="",
                error="No acceptance test results provided.",
            )

        report = "\n".join(sections)

        # Write ACCEPTANCE.md.
        acceptance_path = charm_dir / "ACCEPTANCE.md"
        acceptance_path.write_text(report)

        summary = (
            f"Wrote ACCEPTANCE.md ({section_count} sections: {', '.join(section_summaries)})."
        )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "app": app,
                "path": str(acceptance_path),
                "section_count": section_count,
                "sections": section_summaries,
            },
            caption=(
                f"Wrote ACCEPTANCE.md ({section_count} section{'s' if section_count != 1 else ''})"
            ),
        )
