"""Tests for the MCP client (Phase 45.1)."""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import sys
from typing import TYPE_CHECKING, Any

import mcp.types as mcp_types
import pytest

from cantrip.mcp import (
    MCPClient,
    MCPConfigError,
    MCPConnectionError,
    MCPInvocationError,
    ServerConfig,
)
from cantrip.mcp.client import _build_tool_infos
from cantrip.mcp.types import TransportKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Project root — ``python -m tests.unit.mcp_stub_server`` only resolves
# when invoked from here, and xdist workers may have a different cwd.
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _stub_config(name: str = "stub", **overrides: object) -> ServerConfig:
    """Build a ``ServerConfig`` that launches the in-tree stub server."""
    return ServerConfig(
        name=name,
        transport=TransportKind.STDIO,
        command=sys.executable,
        args=["-m", "tests.unit.mcp_stub_server"],
        cwd=str(_PROJECT_ROOT),
        timeout_seconds=10.0,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
async def client() -> AsyncIterator[MCPClient]:
    """Start a connected MCPClient against the stub server."""
    c = MCPClient(_stub_config())
    await c.start()
    try:
        yield c
    finally:
        await c.stop()


# ── Lifecycle ──────────────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_lists_tools(self, client: MCPClient) -> None:
        names = sorted(t.name for t in client.tools)
        assert names == ["boom", "echo"]
        echo = next(t for t in client.tools if t.name == "echo")
        assert echo.server_name == "stub"
        assert echo.qualified_name == "mcp__stub__echo"
        assert echo.description == "Echo a string back"
        assert echo.input_schema["type"] == "object"
        assert "text" in echo.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, client: MCPClient) -> None:
        # Second start() on an already-running client is a noop.
        await client.start()
        assert client.is_connected

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        c = MCPClient(_stub_config())
        await c.start()
        await c.stop()
        await c.stop()
        assert not c.is_connected
        assert c.tools == []

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with MCPClient(_stub_config()) as c:
            assert c.is_connected
            assert any(t.name == "echo" for t in c.tools)
        assert not c.is_connected


# ── Configuration errors ───────────────────────────────────────────────


class TestConfigErrors:
    @pytest.mark.asyncio
    async def test_stdio_requires_command(self) -> None:
        c = MCPClient(ServerConfig(name="bad", transport=TransportKind.STDIO, command=None))
        with pytest.raises(MCPConfigError, match="command"):
            await c.start()

    @pytest.mark.asyncio
    async def test_http_requires_url(self) -> None:
        c = MCPClient(ServerConfig(name="bad", transport=TransportKind.HTTP, url=None))
        with pytest.raises(MCPConfigError, match="url"):
            await c.start()


# ── Tool invocation ────────────────────────────────────────────────────


class TestCallTool:
    @pytest.mark.asyncio
    async def test_echo(self, client: MCPClient) -> None:
        out = await client.call_tool("echo", {"text": "hello"})
        assert out.text == "hello"
        assert out.app_renders == ()

    @pytest.mark.asyncio
    async def test_boom_surfaces_error(self, client: MCPClient) -> None:
        with pytest.raises(MCPInvocationError):
            await client.call_tool("boom", {})

    @pytest.mark.asyncio
    async def test_call_tool_when_disconnected(self) -> None:
        c = MCPClient(_stub_config())
        with pytest.raises(MCPConnectionError):
            await c.call_tool("echo", {"text": "x"})


# ── Allowlist enforcement ──────────────────────────────────────────────


class TestAllowlist:
    @pytest.mark.asyncio
    async def test_disallowed_tool_filtered_from_list(self) -> None:
        async with MCPClient(_stub_config(allowed_tools=["echo"])) as c:
            assert [t.name for t in c.tools] == ["echo"]

    @pytest.mark.asyncio
    async def test_disallowed_tool_rejected_on_invoke(self) -> None:
        async with MCPClient(_stub_config(allowed_tools=["echo"])) as c:
            with pytest.raises(MCPInvocationError, match="not in the allowlist"):
                await c.call_tool("boom", {})

    @pytest.mark.asyncio
    async def test_empty_allowlist_means_all_tools(self) -> None:
        async with MCPClient(_stub_config(allowed_tools=[])) as c:
            names = sorted(t.name for t in c.tools)
            assert names == ["boom", "echo"]


# ── Transient failure recovery ─────────────────────────────────────────


class TestReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_after_explicit_stop(self) -> None:
        """Stop + start round-trips cleanly without leaking state."""
        c = MCPClient(_stub_config())
        await c.start()
        await c.call_tool("echo", {"text": "first"})
        await c.stop()
        await c.start()
        out = await c.call_tool("echo", {"text": "second"})
        assert out.text == "second"
        await c.stop()

    @pytest.mark.asyncio
    async def test_reconnect_handles_failed_open(self) -> None:
        """An open() that fails surfaces MCPConnectionError, not a hung promise."""
        c = MCPClient(
            ServerConfig(
                name="missing",
                transport=TransportKind.STDIO,
                command="/no/such/binary",
                timeout_seconds=2.0,
            )
        )
        with pytest.raises((MCPConnectionError, FileNotFoundError, OSError)):
            await asyncio.wait_for(c.start(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_reconnect_caps_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A permanently-dead server surfaces a clean error after the cap, not a hang."""
        monkeypatch.setattr("cantrip.mcp.client._MAX_RECONNECT_ATTEMPTS", 3)
        monkeypatch.setattr("cantrip.mcp.client._INITIAL_RECONNECT_BACKOFF", 0.0)
        monkeypatch.setattr("cantrip.mcp.client._MAX_RECONNECT_BACKOFF", 0.0)
        c = MCPClient(
            ServerConfig(
                name="dead",
                transport=TransportKind.STDIO,
                command="/no/such/binary",
                timeout_seconds=2.0,
            )
        )
        with pytest.raises(MCPConnectionError, match="after 3 attempts"):
            await asyncio.wait_for(c._reconnect(), timeout=10.0)


# ── SDK shape ──────────────────────────────────────────────────────────
#
# The stdio suite above drives a real server, so it covers the handshake
# and the happy path.  These tests pin the two places where Cantrip
# reads SDK objects field by field: a rename on either side degrades
# silently (empty schemas, swallowed tool errors) rather than raising,
# so assert against genuine SDK models rather than hand-rolled stubs.


class TestSDKShape:
    def test_tool_input_schema_survives_conversion(self) -> None:
        schema = {"type": "object", "properties": {"text": {"type": "string"}}}
        tools = _build_tool_infos(
            "srv",
            [mcp_types.Tool(name="echo", description="d", input_schema=schema)],
            [],
        )
        assert [t.input_schema for t in tools] == [schema]

    @pytest.mark.asyncio
    async def test_error_result_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c = MCPClient(_stub_config())
        result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="server said no")],
            is_error=True,
        )
        monkeypatch.setattr(c, "_session", _SessionStub(result), raising=False)
        with pytest.raises(MCPInvocationError, match="server said no"):
            await c._call_tool_once("echo", {})


class _SessionStub:
    """Minimal stand-in for ``ClientSession`` in the call-tool path."""

    def __init__(self, result: mcp_types.CallToolResult) -> None:
        self._result = result

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        del name, arguments
        return self._result


# ── HTTP transport wiring ──────────────────────────────────────────────


class _HTTPTransportRecorder:
    """Replaces the SDK's streamable-HTTP transport and client session.

    Captures the URL and the ``httpx2`` client Cantrip hands to the
    transport so the test can assert the per-server headers, timeout,
    and auth actually reach the wire.
    """

    def __init__(self) -> None:
        self.url: str | None = None
        self.http_client: Any = None

    @contextlib.asynccontextmanager
    async def transport(self, url: str, *, http_client: Any) -> Any:
        self.url = url
        self.http_client = http_client
        yield object(), object()

    def session(self, *_args: Any, **_kwargs: Any) -> Any:
        return _SessionContext()


class _SessionContext:
    """Async-context stand-in for ``ClientSession`` during ``_run``."""

    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Any:
        return mcp_types.ListToolsResult(
            tools=[mcp_types.Tool(name="ping", description="p", input_schema={})]
        )


class TestHTTPTransport:
    """The HTTP branch has no live server in the unit suite, so pin the
    call contract Cantrip has with the SDK transport instead."""

    @pytest.mark.asyncio
    async def test_http_transport_receives_configured_http_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mcp
        import mcp.client.streamable_http as sdk_http

        recorder = _HTTPTransportRecorder()
        monkeypatch.setattr(sdk_http, "streamable_http_client", recorder.transport)
        monkeypatch.setattr(mcp, "ClientSession", recorder.session)

        config = ServerConfig(
            name="remote",
            transport=TransportKind.HTTP,
            url="https://mcp.example.com/mcp",
            headers={"X-Cantrip": "1"},
            timeout_seconds=12.0,
        )
        async with MCPClient(config) as c:
            assert [t.name for t in c.tools] == ["ping"]

        assert recorder.url == "https://mcp.example.com/mcp"
        assert recorder.http_client.headers["X-Cantrip"] == "1"
        assert recorder.http_client.timeout.connect == 12.0
        # The server-initiated GET stream outlives a single request.
        assert recorder.http_client.timeout.read == 300.0
