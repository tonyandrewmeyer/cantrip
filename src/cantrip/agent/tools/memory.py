"""Agent tools for charm-scope and global memory (Phase 43)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cantrip.agent.memory import (
    VALID_KINDS,
    VALID_STATUSES,
    MemoryScopeError,
)
from cantrip.agent.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from cantrip.agent.memory import MemoryEntry, MemoryManager


_SCOPE_ENUM = ["charm", "global"]


def _entry_summary(entry: MemoryEntry) -> str:
    """One-line summary of a memory entry for list output."""
    tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
    return f"- ({entry.scope}) **{entry.title}** — {entry.kind}{tags}"


class _MemoryToolBase(Tool):
    """Shared constructor for memory tools that need a manager reference."""

    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager


class MemoryListTool(_MemoryToolBase):
    """List memory entries filtered by scope, kind, tag, or status."""

    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return (
            "List charm-scope and global memory entries.  Returns titles, "
            "kinds, scopes, and tags — not bodies.  Use memory_read to fetch "
            "the full body of a specific entry.  Filter by scope (charm|global), "
            "kind (fact|rule|lesson), tag, or status (active|quarantined|archived)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": ("Optional scope filter. Omit to list both scopes."),
                },
                "kind": {
                    "type": "string",
                    "enum": sorted(VALID_KINDS),
                    "description": "Optional kind filter.",
                },
                "tag": {
                    "type": "string",
                    "description": "Optional single tag to match.",
                },
                "status": {
                    "type": "string",
                    "enum": sorted(VALID_STATUSES),
                    "description": (
                        "Optional status filter.  Defaults to 'active' — pass "
                        "'archived' or 'quarantined' to see those."
                    ),
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """List entries matching the given filters."""
        scope = kwargs.get("scope")
        kind = kwargs.get("kind")
        tag = kwargs.get("tag")
        status = kwargs.get("status", "active")
        entries = self._manager.list_entries(scope=scope, kind=kind, status=status, tag=tag)
        if not entries:
            return ToolResult(success=True, output="(no memories)")
        lines = [_entry_summary(e) for e in entries]
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"entries": [e.to_dict() for e in entries]},
        )


class MemoryReadTool(_MemoryToolBase):
    """Read the full body of a memory entry."""

    @property
    def name(self) -> str:
        return "memory_read"

    @property
    def description(self) -> str:
        return (
            "Read the full body and metadata of a memory entry by title.  "
            "Charm-scope is searched before global-scope when no scope is given, "
            "so a charm memory overrides a global memory of the same name."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the memory to read.",
                },
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Optional scope to restrict the lookup.",
                },
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Load the full body of the memory identified by ``title``."""
        title = kwargs.get("title")
        if not isinstance(title, str) or not title.strip():
            return ToolResult(success=False, output="", error="title is required")
        scope = kwargs.get("scope")
        entry = self._manager.read(title=title, scope=scope)
        if entry is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No memory found with title {title!r}",
            )
        header = f"# {entry.title}\n\n*Kind:* {entry.kind}  *Scope:* {entry.scope}"
        if entry.tags:
            header += f"  *Tags:* {', '.join(entry.tags)}"
        return ToolResult(
            success=True,
            output=f"{header}\n\n{entry.body}",
            data={"entry": entry.to_dict()},
        )


class MemorySearchTool(_MemoryToolBase):
    """Keyword search across memory bodies."""

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Keyword search across memory titles and bodies.  Case-insensitive "
            "substring match.  Returns matching entries as summaries — use "
            "memory_read to fetch full bodies."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for.",
                },
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Optional scope filter.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Search both scopes (or one) for memories matching the substring."""
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(success=False, output="", error="query is required")
        scope = kwargs.get("scope")
        entries = self._manager.search(query, scope=scope)
        if not entries:
            return ToolResult(success=True, output=f"(no matches for {query!r})")
        lines = [_entry_summary(e) for e in entries]
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"entries": [e.to_dict() for e in entries]},
        )


class MemoryWriteTool(_MemoryToolBase):
    """Create a new memory or overwrite an existing one."""

    @property
    def name(self) -> str:
        return "memory_write"

    @property
    def description(self) -> str:
        return (
            "Create a memory in the given scope.  Charm-scope is specific to "
            "this charm (stored in .cantrip); global-scope is reusable across "
            "charms (stored under ~/.config/cantrip/memory/).  Overwrites any "
            "existing entry with the same title in the same scope."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Where to store the memory.",
                },
                "title": {
                    "type": "string",
                    "description": "Short unique title for the memory.",
                },
                "kind": {
                    "type": "string",
                    "enum": sorted(VALID_KINDS),
                    "description": (
                        "'fact' for neutral information, 'rule' for required "
                        "behaviour from the user, 'lesson' for lessons learned "
                        "from past mistakes or successes."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": "Markdown body of the memory.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for filtering.",
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line_start": {"type": "integer"},
                            "line_end": {"type": "integer"},
                            "sha": {"type": "string"},
                        },
                    },
                    "description": (
                        "Optional citations to source files — used later by "
                        "revalidation to check whether the memory is still valid."
                    ),
                },
            },
            "required": ["scope", "title", "kind", "body"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Persist a new memory entry in the requested scope."""
        scope = kwargs.get("scope")
        title = kwargs.get("title")
        kind = kwargs.get("kind")
        body = kwargs.get("body")
        if not isinstance(title, str) or not title.strip():
            return ToolResult(success=False, output="", error="title is required")
        if not isinstance(body, str) or not body.strip():
            return ToolResult(success=False, output="", error="body is required")
        if not isinstance(scope, str) or not isinstance(kind, str):
            return ToolResult(success=False, output="", error="scope and kind are required")
        tags = kwargs.get("tags") or []
        citations = kwargs.get("citations") or []
        try:
            entry = self._manager.write(
                scope=scope,
                title=title,
                kind=kind,
                body=body,
                tags=list(tags),
                citations=list(citations),
                source="manual",
            )
        except MemoryScopeError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(
            success=True,
            output=f"Wrote memory: {entry.title} ({entry.scope})",
            data={"entry": entry.to_dict()},
        )


