"""Charm-discovery slash commands.

Extracted from :mod:`cantrip.agent.commands.slash` (Phase 113.5).  Groups the
charm-authoring helpers — ``/search-charms`` (Charmhub + Launchpad REST plus,
when configured, the ``launchpad`` MCP server's project/bug lookups) and
``/icon`` (the Painter) — each a cheap prelude paired with an async followup
that does the real work.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent

log = logging.getLogger(__name__)


def _handle_search_charms(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch the ``/search-charms`` slash command.

    Returns an immediate "searching…" prelude plus a followup that
    queries Charmhub and Launchpad in parallel and renders both
    result blocks together as Markdown.  Cheap — no source fetch is
    triggered from the slash; the agent invokes ``charmhub_fetch``
    / ``launchpad_fetch`` if it needs to read source.

    When the user has configured a ``launchpad`` MCP server (Phase 95.3),
    its ``project_lookup`` and ``bug_search`` outputs are appended as
    a third section so unpublished projects and tracker entries
    surface alongside the public REST results.
    """
    from cantrip.agent.commands.slash import SlashResult

    query = args.strip()
    if not query:
        return SlashResult(
            text=(
                "Usage: ``/search-charms <query>`` — searches Charmhub and "
                "Launchpad for existing charms or projects matching *query*."
            )
        )
    return SlashResult(
        text=f"Searching Charmhub and Launchpad for `{query}`…",
        followup=_run_search_charms(agent, query),
        markdown=True,
    )


# Phase 95.3: tool name → argument-dict template applied when the
# launchpad MCP server is configured.  Kept narrow so the integration
# doesn't speculate about server-side schemas — calls that don't match
# the server's actual argument names surface their error in the
# rendered section rather than blocking the rest of the search.
_LAUNCHPAD_MCP_SERVER = "launchpad"
_LAUNCHPAD_MCP_CALLS: tuple[tuple[str, str], ...] = (
    ("project_lookup", "name"),
    ("bug_search", "text"),
)


async def _run_search_charms(agent: CantripAgent, query: str) -> str:
    """Query Charmhub + Launchpad concurrently; render combined Markdown."""
    # Late imports keep the slash module's cold-start cheap when the
    # user never reaches for the Librarian.
    from cantrip.agent.tools.charmhub import CharmhubSearchTool
    from cantrip.agent.tools.launchpad import LaunchpadSearchTool

    charmhub_tool = CharmhubSearchTool()
    launchpad_tool = LaunchpadSearchTool()

    charmhub_result, launchpad_result = await asyncio.gather(
        charmhub_tool.execute(query=query),
        launchpad_tool.execute(query=query),
        return_exceptions=False,
    )

    sections: list[str] = [f"# Charm-library search: `{query}`", ""]

    sections.append("## Charmhub")
    if charmhub_result.success:
        sections.append(charmhub_result.output or "_No results._")
    else:
        sections.append(f"_Charmhub search failed: {charmhub_result.error}_")
    sections.append("")

    sections.append("## Launchpad")
    if launchpad_result.success:
        sections.append(launchpad_result.output or "_No results._")
    else:
        sections.append(f"_Launchpad search failed: {launchpad_result.error}_")

    mcp_block = await _launchpad_mcp_section(agent, query)
    if mcp_block is not None:
        sections.append("")
        sections.append(mcp_block)

    return "\n".join(sections)


async def _launchpad_mcp_section(agent: CantripAgent, query: str) -> str | None:
    """Render the Launchpad MCP results as a Markdown section.

    Returns ``None`` when no ``launchpad`` MCP server is configured or
    connected, so the slash command's output stays unchanged for
    users without the catalogue entry installed.
    """
    registry = _mcp_registry_or_none(agent)
    if registry is None:
        return None
    client = registry.get_client(_LAUNCHPAD_MCP_SERVER)
    if client is None:
        return None
    available = {tool.name for tool in client.tools}
    candidates = [(name, arg) for name, arg in _LAUNCHPAD_MCP_CALLS if name in available]
    if not candidates:
        return None

    lines: list[str] = [f"## Launchpad (mcp__{_LAUNCHPAD_MCP_SERVER})"]
    rendered_any = False
    for tool_name, arg_name in candidates:
        try:
            result = await client.call_tool(tool_name, {arg_name: query})
        except Exception as exc:  # noqa: BLE001 - MCP SDK can raise anything
            log.debug(
                "launchpad MCP %s call failed: %s",
                tool_name,
                exc,
                exc_info=True,
            )
            lines.append(f"_[{tool_name}] failed: {exc}_")
            rendered_any = True
            continue
        text = (result.text or "").strip()
        lines.append(f"### {tool_name}")
        lines.append(text if text else "_No results._")
        rendered_any = True
    if not rendered_any:
        return None
    return "\n".join(lines)


def _mcp_registry_or_none(agent: CantripAgent) -> Any:
    """Return the agent's MCP registry if one has been materialised."""
    mcp = getattr(agent, "_mcp", None)
    if mcp is None:
        return None
    getter = getattr(mcp, "registry_if_loaded", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:  # noqa: BLE001 - never block the slash on registry errors
        log.debug("registry_if_loaded raised", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Phase 70.5 — /icon slash command (Painter)
# ---------------------------------------------------------------------------


def _handle_icon(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch the ``/icon`` slash command.

    Returns an immediate "painting…" prelude plus a followup that
    invokes :class:`CharmIconGenerateTool` against the active charm
    path and renders the per-call cost summary.  Cheap edge cases
    (missing charm path, empty description) short-circuit before
    spawning any image-provider call.
    """
    from cantrip.agent.commands.slash import SlashResult

    description = args.strip()
    if not description:
        return SlashResult(
            text=(
                "Usage: ``/icon <one-line workload description>`` — "
                "generates a Charmhub-style icon.svg for the active "
                "charm using the configured image provider (default: "
                "Imagen).  Example: ``/icon a Postgres database "
                "operator``."
            )
        )
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot paint icon: no charm path for this session._")
    if not pathlib.Path(charm_path).is_dir():
        return SlashResult(text=f"_Charm path does not exist: {charm_path}._")
    return SlashResult(
        text=f"Painting icon.svg for `{description}`…",
        followup=_run_icon(agent, description, str(charm_path)),
        markdown=True,
    )


async def _run_icon(agent: CantripAgent, description: str, charm_path: str) -> str:
    """Invoke the Painter tool and render the result as Markdown."""
    # Late import keeps the dispatcher cheap when the user never
    # reaches for the Painter.
    from cantrip.agent.tools.icon import CharmIconGenerateTool

    tool = CharmIconGenerateTool(
        state=agent.state,
        store_getter=lambda: getattr(agent, "_store", None),
    )
    result = await tool.execute(description=description, path=charm_path)
    if not result.success:
        return f"_Painter failed: {result.error}_"
    return result.output
