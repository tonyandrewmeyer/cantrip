"""Tests for the MCP registry and /mcp slash command (Phase 45.2)."""

from __future__ import annotations

import pathlib
import sys

import pytest

from cantrip.agent.mcp_commands import handle_mcp, mcp_help_text
from cantrip.mcp import MCPRegistry, ServerConfig, ServerStatus
from cantrip.mcp.types import TransportKind

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _stub_config(name: str = "stub", **overrides: object) -> ServerConfig:
    return ServerConfig(
        name=name,
        transport=TransportKind.STDIO,
        command=sys.executable,
        args=["-m", "tests.unit.mcp_stub_server"],
        cwd=str(_PROJECT_ROOT),
        timeout_seconds=10.0,
        **overrides,  # type: ignore[arg-type]
    )


def _broken_config(name: str = "broken") -> ServerConfig:
    """A config that points at a non-existent binary."""
    return ServerConfig(
        name=name,
        transport=TransportKind.STDIO,
        command="/no/such/binary",
        timeout_seconds=2.0,
    )


# ── Registry lifecycle ────────────────────────────────────────────────


class TestMCPRegistry:
    @pytest.mark.asyncio
    async def test_empty_registry(self) -> None:
        reg = MCPRegistry([])
        await reg.start_all()
        assert reg.snapshot() == []
        assert reg.aggregated_tools() == []
        await reg.stop_all()

    @pytest.mark.asyncio
    async def test_single_server_starts(self) -> None:
        reg = MCPRegistry([_stub_config()])
        try:
            await reg.start_all()
            snaps = reg.snapshot()
            assert len(snaps) == 1
            assert snaps[0].status == ServerStatus.CONNECTED
            assert snaps[0].tool_count == 2  # echo + boom
            assert {t.name for t in reg.aggregated_tools()} == {"echo", "boom"}
        finally:
            await reg.stop_all()

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_block_others(self) -> None:
        """A broken server must not prevent a healthy one from connecting."""
        reg = MCPRegistry([_stub_config(name="ok"), _broken_config(name="bad")])
        try:
            await reg.start_all()
            snaps = {s.name: s for s in reg.snapshot()}
            assert snaps["ok"].status == ServerStatus.CONNECTED
            assert snaps["bad"].status == ServerStatus.FAILED
            assert snaps["bad"].error  # populated.
            # Aggregated tools include only the healthy server's tools.
            servers = {t.server_name for t in reg.aggregated_tools()}
            assert servers == {"ok"}
        finally:
            await reg.stop_all()

    @pytest.mark.asyncio
    async def test_stop_all_marks_connected_as_stopped(self) -> None:
        reg = MCPRegistry([_stub_config()])
        await reg.start_all()
        await reg.stop_all()
        snaps = reg.snapshot()
        assert snaps[0].status == ServerStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_all_leaves_failed_status(self) -> None:
        """A previously-failed server stays ``failed`` after stop_all."""
        reg = MCPRegistry([_broken_config()])
        await reg.start_all()
        await reg.stop_all()
        snaps = reg.snapshot()
        assert snaps[0].status == ServerStatus.FAILED

    @pytest.mark.asyncio
    async def test_get_client(self) -> None:
        reg = MCPRegistry([_stub_config()])
        try:
            await reg.start_all()
            assert reg.get_client("stub") is not None
            assert reg.get_client("missing") is None
        finally:
            await reg.stop_all()


# ── /mcp slash command ───────────────────────────────────────────────


class TestMcpSlashCommand:
    def test_no_registry(self) -> None:
        out = handle_mcp(None, "")
        assert "not configured" in out

    def test_help(self) -> None:
        reg = MCPRegistry([])
        out = handle_mcp(reg, "help")
        assert "MCP commands" in out

    def test_help_text_mentions_subcommands(self) -> None:
        text = mcp_help_text()
        assert "/mcp" in text
        assert "tools" in text

    def test_empty_overview(self) -> None:
        reg = MCPRegistry([])
        assert "No MCP servers" in handle_mcp(reg, "")

    @pytest.mark.asyncio
    async def test_overview_lists_servers(self) -> None:
        reg = MCPRegistry([_stub_config()])
        try:
            await reg.start_all()
            out = handle_mcp(reg, "")
            assert "**stub**" in out
            assert "connected" in out
            assert "2 tools" in out
            assert "[ok]" in out
        finally:
            await reg.stop_all()

    @pytest.mark.asyncio
    async def test_overview_shows_failure(self) -> None:
        reg = MCPRegistry([_broken_config()])
        await reg.start_all()
        out = handle_mcp(reg, "")
        assert "**broken**" in out
        assert "failed" in out
        assert "[!!]" in out

    @pytest.mark.asyncio
    async def test_tools_subcommand(self) -> None:
        reg = MCPRegistry([_stub_config()])
        try:
            await reg.start_all()
            out = handle_mcp(reg, "tools stub")
            assert "Tools on `stub`" in out
            assert "mcp__stub__echo" in out
            assert "mcp__stub__boom" in out
        finally:
            await reg.stop_all()

    @pytest.mark.asyncio
    async def test_tools_unknown_server(self) -> None:
        reg = MCPRegistry([_stub_config()])
        try:
            await reg.start_all()
            out = handle_mcp(reg, "tools nope")
            assert "Error" in out
            assert "unknown server" in out
        finally:
            await reg.stop_all()

    @pytest.mark.asyncio
    async def test_tools_disconnected_server(self) -> None:
        reg = MCPRegistry([_broken_config()])
        await reg.start_all()
        out = handle_mcp(reg, "tools broken")
        assert "Error" in out
        assert "failed" in out
        assert "tool list unavailable" in out

    def test_tools_missing_server_arg(self) -> None:
        reg = MCPRegistry([])
        out = handle_mcp(reg, "tools")
        assert "Error" in out
        assert "expected" in out

    def test_tools_too_many_args(self) -> None:
        reg = MCPRegistry([])
        out = handle_mcp(reg, "tools a b")
        assert "Error" in out
        assert "too many" in out

    def test_unknown_subcommand(self) -> None:
        reg = MCPRegistry([])
        out = handle_mcp(reg, "wat")
        assert "Error" in out
        assert "unknown subcommand" in out
