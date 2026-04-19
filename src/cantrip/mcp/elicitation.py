"""Elicitation routing for MCP (Phase 45.4c).

The MCP spec lets a server pause a tool call and ask the human user for
structured input — "what database name should I create?", "paste the
verification code from your email", etc.  The SDK delivers these as a
callback on :class:`mcp.ClientSession`; Cantrip converts them into UI
events the TUI / Web can render and waits on an :class:`asyncio.Future`
for the response.

The flow:

1. Server emits an ``elicitation/request`` over the wire.
2. SDK invokes the registered ``elicitation_callback`` with a typed
   request object.
3. :class:`ElicitationManager` mints a request id, parks an
   :class:`asyncio.Future`, publishes a ``MCP_ELICITATION_REQUEST``
   event on the bus, and ``await``s the future.
4. UI subscribes to the event, prompts the user, and calls
   :meth:`ElicitationManager.complete` with the user's choice.
5. The future resolves; the manager builds the SDK's
   :class:`mcp.types.ElicitResult` and returns it to the SDK.

A bounded timeout prevents a runaway server from parking the
conversation forever — when the user doesn't answer within the
configured window the manager auto-declines.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    import mcp.types as mcp_types
    from mcp.shared.context import RequestContext

log = logging.getLogger(__name__)


# Default timeout for an unanswered elicitation, in seconds.  A server
# that asks for input and never gets an answer eventually auto-declines
# so the conversation loop can move on.
DEFAULT_ELICITATION_TIMEOUT = 600.0  # 10 minutes


@dataclasses.dataclass(frozen=True)
class ElicitationRequest:
    """Cantrip-side view of one pending elicitation.

    Decouples the UI from the SDK's request types so a new SDK shape
    doesn't ripple into the TUI/Web layer.
    """

    request_id: str
    server_name: str
    mode: str  # "form" or "url"
    message: str
    requested_schema: dict[str, Any] | None = None
    url: str | None = None


@dataclasses.dataclass(frozen=True)
class ElicitationResponse:
    """User's reply to an elicitation request.

    ``action`` matches the SDK's ``Literal['accept', 'decline', 'cancel']``;
    ``content`` is the form payload when ``action == 'accept'`` and the
    schema asked for one.
    """

    action: str
    content: dict[str, Any] | None = None


# Subscriber callback type — the agent passes one in to forward
# requests to the UI event bus.
EventCallback = "Callable[[ElicitationRequest], None] | None"


class ElicitationManager:
    """Track in-flight elicitations and resolve them when the user replies.

    Created once per :class:`MCPClient`; the agent passes a callback
    that publishes ``MCP_ELICITATION_REQUEST`` events to the UI bus.
    The UI later calls :meth:`complete` (via the agent) with the
    matching ``request_id``.
    """

    def __init__(
        self,
        server_name: str,
        *,
        on_request: Callable[[ElicitationRequest], None] | None = None,
        timeout: float = DEFAULT_ELICITATION_TIMEOUT,
    ) -> None:
        self._server_name = server_name
        self._on_request = on_request
        self._timeout = timeout
        self._pending: dict[str, asyncio.Future[ElicitationResponse]] = {}

    @property
    def pending(self) -> list[str]:
        """Request ids of currently-parked elicitations.  For UI listing."""
        return list(self._pending)

    def set_callback(self, callback: Callable[[ElicitationRequest], None] | None) -> None:
        """Register or clear the UI-fanout callback after construction."""
        self._on_request = callback

    async def handle(
        self,
        _context: RequestContext[Any, Any] | None,
        params: mcp_types.ElicitRequestParams,
    ) -> mcp_types.ElicitResult | mcp_types.ErrorData:
        """SDK-facing callback bound to ``ClientSession.elicitation_callback``.

        Converts the SDK params to a Cantrip request, publishes it via
        the configured callback, and ``await``s the user's response.
        On timeout the manager auto-declines and removes the entry so a
        late reply doesn't surprise a fresh request.
        """
        import mcp.types as mcp_types_local

        request_id = uuid.uuid4().hex
        request = _request_from_params(self._server_name, request_id, params)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ElicitationResponse] = loop.create_future()
        self._pending[request_id] = future
        if self._on_request is not None:
            try:
                self._on_request(request)
            except Exception:  # noqa: BLE001 - UI hook must not break the SDK call.
                log.debug(
                    "elicitation request callback failed for %s",
                    self._server_name,
                    exc_info=True,
                )
        try:
            response = await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError:
            log.warning(
                "Elicitation %s on %s timed out after %.0fs; auto-declining",
                request_id,
                self._server_name,
                self._timeout,
            )
            self._pending.pop(request_id, None)
            return mcp_types_local.ElicitResult(action="decline")
        finally:
            self._pending.pop(request_id, None)
        return mcp_types_local.ElicitResult(
            action=response.action,
            content=response.content,
        )

    def complete(
        self,
        request_id: str,
        action: str,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """Resolve a parked elicitation; return True when one was found.

        Called by the agent layer after the UI collects the user's
        response.  Validates the action against the SDK's set
        (``accept``/``decline``/``cancel``) and refuses anything else
        rather than corrupting the protocol.
        """
        if action not in {"accept", "decline", "cancel"}:
            raise ValueError(
                f"unknown elicitation action {action!r}; expected accept|decline|cancel"
            )
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(ElicitationResponse(action=action, content=content))
        return True

    def cancel_all(self) -> None:
        """Auto-decline every pending elicitation.

        Called on client shutdown so an outstanding request doesn't
        keep the SDK call waiting forever.  The SDK sees a regular
        ``decline`` reply rather than a cancelled future — easier to
        reason about server-side.
        """
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_result(ElicitationResponse(action="decline"))
            self._pending.pop(request_id, None)


def _request_from_params(
    server_name: str,
    request_id: str,
    params: mcp_types.ElicitRequestParams,
) -> ElicitationRequest:
    """Build the Cantrip-side request from the SDK's union of param types."""
    mode = getattr(params, "mode", "form")
    message = getattr(params, "message", "") or ""
    schema = getattr(params, "requestedSchema", None)
    url = getattr(params, "url", None)
    return ElicitationRequest(
        request_id=request_id,
        server_name=server_name,
        mode=str(mode),
        message=str(message),
        requested_schema=dict(schema) if isinstance(schema, dict) else None,
        url=str(url) if url else None,
    )


__all__ = [
    "DEFAULT_ELICITATION_TIMEOUT",
    "ElicitationManager",
    "ElicitationRequest",
    "ElicitationResponse",
]
