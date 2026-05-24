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
from cantrip.mcp.types import (
    MCPAppRender,
    MCPCallResult,
    MCPToolInfo,
    ServerConfig,
    TransportKind,
)

if TYPE_CHECKING:
    from mcp import ClientSession

log = logging.getLogger(__name__)

# Backoff between reconnect attempts.  Doubles up to ``_MAX_RECONNECT_BACKOFF``
# seconds — matches the existing tool-call retry path in ``cantrip.agent.retry``.
_INITIAL_RECONNECT_BACKOFF = 1.0
_MAX_RECONNECT_BACKOFF = 30.0
# Cap reconnect attempts so a permanently-dead server surfaces a clean
# error instead of hanging the conversation forever.  Five attempts with
# the backoff schedule above is ~31 s of wait — enough for a transient
# blip, short enough that the user sees a failure rather than a hang.
_MAX_RECONNECT_ATTEMPTS = 5


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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Invoke ``name`` on the server and return its content.

        The result carries the textual collation under
        :attr:`MCPCallResult.text` plus any ``ui`` blocks extracted from
        the server's response under :attr:`MCPCallResult.app_renders`
        (Phase 73.2 — MCP Apps).

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

    async def _call_tool_once(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if self._session is None:
            raise MCPConnectionError(f"server {self._config.name!r} is not connected")
        try:
            result = await self._session.call_tool(name, arguments)
        except (ConnectionError, BrokenPipeError, OSError) as exc:
            raise MCPConnectionError(str(exc)) from exc
        structured = _content_to_structured(result.content, server_name=self._config.name)
        if getattr(result, "isError", False):
            raise MCPInvocationError(structured.text or f"tool {name!r} reported an error")
        return structured

    # ── Internal connection management ─────────────────────────────────

    def _validate_config(self) -> None:
        """Raise :class:`MCPConfigError` if the config is unusable."""
        if self._config.transport == TransportKind.STDIO:
            if not self._config.command:
                raise MCPConfigError(
                    f"server {self._config.name!r}: stdio transport requires `command`"
                )
            if self._config.oauth is not None:
                raise MCPConfigError(
                    f"server {self._config.name!r}: `oauth` is only valid for the http transport"
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

    def _build_oauth_provider(self) -> Any:
        """Construct the SDK's ``OAuthClientProvider`` when ``oauth`` is set.

        Returns ``None`` when the server doesn't use OAuth.  Wires our
        :class:`FileTokenStorage` so refresh tokens persist across
        sessions; redirect/callback handlers come from
        :mod:`cantrip.mcp.oauth`.  Tests override this method to inject
        a fake auth provider without spinning up the live OAuth flow.
        """
        from cantrip.mcp.oauth import (
            build_client_metadata,
            make_callback_handler,
            make_redirect_handler,
        )
        from cantrip.mcp.token_storage import FileTokenStorage

        if self._config.oauth is None or self._config.url is None:
            return None
        from mcp.client.auth import OAuthClientProvider

        return OAuthClientProvider(
            server_url=self._config.url,
            client_metadata=build_client_metadata(self._config.oauth),
            storage=FileTokenStorage(self._config.name),
            redirect_handler=make_redirect_handler(),
            callback_handler=make_callback_handler(self._config.oauth.redirect_port),
            client_metadata_url=self._config.oauth.client_metadata_url,
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
                auth = self._build_oauth_provider()
                async with streamablehttp_client(
                    self._config.url or "",
                    headers=dict(self._config.headers) or None,
                    timeout=self._config.timeout_seconds,
                    auth=auth,
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

        Retries up to :data:`_MAX_RECONNECT_ATTEMPTS` times on
        :class:`MCPConnectionError` so a server that briefly went away
        comes back online without losing the client.  After the cap the
        last error propagates so a permanently-dead server surfaces as
        a tool-call failure instead of hanging the conversation forever.
        :class:`MCPConfigError` aborts immediately — the config cannot
        recover by retry alone.
        """
        await self.stop()
        backoff = _INITIAL_RECONNECT_BACKOFF
        last_error: MCPConnectionError | None = None
        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            try:
                await self.start()
                return
            except MCPConfigError:
                raise
            except MCPConnectionError as exc:
                last_error = exc
                if attempt >= _MAX_RECONNECT_ATTEMPTS:
                    break
                log.warning(
                    "Reconnect to %s failed (attempt %d/%d): %s; retrying in %.1fs",
                    self._config.name,
                    attempt,
                    _MAX_RECONNECT_ATTEMPTS,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_RECONNECT_BACKOFF)
        assert last_error is not None
        raise MCPConnectionError(
            f"reconnect to {self._config.name!r} failed after "
            f"{_MAX_RECONNECT_ATTEMPTS} attempts: {last_error}"
        ) from last_error

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


def _content_to_structured(content: list[Any], *, server_name: str) -> MCPCallResult:
    """Split an MCP ``CallToolResult.content`` list into text + ui parts.

    Textual parts are joined into a single string (the same shape the
    pre-Phase-73.2 ``_content_to_text`` returned).  Content blocks that
    look like an MCP Apps ``ui`` block (``type == "ui"`` with a
    ``text/html`` mime type) are extracted into :class:`MCPAppRender`
    entries so the agent's tool adapter can publish an app-render event
    without re-parsing the SDK shape.

    Unknown non-text blocks fall through to a ``[<type>]`` placeholder
    so the textual result is still non-lossy.  ``ui`` blocks also leave
    a placeholder in the text collation so a chat surface that drops
    the iframe (e.g. plain-text transcript export) still sees that an
    app render existed at this position.
    """
    text_parts: list[str] = []
    app_renders: list[MCPAppRender] = []
    for item in content or []:
        render = _extract_app_render(item, server_name=server_name)
        if render is not None:
            app_renders.append(render)
            placeholder = render.fallback_text or f"[MCP App: {render.title}]"
            text_parts.append(placeholder)
            continue
        text = getattr(item, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
            continue
        kind = getattr(item, "type", item.__class__.__name__)
        text_parts.append(f"[{kind}]")
    return MCPCallResult(
        text="\n".join(text_parts),
        app_renders=tuple(app_renders),
    )


def _extract_app_render(item: Any, *, server_name: str) -> MCPAppRender | None:
    """Detect an MCP Apps ``ui`` content block; ``None`` if not a render.

    Defensive against the two shapes the spec permits in the wild: a
    first-class ``type == "ui"`` block with the HTML on ``html`` /
    ``text``, and an OpenAI-widget-style ``_meta`` annotation on a
    plain resource block.  Either way the HTML payload, title, fallback
    text, and optional max-height are pulled into a :class:`MCPAppRender`.
    """
    item_type = getattr(item, "type", None)
    meta = _coerce_meta(getattr(item, "meta", None) or getattr(item, "_meta", None))

    # Shape A — explicit ``type: "ui"`` block (the canonical MCP Apps shape).
    if item_type == "ui":
        mime = getattr(item, "mimeType", None) or getattr(item, "mime_type", None) or "text/html"
        if mime != "text/html":
            return None
        html = _coerce_string(
            getattr(item, "html", None) or getattr(item, "text", None) or meta.get("html")
        )
        if not html:
            return None
        return MCPAppRender(
            server_name=server_name,
            title=_coerce_string(meta.get("title") or getattr(item, "title", None)) or "App",
            mime="text/html",
            html=html,
            fallback_text=_coerce_string(meta.get("fallback") or meta.get("text_fallback")),
            max_height_px=_coerce_max_height(meta.get("max_height_px") or meta.get("maxHeightPx")),
        )

    # Shape B — generic content with an MCP-Apps ``_meta`` annotation.
    app_meta = meta.get("app") if isinstance(meta.get("app"), dict) else None
    if app_meta is None and "html" in meta and meta.get("mime") == "text/html":
        app_meta = meta
    if app_meta is None:
        return None
    html = _coerce_string(app_meta.get("html"))
    if not html:
        return None
    return MCPAppRender(
        server_name=server_name,
        title=_coerce_string(app_meta.get("title")) or "App",
        mime="text/html",
        html=html,
        fallback_text=_coerce_string(app_meta.get("fallback") or app_meta.get("text_fallback")),
        max_height_px=_coerce_max_height(
            app_meta.get("max_height_px") or app_meta.get("maxHeightPx")
        ),
    )


def _coerce_meta(value: Any) -> dict[str, Any]:
    """Best-effort cast of an SDK-supplied ``_meta`` field to ``dict``."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    # Pydantic models, namedtuples — pull out the canonical attributes.
    as_dict = getattr(value, "model_dump", None)
    if callable(as_dict):
        try:
            dumped = as_dict()
        except (TypeError, ValueError):
            return {}
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _coerce_string(value: Any) -> str:
    """Return *value* as a string, treating ``None`` / non-strings as empty."""
    if isinstance(value, str):
        return value
    return ""


def _coerce_max_height(value: Any) -> int | None:
    """Cast to ``int`` when *value* is a positive number; ``None`` otherwise."""
    if isinstance(value, bool):  # bools are ints in Python — exclude explicitly.
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    return None


__all__ = ["MCPClient"]
