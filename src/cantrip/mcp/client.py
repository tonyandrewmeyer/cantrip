"""MCP client wrapper with lifecycle and reconnect (Phase 45.1)."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Any

from cantrip.mcp.elicitation import ElicitationManager
from cantrip.mcp.exceptions import (
    MCPConfigError,
    MCPConnectionError,
    MCPInvocationError,
)
from cantrip.mcp.types import MCPToolInfo, ServerConfig, TransportKind

if TYPE_CHECKING:
    from mcp import ClientSession

log = logging.getLogger(__name__)

# Backoff between reconnect attempts.  Doubles up to ``_MAX_RECONNECT_BACKOFF``
# seconds — matches the existing tool-call retry path in ``cantrip.agent.retry``.
_INITIAL_RECONNECT_BACKOFF = 1.0
_MAX_RECONNECT_BACKOFF = 30.0


class MCPClient:
    """Long-lived async client for a single MCP server.

    Owns a dedicated background task that keeps the transport and the
    SDK ``ClientSession`` alive between ``start()`` and ``stop()``.  The
    background-task pattern is required because the SDK uses ``anyio``
    context managers internally, and anyio refuses to exit a cancel
    scope in a different task than it was entered in — so the contexts
    must be entered and exited in the same task.

    Concurrent ``call_tool`` invocations from any number of caller
    tasks are safe because ``ClientSession`` serialises requests
    internally; only ``start()`` and ``stop()`` are mutually exclusive.
    """

    def __init__(
        self,
        config: ServerConfig,
        *,
        elicitation_manager: ElicitationManager | None = None,
    ) -> None:
        self._config = config
        self._session: ClientSession | None = None
        self._tools: list[MCPToolInfo] = []
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event = asyncio.Event()
        self._stop: asyncio.Event = asyncio.Event()
        self._start_error: BaseException | None = None
        self._elicitation = elicitation_manager or ElicitationManager(config.name)

    @property
    def elicitation(self) -> ElicitationManager:
        """The elicitation manager bound to this client."""
        return self._elicitation

    @property
    def name(self) -> str:
        """The local handle for this server (from the config)."""
        return self._config.name

    @property
    def is_connected(self) -> bool:
        """Whether the underlying session is live."""
        return self._session is not None

    @property
    def tools(self) -> list[MCPToolInfo]:
        """Tools the server advertises, filtered by the config's allowlist."""
        return list(self._tools)

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Open the transport, run the handshake, cache the tool list.

        Idempotent — calling it on an already-started client is a noop.
        """
        if self._task is not None and not self._task.done():
            return
        self._validate_config()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._start_error = None
        self._task = asyncio.create_task(self._run(), name=f"mcp-client-{self._config.name}")
        await self._ready.wait()
        if self._start_error is not None:
            err = self._start_error
            await self._await_task()
            self._task = None
            if isinstance(err, MCPConfigError):
                raise err
            raise MCPConnectionError(
                f"failed to start MCP server {self._config.name!r}: {err}"
            ) from err

    async def stop(self) -> None:
        """Tear down the transport and session.  Idempotent."""
        if self._task is None:
            return
        self._stop.set()
        await self._await_task()
        self._task = None
        self._session = None
        self._tools = []

    async def __aenter__(self) -> MCPClient:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    # ── Tool invocation ────────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Invoke ``name`` on the server and return its content as text.

        Raises :class:`MCPConnectionError` if the client was never started
        or has already been stopped.  On a transient connection error
        mid-call the client tears down, reconnects with bounded backoff,
        and retries the call once.
        """
        if not self._is_tool_allowed(name):
            raise MCPInvocationError(
                f"tool {name!r} is not in the allowlist for server {self._config.name!r}"
            )
        if self._session is None:
            raise MCPConnectionError(
                f"server {self._config.name!r} is not connected — call start() first"
            )
        try:
            return await self._call_tool_once(name, arguments)
        except MCPConnectionError:
            log.warning("MCP connection lost on call_tool(%s); reconnecting once", name)
            await self._reconnect()
            return await self._call_tool_once(name, arguments)

    async def _call_tool_once(self, name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            raise MCPConnectionError(f"server {self._config.name!r} is not connected")
        try:
            result = await self._session.call_tool(name, arguments)
        except (ConnectionError, BrokenPipeError, OSError) as exc:
            raise MCPConnectionError(str(exc)) from exc
        text = _content_to_text(result.content)
        if getattr(result, "isError", False):
            raise MCPInvocationError(text or f"tool {name!r} reported an error")
        return text

    # ── Internal connection management ─────────────────────────────────

    def _validate_config(self) -> None:
        """Raise :class:`MCPConfigError` if the config is unusable."""
        if self._config.transport == TransportKind.STDIO:
            if not self._config.command:
                raise MCPConfigError(
                    f"server {self._config.name!r}: stdio transport requires `command`"
                )
        elif self._config.transport == TransportKind.HTTP:
            if not self._config.url:
                raise MCPConfigError(
                    f"server {self._config.name!r}: http transport requires `url`"
                )
        else:
            raise MCPConfigError(
                f"server {self._config.name!r}: unknown transport {self._config.transport!r}"
            )

    async def _run(self) -> None:
        """Background task body — owns the transport and session lifetime.

        Enters the SDK's async-context-managed transport and session,
        signals readiness, then blocks on the ``stop`` event.  Both
        contexts exit in this task, satisfying anyio's same-task rule.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        try:
            if self._config.transport == TransportKind.STDIO:
                params = StdioServerParameters(
                    command=self._config.command or "",
                    args=list(self._config.args),
                    env=dict(self._config.env) or None,
                    cwd=self._config.cwd,
                )
                async with stdio_client(params) as (read, write):
                    await self._serve(ClientSession, read, write)
            else:
                async with streamablehttp_client(
                    self._config.url or "",
                    headers=dict(self._config.headers) or None,
                    timeout=self._config.timeout_seconds,
                ) as (read, write, _get_session_id):
                    await self._serve(ClientSession, read, write)
        except BaseException as exc:  # noqa: BLE001 - capture for the start() waiter
            if not self._ready.is_set():
                self._start_error = exc
                self._ready.set()
            elif not isinstance(exc, asyncio.CancelledError):
                log.debug(
                    "MCP server %s background task ended with %r",
                    self._config.name,
                    exc,
                )
        finally:
            self._session = None

    async def _serve(
        self,
        client_session_cls: type[ClientSession],
        read: Any,
        write: Any,
    ) -> None:
        """Run the session inside the transport context, then await stop."""
        timeout = datetime.timedelta(seconds=self._config.timeout_seconds)
        async with client_session_cls(
            read,
            write,
            read_timeout_seconds=timeout,
            elicitation_callback=self._elicitation.handle,
        ) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            self._session = session
            self._tools = _build_tool_infos(
                self._config.name, tools_result.tools, self._config.allowed_tools
            )
            self._ready.set()
            try:
                await self._stop.wait()
            finally:
                # Auto-decline any in-flight elicitations so the SDK call
                # doesn't hang when the connection is being torn down.
                self._elicitation.cancel_all()
            self._session = None

    async def _await_task(self) -> None:
        """Wait for the background task; swallow CancelledError on stop."""
        if self._task is None:
            return
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - keep stop() best-effort
            log.debug(
                "MCP server %s background task raised on shutdown",
                self._config.name,
                exc_info=True,
            )

    async def _reconnect(self) -> None:
        """Tear down and re-establish the session with bounded backoff.

        Repeatedly retries on :class:`MCPConnectionError` so a server
        that briefly went away comes back online without losing the
        client.  :class:`MCPConfigError` aborts immediately — the config
        cannot recover by retry alone.
        """
        await self.stop()
        backoff = _INITIAL_RECONNECT_BACKOFF
        while True:
            try:
                await self.start()
                return
            except MCPConfigError:
                raise
            except MCPConnectionError as exc:
                log.warning(
                    "Reconnect to %s failed: %s; retrying in %.1fs",
                    self._config.name,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_RECONNECT_BACKOFF)

    def _is_tool_allowed(self, name: str) -> bool:
        """Check the per-server allowlist.  Empty allowlist = allow all."""
        if not self._config.allowed_tools:
            return True
        return name in self._config.allowed_tools


def _build_tool_infos(
    server_name: str,
    sdk_tools: list[Any],
    allowed: list[str],
) -> list[MCPToolInfo]:
    """Convert SDK ``Tool`` objects into Cantrip's :class:`MCPToolInfo`.

    Drops anything not in ``allowed`` when the allowlist is non-empty.
    """
    allowlist = set(allowed) if allowed else None
    out: list[MCPToolInfo] = []
    for tool in sdk_tools:
        name = getattr(tool, "name", None)
        if name is None:
            continue
        if allowlist is not None and name not in allowlist:
            continue
        description = getattr(tool, "description", "") or ""
        schema = getattr(tool, "inputSchema", None) or {}
        # The SDK declares inputSchema as ``dict[str, Any]``; copy
        # defensively so a downstream caller cannot mutate the SDK's
        # internal structure.
        out.append(
            MCPToolInfo(
                server_name=server_name,
                name=name,
                description=description,
                input_schema=dict(schema) if isinstance(schema, dict) else {},
            )
        )
    return out


def _content_to_text(content: list[Any]) -> str:
    """Join textual parts of an MCP ``CallToolResult.content`` list.

    Non-text parts (images, embedded resources) are surfaced as a short
    ``[<type>]`` placeholder so the result text is always non-lossy.
    """
    parts: list[str] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
            continue
        kind = getattr(item, "type", item.__class__.__name__)
        parts.append(f"[{kind}]")
    return "\n".join(parts)


__all__ = ["MCPClient"]
