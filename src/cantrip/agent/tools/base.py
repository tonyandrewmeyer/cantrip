"""Base tool interface for agent tools."""

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from cantrip.llm.base import Image

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result of a tool execution.

    ``images`` attaches image payloads produced by the tool.  The
    conversation loop forwards them into the next ``tool_result``
    message so vision-capable providers can reason about the image
    alongside the text caption in ``output``.  The caption should
    still carry enough information to be useful on its own —
    providers whose tool-role messages are text-only (Gemini,
    OpenAI-compatible) drop the images.
    """

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    images: list[Image] = field(default_factory=list)


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
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        AttributeError,
        UnicodeDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        log.warning("Tool %s raised %s: %s", name, type(exc).__name__, exc)
        return ToolResult(success=False, output="", error=f"Tool execution failed: {exc}")
