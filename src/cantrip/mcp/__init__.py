"""Model Context Protocol (MCP) client for Cantrip (Phase 45).

Provides an async client wrapper around the official ``mcp`` Python SDK
so Cantrip can pull tools from third-party MCP servers and surface them
to subagents alongside its built-in tools.

The submodule layout:

* :mod:`cantrip.mcp.types` — Cantrip-side dataclasses for server config
  and tool descriptors.
* :mod:`cantrip.mcp.client` — :class:`MCPClient`, the long-lived client
  wrapper with connect/handshake/invoke/close lifecycle and reconnect
  on transient failure.
* :mod:`cantrip.mcp.exceptions` — typed exceptions distinguishing
  configuration errors from runtime transport errors.
"""

from __future__ import annotations

from cantrip.mcp.client import MCPClient
from cantrip.mcp.exceptions import (
    MCPConfigError,
    MCPConnectionError,
    MCPError,
    MCPInvocationError,
)
from cantrip.mcp.types import MCPToolInfo, ServerConfig

__all__ = [
    "MCPClient",
    "MCPConfigError",
    "MCPConnectionError",
    "MCPError",
    "MCPInvocationError",
    "MCPToolInfo",
    "ServerConfig",
]
