"""Adapter that surfaces an MCP server's tool to the agent (Phase 45.3).

Wraps a single :class:`cantrip.mcp.MCPToolInfo` as a Cantrip
:class:`Tool` so the LLM sees it alongside the built-in tools.  The
tool's name follows Claude Code's convention — ``mcp__<server>__<tool>``
— so a glance at any tool call tells the operator which server it came
from.

Tool execution proxies to the registry's live client; if the server is
down the call surfaces a :class:`ToolResult` failure rather than
crashing the conversation loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.mcp.exceptions import MCPError

if TYPE_CHECKING:
    from cantrip.mcp import MCPRegistry, MCPToolInfo


class MCPTool(Tool):
    """One MCP server tool exposed to the agent's tool layer."""

    def __init__(self, info: MCPToolInfo, registry: MCPRegistry) -> None:
        self._info = info
        self._registry = registry

    @property
    def name(self) -> str:
        return self._info.qualified_name

    @property
    def description(self) -> str:
        prefix = f"[MCP {self._info.server_name}] "
        return prefix + (self._info.description or self._info.name)

    @property
    def parameters(self) -> dict[str, Any]:
        # Defensive copy — callers may mutate.  Fall back to a permissive
        # empty-object schema when the server didn't declare one.
        if self._info.input_schema:
            return dict(self._info.input_schema)
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Invoke the underlying MCP tool via the registry."""
        client = self._registry.get_client(self._info.server_name)
        if client is None or not client.is_connected:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"MCP server {self._info.server_name!r} is not connected; "
                    "use /mcp to inspect its status"
                ),
            )
        try:
            text = await client.call_tool(self._info.name, dict(kwargs))
        except MCPError as exc:
            return ToolResult(success=False, output="", error=f"MCP call failed: {exc}")
        return ToolResult(
            success=True,
            output=text,
            data={
                "mcp_server": self._info.server_name,
                "mcp_tool": self._info.name,
            },
        )


__all__ = ["MCPTool"]
