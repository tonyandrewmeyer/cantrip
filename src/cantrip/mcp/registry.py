"""Registry of running MCP clients (Phase 45.2).

Owns the set of long-lived :class:`MCPClient` instances configured for
this Cantrip session.  ``start_all()`` launches every configured server
in parallel, captures any startup failures so unreachable servers are
logged but never crash the agent, and exposes a status snapshot for the
``/mcp`` slash command.

The registry is the single point the rest of the codebase reaches for
MCP tools — Phase 45.3 wires its ``aggregated_tools`` view into the
agent's tool list with ``mcp__<server>__<tool>`` qualified names.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cantrip.mcp.client import MCPClient
from cantrip.mcp.exceptions import MCPError
from cantrip.mcp.types import MCPToolInfo, ServerConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from cantrip.mcp.elicitation import ElicitationRequest

log = logging.getLogger(__name__)


class ServerStatus(enum.StrEnum):
    """Connection lifecycle as surfaced to the UI."""

    PENDING = "pending"
    CONNECTED = "connected"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ServerSnapshot:
    """A point-in-time view of one server, for the ``/mcp`` command."""

    name: str
    status: ServerStatus
    transport: str
    tool_count: int
    tools: list[MCPToolInfo] = field(default_factory=list)
    error: str | None = None


class MCPRegistry:
    """Manage the lifecycle of every configured MCP server.

    Independent of the agent — tests can drive it directly.  The agent
    constructs one and wires it through to the tool layer.
    """

    def __init__(self, configs: list[ServerConfig]) -> None:
        self._clients: dict[str, MCPClient] = {cfg.name: MCPClient(cfg) for cfg in configs}
        self._configs: dict[str, ServerConfig] = {cfg.name: cfg for cfg in configs}
        # Stop tracking per server: PENDING until ``start_all()`` resolves.
        self._status: dict[str, ServerStatus] = {cfg.name: ServerStatus.PENDING for cfg in configs}
        self._errors: dict[str, str] = {}

    def set_elicitation_callback(
        self, callback: Callable[[ElicitationRequest], None] | None
    ) -> None:
        """Forward every server's elicitation requests through ``callback``.

        Called by the agent layer to wire elicitation events to the UI
        bus.  The callback receives one :class:`ElicitationRequest` per
        request and must call :meth:`complete_elicitation` later.
        """
        for client in self._clients.values():
            client.elicitation.set_callback(callback)

    def complete_elicitation(
        self,
        request_id: str,
        action: str,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """Resolve an elicitation across every server.

        The UI doesn't need to know which server originated a request;
        the registry tries each pending manager and returns ``True``
        on the first match.  Concurrent requests are still safe — each
        elicitation has its own UUID.
        """
        for client in self._clients.values():
            if client.elicitation.complete(request_id, action, content):
                return True
        return False

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start every configured client in parallel.

        Failures are captured per server so a single misconfigured
        entry never blocks the rest.  Already-running clients are
        skipped (``MCPClient.start`` is idempotent).
        """
        if not self._clients:
            return
        results = await asyncio.gather(
            *(self._start_one(name) for name in self._clients),
            return_exceptions=True,
        )
        # gather already routes exceptions into _start_one; this loop
        # exists only to surface anything that escaped (it shouldn't).
        for name, exc in zip(self._clients, results, strict=True):
            if isinstance(exc, BaseException) and not isinstance(exc, asyncio.CancelledError):
                self._record_failure(name, exc)

    async def stop_all(self) -> None:
        """Tear down every client.  Best-effort; never raises."""
        if not self._clients:
            return
        await asyncio.gather(
            *(self._stop_one(name) for name in self._clients),
            return_exceptions=True,
        )

    async def _start_one(self, name: str) -> None:
        client = self._clients[name]
        try:
            await client.start()
        except MCPError as exc:
            self._record_failure(name, exc)
            return
        except Exception as exc:  # noqa: BLE001 - SDK can raise anything
            self._record_failure(name, exc)
            return
        self._status[name] = ServerStatus.CONNECTED
        self._errors.pop(name, None)
        log.info("MCP server %r connected (%d tools)", name, len(client.tools))

    async def _stop_one(self, name: str) -> None:
        client = self._clients[name]
        try:
            await client.stop()
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            log.debug("Error stopping MCP server %r", name, exc_info=True)
        # Don't override an already-failed entry — keeps the status
        # readable in /mcp output after a partial outage.
        if self._status.get(name) == ServerStatus.CONNECTED:
            self._status[name] = ServerStatus.STOPPED

    def _record_failure(self, name: str, exc: BaseException) -> None:
        self._status[name] = ServerStatus.FAILED
        self._errors[name] = str(exc) or exc.__class__.__name__
        log.warning("MCP server %r failed to start: %s", name, exc)

    # ── Inspection ──────────────────────────────────────────────────────

    @property
    def configured(self) -> list[ServerConfig]:
        """Return every configured server, regardless of status."""
        return list(self._configs.values())

    def get_client(self, name: str) -> MCPClient | None:
        """Return the live client by server name, or ``None`` if unknown."""
        return self._clients.get(name)

    def aggregated_tools(self) -> list[MCPToolInfo]:
        """Tools across every connected server, ready for the agent layer.

        Disconnected and failed servers contribute nothing — keeping the
        aggregated list a faithful "what can the agent actually call right
        now" view.  Phase 45.3 wraps each entry as a Cantrip ``Tool``.
        """
        out: list[MCPToolInfo] = []
        for name, client in self._clients.items():
            if self._status.get(name) != ServerStatus.CONNECTED:
                continue
            out.extend(client.tools)
        return out

    def snapshot(self) -> list[ServerSnapshot]:
        """Build the ``/mcp`` command's view: status + tool list per server."""
        snapshots: list[ServerSnapshot] = []
        for name, config in sorted(self._configs.items()):
            client = self._clients.get(name)
            tools = client.tools if client else []
            snapshots.append(
                ServerSnapshot(
                    name=name,
                    status=self._status.get(name, ServerStatus.PENDING),
                    transport=config.transport.value,
                    tool_count=len(tools),
                    tools=tools,
                    error=self._errors.get(name),
                )
            )
        return snapshots


__all__ = ["MCPRegistry", "ServerSnapshot", "ServerStatus"]
