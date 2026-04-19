"""Exception hierarchy for the MCP client (Phase 45)."""

from __future__ import annotations


class MCPError(Exception):
    """Base class for all MCP-related errors."""


class MCPConfigError(MCPError):
    """Raised when a server config is malformed or unusable."""


class MCPConnectionError(MCPError):
    """Raised when the transport cannot be established or has been lost."""


class MCPInvocationError(MCPError):
    """Raised when a tool invocation fails server-side or times out."""


__all__ = [
    "MCPConfigError",
    "MCPConnectionError",
    "MCPError",
    "MCPInvocationError",
]
