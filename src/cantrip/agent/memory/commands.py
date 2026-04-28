"""Slash-command handlers for memory operations (Phase 43.3).

These functions are pure: they take a :class:`MemoryManager` and the raw
text the user typed after the slash command, and return a Markdown
string to render back as a system message.  Both the TUI and the Web
front-ends call them so the behaviour is identical across surfaces.

Recognised commands:

* ``/memory [scope]`` — list memories (defaults to both scopes)
* ``/remember <kind> [scope] -- <title> -- <body>`` — write a memory
* ``/forget <title>`` — delete a memory by exact title

The lightweight syntax is documented in the help text returned by
:func:`memory_help_text`; ill-formed input produces an error message
that includes the help text rather than silently failing.
"""

from __future__ import annotations

import pathlib
import re
import shlex
from typing import TYPE_CHECKING

from cantrip.agent.memory import export as memory_export
from cantrip.agent.memory.core import VALID_KINDS, MemoryScopeError

if TYPE_CHECKING:
    from cantrip.agent.memory.core import MemoryEntry, MemoryManager


_SCOPES = frozenset({"charm", "global"})


def memory_help_text() -> str:
    """Return the multi-line help block printed on misuse or ``/memory help``."""
    return (
        "**Memory commands**\n\n"
        "- `/memory [scope]` — list memories.  `scope` is optional "
        "(`charm` or `global`); omit to list both.\n"
        "- `/memory export <name> <output_path> [scope]` — bundle "
        "memories into a SKILL.md file at `<output_path>/<name>/SKILL.md` "
        "(or write to `<output_path>` directly when it ends in `.md`).\n"
        "- `/memory export-md <output_dir> [scope]` — write one Markdown "
        "file per memory under `<output_dir>`.\n"
        "- `/memory import <source_path> [target_scope]` — read a "
        "SKILL.md or directory of memory `.md` files; merges into "
        "`global` by default.\n"
        "- `/remember <kind> [scope] -- <title> -- <body>` — write a "
        "memory.  `kind` is one of `fact`, `rule`, `lesson`; `scope` "
        "defaults to `charm`.  Use ` -- ` (space dash dash space) as the "
        "field separator.\n"
        "- `/forget <title>` — delete a memory by exact title.  Asks for "
        "the scope when the same title exists in both."
    )


def handle_memory(
    manager: MemoryManager,
    args: str,
    *,
    charm_path: pathlib.Path | None = None,
) -> str:
    """Handle the ``/memory …`` command and its subcommands."""
    tokens = shlex.split(args.strip(), posix=True) if args.strip() else []
    if tokens and tokens[0].lower() in {"help", "-h", "--help"}:
        return memory_help_text()
    if tokens and tokens[0].lower() == "export":
        return _handle_export(manager, tokens[1:], charm_path=charm_path)
    if tokens and tokens[0].lower() == "export-md":
        return _handle_export_markdown(manager, tokens[1:], charm_path=charm_path)
    if tokens and tokens[0].lower() == "import":
        return _handle_import(manager, tokens[1:])
    scope: str | None = None
    if tokens:
        candidate = tokens[0].lower()
        if candidate not in _SCOPES:
            return _error(f"unknown scope {candidate!r}; expected `charm` or `global`")
        scope = candidate
    entries = manager.list_entries(scope=scope)
    if not entries:
        scope_label = scope or "any scope"
        return f"_No memories in {scope_label}._"
    return _format_entry_list(entries)


def _handle_export(
    manager: MemoryManager, tokens: list[str], *, charm_path: pathlib.Path | None
) -> str:
    """Handle ``/memory export <name> <output_path> [scope]``."""
    if len(tokens) < 2:
        return _error("expected `<name> <output_path> [scope]`. " + memory_help_text())
    name = tokens[0]
    output_path = pathlib.Path(tokens[1]).expanduser()
    scope: str | None = None
    if len(tokens) >= 3:
        candidate = tokens[2].lower()
        if candidate not in _SCOPES:
            return _error(f"unknown scope {candidate!r}; expected `charm` or `global`")
        scope = candidate
    if len(tokens) > 3:
        return _error("too many arguments to export")
    try:
        result = memory_export.export_to_skill(
            manager,
            name=name,
            output_path=output_path,
            scope=scope,
            charm_path=charm_path,
        )
    except (OSError, ValueError) as exc:
        return _error(f"export failed: {exc}")
    suffix = (
        f" ({result.redactions} secret redaction{'s' if result.redactions != 1 else ''})"
        if result.redactions
        else ""
    )
    return f"Exported {len(result.entries)} memories to `{result.output_path}`{suffix}"


def _handle_export_markdown(
    manager: MemoryManager, tokens: list[str], *, charm_path: pathlib.Path | None
) -> str:
    """Handle ``/memory export-md <output_dir> [scope]``."""
    if not tokens:
        return _error("expected `<output_dir> [scope]`. " + memory_help_text())
    output_dir = pathlib.Path(tokens[0]).expanduser()
    scope: str | None = None
    if len(tokens) >= 2:
        candidate = tokens[1].lower()
        if candidate not in _SCOPES:
            return _error(f"unknown scope {candidate!r}; expected `charm` or `global`")
        scope = candidate
    if len(tokens) > 2:
        return _error("too many arguments to export-md")
    try:
        result = memory_export.export_to_markdown(
            manager, output_dir=output_dir, scope=scope, charm_path=charm_path
        )
    except (OSError, ValueError) as exc:
        return _error(f"export failed: {exc}")
    suffix = (
        f" ({result.redactions} secret redaction{'s' if result.redactions != 1 else ''})"
        if result.redactions
        else ""
    )
    return f"Exported {len(result.entries)} memories under `{result.output_path}`{suffix}"


