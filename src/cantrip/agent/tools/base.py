"""Base tool interface for agent tools."""

from __future__ import annotations

import dataclasses
import logging
import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pathlib

    from cantrip.agent.tools.post_edit_lint import DiagnosticsReport
    from cantrip.llm.base import Image

log = logging.getLogger(__name__)

# Tools that the post-edit lint hook (Phase 71.4) recognises as
# producing file changes worth re-linting.  Kept as a module-level
# constant so the dispatcher's quick-check stays a hash-set lookup.
_EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "write_file",
        "edit_file",
        "multi_edit",
    }
)


@dataclasses.dataclass
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
    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    error: str | None = None
    images: list[Image] = dataclasses.field(default_factory=list)
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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        """Return a present-continuous "running now" caption (Phase 82).

        The pre-call counterpart to :attr:`ToolResult.caption`: rendered
        in place when the tool is dispatched (``"Packing the charm…"``,
        ``"Querying Tempo for the last 5 traces…"``) and replaced by the
        post-call caption when the tool returns.  Override on tools whose
        users would otherwise stare at silence between the agent's last
        line and the next visible event — slow file packers, network
        queries, long juju waits.

        Returning ``None`` (the default) lets
        :func:`build_tool_intro_caption` synthesise a generic
        ``"Running <tool_name>…"`` from the tool's name and arguments.
        """
        del arguments
        return None


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

# Phase 108.5: tool-name → English verb so the fallback caption reads
# as ``read src/foo.py`` rather than ``read_file(path=src/foo.py)``.
# Tools not in this map fall through to the bare tool name as the
# verb, which still gives ``unknown_tool src/foo.py`` — verb-target
# in shape, just less polished in vocabulary.  Add an entry only
# when the bare name reads awkwardly; the map is *not* a complete
# inventory of cantrip's tools.
_TOOL_VERBS: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "edit",
    "multi_edit": "edit",
    "list_dir": "list",
    "run_command": "run",
    "web_fetch": "fetch",
    "git_clone": "clone",
    "charmcraft_init": "scaffold",
    "charmcraft_pack": "pack",
    "quick_pack": "pack",
    "charmlint": "lint",
    "plan_tasks": "plan",
    "juju": "juju",
    "run_charm_tests": "test",
}


def build_tool_caption(
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: ToolResult | None = None,
) -> str:
    """Return a one-line human caption for a tool invocation.

    Prefers the tool's own ``ToolResult.caption`` when present.  Falls
    back (Phase 108.5) to ``verb value`` — the verb is looked up in
    :data:`_TOOL_VERBS` (or defaults to the bare tool name), and the
    value comes from the first argument matching the
    :data:`_CAPTION_KEY_PREFERENCE` list (``path``, ``command``,
    ``url``, …).  This produces ``read src/foo.py`` rather than the
    older ``read_file(path=src/foo.py)``, so the chat reads as
    English instead of as Python source.  When no argument matches,
    returns just the verb.  Values are truncated to
    :data:`_CAPTION_VALUE_MAX` characters and newlines collapsed so
    the caption always fits one line.
    """
    if result is not None and result.caption:
        return result.caption

    verb = _TOOL_VERBS.get(tool_name, tool_name)
    args = arguments or {}
    for key in _CAPTION_KEY_PREFERENCE:
        if key in args and args[key] not in (None, ""):
            value = _format_caption_value(args[key])
            return f"{verb} {value}"

    # No preferred key; fall back to the first argument with a
    # non-empty value so the caption still carries *something*.
    for raw in args.values():
        if raw in (None, ""):
            continue
        value = _format_caption_value(raw)
        return f"{verb} {value}"

    return verb


