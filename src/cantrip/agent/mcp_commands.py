"""Slash-command handlers for MCP operations (Phase 45.2).

Pure formatting functions — both the TUI and the Web call them so the
``/mcp`` output is identical across surfaces.

Recognised commands:

* ``/mcp`` — list configured servers, their status, and the tools each
  exposes.
* ``/mcp tools <server>`` — list the tools advertised by a single server,
  with descriptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.mcp import MCPRegistry, ServerSnapshot


def handle_mcp(registry: MCPRegistry | None, args: str) -> str:
    """Dispatch ``/mcp`` and its subcommands."""
    if registry is None:
        return "_MCP is not configured for this session._"
    tokens = args.strip().split()
    if tokens and tokens[0].lower() in {"help", "-h", "--help"}:
        return mcp_help_text()
    if tokens and tokens[0].lower() == "tools":
        if len(tokens) < 2:
            return _error("expected `<server_name>` after `tools`. " + mcp_help_text())
        if len(tokens) > 2:
            return _error("too many arguments to `mcp tools`")
        return _format_server_tools(registry, tokens[1])
    if tokens:
        return _error(f"unknown subcommand {tokens[0]!r}. " + mcp_help_text())
    snapshots = registry.snapshot()
    if not snapshots:
        return "_No MCP servers configured._"
    return _format_overview(snapshots)


def mcp_help_text() -> str:
    """Return the help block for the ``/mcp`` command family."""
    return (
        "**MCP commands**\n\n"
        "- `/mcp` — list configured servers, their status, and the tool "
        "count each exposes.\n"
        "- `/mcp tools <server>` — list every tool the named server "
        "advertises, with descriptions."
    )


def _format_overview(snapshots: list[ServerSnapshot]) -> str:
    """Render the default ``/mcp`` view: one line per server."""
    lines: list[str] = []
    for snap in snapshots:
        marker = _status_marker(snap.status.value)
        suffix = ""
        if snap.error:
            suffix = f" — {snap.error}"
        elif snap.status.value == "connected":
            suffix = f" — {snap.tool_count} tools"
        lines.append(f"- {marker} **{snap.name}** ({snap.transport}, {snap.status.value}){suffix}")
    return "\n".join(lines)


def _format_server_tools(registry: MCPRegistry, server_name: str) -> str:
    """Render ``/mcp tools <server>`` for a single server."""
    snapshot = next((s for s in registry.snapshot() if s.name == server_name), None)
    if snapshot is None:
        return _error(f"unknown server {server_name!r}")
    if snapshot.status.value != "connected":
        return _error(
            f"server {server_name!r} is {snapshot.status.value}; "
            "tool list unavailable until it connects"
        )
    if not snapshot.tools:
        return f"_Server {server_name!r} exposes no tools._"
    lines = [f"**Tools on `{server_name}`:**"]
    for tool in snapshot.tools:
        lines.append(f"- `{tool.qualified_name}` — {tool.description or '(no description)'}")
    return "\n".join(lines)


def _status_marker(status: str) -> str:
    """Return a short text marker for a status — kept ASCII for portability."""
    return {
        "connected": "[ok]",
        "failed": "[!!]",
        "stopped": "[--]",
        "pending": "[..]",
    }.get(status, "[??]")


def _error(reason: str) -> str:
    return f"_Error: {reason}_"


__all__ = ["handle_mcp", "mcp_help_text"]