def _handle_import(manager: MemoryManager, tokens: list[str]) -> str:
    """Handle ``/memory import <source_path> [target_scope]``."""
    if not tokens:
        return _error("expected `<source_path> [target_scope]`. " + memory_help_text())
    source = pathlib.Path(tokens[0]).expanduser()
    target_scope = "global"
    if len(tokens) >= 2:
        candidate = tokens[1].lower()
        if candidate not in _SCOPES:
            return _error(f"unknown scope {candidate!r}; expected `charm` or `global`")
        target_scope = candidate
    if len(tokens) > 2:
        return _error("too many arguments to import")
    try:
        result = memory_export.import_from_path(manager, source, target_scope=target_scope)
    except (FileNotFoundError, ValueError, MemoryScopeError) as exc:
        return _error(f"import failed: {exc}")
    parts = [f"Imported {len(result.imported)} memories into `{target_scope}`."]
    if result.skipped:
        parts.append(
            f"Skipped {len(result.skipped)} duplicate{'s' if len(result.skipped) != 1 else ''}: "
            + ", ".join(f"`{t}`" for t in result.skipped[:5])
            + ("…" if len(result.skipped) > 5 else "")
        )
    if result.failed:
        parts.append(
            f"{len(result.failed)} failed: "
            + "; ".join(f"`{t}` ({reason})" for t, reason in result.failed[:5])
        )
    return "\n".join(parts)


def handle_remember(manager: MemoryManager, args: str) -> str:
    """Handle the ``/remember <kind> [scope] -- <title> -- <body>`` command."""
    if not args.strip():
        return _error("missing arguments. " + memory_help_text())

    parts = [p.strip() for p in re.split(r"\s+--\s+", args.strip())]
    if len(parts) != 3:
        return _error(
            "expected three ` -- ` separated fields: `<kind> [scope] -- <title> -- <body>`."
            "\n\n" + memory_help_text()
        )
    head, title, body = parts
    if not title:
        return _error("title is empty")
    if not body:
        return _error("body is empty")

    head_tokens = head.split()
    if not head_tokens:
        return _error("kind is required")
    kind = head_tokens[0].lower()
    if kind not in VALID_KINDS:
        return _error(f"unknown kind {kind!r}; expected one of {', '.join(sorted(VALID_KINDS))}")
    scope = "charm"
    if len(head_tokens) >= 2:
        candidate = head_tokens[1].lower()
        if candidate not in _SCOPES:
            return _error(f"unknown scope {candidate!r}; expected `charm` or `global`")
        scope = candidate
    if len(head_tokens) > 2:
        return _error("too many tokens before `--`; use `<kind> [scope] -- ...`")

    try:
        entry = manager.write(scope=scope, title=title, kind=kind, body=body, source="manual")
    except MemoryScopeError as exc:
        return _error(str(exc))
    return f"Wrote {entry.kind} memory: **{entry.title}** ({entry.scope})"


def handle_forget(manager: MemoryManager, args: str) -> str:
    """Handle the ``/forget <title>`` command."""
    raw = args.strip()
    if not raw:
        return _error("missing title. " + memory_help_text())
    # Allow quoted titles for ones containing whitespace.
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        return _error(f"could not parse arguments: {exc}")
    if not tokens:
        return _error("missing title")

    # Last token may be an explicit scope; otherwise scan both.
    explicit_scope: str | None = None
    if len(tokens) >= 2 and tokens[-1].lower() in _SCOPES:
        explicit_scope = tokens[-1].lower()
        title = " ".join(tokens[:-1])
    else:
        title = " ".join(tokens)

    if explicit_scope is not None:
        if manager.forget(scope=explicit_scope, title=title):
            return f"Forgot memory: **{title}** ({explicit_scope})"
        return _error(f"no memory titled {title!r} in scope {explicit_scope!r}")

    # No scope given — try both.  If both have the same title, ask the
    # user to disambiguate rather than guessing.
    matches: list[str] = []
    for scope in ("charm", "global"):
        entry = manager.read(title=title, scope=scope)
        if entry is not None:
            matches.append(scope)
    if not matches:
        return _error(f"no memory titled {title!r}")
    if len(matches) > 1:
        return _error(
            f"ambiguous: {title!r} exists in both scopes — re-run with an "
            'explicit scope, e.g. `/forget "' + title + '" charm`'
        )
    target_scope = matches[0]
    if manager.forget(scope=target_scope, title=title):
        return f"Forgot memory: **{title}** ({target_scope})"
    return _error(f"failed to delete {title!r} ({target_scope})")


def _error(reason: str) -> str:
    """Format an error response."""
    return f"_Error: {reason}_"


def _format_entry_list(entries: list[MemoryEntry]) -> str:
    """Render a Markdown bullet list of memory entries."""
    lines = []
    for entry in entries:
        tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"- **{entry.title}** ({entry.kind}, {entry.scope}){tags}")
    return "\n".join(lines)


__all__ = [
    "handle_forget",
    "handle_memory",
    "handle_remember",
    "memory_help_text",
]
