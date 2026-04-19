"""Cantrip-side dataclasses for the MCP subsystem (Phase 45)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class TransportKind(enum.StrEnum):
    """How a Cantrip MCP client talks to a server."""

    STDIO = "stdio"
    HTTP = "http"


@dataclass(frozen=True)
class ServerConfig:
    """Declarative description of one MCP server.

    The same dataclass covers both stdio and HTTP transports — fields
    irrelevant to the chosen transport are simply ignored.  ``name`` is
    the local handle Cantrip uses (and the prefix in ``mcp__<name>__<tool>``
    tool names); the server's own self-reported name is captured at
    handshake time but does not have to match.
    """

    name: str
    transport: TransportKind = TransportKind.STDIO
    # stdio fields
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    # HTTP fields
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # Common
    timeout_seconds: float = 30.0
    # Tool allowlist — names exactly as the server reports them.  An
    # empty list means "expose every tool the server publishes"; a
    # non-empty list means only those explicit names are surfaced.
    allowed_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MCPToolInfo:
    """Cantrip-side view of one tool advertised by an MCP server.

    Decouples the agent's tool layer from the MCP SDK types so the rest
    of the codebase doesn't grow a hard dependency on the SDK.
    """

    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """Return the ``mcp__<server>__<tool>`` prefixed name (Phase 45.3)."""
        return f"mcp__{self.server_name}__{self.name}"


__all__ = [
    "MCPToolInfo",
    "ServerConfig",
    "TransportKind",
]
