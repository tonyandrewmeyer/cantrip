"""Tests for the MCPTool wrapper and build_tools integration (Phase 45.3)."""

from __future__ import annotations

import pathlib
import sys
from collections.abc import AsyncIterator

import pytest

from cantrip.agent.queue import TaskCategory
from cantrip.agent.subagent import _filter_tools
from cantrip.agent.tools import build_tools
from cantrip.agent.tools.base import Tool
from cantrip.agent.tools.mcp_tool import MCPTool
from cantrip.mcp import MCPRegistry, ServerConfig
from cantrip.mcp.types import MCPToolInfo, TransportKind

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[4]


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


@pytest.fixture
async def connected_registry() -> AsyncIterator[MCPRegistry]:
    reg = MCPRegistry([_stub_config()])
    await reg.start_all()
    try:
        yield reg
    finally:
        await reg.stop_all()


# ── MCPTool descriptor ─────────────────────────────────────────────────


class TestMCPToolDescriptor:
    def test_qualified_name(self) -> None:
        info = MCPToolInfo(
            server_name="charmhub",
            name="search",
            description="search Charmhub",
            input_schema={"type": "object"},
        )
        # Build a tool against an empty registry — descriptors only.
        tool = MCPTool(info, MCPRegistry([]))
        assert tool.name == "mcp__charmhub__search"
        assert "MCP charmhub" in tool.description
        assert "search Charmhub" in tool.description
        assert tool.parameters == {"type": "object"}

    def test_default_parameters_when_schema_missing(self) -> None:
        info = MCPToolInfo(server_name="x", name="t", description="", input_schema={})
        tool = MCPTool(info, MCPRegistry([]))
        assert tool.parameters == {"type": "object", "properties": {}}


# ── MCPTool execution against a live registry ──────────────────────────


class TestMCPToolExecute:
    @pytest.mark.asyncio
    async def test_echo(self, connected_registry: MCPRegistry) -> None:
        info = next(t for t in connected_registry.aggregated_tools() if t.name == "echo")
        tool = MCPTool(info, connected_registry)
        result = await tool.execute(text="hi")
        assert result.success
        assert result.output == "hi"
        assert result.data == {"mcp_server": "stub", "mcp_tool": "echo"}

    @pytest.mark.asyncio
    async def test_server_error_surfaces_failure(self, connected_registry: MCPRegistry) -> None:
        info = next(t for t in connected_registry.aggregated_tools() if t.name == "boom")
        tool = MCPTool(info, connected_registry)
        result = await tool.execute()
        assert not result.success
        assert "MCP call failed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_disconnected_server_returns_error(self) -> None:
        reg = MCPRegistry([_stub_config()])
        # Don't start.
        info = MCPToolInfo(
            server_name="stub",
            name="echo",
            description="",
            input_schema={"type": "object"},
        )
        tool = MCPTool(info, reg)
        result = await tool.execute(text="x")
        assert not result.success
        assert "not connected" in (result.error or "")

    @pytest.mark.asyncio
    async def test_unknown_server_returns_error(self) -> None:
        reg = MCPRegistry([])
        info = MCPToolInfo(
            server_name="missing",
            name="echo",
            description="",
            input_schema={"type": "object"},
        )
        tool = MCPTool(info, reg)
        result = await tool.execute()
        assert not result.success
        assert "not connected" in (result.error or "")


# ── build_tools integration ────────────────────────────────────────────


class TestBuildToolsRegistersMCP:
    @pytest.mark.asyncio
    async def test_mcp_tools_appear_in_build_tools(self, connected_registry: MCPRegistry) -> None:
        tools = build_tools(mcp_registry=connected_registry)
        names = {t.name for t in tools}
        assert "mcp__stub__echo" in names
        assert "mcp__stub__boom" in names

    def test_no_registry_no_mcp_tools(self) -> None:
        tools = build_tools()
        assert not any(t.name.startswith("mcp__") for t in tools)


# ── Subagent passthrough ──────────────────────────────────────────────


class _DummyTool(Tool):
    """Lightweight Tool subclass for filter testing — no real execution."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object"}

    async def execute(self, **kwargs: object) -> object:
        raise NotImplementedError


class TestSubagentMCPFilter:
    """``_filter_tools`` lets ``mcp__*`` tools through every category."""

    def test_mcp_tool_visible_in_research(self) -> None:
        tools = [
            _DummyTool("mcp__charmhub__search"),
            _DummyTool("not_in_any_allowlist"),
        ]
        filtered = _filter_tools(tools, TaskCategory.RESEARCH)
        names = {t.name for t in filtered}
        assert "mcp__charmhub__search" in names
        assert "not_in_any_allowlist" not in names

    def test_mcp_tool_visible_in_build(self) -> None:
        tools = [_DummyTool("mcp__grafana__query")]
        filtered = _filter_tools(tools, TaskCategory.BUILD)
        assert [t.name for t in filtered] == ["mcp__grafana__query"]

    def test_non_mcp_still_filtered(self) -> None:
        """A non-MCP tool not in the category allowlist is still excluded."""
        tools = [_DummyTool("totally_made_up_tool")]
        filtered = _filter_tools(tools, TaskCategory.BUILD)
        assert filtered == []
