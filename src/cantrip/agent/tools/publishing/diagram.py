"""Mermaid architecture-diagram tool."""

import pathlib
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.publishing._common import (
    _read_charm_metadata,
    generate_architecture_diagram,
)


class GenerateDiagramTool(Tool):
    """Generate a Mermaid architecture diagram for a charm."""

    @property
    def name(self) -> str:
        return "generate_diagram"

    @property
    def description(self) -> str:
        return (
            "Generate a Mermaid architecture diagram from charmcraft.yaml "
            "showing the charm's relations, containers, and integrations. "
            "Writes architecture.md to the charm directory."
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
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate architecture.md with a Mermaid diagram."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        metadata = _read_charm_metadata(charm_dir)
        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        diagram = generate_architecture_diagram(charm_name, metadata)

        content = f"# {charm_name} — Architecture\n\n```mermaid\n{diagram}```\n"

        out_path = charm_dir / "architecture.md"
        out_path.write_text(content)

        return ToolResult(
            success=True,
            output=(f"Generated architecture diagram for '{charm_name}' at {out_path}"),
            data={"path": str(out_path), "charm_name": charm_name},
            caption=f"Wrote architecture.md ({charm_name})",
        )
