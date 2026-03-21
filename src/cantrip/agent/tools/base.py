"""Base tool interface for agent tools."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Tool(ABC):
    """Base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for LLM."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""


def tool_to_schema(tool: Tool) -> dict[str, Any]:
    """Convert a Tool to LLM-compatible schema."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


async def execute_tool(
    tool_map: dict[str, Tool], name: str, arguments: dict[str, Any]
) -> ToolResult:
    """Look up and execute a tool by name with error handling.

    Shared by the main conversation loop and subagent runners.
    """
    tool = tool_map.get(name)
    if not tool:
        return ToolResult(success=False, output="", error=f"Unknown tool: {name}")

    try:
        return await tool.execute(**arguments)
    except TypeError as exc:
        return ToolResult(
            success=False,
            output="",
            error=f"Invalid arguments for {name}: {exc}",
        )
    except Exception as exc:
        log.warning("Tool %s raised %s: %s", name, type(exc).__name__, exc)
        return ToolResult(success=False, output="", error=f"Tool execution failed: {exc}")