class MemoryUpdateTool(_MemoryToolBase):
    """Update an existing memory's body, kind, tags, or status."""

    @property
    def name(self) -> str:
        return "memory_update"

    @property
    def description(self) -> str:
        return (
            "Update fields on an existing memory.  Any field omitted is left "
            "unchanged.  Use this to change the body after learning something "
            "new, to move a stale memory to 'archived', or to adjust tags."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": _SCOPE_ENUM},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "kind": {"type": "string", "enum": sorted(VALID_KINDS)},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": sorted(VALID_STATUSES)},
                "citations": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Replacement citation list.",
                },
            },
            "required": ["scope", "title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Apply the given partial update to the named memory."""
        scope = kwargs.get("scope")
        title = kwargs.get("title")
        if not isinstance(scope, str) or not isinstance(title, str):
            return ToolResult(success=False, output="", error="scope and title are required")
        try:
            entry = self._manager.update(
                scope=scope,
                title=title,
                body=kwargs.get("body"),
                kind=kwargs.get("kind"),
                tags=kwargs.get("tags"),
                status=kwargs.get("status"),
                citations=kwargs.get("citations"),
            )
        except MemoryScopeError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        if entry is None:
            return ToolResult(
                success=False,
                output="",
                error=f"No memory found with title {title!r} in scope {scope!r}",
            )
        return ToolResult(
            success=True,
            output=f"Updated memory: {entry.title} ({entry.scope})",
            data={"entry": entry.to_dict()},
        )


class MemoryRevalidateTool(_MemoryToolBase):
    """Re-check citations on memories and quarantine stale ones."""

    @property
    def name(self) -> str:
        return "memory_revalidate"

    @property
    def description(self) -> str:
        return (
            "Re-check a memory's citations (file exists, SHA still matches) and "
            "update its status.  Memories whose cited source has drifted are "
            "quarantined so the prompt index stops surfacing them; recovery "
            "happens automatically when the citations become valid again.  "
            "Pass a title to revalidate one entry, or omit it to sweep the "
            "given scope (or both scopes)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Optional scope filter.",
                },
                "title": {
                    "type": "string",
                    "description": "Title of a single memory to revalidate.",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Revalidate one memory or sweep a scope."""
        scope = kwargs.get("scope")
        title = kwargs.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                return ToolResult(success=False, output="", error="title must be a string")
            if not isinstance(scope, str):
                return ToolResult(
                    success=False,
                    output="",
                    error="scope is required when title is given",
                )
            result = self._manager.revalidate(scope=scope, title=title)
            if not result.checks and result.reason == "not found":
                return ToolResult(success=False, output="", error=f"No memory found: {title}")
            lines = [
                f"{result.title} ({result.scope}): {result.reason}",
            ]
            for check in result.checks:
                marker = "✓" if check.ok else "✗"
                path = check.citation.get("path", "(no path)")
                lines.append(f"  {marker} {path} — {check.reason}")
            if result.new_status:
                lines.append(f"  status → {result.new_status}")
            return ToolResult(success=True, output="\n".join(lines))
        # Bulk sweep.
        results = self._manager.revalidate_all(scope=scope)
        quarantined = sum(1 for r in results if r.new_status == "quarantined")
        recovered = sum(1 for r in results if r.new_status == "active")
        clean = sum(1 for r in results if r.ok and r.new_status is None)
        failing = sum(1 for r in results if not r.ok and r.new_status is None)
        summary = (
            f"Revalidated {len(results)} memories — "
            f"{clean} clean, {quarantined} newly quarantined, "
            f"{recovered} recovered, {failing} still failing"
        )
        detail_lines = [summary]
        for result in results:
            if result.new_status or not result.ok:
                marker = "✗" if not result.ok else "→"
                detail_lines.append(f"  {marker} {result.title} ({result.scope}): {result.reason}")
        return ToolResult(success=True, output="\n".join(detail_lines))


class MemorySweepTool(_MemoryToolBase):
    """Archive memories that haven't been accessed or validated recently."""

    @property
    def name(self) -> str:
        return "memory_sweep"

    @property
    def description(self) -> str:
        return (
            "Archive memories that haven't been accessed or validated recently.  "
            "By default anything whose last touch is older than 60 days is moved "
            "from 'active' to 'archived', so the prompt index stays focused on "
            "recent material.  Already-archived and quarantined memories are "
            "untouched.  Pass `soft_days` to override the threshold for this call."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Optional scope filter.",
                },
                "soft_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Staleness threshold in days.  Defaults to 60 (or the "
                        "CANTRIP_MEMORY_SOFT_EXPIRY_DAYS environment variable)."
                    ),
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Archive memories whose last touch is older than the threshold."""
        scope = kwargs.get("scope")
        soft_days = kwargs.get("soft_days")
        if soft_days is not None:
            try:
                soft_days = int(soft_days)
            except (TypeError, ValueError):
                return ToolResult(success=False, output="", error="soft_days must be an integer")
            if soft_days <= 0:
                return ToolResult(success=False, output="", error="soft_days must be positive")
        result = self._manager.sweep_stale(scope=scope, soft_days=soft_days)
        lines = [
            f"Swept memories: {len(result.archived)} archived, "
            f"{result.kept} kept active (cutoff {result.cutoff})"
        ]
        for entry_scope, title in result.archived:
            lines.append(f"  → archived: {title} ({entry_scope})")
        return ToolResult(success=True, output="\n".join(lines))


class MemoryPurgeCheckTool(_MemoryToolBase):
    """List archived memories that have aged past the hard-prompt threshold."""

    @property
    def name(self) -> str:
        return "memory_purge_check"

    @property
    def description(self) -> str:
        return (
            "List archived memories that have aged past the hard-prompt "
            "threshold (default 180 days since archiving).  These are "
            "candidates for permanent deletion — surface them to the user "
            "and ask whether to forget or refresh.  Returns an empty list "
            "when nothing has aged out, which means there's no need to "
            "interrupt the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_ENUM,
                    "description": "Optional scope filter.",
                },
                "hard_days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Threshold in days since archiving.  Defaults to 180 "
                        "(or the CANTRIP_MEMORY_HARD_EXPIRY_DAYS environment variable)."
                    ),
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """List candidates for permanent deletion."""
        scope = kwargs.get("scope")
        hard_days = kwargs.get("hard_days")
        if hard_days is not None:
            try:
                hard_days = int(hard_days)
            except (TypeError, ValueError):
                return ToolResult(success=False, output="", error="hard_days must be an integer")
            if hard_days <= 0:
                return ToolResult(success=False, output="", error="hard_days must be positive")
        candidates = self._manager.list_due_for_purge(scope=scope, hard_days=hard_days)
        if not candidates:
            return ToolResult(success=True, output="(no memories due for purge)")
        lines = [f"{len(candidates)} memories due for purge — ask the user before deleting:"]
        lines.extend(_entry_summary(entry) for entry in candidates)
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"candidates": [e.to_dict() for e in candidates]},
        )


class MemoryForgetTool(_MemoryToolBase):
    """Delete a memory by title."""

    @property
    def name(self) -> str:
        return "memory_forget"

    @property
    def description(self) -> str:
        return (
            "Permanently delete a memory from the given scope.  Use "
            "memory_update with status='archived' instead when you are unsure, "
            "since archived memories can be restored later."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": _SCOPE_ENUM},
                "title": {"type": "string"},
            },
            "required": ["scope", "title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Remove the memory from the requested scope."""
        scope = kwargs.get("scope")
        title = kwargs.get("title")
        if not isinstance(scope, str) or not isinstance(title, str):
            return ToolResult(success=False, output="", error="scope and title are required")
        try:
            removed = self._manager.forget(scope=scope, title=title)
        except MemoryScopeError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        if not removed:
            return ToolResult(
                success=False,
                output="",
                error=f"No memory found with title {title!r} in scope {scope!r}",
            )
        return ToolResult(success=True, output=f"Forgot memory: {title} ({scope})")


def build_memory_tools(manager: MemoryManager) -> list[Tool]:
    """Return the memory tools bound to *manager*."""
    return [
        MemoryListTool(manager),
        MemoryReadTool(manager),
        MemorySearchTool(manager),
        MemoryWriteTool(manager),
        MemoryUpdateTool(manager),
        MemoryRevalidateTool(manager),
        MemorySweepTool(manager),
        MemoryPurgeCheckTool(manager),
        MemoryForgetTool(manager),
    ]


__all__ = [
    "MemoryForgetTool",
    "MemoryListTool",
    "MemoryPurgeCheckTool",
    "MemoryReadTool",
    "MemoryRevalidateTool",
    "MemorySearchTool",
    "MemorySweepTool",
    "MemoryUpdateTool",
    "MemoryWriteTool",
    "build_memory_tools",
]
