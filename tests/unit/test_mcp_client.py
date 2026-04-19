"""Tests for the MCP client (Phase 45.1)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cantrip.mcp import (
    MCPClient,
    MCPConfigError,
    MCPConnectionError,
    MCPInvocationError,
    ServerConfig,
)
from cantrip.mcp.types import TransportKind

# Project root — ``python -m tests.unit.mcp_stub_server`` only resolves
# when invoked from here, and xdist workers may have a different cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        assert out == "hello"

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
        assert out == "second"
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
