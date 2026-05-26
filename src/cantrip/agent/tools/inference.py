"""Inference snap discovery tool."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.inference_snap import (
    _SNAP_DEFAULTS,
    discover_snap_endpoint,
    list_available_snaps,
)

if TYPE_CHECKING:
    from cantrip.mcp.registry import MCPRegistry

log = logging.getLogger(__name__)

# Phase 95.3: enrich local snap enumeration with Snap Store metadata
# (summary, channels, aliases) when a ``snapcraft`` MCP server is
# configured.  Local detection remains the source of truth for
# "what's installed and reachable"; the MCP layer only adds context.
_SNAPCRAFT_MCP_SERVER = "snapcraft"
_SNAP_INFO_TOOL = "snap_info"


class ListInferenceSnapsTool(Tool):
    """List locally installed Ubuntu inference snaps.

    When a ``snapcraft`` MCP server is configured and connected
    (Phase 95.3), each enumerated snap is enriched with Snap Store
    metadata (summary, channels, aliases) via ``snap_info``.  The MCP
    call is best-effort — local discovery stays authoritative on its
    own.
    """

    def __init__(self, *, mcp_registry: MCPRegistry | None = None) -> None:
        self._mcp_registry = mcp_registry

    @property
    def name(self) -> str:
        return "list_inference_snaps"

    @property
    def description(self) -> str:
        return (
            "List Ubuntu inference snaps installed on this machine. "
            "Each snap serves a local AI model via an OpenAI-compatible API. "
            "Returns snap names, default ports, and whether each is reachable. "
            "When a `snapcraft` MCP server is configured, also enriches each "
            "entry with Snap Store metadata (summary, channels, aliases)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        """Discover installed inference snaps and their status."""
        installed = list_available_snaps()
        if not installed:
            return ToolResult(
                success=True,
                output=(
                    "No inference snaps found. Known snaps: "
                    + ", ".join(sorted(_SNAP_DEFAULTS))
                    + ". Install with: sudo snap install <name>"
                ),
                caption="no snaps installed",
            )

        lines = []
        running_count = 0
        snap_details: dict[str, dict[str, Any]] = {}
        for snap in sorted(installed):
            endpoint = discover_snap_endpoint(snap)
            # Quick health check.  Catches ``ValueError`` alongside
            # ``httpx.HTTPError`` because a broken snap returning an HTML
            # error page makes ``resp.json()`` raise ``json.JSONDecodeError``
            # (a ``ValueError`` subclass), which would otherwise crash the
            # whole listing tool.  Non-dict payloads (``models = data.get``
            # on a list) are handled by the ``isinstance`` guard.
            status = "unreachable"
            model_name = "unknown"
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(f"{endpoint}/models")
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            models = data.get("data", [])
                            if isinstance(models, list) and models:
                                first = models[0]
                                if isinstance(first, dict):
                                    model_name = first.get("id", "unknown")
                        status = "running"
                        running_count += 1
            except (httpx.HTTPError, ValueError):
                pass

            lines.append(f"  {snap}: {status} (endpoint: {endpoint}, model: {model_name})")
            snap_details[snap] = {"status": status, "endpoint": endpoint, "model": model_name}

        store_metadata = await self._snapcraft_store_metadata(sorted(installed))
        if store_metadata:
            lines.append("")
            lines.append(f"Snap Store metadata (mcp__{_SNAPCRAFT_MCP_SERVER}):")
            for snap in sorted(installed):
                entry = store_metadata.get(snap)
                if entry is None:
                    continue
                if "error" in entry:
                    lines.append(f"  {snap}: store lookup failed — {entry['error']}")
                    continue
                text = entry.get("text", "").strip()
                if not text:
                    lines.append(f"  {snap}: store returned no detail")
                    continue
                # Indent the multi-line MCP response under the snap header.
                indented = "\n".join(f"    {line}" for line in text.splitlines())
                lines.append(f"  {snap}:\n{indented}")
                snap_details[snap]["store"] = entry

        data: dict[str, Any] = {"snaps": installed, "details": snap_details}
        if store_metadata:
            data["store_metadata"] = store_metadata

        return ToolResult(
            success=True,
            output="Installed inference snaps:\n" + "\n".join(lines),
            data=data,
            caption=f"{len(installed)} snap{'s' if len(installed) != 1 else ''}, {running_count} running",
        )

    async def _snapcraft_store_metadata(
        self, snap_names: list[str]
    ) -> dict[str, dict[str, str]] | None:
        """Query the configured snapcraft MCP server for store metadata.

        Returns ``None`` when no server is configured or it doesn't
        advertise ``snap_info``.  Returns a per-snap dict otherwise —
        with an ``error`` key for any individual lookup that raised
        (so a single failing snap never starves the rest).
        """
        registry = self._mcp_registry
        if registry is None:
            return None
        client = registry.get_client(_SNAPCRAFT_MCP_SERVER)
        if client is None:
            return None
        if _SNAP_INFO_TOOL not in {tool.name for tool in client.tools}:
            return None
        results: dict[str, dict[str, str]] = {}
        for snap in snap_names:
            try:
                result = await client.call_tool(_SNAP_INFO_TOOL, {"name": snap})
            except Exception as exc:  # noqa: BLE001 - MCP SDK can raise anything
                log.debug("snapcraft MCP snap_info(%s) failed: %s", snap, exc, exc_info=True)
                results[snap] = {"error": str(exc)}
                continue
            results[snap] = {"text": result.text or ""}
        return results
