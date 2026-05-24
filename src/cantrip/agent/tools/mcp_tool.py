"""Adapter that surfaces an MCP server's tool to the agent (Phase 45.3).

Wraps a single :class:`cantrip.mcp.MCPToolInfo` as a Cantrip
:class:`Tool` so the LLM sees it alongside the built-in tools.  The
tool's name follows Claude Code's convention — ``mcp__<server>__<tool>``
— so a glance at any tool call tells the operator which server it came
from.

Tool execution proxies to the registry's live client; if the server is
down the call surfaces a :class:`ToolResult` failure rather than
crashing the conversation loop.

Phase 73.2: an MCP server can return a tool result that includes a
``ui`` block (MCP Apps extension).  When a controller is wired in,
each ``ui`` block is registered with the controller — which mints an
``app_id``, publishes an ``MCP_APP_RENDER`` event, and remembers the
mapping so a later iframe-emitted tool call resolves to the right
server scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.mcp.exceptions import MCPError

if TYPE_CHECKING:
    from cantrip.agent.mcp_controller import MCPController
    from cantrip.mcp import MCPRegistry, MCPToolInfo


class MCPTool(Tool):
    """One MCP server tool exposed to the agent's tool layer."""

    def __init__(
        self,
        info: MCPToolInfo,
        registry: MCPRegistry,
        controller: MCPController | None = None,
    ) -> None:
        self._info = info
        self._registry = registry
        self._controller = controller

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
            structured = await client.call_tool(self._info.name, dict(kwargs))
        except MCPError as exc:
            return ToolResult(success=False, output="", error=f"MCP call failed: {exc}")

        # Phase 73.2: forward every ``ui`` block to the controller so
        # the Web UI iframe renders and the TUI fallback can fire.  The
        # controller-less path (tests, bare ``build_tools`` callers)
        # silently swallows renders — the textual ``output`` still
        # carries the spec's fallback placeholder.
        app_ids: list[str] = []
        if self._controller is not None and structured.app_renders:
            for render in structured.app_renders:
                app_id = self._controller.register_app_render(
                    render,
                    tool_name=self._info.qualified_name,
                )
                app_ids.append(app_id)

        data: dict[str, Any] = {
            "mcp_server": self._info.server_name,
            "mcp_tool": self._info.name,
        }
        if app_ids:
            data["app_ids"] = app_ids
        return ToolResult(
            success=True,
            output=structured.text,
            data=data,
        )


__all__ = ["MCPTool"]
