"""Tiny MCP stub server used by ``test_mcp_client``.

Run as a subprocess via stdio.  Exposes two tools:

* ``echo`` — returns whatever string was passed in.
* ``boom`` — reports a tool error so the client sees an error response.

Run via ``python -m tests.unit.mcp_stub_server`` (the test launches it
through ``uv run python -m`` so it sees the project venv).
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

if TYPE_CHECKING:
    from mcp.server import ServerRequestContext

_TOOLS = [
    types.Tool(
        name="echo",
        description="Echo a string back",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    types.Tool(
        name="boom",
        description="Always errors",
        input_schema={"type": "object", "properties": {}},
    ),
]


async def _list_tools(
    _context: ServerRequestContext[None],
    _params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=list(_TOOLS))


async def _call_tool(
    _context: ServerRequestContext[None],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    arguments = params.arguments or {}
    if params.name == "echo":
        text = str(arguments.get("text", ""))
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    if params.name == "boom":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="intentional failure for tests")],
            is_error=True,
        )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"unknown tool: {params.name}")],
        is_error=True,
    )


def build_server() -> Server[None]:
    """Build the stub server with its two tool handlers wired up."""
    return Server("cantrip-stub", on_list_tools=_list_tools, on_call_tool=_call_tool)


async def main() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    # Make sure stdout is unbuffered — MCP framing is line-sensitive.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    asyncio.run(main())
