"""Workspace tool — surfaces the multi-charm manifest to the agent (Phase 33.3)."""

from __future__ import annotations

import pathlib
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.workspace import MANIFEST_FILENAME, WorkspaceError, find_manifest, load_workspace


class WorkspaceInfoTool(Tool):
    """Read a ``cantrip.workspace.yaml`` manifest and report its contents.

    The manifest declares the charms that live under a shared root,
    their cross-charm relations, and any shared config.  The agent
    calls this tool when the user asks about multi-charm work so it
    can see the workspace layout without having to glob the repo.
    """

    @property
    def name(self) -> str:
        return "workspace_info"

    @property
    def description(self) -> str:
        return (
            "Read a cantrip.workspace.yaml manifest and return its "
            "charm list, cross-charm relations, and any shared config. "
            "Walks up the filesystem from the given directory (or the "
            "current working directory) to find the manifest. Use this "
            "when working across multiple related charms in a monorepo."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Manifest file path, workspace root directory, or "
                        "any directory inside the workspace (the tool walks "
                        "upwards looking for cantrip.workspace.yaml). "
                        "Defaults to the current working directory."
                    ),
                },
            },
        }

    async def execute(self, path: str | None = None) -> ToolResult:
        start = pathlib.Path(path) if path else pathlib.Path.cwd()
        manifest = find_manifest(start)
        if manifest is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"No {MANIFEST_FILENAME} found at or above {start}. "
                    "Create one to declare a multi-charm workspace."
                ),
            )

        try:
            workspace = load_workspace(manifest)
        except WorkspaceError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        lines: list[str] = [f"Workspace: {workspace.name}"]
        if workspace.description:
            lines.append(f"  {workspace.description}")
        lines.append(f"Root: {workspace.root}")
        lines.append("")
        lines.append(f"Charms ({len(workspace.charms)}):")
        for charm in workspace.charms:
            lines.append(f"  - {charm.name} @ {charm.path}")
            if charm.description:
                lines.append(f"      {charm.description}")

        if workspace.relations:
            lines.append("")
            lines.append(f"Cross-charm relations ({len(workspace.relations)}):")
            for relation in workspace.relations:
                lines.append(
                    f"  - {relation.provider} → {relation.requirer} "
                    f"(interface: {relation.interface})"
                )
                if relation.description:
                    lines.append(f"      {relation.description}")

        if workspace.shared_config:
            lines.append("")
            lines.append("Shared config:")
            for key, value in workspace.shared_config.items():
                lines.append(f"  {key}: {value}")

        n_charms = len(workspace.charms)
        n_relations = len(workspace.relations)
        caption_parts = [f"{n_charms} charm{'s' if n_charms != 1 else ''}"]
        if n_relations:
            caption_parts.append(f"{n_relations} relation{'s' if n_relations != 1 else ''}")
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=workspace.to_dict() | {"manifest": str(manifest)},
            caption=", ".join(caption_parts),
        )
