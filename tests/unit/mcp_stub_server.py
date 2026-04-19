"""Tiny MCP stub server used by ``test_mcp_client``.

Run as a subprocess via stdio.  Exposes two tools:

* ``echo`` — returns whatever string was passed in.
* ``boom`` — raises so the client sees an error response.

Run via ``python -m tests.unit.mcp_stub_server`` (the test launches it
through ``uv run python -m`` so it sees the project venv).
"""

from __future__ import annotations

import asyncio
import json
import sys

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server


def build_server() -> Server:
    server: Server = Server("cantrip-stub")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="Echo a string back",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="boom",
                description="Always errors",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> list[types.TextContent]:
        if name == "echo":
            text = str(arguments.get("text", ""))
            return [types.TextContent(type="text", text=text)]
        if name == "boom":
            raise RuntimeError("intentional failure for tests")
        return [types.TextContent(type="text", text=f"unknown tool: {name}")]

    return server


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
    # Suppress the JSON debug noise some MCP shutdown paths print.
    asyncio.run(main())
    # Forces a clean exit if the server returns due to EOF on stdin.
    json  # noqa: B018  silence unused-import lint
