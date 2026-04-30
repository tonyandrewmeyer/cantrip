"""MCP lifecycle controller — registry, marketplace, and elicitation bridge.

Held by :class:`CantripAgent` as ``self._mcp`` and re-exposed through thin
delegators so the public surface (``mcp_registry`` / ``start_mcp`` /
``stop_mcp`` / ``complete_mcp_elicitation`` / ``_on_mcp_elicitation``)
keeps working unchanged.  Lazy registry/loader construction stays inside
this module so ``_build_tools`` can ask whether a registry has been
materialised without forcing one into existence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cantrip.mcp import (
    MarketplaceLoader,
    MarketplaceSource,
    MCPRegistry,
    load_marketplace_sources,
)
from cantrip.mcp import load_configs as load_mcp_configs
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.agent.state import AgentState

log = logging.getLogger(__name__)


class MCPController:
    """Owns the MCP registry, marketplace state, and elicitation bridge.

    *invalidate_tools_cache* is invoked after :meth:`start` so the agent's
    tool list rebuild picks up newly-connected servers.  *event_bus* is
    where elicitation requests are published as
    ``MCP_ELICITATION_REQUEST`` events.
    """

    def __init__(
        self,
        *,
        state: AgentState,
        event_bus: ui_events.EventBus,
        invalidate_tools_cache: Callable[[], None],
    ) -> None:
        self._state = state
        self._event_bus = event_bus
        self._invalidate_tools_cache = invalidate_tools_cache
        self._registry_cache: MCPRegistry | None = None
        self._started: bool = False
        self._marketplace_sources_cache: list[MarketplaceSource] | None = None
        self._marketplace_loader: MarketplaceLoader | None = None

    @property
    def registry(self) -> MCPRegistry:
        """Lazy registry of configured MCP servers (Phase 45.2).

        Loads ``cantrip.mcp.yaml`` (repo) and ``~/.config/cantrip/mcp.yaml``
        (user) on first access and builds an :class:`MCPRegistry` over
        them.  Returns the same instance on subsequent calls — call
        :meth:`start` to actually open the connections.
        """
        if self._registry_cache is None:
            configs = load_mcp_configs(repo_root=self._state.charm_path)
            self._registry_cache = MCPRegistry(configs)
        return self._registry_cache

    def registry_if_loaded(self) -> MCPRegistry | None:
        """Return the cached registry without instantiating it.

        Used by tool builders that want to expose MCP tools when a
        registry already exists but must not force one into existence
        before :meth:`start` has been called.
        """
        return self._registry_cache

    @property
    def marketplace_sources(self) -> list[MarketplaceSource]:
        """Marketplace sources declared in user + repo MCP configs (Phase 45.5)."""
        if self._marketplace_sources_cache is None:
            self._marketplace_sources_cache = load_marketplace_sources(
                repo_root=self._state.charm_path
            )
        return list(self._marketplace_sources_cache)

    @property
    def marketplace_loader(self) -> MarketplaceLoader:
        """Lazy :class:`MarketplaceLoader` shared across slash-command calls."""
        if self._marketplace_loader is None:
            self._marketplace_loader = MarketplaceLoader()
        return self._marketplace_loader

    async def start(self) -> None:
        """Open every configured MCP connection.  Idempotent.

        Failures are captured by the registry — a misconfigured server
        logs a warning but never blocks the others.  Safe to call from
        any UI startup path; subsequent calls are no-ops.  Invalidates
        the tools cache so the next access picks up the newly-connected
        servers' tools.  Wires the elicitation callback so server-driven
        prompts surface as ``MCP_ELICITATION_REQUEST`` events.
        """
        if self._started:
            return
        self._started = True
        self.registry.set_elicitation_callback(self.handle_elicitation)
        await self.registry.start_all()
        self._invalidate_tools_cache()

    async def stop(self) -> None:
        """Tear down every MCP connection.  Best-effort, never raises."""
        if self._registry_cache is None:
            return
        await self._registry_cache.stop_all()
        self._started = False

    def handle_elicitation(self, request: object) -> None:
        """Forward an MCP elicitation request to the UI event bus."""
        from cantrip.mcp.elicitation import ElicitationRequest

        if not isinstance(request, ElicitationRequest):
            return
        try:
            self._event_bus.publish(
                ui_events.mcp_elicitation_request(
                    request_id=request.request_id,
                    server_name=request.server_name,
                    mode=request.mode,
                    message=request.message,
                    requested_schema=request.requested_schema,
                    url=request.url,
                )
            )
        except Exception:  # noqa: BLE001 - UI hook must not break the SDK call.
            log.debug("mcp_elicitation_request publish failed", exc_info=True)

    def complete_elicitation(
        self,
        request_id: str,
        action: str,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """UI entry point — answer a parked MCP elicitation by id.

        Returns ``True`` when the request was found and resolved.
        Validates ``action`` against ``accept|decline|cancel``.
        """
        if self._registry_cache is None:
            return False
        return self._registry_cache.complete_elicitation(request_id, action, content)
