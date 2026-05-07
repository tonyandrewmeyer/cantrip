"""Shared fixtures and helpers for subagent unit tests."""

from typing import Any
from unittest.mock import AsyncMock

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    SubagentContext,
)
from cantrip.agent.tools.base import Tool, ToolResult
from tests.support.tools import make_stub_tool


def _make_tool(name: str, execute_return: ToolResult | None = None) -> Tool:
    """Stub tool whose ``execute`` is wrapped in :class:`AsyncMock` for assertion."""
    result = execute_return or ToolResult(success=True, output="ok")
    tool = make_stub_tool(name, output=result.output, success=result.success)
    tool.execute = AsyncMock(return_value=result)  # type: ignore[method-assign]
    return tool


def _make_context(**overrides: Any) -> SubagentContext:
    """Build a SubagentContext with sensible defaults."""
    defaults: dict[str, Any] = {
        "task": AgentTask(
            id="test-task",
            title="Test task",
            category=TaskCategory.BUILD,
            description="A test task description.",
        ),
    }
    defaults.update(overrides)
    return SubagentContext(**defaults)
