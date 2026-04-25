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


def render_full_markdown(rankings: list[FileRanking]) -> str:
    r"""Render the full map as Markdown sections, one heading per file.

    The plain :func:`render` output is a single text block that's
    fine inside the system prompt but reads as a wall of monospace
    when shown in a chat panel — once the user scrolls past the
    top, no visible landmarks remain.  This variant emits a
    Markdown ``### `<path>``` heading per file followed by
    bullet-point symbol lines, so every section keeps a visible
    boundary as the user scrolls through the output.
    """
    parts: list[str] = []
    for ranking in rankings:
        symbols = _select_symbols(ranking.symbols)
        if not symbols:
            continue
        parts.append(f"### `{ranking.file}`")
        parts.append("")
        for sym in symbols:
            parts.append(f"- `{_format_symbol(sym)}`")
        parts.append("")
    return "\n".join(parts).rstrip()


def render_summary(rankings: list[FileRanking], *, top_n: int = 8) -> str:
    """Render a one-line-per-file summary for the chat surface.

    The full :func:`render` output is overwhelming on a charm with
    many vendored libs or test fixtures — five thousand-plus
    characters of nested symbols dominate the chat window.  This
    summary surfaces the *top_n* highest-ranked files with a short
    label of what each one defines so the user can scan it in two
    seconds and dig deeper with ``/map full`` if needed.

    Format: one column of file paths, one column of "(N defs)
    primary symbol, ..." derived from the same ordered kinds the
    full renderer uses.  Files with no surfaceable symbols are
    skipped.
    """
    out: list[str] = []
    shown = 0
    for ranking in rankings:
        if shown >= top_n:
            break
        if not ranking.symbols:
            continue
        primaries = _select_symbols(ranking.symbols)
        if not primaries:
            continue
        first = _format_symbol(primaries[0])
        # Trim long signatures so the summary stays one line per file.
        if len(first) > 80:
            first = first[:77] + "..."
        more = len(ranking.symbols) - 1
        suffix = f", +{more} more" if more > 0 else ""
        out.append(f"  {ranking.file}  —  {first}{suffix}")
        shown += 1
    return "\n".join(out)


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
