"""Shared fixtures and helpers for subagent unit tests."""

from typing import Any
from unittest.mock import AsyncMock

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    SubagentContext,
)
from cantrip.agent.tools.base import Tool, ToolResult


def _make_tool(name: str, execute_return: ToolResult | None = None) -> Tool:
    """Build a minimal Tool stub with the given *name*."""

    class _StubTool(Tool):
        @property
        def _name(self) -> str:
            return name

        @property
        def _desc(self) -> str:
            return f"Stub tool {name}"

        @property
        def _params(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

    # We cannot override abstract properties with simple assignments, so
    # we use a concrete subclass with the right property names.
    class StubTool(_StubTool):
        @property
        def name(self) -> str:  # type: ignore[override]
            return self._name

        @property
        def description(self) -> str:  # type: ignore[override]
            return self._desc

        @property
        def parameters(self) -> dict[str, Any]:  # type: ignore[override]
            return self._params

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            return execute_return or ToolResult(success=True, output="ok")

    tool = StubTool()
    tool.execute = AsyncMock(  # type: ignore[method-assign]
        return_value=execute_return or ToolResult(success=True, output="ok"),
    )
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
