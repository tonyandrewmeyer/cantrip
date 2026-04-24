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

    ``caption`` (Phase 75) is a short human-readable one-liner
    describing what the tool *did* (``"Read 47 lines from
    src/foo.py"``, ``"Deployed redis to dev-model"``).  Rendered
    inline in the chat window via the ``TOOL_INVOKED`` event so
    users can see what's happening without opening the transcript.
    Tools that don't set this get a formulaic fallback
    (``tool_name → ok/failed``) synthesised by the agent loop.
    """

    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    images: list[Image] = field(default_factory=list)
    caption: str | None = None


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


# Keys checked, in priority order, when synthesising a fallback
# caption for a tool call.  Most high-traffic tools use one of these
# argument names for their primary target; hitting the first match
# keeps the fallback deterministic without per-tool configuration.
_CAPTION_KEY_PREFERENCE: tuple[str, ...] = (
    "path",
    "file_path",
    "command",
    "cmd",
    "url",
    "query",
    "skill_name",
    "name",
    "tool",
    "charm",
    "app",
    "model",
    "branch",
    "title",
    "message",
)

# Maximum display length for the fallback caption's argument value.
# Longer values are truncated with an ellipsis so the chat block stays
# on one line even when the agent passes a multi-line command.
_CAPTION_VALUE_MAX = 60


def build_tool_caption(
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: "ToolResult | None" = None,
) -> str:
    """Return a one-line human caption for a tool invocation.

    Prefers the tool's own ``ToolResult.caption`` when present.  Falls
    back to ``tool_name(key=value)`` using the first matching key from
    ``_CAPTION_KEY_PREFERENCE`` — most tools hit one of those names
    (``path``, ``command``, ``url``, …) so the fallback is informative
    without per-tool rules.  When no argument matches, returns
    ``tool_name()``.  Values are truncated to :data:`_CAPTION_VALUE_MAX`
    characters and newlines are collapsed so the caption always fits
    one line.
    """
    if result is not None and result.caption:
        return result.caption

    args = arguments or {}
    for key in _CAPTION_KEY_PREFERENCE:
        if key in args and args[key] not in (None, ""):
            value = _format_caption_value(args[key])
            return f"{tool_name}({key}={value})"

    # No preferred key; fall back to the first argument with a
    # non-empty value so the caption still carries *something*.
    for key, raw in args.items():
        if raw in (None, ""):
            continue
        value = _format_caption_value(raw)
        return f"{tool_name}({key}={value})"

    return f"{tool_name}()"


def _format_caption_value(value: Any) -> str:
    """Stringify a caption value, collapsing newlines and truncating."""
    text = str(value).strip().replace("\n", " ⏎ ")
    if len(text) > _CAPTION_VALUE_MAX:
        text = text[: _CAPTION_VALUE_MAX - 1] + "…"
    # Quote the value if it contains spaces or quotes so the caption
    # reads cleanly in the chat: ``run_command(cmd="make check")``.
    if " " in text or '"' in text or "'" in text:
        return '"' + text.replace('"', "'") + '"'
    return text


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
