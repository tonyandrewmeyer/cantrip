"""``/symbols``, ``/definition`` and ``/references`` — Phase 72b code intel.

Three slash commands that mirror the codeintel tool output so print
mode, the TUI chat, and the Web UI all see the same content.  Each
command returns a Markdown-rendered string the dispatcher displays
directly; an empty index or a missing charm path produces a friendly
"no map" notice rather than an internal error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip import diagnostics
from cantrip.codeintel.index import (
    render_definitions,
    render_references,
    render_symbols,
)

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


_NO_INDEX_NOTICE = (
    "No code-intelligence index: this session has no active charm path.  "
    "Open a charm and try again, or set the path with the CLI."
)


def _split_args(args: str) -> tuple[str, str]:
    """Split a slash-command arg string into ``(query, rest)``.

    The first whitespace-delimited token is treated as the query;
    everything after the first space is preserved as ``rest`` so a
    follow-up ``--scope`` style flag can land here later.  Today no
    command consumes ``rest``, but keeping the signature stable now
    avoids churn when one is added.
    """
    args = args.strip()
    if not args:
        return "", ""
    head, _, tail = args.partition(" ")
    return head, tail.strip()


def handle_symbols(agent: CantripAgent, args: str = "") -> str:
    """``/symbols <query>`` — search the workspace symbol index."""
    query, _ = _split_args(args)
    if not query:
        return "Usage: `/symbols <query>` — searches workspace symbols by name."
    ci = agent.code_intel
    if ci is None:
        return _NO_INDEX_NOTICE
    try:
        ci.build()
        matches, truncated = ci.workspace_symbols(query)
    except Exception as exc:  # noqa: BLE001 — surface via diagnostics log.
        return diagnostics.report_internal_error("/symbols", exc)
    if not matches:
        return f"**No symbols matching `{query}`.**"
    body = render_symbols(matches, truncated=truncated)
    return f"**{len(matches)} symbol match{'es' if len(matches) != 1 else ''} for `{query}`**\n\n```\n{body}\n```"


def handle_definition(agent: CantripAgent, args: str = "") -> str:
    """``/definition <symbol>`` — resolve a symbol to its defining site."""
    symbol, _ = _split_args(args)
    if not symbol:
        return "Usage: `/definition <symbol>` — returns the defining file/line plus a snippet."
    ci = agent.code_intel
    if ci is None:
        return _NO_INDEX_NOTICE
    try:
        ci.build()
        result = ci.go_to_definition(symbol)
    except Exception as exc:  # noqa: BLE001 — surface via diagnostics log.
        return diagnostics.report_internal_error("/definition", exc)
    if not result.semantic:
        return f"**No definition for `{symbol}`.**"
    body = render_definitions(result)
    if len(result.matches) == 1:
        header = f"**Definition of `{symbol}`**"
    else:
        header = f"**{len(result.matches)} candidate definitions for `{symbol}`**"
    return f"{header}\n\n{body}"


def handle_references(agent: CantripAgent, args: str = "") -> str:
    """``/references <symbol>`` — list every recorded callsite for a symbol."""
    symbol, _ = _split_args(args)
    if not symbol:
        return "Usage: `/references <symbol>` — lists every recorded callsite."
    ci = agent.code_intel
    if ci is None:
        return _NO_INDEX_NOTICE
    try:
        ci.build()
        result = ci.find_references(symbol)
    except Exception as exc:  # noqa: BLE001 — surface via diagnostics log.
        return diagnostics.report_internal_error("/references", exc)
    if not result.semantic:
        return f"**No references for `{symbol}`.**"
    body = render_references(result)
    files = {ref.file for ref in result.locations}
    header = (
        f"**{len(result.locations)} reference"
        f"{'s' if len(result.locations) != 1 else ''} to `{symbol}` "
        f"across {len(files)} file{'s' if len(files) != 1 else ''}**"
    )
    if result.truncated:
        header += f" *(+{result.truncated} elided)*"
    return f"{header}\n\n```\n{body}\n```"
