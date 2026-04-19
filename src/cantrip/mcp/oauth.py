"""OAuth flow handlers for MCP HTTP servers (Phase 45.4b).

The MCP SDK's :class:`mcp.client.auth.OAuthClientProvider` does the
heavy lifting — PKCE, dynamic client registration, RFC 9728 Protected
Resource Metadata discovery, token refresh.  Cantrip just provides the
two application-level callbacks the SDK can't infer:

* **Redirect handler** — called with the authorization URL.  Opens the
  user's default browser via :mod:`webbrowser`.  Falls back to logging
  the URL when the platform has no browser configured (server
  environments, CI).
* **Callback handler** — runs a single-purpose ``aiohttp`` server bound
  to ``127.0.0.1:<redirect_port>``, waits for one ``GET /callback``
  request carrying the OAuth ``code``/``state``, and returns
  ``(code, state)`` to the SDK.  The server tears down as soon as the
  reply arrives.

Both handlers cap on a configurable timeout so a user who walks away
from the prompt eventually surfaces a clean :class:`MCPConnectionError`
rather than parking the conversation forever.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.mcp.types import OAuthConfig

log = logging.getLogger(__name__)


# Default callback path on the localhost listener.
CALLBACK_PATH = "/callback"

# Default timeout for the user-completes-OAuth round-trip.  Five minutes
# matches the SDK's own ``OAuthClientProvider`` default and is long
# enough for a user to read their email + paste a verification code.
DEFAULT_OAUTH_TIMEOUT = 300.0


def make_redirect_uri(port: int) -> str:
    """Build the canonical localhost redirect URI for an OAuth flow."""
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def make_redirect_handler() -> Callable[[str], Awaitable[None]]:
    """Return an async redirect handler that opens the URL in a browser.

    Splitting this off as a factory keeps the SDK-facing callback a
    pure async function with no captured state — easier to swap out
    in tests.
    """

    async def _redirect(url: str) -> None:
        log.info("Opening MCP OAuth authorization URL: %s", url)
        opened = await asyncio.to_thread(_open_browser, url)
        if not opened:
            # Server environments may not have a browser; log clearly
            # so the user can copy the URL manually.
            log.warning("Could not open a browser; visit this URL to authorize: %s", url)

    return _redirect


def _open_browser(url: str) -> bool:
    """Sync wrapper around :func:`webbrowser.open`; ``False`` on failure."""
    try:
        return webbrowser.open(url, new=1, autoraise=True)
    except (webbrowser.Error, OSError) as exc:
        log.debug("webbrowser.open failed: %s", exc)
        return False


def make_callback_handler(
    port: int,
    *,
    timeout: float = DEFAULT_OAUTH_TIMEOUT,
) -> Callable[[], Awaitable[tuple[str, str | None]]]:
    """Return an async callback handler that captures one OAuth redirect.

    The returned coroutine, when awaited, binds an aiohttp server to
    ``127.0.0.1:<port>``, waits for one ``GET /callback?code=...&state=...``
    request, and returns ``(code, state)``.  The server stops listening
    immediately afterwards.

    The factory pattern lets tests stub the handler with a custom
    ``code/state`` source without touching the network.
    """

    async def _wait_for_callback() -> tuple[str, str | None]:
        return await wait_for_localhost_callback(port, timeout=timeout)

    return _wait_for_callback


async def wait_for_localhost_callback(
    port: int,
    *,
    timeout: float = DEFAULT_OAUTH_TIMEOUT,
    bind_host: str = "127.0.0.1",
) -> tuple[str, str | None]:
    """Listen on ``bind_host:port`` for one OAuth callback, return ``(code, state)``.

    Raises :class:`TimeoutError` when the callback doesn't arrive within
    ``timeout`` seconds, and :class:`OSError` when the OAuth provider
    returns an ``error`` query parameter (auth refused, scope rejected,
    etc.).  Both surface up to the SDK as a clean
    :class:`MCPConnectionError` at the call site.
    """
    from aiohttp import web

    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, str | None]] = loop.create_future()

    async def handler(request: web.Request) -> web.Response:
        if request.path != CALLBACK_PATH:
            return web.Response(status=404, text="not found")
        params = request.query
        if "error" in params:
            err = params.get("error", "unknown")
            description = params.get("error_description", "")
            message = f"OAuth error: {err}" + (f" — {description}" if description else "")
            if not future.done():
                future.set_exception(OSError(message))
            return web.Response(
                status=400,
                text=(f"Authentication failed.\n\n{message}\n\nYou can close this tab."),
                content_type="text/plain",
            )
        code = params.get("code")
        if not code:
            if not future.done():
                future.set_exception(OSError("OAuth callback missing `code` parameter"))
            return web.Response(
                status=400,
                text="Authentication failed: missing code parameter.",
                content_type="text/plain",
            )
        state = params.get("state")
        if not future.done():
            future.set_result((code, state))
        return web.Response(
            status=200,
            text=("Authentication complete.\n\nYou can close this tab and return to Cantrip."),
            content_type="text/plain",
        )

    app = web.Application()
    app.router.add_get(CALLBACK_PATH, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, bind_host, port)
    try:
        await site.start()
    except OSError as exc:
        await runner.cleanup()
        raise OSError(
            f"could not bind OAuth callback listener on {bind_host}:{port}: {exc}"
        ) from exc
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        await runner.cleanup()


def build_client_metadata(config: OAuthConfig) -> object:
    """Return an :class:`OAuthClientMetadata` populated from ``config``.

    Wrapped here rather than inlined so the call site doesn't import
    SDK-internal types directly — a future SDK reshuffle stays
    contained.
    """
    from mcp.shared.auth import OAuthClientMetadata

    return OAuthClientMetadata(
        redirect_uris=[make_redirect_uri(config.redirect_port)],
        client_name=config.client_name,
        scope=" ".join(config.scopes) if config.scopes else None,
        token_endpoint_auth_method="none",  # PKCE flow — no client secret.
    )


__all__ = [
    "CALLBACK_PATH",
    "DEFAULT_OAUTH_TIMEOUT",
    "build_client_metadata",
    "make_callback_handler",
    "make_redirect_handler",
    "make_redirect_uri",
    "wait_for_localhost_callback",
]
