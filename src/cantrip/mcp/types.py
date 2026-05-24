"""Cantrip-side dataclasses for the MCP subsystem (Phase 45)."""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class TransportKind(enum.StrEnum):
    """How a Cantrip MCP client talks to a server."""

    STDIO = "stdio"
    HTTP = "http"


@dataclasses.dataclass(frozen=True)
class OAuthConfig:
    """Per-server OAuth 2.1 configuration (Phase 45.4b).

    Used only when an HTTP MCP server requires OAuth.  The MCP SDK
    handles the protocol details — PKCE, token exchange, RFC 9728
    Protected Resource Metadata discovery — so this dataclass mostly
    captures Cantrip-specific UX knobs.

    ``redirect_port`` is the localhost port Cantrip binds for the
    OAuth callback; pick a port unlikely to clash with other tools on
    the dev machine.  ``client_metadata_url`` lets ops point Cantrip
    at a published metadata document (RFC 9728) rather than relying on
    dynamic client registration — required by some servers that don't
    support DCR.
    """

    client_name: str = "cantrip"
    scopes: list[str] = dataclasses.field(default_factory=list)
    redirect_port: int = 9876
    client_metadata_url: str | None = None


@dataclasses.dataclass(frozen=True)
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
    args: list[str] = dataclasses.field(default_factory=list)
    env: dict[str, str] = dataclasses.field(default_factory=dict)
    cwd: str | None = None
    # HTTP fields
    url: str | None = None
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    # Optional OAuth 2.1 config — HTTP transport only.
    oauth: OAuthConfig | None = None
    # Common
    timeout_seconds: float = 30.0
    # Tool allowlist — names exactly as the server reports them.  An
    # empty list means "expose every tool the server publishes"; a
    # non-empty list means only those explicit names are surfaced.
    allowed_tools: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
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


@dataclasses.dataclass(frozen=True)
class MCPAppRender:
    """One ``ui`` block extracted from a tool result (Phase 73.2).

    The MCP Apps extension lets a server return interactive HTML
    alongside a textual reply.  Conformant hosts (cantrip's Web UI,
    Claude Desktop, VS Code Copilot, Goose, …) render the HTML in a
    sandboxed iframe and bridge ``postMessage`` events back through
    the host's tool pipeline.

    *fallback_text* is what surfaces in non-rendering hosts (the TUI,
    a text-only transcript export) so the call is never silently lost.
    *max_height_px* is the server's suggested vertical cap; the Web UI
    clamps it to a safe upper bound before applying.
    """

    server_name: str
    title: str
    mime: str
    html: str
    fallback_text: str = ""
    max_height_px: int | None = None


@dataclasses.dataclass(frozen=True)
class MCPCallResult:
    """Structured return shape of :meth:`MCPClient.call_tool` (Phase 73.2).

    ``text`` is the legacy textual collation that callers (other than
    :class:`~cantrip.agent.tools.mcp_tool.MCPTool`) used to receive
    directly.  ``app_renders`` carries any ``ui`` content blocks the
    server attached so the agent's tool adapter can emit per-render
    events without re-parsing the SDK shape.
    """

    text: str
    app_renders: tuple[MCPAppRender, ...] = ()


__all__ = [
    "MCPAppRender",
    "MCPCallResult",
    "MCPToolInfo",
    "OAuthConfig",
    "ServerConfig",
    "TransportKind",
]
