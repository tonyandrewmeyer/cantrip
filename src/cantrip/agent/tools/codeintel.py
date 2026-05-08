"""Phase 72b read-only code-intelligence tools.

Three explicit tools rather than one mode-stringed entry point so the
model can pick them apart in the function-call surface.  Every result
states whether it came from the semantic index or from a literal-search
fallback so a "no semantic match" answer is honest rather than
disguised as a hit.

The tools share a single :class:`~cantrip.codeintel.CodeIntel` instance
through the ``code_intel_getter`` callable: building one is cheap
(seconds for a charm), but rebuilding on every tool call would drop
the cache benefit.  Sessions without an active charm path get
``None`` from the getter; the tools then return a clear "no charm
configured" error rather than silently producing empty results.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.codeintel import CodeIntel, SymbolKind
from cantrip.codeintel.index import (
    render_definitions,
    render_references,
    render_symbols,
)

log = logging.getLogger(__name__)


# Result caps applied by the tool layer.  Looser than
# :data:`cantrip.codeintel.index._DEFAULT_RESULT_LIMIT` because the
# agent occasionally wants to see "everywhere `Foo` shows up" and the
# index already truncates at its own absolute cap.
_TOOL_RESULT_LIMIT = 50


CodeIntelGetter = Callable[[], CodeIntel | None]


def _no_charm_result(tool_name: str) -> ToolResult:
    return ToolResult(
        success=False,
        output="",
        error=(
            "code-intelligence index is unavailable — no active charm "
            "path on this session.  Open a charm or set the path on the "
            "CLI before using ``" + tool_name + "``."
        ),
    )


def _coerce_kinds(value: Any) -> list[SymbolKind] | None:
    """Translate a free-form ``kinds`` argument into a typed list.

    The LLM emits this as a list of strings (function-calling JSON
    cannot serialise enum values directly), so we normalise here
    instead of pushing the burden onto the index.  Unknown labels
    are dropped with a debug log; callers are expected to pick from
    the documented schema enum.
    """
    if value in (None, ""):
        return None
    if isinstance(value, str):
        # Tolerate ``"class,function"`` or ``"class function"`` shapes.
        labels = [label.strip() for label in value.replace(",", " ").split() if label.strip()]
    elif isinstance(value, list):
        labels = [str(label).strip() for label in value if label]
    else:
        return None
    out: list[SymbolKind] = []
    for label in labels:
        try:
            out.append(SymbolKind(label))
        except ValueError:
            log.debug("codeintel tool: ignoring unknown kind %r", label)
    return out or None


class CodeSymbolsTool(Tool):
    """Search workspace symbols by name, with deterministic match policy."""

    def __init__(self, code_intel_getter: CodeIntelGetter) -> None:
        self._getter = code_intel_getter

    @property
    def name(self) -> str:
        return "code_symbols"

    @property
    def description(self) -> str:
        return (
            "Search the workspace for definitions whose name matches QUERY. "
            "Returns kind / qualified-name / signature / file:line per hit, "
            "ordered by match precision: exact qualified > exact > prefix > "
            "fuzzy.  Read-only; the index is built once per session and "
            "refreshed on file mtime changes.  Use this instead of grep "
            "when you know the symbol name and want a structured answer."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol name to look up (e.g. ``MyCharm._on_install``).",
                },
                "path_scope": {
                    "type": "string",
                    "description": (
                        "Optional repo-relative path prefix; restricts the search "
                        "to files whose POSIX path starts with this string."
                    ),
                },
                "kinds": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [k.value for k in SymbolKind],
                    },
                    "description": (
                        "Restrict to specific symbol kinds (class, function, "
                        "method, action, relation, …).  Omit to search all kinds."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (f"Maximum results to return (default {_TOOL_RESULT_LIMIT})."),
                },
            },
            "required": ["query"],
        }

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        query = arguments.get("query")
        return f"Searching symbols for {query!r}…" if query else None

    async def execute(
        self,
        query: str,
        path_scope: str | None = None,
        kinds: Any = None,
        limit: int = _TOOL_RESULT_LIMIT,
    ) -> ToolResult:
        index = self._getter()
        if index is None:
            return _no_charm_result(self.name)
        index.build()
        normalised_kinds = _coerce_kinds(kinds)
        matches, truncated = index.workspace_symbols(
            query,
            path_scope=path_scope,
            kinds=normalised_kinds,
            limit=limit,
        )
        if not matches:
            return ToolResult(
                success=True,
                output=f"No symbols matching {query!r}.",
                data={
                    "match_count": 0,
                    "truncated": 0,
                    "semantic": True,
                    "match_kind": None,
                },
                caption=f"No symbols match {query!r}",
            )
        text = render_symbols(matches, truncated=truncated)
        first_kind = matches[0].match_kind.value
        caption = (
            f"{len(matches)} {first_kind.replace('_', ' ')} symbol match"
            f"{'es' if len(matches) != 1 else ''} for {query!r}"
        )
        if truncated:
            caption += f" (+{truncated} elided)"
        return ToolResult(
            success=True,
            output=text,
            data={
                "match_count": len(matches),
                "truncated": truncated,
                "semantic": True,
                "match_kind": first_kind,
            },
            caption=caption,
        )


class CodeDefinitionTool(Tool):
    """Resolve a symbol to its defining file/line plus a bounded snippet."""

    def __init__(self, code_intel_getter: CodeIntelGetter) -> None:
        self._getter = code_intel_getter

    @property
    def name(self) -> str:
        return "code_definition"

    @property
    def description(self) -> str:
        return (
            "Return the file, line, and a small snippet for the definition of "
            "SYMBOL.  Ambiguous queries (e.g. a method name that exists on "
            "several classes) return every candidate so the caller can "
            "disambiguate.  Read-only; pairs naturally with ``code_symbols`` "
            "(broad search) and ``code_references`` (callsite hunt)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol to resolve (e.g. ``RepoMap.render_for_prompt``).",
                },
                "from_path": {
                    "type": "string",
                    "description": (
                        "Optional repo-relative path of the file initiating "
                        "the lookup.  Used to resolve import aliases and to "
                        "tie-break local vs cross-file definitions."
                    ),
                },
            },
            "required": ["symbol"],
        }

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        symbol = arguments.get("symbol")
        return f"Looking up definition of {symbol!r}…" if symbol else None

    async def execute(
        self,
        symbol: str,
        from_path: str | None = None,
    ) -> ToolResult:
        index = self._getter()
        if index is None:
            return _no_charm_result(self.name)
        index.build()
        result = index.go_to_definition(symbol, from_path=from_path)
        text = render_definitions(result)
        if not result.semantic:
            return ToolResult(
                success=True,
                output=text,
                data={
                    "match_count": 0,
                    "semantic": False,
                    "note": result.note,
                },
                caption=f"No definition for {symbol!r}",
            )
        if len(result.matches) == 1:
            sym = result.matches[0].symbol
            position = f"{sym.file}:{sym.line}" if sym.line else sym.file
            caption = f"Definition of {sym.display_name} at {position}"
        else:
            caption = f"{len(result.matches)} candidate definitions for {symbol!r}"
        return ToolResult(
            success=True,
            output=text,
            data={
                "match_count": len(result.matches),
                "semantic": True,
                "match_kind": result.match_kind.value if result.match_kind else None,
                "note": result.note,
                "matches": [
                    {
                        "kind": m.symbol.kind.value,
                        "name": m.symbol.display_name,
                        "file": m.symbol.file,
                        "line": m.symbol.line,
                    }
                    for m in result.matches
                ],
            },
            caption=caption,
        )


class CodeReferencesTool(Tool):
    """Return the recorded reference locations for a symbol."""

    def __init__(self, code_intel_getter: CodeIntelGetter) -> None:
        self._getter = code_intel_getter

    @property
    def name(self) -> str:
        return "code_references"

    @property
    def description(self) -> str:
        return (
            "List every recorded reference (call, attribute access, import) "
            "to SYMBOL across the workspace, with file:line locations.  "
            "Honest about ambiguity (multiple symbols share the name) and "
            "truncation (the rest are counted in the result).  Read-only."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol to find references for.",
                },
                "from_path": {
                    "type": "string",
                    "description": (
                        "Optional repo-relative path of the file initiating "
                        "the lookup.  Reserved for future scope-aware "
                        "resolution; currently informational."
                    ),
                },
                "include_definition": {
                    "type": "boolean",
                    "description": (
                        "Prepend the defining symbol's file/line to the "
                        "result list.  Useful for displays that want to "
                        "render 'def + N references' together."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Maximum locations to return (default {_TOOL_RESULT_LIMIT})."
                    ),
                },
            },
            "required": ["symbol"],
        }

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        symbol = arguments.get("symbol")
        return f"Searching references to {symbol!r}…" if symbol else None

    async def execute(
        self,
        symbol: str,
        from_path: str | None = None,
        include_definition: bool = False,
        limit: int = _TOOL_RESULT_LIMIT,
    ) -> ToolResult:
        index = self._getter()
        if index is None:
            return _no_charm_result(self.name)
        index.build()
        result = index.find_references(
            symbol,
            from_path=from_path,
            include_definition=include_definition,
            limit=limit,
        )
        text = render_references(result)
        if not result.semantic:
            return ToolResult(
                success=True,
                output=text,
                data={
                    "match_count": 0,
                    "truncated": 0,
                    "semantic": False,
                    "candidate_count": len(result.candidates),
                    "note": result.note,
                },
                caption=f"No references to {symbol!r}",
            )
        files = {ref.file for ref in result.locations}
        caption = (
            f"{len(result.locations)} reference"
            f"{'s' if len(result.locations) != 1 else ''} to {symbol!r} "
            f"across {len(files)} file{'s' if len(files) != 1 else ''}"
        )
        if result.truncated:
            caption += f" (+{result.truncated} elided)"
        return ToolResult(
            success=True,
            output=text,
            data={
                "match_count": len(result.locations),
                "truncated": result.truncated,
                "semantic": True,
                "candidate_count": len(result.candidates),
                "note": result.note,
            },
            caption=caption,
        )


def build_codeintel_tools(getter: CodeIntelGetter) -> list[Tool]:
    """Construct the three Phase 72b tools sharing one index getter."""
    return [
        CodeSymbolsTool(getter),
        CodeDefinitionTool(getter),
        CodeReferencesTool(getter),
    ]


__all__ = [
    "CodeDefinitionTool",
    "CodeIntelGetter",
    "CodeReferencesTool",
    "CodeSymbolsTool",
    "build_codeintel_tools",
]
