"""MCP lifecycle controller — registry, marketplace, and elicitation bridge.

Held by :class:`CantripAgent` as ``self._mcp`` and re-exposed through thin
delegators so the public surface (``mcp_registry`` / ``start_mcp`` /
``stop_mcp`` / ``complete_mcp_elicitation`` / ``_on_mcp_elicitation``)
keeps working unchanged.  Lazy registry/loader construction stays inside
this module so ``_build_tools`` can ask whether a registry has been
materialised without forcing one into existence.

Phase 73.2: also owns the MCP Apps bridge — registers per-render app
ids when a tool result carries a ``ui`` block, and routes iframe-
emitted ``postMessage`` tool calls back through the agent's permission
gate + tool registry with a full audit trail.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from cantrip.agent.audit import AuditAction, AuditWriter, make_entry
from cantrip.agent.safety.permissions import (
    PermissionDecision,
    PermissionManager,
    PermissionOutcome,
)
from cantrip.agent.tools.base import ToolResult
from cantrip.mcp import (
    MarketplaceLoader,
    MarketplaceSource,
    MCPRegistry,
    load_marketplace_sources,
)
from cantrip.mcp import load_configs as load_mcp_configs
from cantrip.mcp.types import MCPAppRender
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.agent.state import AgentState

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _AppRegistration:
    """Internal record of one live MCP App render (Phase 73.2)."""

    app_id: str
    server_name: str
    tool_name: str


# Cantrip's per-agent overlay name applied when iframe-emitted tool
# calls run through the permission gate.  Lets users write a per-
# section override in ``.cantrip/permissions.yaml`` that scopes only
# to MCP-App-originated calls, distinct from main / subagent tool calls.
APP_AGENT_NAME = "mcp-app"


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
        # Phase 73.2 — MCP Apps state.  Each call to ``register_app_render``
        # mints an entry here so a later iframe ``postMessage`` carrying
        # the same ``app_id`` resolves to a known server, and audit lines
        # always know which server emitted the app.
        self._apps: dict[str, _AppRegistration] = {}
        self._evaluate_app_permission: (
            Callable[[str, dict[str, Any]], PermissionDecision] | None
        ) = None
        self._dispatch_app_tool: Callable[[str, dict[str, Any]], Awaitable[ToolResult]] | None = (
            None
        )
        self._app_permission_manager: PermissionManager | None = None
        self._app_audit_writer: AuditWriter | None = None

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

    # ── MCP Apps bridge (Phase 73.2) ────────────────────────────────────

    def register_app_render(
        self,
        render: MCPAppRender,
        *,
        tool_name: str,
        tool_call_id: str | None = None,
    ) -> str:
        """Record an MCP App render and publish the bus event.

        Mints a UUID *app_id*, remembers the originating server so a
        later iframe-emitted tool call can be validated against the
        right scope, and publishes an :data:`EventType.MCP_APP_RENDER`
        event so the Web UI renders the iframe and the TUI surfaces
        its fallback marker.  Returns the *app_id* in case a caller
        wants it for direct lookup.
        """
        app_id = uuid.uuid4().hex
        self._apps[app_id] = _AppRegistration(
            app_id=app_id,
            server_name=render.server_name,
            tool_name=tool_name,
        )
        try:
            self._event_bus.publish(
                ui_events.mcp_app_render(
                    app_id=app_id,
                    server_name=render.server_name,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    title=render.title,
                    html=render.html,
                    fallback_text=render.fallback_text,
                    max_height_px=render.max_height_px,
                )
            )
        except Exception:  # noqa: BLE001 — UI bus hook must not crash a tool call.
            log.debug("mcp_app_render publish failed", exc_info=True)
        return app_id

    def register_app_dispatcher(
        self,
        *,
        evaluate_permission: Callable[[str, dict[str, Any]], PermissionDecision],
        dispatch_tool: Callable[[str, dict[str, Any]], Awaitable[ToolResult]],
        permission_manager: PermissionManager | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        """Wire the agent-side hooks that ``handle_app_tool_call`` needs.

        The agent layer (``cantrip.agent.core``) calls this after the
        executor's permission stack and audit writer exist so an
        iframe-emitted tool call can be gated against exactly the
        same ruleset as an agent-initiated call.
        """
        self._evaluate_app_permission = evaluate_permission
        self._dispatch_app_tool = dispatch_tool
        self._app_permission_manager = permission_manager
        self._app_audit_writer = audit_writer

    async def handle_app_tool_call(
        self,
        *,
        app_id: str,
        request_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> None:
        """Route an iframe-emitted tool call through the agent's gate.

        Flow:

        1. Validate *app_id* is a known render — unknown ids audit as
           DENIED with an explanatory reason and the iframe sees an
           error result.
        2. Emit a ``TOOL_INVOKED_PENDING`` event tagged
           ``source="mcp-app"`` so chat surfaces show the call in
           flight, paired by *request_id*.
        3. Evaluate the permission ruleset via the registered hook.
           DENY → audit, emit failure, push result.  ASK → park on
           :class:`PermissionManager` (same CONFIRM surface the agent
           uses); on approval, continue; on denial, audit + emit.
        4. ALLOW → dispatch through the registered tool callable,
           audit the outcome, emit success/failure event, push
           :data:`EventType.MCP_APP_TOOL_RESULT` for the Web UI to
           ``postMessage`` back into the originating iframe.

        Best-effort throughout — exceptions become failure results
        rather than propagating, because the caller is a UI handler
        that must not crash the WebSocket loop.
        """
        args: dict[str, Any] = dict(arguments or {})
        app = self._apps.get(app_id)
        if app is None:
            reason = f"unknown MCP App id {app_id!r}"
            self._audit_app_call(name, AuditAction.DENIED, reason, args)
            self._publish_app_pending(name, request_id)
            self._publish_app_tool_invoked(name, success=False, detail=reason)
            self._publish_app_result(app_id, request_id, success=False, error=reason)
            return

        evaluator = self._evaluate_app_permission
        dispatcher = self._dispatch_app_tool
        if evaluator is None or dispatcher is None:
            reason = "MCP App dispatch is not wired in this session"
            self._audit_app_call(name, AuditAction.DENIED, reason, args, server=app.server_name)
            self._publish_app_pending(name, request_id)
            self._publish_app_tool_invoked(name, success=False, detail=reason)
            self._publish_app_result(app_id, request_id, success=False, error=reason)
            return

        self._publish_app_pending(name, request_id)

        try:
            decision = evaluator(name, args)
        except Exception as exc:  # noqa: BLE001 — evaluator is caller code.
            reason = f"permission evaluation failed: {exc}"
            log.warning("MCP App permission gate raised on %r: %s", name, exc)
            self._audit_app_call(name, AuditAction.DENIED, reason, args, server=app.server_name)
            self._publish_app_tool_invoked(name, success=False, detail=reason)
            self._publish_app_result(app_id, request_id, success=False, error=reason)
            return

        if decision.outcome is PermissionOutcome.DENY:
            self._audit_app_call(
                name, AuditAction.DENIED, decision.reason, args, server=app.server_name
            )
            self._publish_app_tool_invoked(name, success=False, detail=decision.reason)
            self._publish_app_result(app_id, request_id, success=False, error=decision.reason)
            return

        if decision.outcome is PermissionOutcome.ASK:
            manager = self._app_permission_manager
            if manager is None:
                reason = "permission ask requested but no manager wired"
                self._audit_app_call(
                    name, AuditAction.DENIED, reason, args, server=app.server_name
                )
                self._publish_app_tool_invoked(name, success=False, detail=reason)
                self._publish_app_result(app_id, request_id, success=False, error=reason)
                return
            self._audit_app_call(
                name, AuditAction.REVIEW_REQUESTED, decision.reason, args, server=app.server_name
            )
            approved = await manager.request(
                tool_name=name,
                reason=decision.reason,
                arguments=args,
            )
            if not approved:
                reason = f"user declined MCP App tool call: {decision.reason}"
                self._audit_app_call(
                    name, AuditAction.DENIED, reason, args, server=app.server_name
                )
                self._publish_app_tool_invoked(name, success=False, detail=reason)
                self._publish_app_result(app_id, request_id, success=False, error=reason)
                return

        # ALLOW (or ASK approved) — dispatch through the agent's tool registry.
        try:
            result = await dispatcher(name, args)
        except Exception as exc:  # noqa: BLE001 — dispatcher is caller code; iframes shouldn't crash the UI loop.
            reason = f"tool dispatch raised: {exc}"
            log.warning("MCP App dispatch raised on %r: %s", name, exc)
            self._audit_app_call(name, AuditAction.DENIED, reason, args, server=app.server_name)
            self._publish_app_tool_invoked(name, success=False, detail=reason)
            self._publish_app_result(app_id, request_id, success=False, error=reason)
            return

        success = bool(result.success)
        action = AuditAction.ALLOWED if success else AuditAction.DENIED
        self._audit_app_call(name, action, decision.reason, args, server=app.server_name)
        self._publish_app_tool_invoked(
            name,
            success=success,
            detail=(result.error if not success else None),
        )
        self._publish_app_result(
            app_id,
            request_id,
            success=success,
            output=result.output,
            error=result.error,
        )

    # -- Internal helpers ------------------------------------------------

    def _publish_app_pending(self, tool_name: str, request_id: str) -> None:
        try:
            self._event_bus.publish(
                ui_events.tool_invoked_pending(
                    tool_name=tool_name,
                    caption=f"mcp-app: {tool_name}",
                    tool_call_id=f"mcp-app:{request_id}",
                    source="mcp-app",
                )
            )
        except Exception:  # noqa: BLE001 — UI bus hook must not block dispatch.
            log.debug("mcp_app pending publish failed", exc_info=True)

    def _publish_app_tool_invoked(
        self,
        tool_name: str,
        *,
        success: bool,
        detail: str | None = None,
    ) -> None:
        try:
            self._event_bus.publish(
                ui_events.tool_invoked(
                    tool_name=tool_name,
                    caption=f"mcp-app: {tool_name}",
                    success=success,
                    source="mcp-app",
                    detail=detail,
                )
            )
        except Exception:  # noqa: BLE001 — UI bus hook must not block dispatch.
            log.debug("mcp_app tool_invoked publish failed", exc_info=True)

    def _publish_app_result(
        self,
        app_id: str,
        request_id: str,
        *,
        success: bool,
        output: str = "",
        error: str | None = None,
    ) -> None:
        try:
            self._event_bus.publish(
                ui_events.mcp_app_tool_result(
                    app_id=app_id,
                    request_id=request_id,
                    success=success,
                    output=output or "",
                    error=error,
                )
            )
        except Exception:  # noqa: BLE001 — UI bus hook must not block dispatch.
            log.debug("mcp_app_tool_result publish failed", exc_info=True)

    def _audit_app_call(
        self,
        tool_name: str,
        action: AuditAction,
        reason: str,
        arguments: dict[str, Any],
        *,
        server: str | None = None,
    ) -> None:
        """Write one ``.cantrip-audit.jsonl`` row for an iframe tool call."""
        if self._app_audit_writer is None:
            return
        policy_name = f"{APP_AGENT_NAME}:{server}" if server else APP_AGENT_NAME
        try:
            entry = make_entry(
                tool=tool_name,
                action=action,
                policy_name=policy_name,
                reason=reason,
                arguments=arguments,
                charm_path=self._state.charm_path,
            )
            self._app_audit_writer.write(entry)
        except (OSError, ValueError, TypeError):
            log.debug("mcp_app audit write failed", exc_info=True)
