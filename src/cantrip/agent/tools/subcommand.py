"""Bundle a family of related tools behind a single LLM-facing entry.

OpenAI's chat-completions API caps the ``tools`` array at 128 entries.
Cantrip exposes ~120 leaf tools by default, so a couple of new tools
or one MCP server is enough to push it over.  ``SubcommandTool`` wraps
a related family (``juju.*``, ``git.*``, ``gh.*``, ``memory_*``) into
a single tool entry whose ``parameters`` schema carries a
``subcommand`` discriminator and whose ``description`` lists every
leaf's own description and argument schema.  The LLM sees one entry
per family; downstream gates (permissions, audit, hooks, plan mode)
still see the leaf name they expect because the executor rewrites
``bundle(subcommand="deploy", ...)`` into a flat ``juju_deploy(...)``
call before any of those checks fire.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class SubcommandTool(Tool):
    """One LLM-facing tool that fans out to N leaf tools.

    The constructor takes an explicit ``subcommand → leaf`` mapping so
    bundle subcommand names can be natural verbs (``status``,
    ``deploy``) while the leaf tools keep their canonical
    fully-qualified names (``juju_status``, ``juju_deploy``) for
    permissions, audit, plan-mode allow-lists and durability counters
    — those touch ``leaf.name``, not the subcommand label.
    """

    def __init__(
        self,
        name: str,
        summary: str,
        subcommands: Mapping[str, Tool],
    ) -> None:
        if not subcommands:
            raise ValueError(f"SubcommandTool {name!r} must have at least one subcommand")
        self._name = name
        self._summary = summary.strip()
        self._subcommands: dict[str, Tool] = dict(subcommands)
        # Reverse map: leaf canonical name → subcommand label.  Used by
        # ``resolve_subcommand`` to translate a hallucinated direct
        # leaf-name call (``juju_status``) into a normalised
        # ``juju(subcommand="status")`` form so the executor still
        # finds the leaf in ``tool_map``.
        self._by_leaf_name: dict[str, str] = {
            leaf.name: sub for sub, leaf in self._subcommands.items()
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def subcommands(self) -> dict[str, Tool]:
        """Read-only copy of the ``subcommand → Tool`` mapping."""
        return dict(self._subcommands)

    def get_subcommand(self, sub: str) -> Tool | None:
        """Return the leaf for subcommand label *sub*, or ``None``."""
        return self._subcommands.get(sub)

    @property
    def description(self) -> str:
        chunks: list[str] = [self._summary, "", "Subcommands:"]
        for sub, leaf in self._subcommands.items():
            schema_text = json.dumps(leaf.parameters, indent=2, sort_keys=True)
            chunks.append("")
            chunks.append(f"## {sub}")
            chunks.append(leaf.description)
            chunks.append(f'Pass these as top-level keys alongside `subcommand="{sub}"`:')
            chunks.append("```json")
            chunks.append(schema_text)
            chunks.append("```")
        return "\n".join(chunks)

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": sorted(self._subcommands.keys()),
                    "description": (
                        "Which subcommand to invoke. The argument schema "
                        "for each is in this tool's description; pass the "
                        "leaf's args as top-level keys alongside `subcommand`."
                    ),
                }
            },
            "required": ["subcommand"],
            "additionalProperties": True,
        }

    async def execute(self, *, subcommand: str | None = None, **kwargs: Any) -> ToolResult:
        """Dispatch to ``subcommands[subcommand].execute(**kwargs)``.

        Used as a fallback path: the executor normally rewrites a
        bundled call into a flat leaf invocation before it reaches
        here, but if a caller wires the bundle into ``execute_tool``
        directly this still produces the right result.
        """
        if subcommand is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"{self._name}: missing required 'subcommand'. "
                    f"Valid: {', '.join(sorted(self._subcommands))}."
                ),
            )
        leaf = self._subcommands.get(subcommand)
        if leaf is None:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"{self._name}: unknown subcommand {subcommand!r}. "
                    f"Valid: {', '.join(sorted(self._subcommands))}."
                ),
            )
        return await leaf.execute(**kwargs)


def expand_leaves(tools: list[Tool]) -> list[Tool]:
    """Return *tools* with each ``SubcommandTool`` expanded to bundle + leaves.

    The dispatch ``tool_map`` is built from this list so a leaf can be
    looked up by its own canonical name (``juju_deploy``) without the
    caller having to know which bundle owns it.  The bundle stays in
    the output too so a direct call to the bundle's name still
    resolves.
    """
    out: list[Tool] = []
    for tool in tools:
        out.append(tool)
        if isinstance(tool, SubcommandTool):
            out.extend(tool.subcommands.values())
    return out


def resolve_subcommand(
    tool_map: dict[str, Tool], name: str, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Translate ``bundle(subcommand=X, ...)`` into ``(leaf_name, leaf_args)``.

    Called at the top of every tool-call handler so permissions,
    audit, hooks and plan mode see the leaf name (``juju_deploy``)
    rather than the bundle name (``juju``).  Three cases:

    * *name* is a ``SubcommandTool`` and ``arguments['subcommand']``
      names a known subcommand → returns the leaf's canonical name
      and the remaining arguments.
    * *name* is itself a known leaf of some registered bundle (a
      hallucinated direct call) → returned unchanged so dispatch can
      hit the leaf via ``tool_map`` directly.
    * Anything else → returned unchanged so the caller falls through
      to its existing dispatch path.
    """
    tool = tool_map.get(name)
    if isinstance(tool, SubcommandTool):
        sub = arguments.get("subcommand")
        if isinstance(sub, str):
            leaf = tool.get_subcommand(sub)
            if leaf is not None:
                leaf_args = {k: v for k, v in arguments.items() if k != "subcommand"}
                return leaf.name, leaf_args
        return name, arguments
    return name, arguments


__all__ = [
    "SubcommandTool",
    "expand_leaves",
    "resolve_subcommand",
]