def build_tool_intro_caption(
    tool: Tool | None,
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> str:
    """Return a pre-call "running now" caption for a tool invocation (Phase 82).

    Prefers :meth:`Tool.intro_caption` when the tool overrides it.
    Falls back (Phase 108.5) to the same ``verb value`` shape as
    :func:`build_tool_caption` — the leading ``·`` glyph the chat
    surface attaches is what tells the user the call is in flight,
    so the caption itself does not need a ``Running …`` prefix and
    a trailing ``…``.
    """
    if tool is not None:
        try:
            override = tool.intro_caption(arguments or {})
        except (TypeError, ValueError, KeyError, AttributeError):
            log.exception("intro_caption raised for %s", tool_name)
            override = None
        if override:
            return override

    verb = _TOOL_VERBS.get(tool_name, tool_name)
    args = arguments or {}
    for key in _CAPTION_KEY_PREFERENCE:
        if key in args and args[key] not in (None, ""):
            value = _format_caption_value(args[key])
            return f"{verb} {value}"

    for raw in args.values():
        if raw in (None, ""):
            continue
        value = _format_caption_value(raw)
        return f"{verb} {value}"

    return verb


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


_BOOL_TRUE_LITERALS: frozenset[str] = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE_LITERALS: frozenset[str] = frozenset({"false", "0", "no", "off", ""})


def _coerce_argument(value: Any, schema: dict[str, Any]) -> Any:
    """Coerce *value* to the JSONSchema type when the LLM emitted a string.

    Both Anthropic's and Google's function-calling formats sometimes
    surface primitive arguments as strings even when the schema declares
    ``boolean`` / ``integer`` / ``number`` — typically the OpenAI-compat
    arguments-as-JSON-string code path, but Gemini's protobuf and
    misformed cached responses occasionally do it too.  Without coercion
    the tool sees ``destructive_mode="false"`` and ``bool("false")`` is
    ``True``, silently flipping a destructive flag the wrong way.

    Coercion is intentionally narrow: only primitive types declared in
    the schema, only when *value* is a string, only the obvious boolean
    /integer / number literals.  Unknown literals fall through unchanged
    so the tool still sees the original string and can produce a clear
    error.  Schemas without a ``type`` field leave the value untouched —
    this guard never *invents* a type.
    """
    if not isinstance(value, str) or not isinstance(schema, dict):
        return value
    declared = schema.get("type")
    if declared == "boolean":
        lowered = value.strip().lower()
        if lowered in _BOOL_TRUE_LITERALS:
            return True
        if lowered in _BOOL_FALSE_LITERALS:
            return False
        return value
    if declared == "integer":
        try:
            return int(value.strip())
        except ValueError:
            return value
    if declared == "number":
        try:
            return float(value.strip())
        except ValueError:
            return value
    return value


def _coerce_arguments(arguments: dict[str, Any], parameters: Any) -> dict[str, Any]:
    """Apply :func:`_coerce_argument` to every key declared in *parameters*.

    ``parameters`` is the tool's JSONSchema (the ``properties`` block is
    where individual argument schemas live).  Arguments not declared in
    the schema pass through unchanged — the LLM might have emitted an
    extra key that the tool's ``**kwargs`` capture path expects to swallow.
    """
    if not isinstance(parameters, dict):
        return arguments
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return arguments
    coerced: dict[str, Any] = {}
    for key, value in arguments.items():
        sub_schema = properties.get(key)
        coerced[key] = (
            _coerce_argument(value, sub_schema) if isinstance(sub_schema, dict) else value
        )
    return coerced


async def execute_tool(
    tool_map: dict[str, Tool],
    name: str,
    arguments: dict[str, Any],
    *,
    auto_lint: bool = False,
    charm_path: pathlib.Path | None = None,
) -> ToolResult:
    """Look up and execute a tool by name with error handling.

    Shared by the main conversation loop and subagent runners.

    When *auto_lint* is true and the tool is one of the recognised
    file-editing tools (Phase 71.4), the result is enriched with
    diagnostics from ``ruff`` / ``ty`` / ``charmlint`` against the
    touched paths.  Diagnostics are advisory: a successful edit stays
    successful even when the linter complains.  Subagent callers
    leave *auto_lint* at its default ``False`` so the heavyweight
    feedback loop fires only on the primary agent's turn.
    """
    tool = tool_map.get(name)
    if not tool:
        return ToolResult(success=False, output="", error=f"Unknown tool: {name}")

    arguments = _coerce_arguments(arguments, tool.parameters)

    try:
        result = await tool.execute(**arguments)
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

    if auto_lint and result.success and name in _EDIT_TOOL_NAMES:
        await _apply_post_edit_diagnostics(
            tool_name=name,
            arguments=arguments,
            result=result,
            base_path=getattr(tool, "base_path", None),
            charm_path=charm_path,
        )

    return result


async def _apply_post_edit_diagnostics(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: ToolResult,
    base_path: pathlib.Path | None,
    charm_path: pathlib.Path | None,
) -> None:
    """Run post-edit linters and fold their report into *result*.

    Mutates *result* in place — appends a diagnostics block to
    ``result.output`` and stashes the structured payload under
    ``result.data["diagnostics"]`` so UI surfaces and tests can read
    it without re-parsing.  Failures inside the lint pipeline are
    swallowed: this hook never demotes a successful edit.
    """
    # Late import keeps tools/base.py free of the lint subsystem
    # at module import time — relevant for the cold-start budget.
    from cantrip.agent.tools.post_edit_lint import (
        collect_touched_paths,
        run_post_edit_diagnostics,
    )

    paths = collect_touched_paths(tool_name, arguments, base_path)
    if not paths:
        return

    try:
        report: DiagnosticsReport = await run_post_edit_diagnostics(paths, charm_path=charm_path)
    except (OSError, ValueError, RuntimeError) as exc:
        log.warning("Post-edit diagnostics raised %s: %s", type(exc).__name__, exc)
        return

    if report.is_empty():
        return

    text_block = report.to_text()
    if text_block:
        result.output = (result.output + "\n\n" + text_block) if result.output else text_block
    result.data["diagnostics"] = report.to_data()
