"""Tool assembly, caching, curation, and LLM-schema rendering.

This module hosts :class:`ToolBuilder`, a service composed onto
:class:`~cantrip.agent.core.CantripAgent`. It builds the agent's tool list,
maintains the name-indexed tool map, applies phase-aware curation, and renders
the tool schema surfaced to the LLM. All caches stay on the agent; the service
reads and writes them through ``self._agent``.
"""

from __future__ import annotations

import logging
import typing

from cantrip.agent.tools import Tool, build_tools
from cantrip.llm import base as llm

if typing.TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent

log = logging.getLogger("cantrip.agent.core")


class ToolBuilder:
    """Tool construction, caching, curation, and LLM-schema rendering."""

    def __init__(self, agent: CantripAgent) -> None:
        self._agent = agent

    def tool_map(self) -> dict[str, Tool]:
        """Tool lookup by name, built lazily alongside _tools."""
        if self._agent._tool_map_cache is None:
            # Accessing _tools triggers the build.
            _ = self._agent._tools
        assert self._agent._tool_map_cache is not None
        return self._agent._tool_map_cache

    def invalidate_tools_cache(self) -> None:
        """Drop the cached tool list and tool map; next access rebuilds."""
        self._agent._tools_cache = None
        self._agent._tool_map_cache = None

    def build_tools(self) -> list[Tool]:
        """Build available tools."""
        return build_tools(
            base_path=self._agent.state.charm_path,
            skills_index=self._agent._skills_index,
            virtual_store=self._agent._virtual_store,
            provider=self._agent.provider,
            state=self._agent.state,
            queue=self._agent._work_queue,
            memory_manager=self._agent._memory_manager,
            mcp_registry=self._agent._mcp.registry_if_loaded(),
            mcp_controller=self._agent._mcp,
            store_getter=lambda: self._agent._store,
            role_router=self._agent.role_router if self._agent.role_router.has_embed() else None,
            # Sprint mode reroots ``state.charm_path`` into a freshly
            # scaffolded subdirectory inside ``plan_tasks``; the tool
            # cache captured the old path, so without this invalidator
            # subsequent ``edit_file("charmcraft.yaml")`` calls 404 until
            # the model retries with an explicit ``<charm_name>/`` prefix.
            invalidate_tools_cache=self._agent._invalidate_tools_cache,
            # Phase 72b: read-only code intelligence.  Lazy — the
            # property below builds a CodeIntel only on first use, so
            # sessions without an active charm path skip the parser
            # cost entirely.
            code_intel_getter=self._agent._code_intel_or_none,
        )

    def curated_tool_names(self) -> set[str]:
        """Tool-name set for the active workflow phase."""
        return self._agent._CORE_TOOLS_BY_PHASE[self._agent.workflow_phase]

    def tools_for_llm(self) -> list[llm.Tool]:
        """Convert tools to LLM format, curating for tight-context providers.

        The full toolset is offered unchanged to roomy providers (Claude,
        Gemini, …).  When the provider runs in short-session mode
        (tight context window) *or* declares a ``max_tools`` cap that the
        toolset overshoots (inference-snap's 12, or lots of MCP servers
        on an OpenAI-compatible API), the slice is narrowed to the
        :meth:`workflow_phase`'s curated set — that's the ≤11 tools the
        agent's current activity actually needs.  The curated set is
        recomputed every turn, so a work-queue task transition (build →
        debug because a test failed) is picked up on the next LLM call.
        The trim is logged with the dropped names so operators can see
        what disappeared.
        """
        tools = self._agent._tools
        limit = self._agent.provider.max_tools
        short_session = self._agent._context_manager.short_session_mode
        overshoots = limit is not None and len(tools) > limit

        if short_session or overshoots:
            keep_names = self._agent._curated_tool_names()
            kept = [t for t in tools if t.name in keep_names]
            if limit is not None and len(kept) > limit:
                kept = kept[:limit]
            if len(kept) < len(tools):
                kept_names = {t.name for t in kept}
                dropped = sorted(t.name for t in tools if t.name not in kept_names)
                log.info(
                    "Tool curation (%s phase%s): %d tools → %d; dropped: %s",
                    self._agent.workflow_phase.value,
                    ", short-session" if short_session else "",
                    len(tools),
                    len(kept),
                    ", ".join(dropped) if dropped else "(none)",
                )
            tools = kept

        return [
            llm.Tool(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in tools
        ]
