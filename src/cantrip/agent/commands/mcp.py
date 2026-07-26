"""Slash-command handlers for MCP operations (Phase 45.2 + 45.5).

Pure formatting functions — both the TUI and the Web call them so the
``/mcp`` output is identical across surfaces.

Recognised commands:

* ``/mcp`` — list configured servers, their status, and the tools each
  exposes.
* ``/mcp tools <server>`` — list the tools advertised by a single server,
  with descriptions.
* ``/mcp marketplace`` — list servers from configured marketplaces (45.5).
* ``/mcp marketplace refresh`` — bypass the cache and re-fetch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.mcp import (
        Marketplace,
        MarketplaceLoader,
        MarketplaceServer,
        MarketplaceSource,
        MCPRegistry,
        ServerSnapshot,
    )


def handle_mcp(registry: MCPRegistry | None, args: str) -> str:
    """Dispatch the synchronous ``/mcp`` subcommands.

    Marketplace operations are async (network I/O) and live on
    :func:`handle_mcp_async`; the TUI/Web wrappers pick the right
    entry point per subcommand.
    """
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
    if tokens and tokens[0].lower() == "marketplace":
        return _error(
            "`/mcp marketplace` is async — use the TUI/Web entry point or "
            "call handle_mcp_async() directly."
        )
    if tokens:
        return _error(f"unknown subcommand {tokens[0]!r}. " + mcp_help_text())
    snapshots = registry.snapshot()
    if not snapshots:
        return "_No MCP servers configured._"
    return _format_overview(snapshots)


def is_marketplace_subcommand(args: str) -> bool:
    """Return True when *args* targets the marketplace subcommand."""
    tokens = args.strip().split()
    return bool(tokens) and tokens[0].lower() == "marketplace"


async def handle_mcp_async(
    registry: MCPRegistry | None,
    sources: list[MarketplaceSource],
    loader: MarketplaceLoader,
    args: str,
) -> str:
    """Async dispatcher — needed for the network-bound marketplace path.

    The TUI/Web call this directly when ``args`` starts with
    ``marketplace``; the synchronous :func:`handle_mcp` covers
    everything else.
    """
    tokens = args.strip().split()
    if not tokens or tokens[0].lower() != "marketplace":
        return handle_mcp(registry, args)
    sub = tokens[1].lower() if len(tokens) >= 2 else ""
    if sub in {"help", "-h", "--help"}:
        return mcp_help_text()
    refresh = sub == "refresh"
    if sub and not refresh:
        return _error(
            f"unknown marketplace subcommand {sub!r}; expected `refresh`. " + mcp_help_text()
        )
    if not sources:
        return "_No MCP marketplaces configured._\n\n" + _marketplace_config_hint()
    markets = await loader.load_all(sources, refresh=refresh)
    if not markets:
        return _error("every configured marketplace failed to load — check logs for details")
    return _format_marketplaces(markets)


def mcp_help_text() -> str:
    """Return the help block for the ``/mcp`` command family."""
    return (
        "**MCP commands**\n\n"
        "- `/mcp` — list configured servers, their status, and the tool "
        "count each exposes.\n"
        "- `/mcp tools <server>` — list every tool the named server "
        "advertises, with descriptions.\n"
        "- `/mcp marketplace` — list servers from configured marketplaces "
        "(read-only).\n"
        "- `/mcp marketplace refresh` — bypass the cache and re-fetch."
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
    lines.extend(
        f"- `{tool.qualified_name}` — {tool.description or '(no description)'}"
        for tool in snapshot.tools
    )
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


def _format_marketplaces(markets: list[Marketplace]) -> str:
    """Render the marketplace overview for ``/mcp marketplace``."""
    sections: list[str] = []
    for market in markets:
        header = f"## {market.name} (`{market.source.label}`)"
        if market.description:
            header += f"\n\n{market.description}"
        if not market.servers:
            sections.append(header + "\n\n_(no servers in this marketplace)_")
            continue
        lines = [header, ""]
        for server in market.servers:
            install_hint = _format_install_hint(server)
            extras: list[str] = []
            if server.env_required:
                extras.append("env: " + ", ".join(f"`{e}`" for e in server.env_required))
            if server.scopes:
                extras.append("scopes: " + ", ".join(f"`{s}`" for s in server.scopes))
            extra_line = ("  " + " | ".join(extras)) if extras else ""
            description = server.description or "(no description)"
            lines.append(f"- **{server.name}** — {description}")
            lines.append(f"  install: `{install_hint}`{extra_line}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _format_install_hint(server: MarketplaceServer) -> str:
    """Build a one-line install command preview for the marketplace listing."""
    if server.transport == "http" and server.url:
        return f"http {server.url}"
    cmd = server.command or "?"
    if server.args:
        return cmd + " " + " ".join(server.args)
    return cmd


def _marketplace_config_hint() -> str:
    """Hint shown when no marketplaces are configured."""
    return (
        "Add a `marketplaces:` block to your `cantrip.mcp.yaml`:\n\n"
        "```yaml\n"
        "marketplaces:\n"
        "  - github: anthropic-ai/mcp-servers\n"
        "  - directory: ~/local-mcp-catalog\n"
        "  - url: https://example.com/marketplace.json\n"
        "```"
    )


__all__ = [
    "handle_mcp",
    "handle_mcp_async",
    "is_marketplace_subcommand",
    "mcp_help_text",
]
