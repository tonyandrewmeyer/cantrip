"""Render a ranked file list as a compact, token-budgeted text block."""

from __future__ import annotations

from cantrip.repomap.graph import FileRanking
from cantrip.repomap.symbols import Symbol, SymbolKind

# Cantrip's overall token budget tracking is character-based at ~4
# chars per token (matches estimate_message_tokens elsewhere).
_CHARS_PER_TOKEN = 4

# Cap symbols-per-file to keep one heavy file from monopolising the
# rendered map even with a fat budget.  Tuned empirically for charm
# repos: a typical src/charm.py has 15-30 methods; 12 leaves room for
# the most central ones plus the class itself.
_MAX_SYMBOLS_PER_FILE = 12


def render(rankings: list[FileRanking], *, token_budget: int) -> str:
    """Format the ranked file list, stopping once the budget is hit.

    Returns the empty string when ``token_budget`` is non-positive or
    no rankings have any symbols — callers treat empty as "skip the
    section in the prompt entirely".
    """
    if token_budget <= 0:
        return ""
    char_budget = token_budget * _CHARS_PER_TOKEN
    out: list[str] = []
    used = 0
    for ranking in rankings:
        if not ranking.symbols:
            continue
        block = _render_file_block(ranking)
        if not block:
            continue
        cost = len(block) + 1  # +1 for the joining newline.
        if used + cost > char_budget:
            # A single oversized file shouldn't shut the whole map
            # down — record a trailing ellipsis line instead.
            if not out:
                out.append(_truncate_block(block, char_budget))
            else:
                out.append("…")
            break
        out.append(block)
        used += cost
    return "\n".join(out).rstrip()


def _render_file_block(ranking: FileRanking) -> str:
    """One file = one heading line plus indented symbol lines."""
    symbols = _select_symbols(ranking.symbols)
    if not symbols:
        return ""
    lines = [f"{ranking.file}:"]
    for sym in symbols:
        lines.append(f"  {_format_symbol(sym)}")
    return "\n".join(lines)


def _select_symbols(symbols: tuple[Symbol, ...]) -> list[Symbol]:
    """Choose which symbols to surface for one file.

    Order: classes first (so a method's enclosing type appears nearby),
    then free functions, then YAML-derived definitions.  Capped at
    :data:`_MAX_SYMBOLS_PER_FILE`.
    """
    order = (
        SymbolKind.CLASS,
        SymbolKind.FUNCTION,
        SymbolKind.METHOD,
        SymbolKind.RELATION,
        SymbolKind.CONFIG_OPTION,
        SymbolKind.ACTION,
        SymbolKind.CONTAINER,
        SymbolKind.STORAGE,
        SymbolKind.RESOURCE,
    )
    bucketed: dict[SymbolKind, list[Symbol]] = {k: [] for k in order}
    for s in symbols:
        bucketed.setdefault(s.kind, []).append(s)
    chosen: list[Symbol] = []
    for kind in order:
        chosen.extend(bucketed.get(kind, []))
        if len(chosen) >= _MAX_SYMBOLS_PER_FILE:
            break
    return chosen[:_MAX_SYMBOLS_PER_FILE]


def _format_symbol(sym: Symbol) -> str:
    """Render one symbol on a single indented line."""
    name = sym.display_name
    if sym.kind == SymbolKind.CLASS:
        return f"class {name}{sym.signature}"
    if sym.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
        return f"def {name}{sym.signature}"
    # YAML-derived: show the role in square brackets so the agent can
    # see at a glance which file is the source of truth.
    label = sym.kind.value
    return f"[{label}] {name}{sym.signature}"


def _truncate_block(block: str, char_budget: int) -> str:
    """Cut a single oversized file block at a line boundary."""
    if char_budget <= 0:
        return ""
    lines = block.split("\n")
    out: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + 1
        if used + cost > char_budget:
            out.append("  …")
            break
        out.append(line)
        used += cost
    return "\n".join(out)
