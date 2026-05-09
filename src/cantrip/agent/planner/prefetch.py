"""Symbol prefetch — Phase 72b.3.

When a task title or user message contains symbol-shaped tokens,
ask the codeintel index for one compact definition / symbol-match
block so a BUILD/DEBUG subagent starts from the right file instead
of burning a turn on navigation.

The whole helper is best-effort:

- The detector applies a stop-list to keep "TODO" / "API" / "URL"
  out of the candidate set, but the *real* false-positive filter is
  the index itself — a candidate that does not produce an
  ``EXACT_QUALIFIED`` or ``EXACT`` match is silently dropped.
- One block per call site, by design.  The phase brief is explicit:
  "the planner *may* prefetch *one* compact definition or symbol-
  match block."  More than one and we are competing with the
  planner's task description for the subagent's attention budget.
- No charm path / no index → returns ``None``.  Callers concatenate
  the result into a task description only when it is truthy.

The algorithm:

1. Tokenise the text with three patterns (dotted, ``snake_case``,
   ``CamelCase``).
2. Filter through the stop-list and a minimum-length floor.
3. Run :meth:`CodeIntelQuery.workspace_symbols` for each survivor.
   Keep only those whose top match is ``EXACT_QUALIFIED`` or
   ``EXACT`` — anything looser is too speculative to ship blind.
4. Pick the most-precise survivor (qualified beats unqualified;
   then by file path then line for stability).
5. Render a short block via :func:`render_definitions` against a
   :meth:`CodeIntelQuery.go_to_definition` lookup so the subagent
   sees both the location and the first few lines of the body.
"""

from __future__ import annotations

import logging
import re

from cantrip.codeintel import (
    CodeIntelQuery,
    SymbolMatch,
    SymbolMatchKind,
)
from cantrip.codeintel.index import render_definitions

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


# Dotted: ``Foo.bar``, ``module.func``, ``self.handler.refresh`` — the
# pattern accepts two or more segments because a single identifier
# already falls under the snake_case / CamelCase rules below, and
# treating ``foo.py`` as a candidate would force every path-shaped
# token through the index.
_DOTTED = re.compile(r"\b[a-zA-Z_][a-zA-Z_0-9]*(?:\.[a-zA-Z_][a-zA-Z_0-9]*)+\b")

# snake_case: at least one underscore + lowercase start so plain
# words like ``intent`` don't qualify.  Leading underscore allowed
# (``_on_install``); trailing underscores are ignored.
_SNAKE = re.compile(r"\b_?[a-z][a-z0-9]+(?:_[a-z0-9]+)+\b")

# CamelCase: at least two capitalised segments so single-word
# capitalisations like ``Charm`` don't qualify.  ``IngressHandler``,
# ``MyCharm``, ``HTTPSAdapter`` all match.
_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]*)+\b")


# Acronyms / common shouting we never want to chase.  Keys are
# uppercase; the lookup lowercases its input.
_STOP_LIST: frozenset[str] = frozenset(
    {
        "todo",
        "fixme",
        "xxx",
        "hack",
        "note",
        "api",
        "url",
        "uri",
        "json",
        "xml",
        "yaml",
        "html",
        "http",
        "https",
        "ssh",
        "tls",
        "ssl",
        "dns",
        "tcp",
        "udp",
        "css",
        "sql",
        "csv",
    }
)


# Below this many code points a candidate is too short to be a
# meaningful symbol — a three-character ``foo`` will collide with too
# many Python builtins to be worth the index hit.
_MIN_TOKEN_LENGTH = 4


def extract_symbol_candidates(text: str) -> list[str]:
    """Return the symbol-shaped tokens found in *text*, deduplicated.

    Preserves source-position order so callers can use the input
    position as an implicit "user-mentioned-it-first" signal when
    breaking ties later.  Within an overlap (``MyCharm._on_install``
    contains the smaller ``MyCharm`` and ``_on_install`` tokens), the
    longer enclosing token is kept and the smaller fragments
    discarded — they would otherwise produce duplicate prefetch
    candidates pointing at the same definition.  The result still
    needs to be filtered through a real codeintel index — the regex
    set is tuned for recall over precision.
    """
    if not text:
        return []
    spans: list[tuple[int, int, str]] = []
    for pattern in (_DOTTED, _SNAKE, _CAMEL):
        for match in pattern.finditer(text):
            token = match.group(0)
            if len(token) < _MIN_TOKEN_LENGTH:
                continue
            if token.lower() in _STOP_LIST:
                continue
            spans.append((match.start(), match.end(), token))
    if not spans:
        return []
    # Order by start position; on a tie, the longer span wins so a
    # later same-start fragment doesn't shadow the dotted enclosing
    # name.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        start, end, _ = span
        # Skip if this span is fully enclosed by an already-kept span
        # at a lower start position (the dotted ``Foo.bar`` swallows
        # the ``Foo`` inside it).
        if any(k_start <= start and end <= k_end for k_start, k_end, _ in kept):
            continue
        kept.append(span)
    seen: set[str] = set()
    out: list[str] = []
    for _, _, token in kept:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# Best-match selection
# ---------------------------------------------------------------------------


# The two layers we trust enough to prefetch.  Anything looser
# (PREFIX, FUZZY) needs a human in the loop to decide whether it is
# the right symbol — the prefetch surface is meant to *short-circuit*
# navigation, not to leak ambiguity into the task brief.
_TRUSTED_KINDS: frozenset[SymbolMatchKind] = frozenset(
    {SymbolMatchKind.EXACT_QUALIFIED, SymbolMatchKind.EXACT}
)


def _best_match(candidate: str, ci: CodeIntelQuery) -> tuple[str, SymbolMatch] | None:
    """Look up *candidate* in the index and return ``(query, match)`` if any.

    Returns ``None`` when the index has no trusted match.  The query
    string is returned alongside the match so ``go_to_definition``
    can run against the same input later (an alias-resolved query
    might differ from the original token).
    """
    matches, _ = ci.workspace_symbols(candidate, limit=3)
    if not matches:
        return None
    top = matches[0]
    if top.match_kind not in _TRUSTED_KINDS:
        return None
    return candidate, top


def _rank(pair: tuple[str, SymbolMatch]) -> tuple[int, int, str, int]:
    """Sort key that surfaces the best match first.

    Precision wins: ``EXACT_QUALIFIED`` outranks ``EXACT`` so a
    fully-qualified ``MyCharm._on_install`` query beats a bare
    ``_on_install``.  Within a precision band, dotted queries
    (``Foo.bar``) outrank single-token queries (``Foo``) because the
    user-supplied scope carries more intent; both can resolve as
    ``EXACT_QUALIFIED`` against the indexer's ``display_name`` field
    (which equals the bare ``name`` for top-level symbols), but the
    dotted form was a more deliberate signal.  Final tie-break on
    file path then line for deterministic output.
    """
    query, match = pair
    precision = 0 if match.match_kind is SymbolMatchKind.EXACT_QUALIFIED else 1
    is_dotted = "." in query
    return precision, 0 if is_dotted else 1, match.symbol.file, match.symbol.line


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def prefetch_symbol_block(
    text: str,
    ci: CodeIntelQuery | None,
    *,
    from_path: str | None = None,
) -> str | None:
    """Return one compact definition block for the best symbol in *text*.

    ``from_path`` rides through to :meth:`CodeIntelQuery.go_to_definition`
    so a tie-break can prefer a definition in the calling file.
    Returns ``None`` when the index is unavailable, when no candidate
    survives the trusted-match filter, or when the chosen candidate
    cannot be resolved to a definition (e.g. the symbol came from a
    YAML file with no line number).
    """
    if ci is None:
        return None
    candidates = extract_symbol_candidates(text)
    if not candidates:
        return None
    pairs: list[tuple[str, SymbolMatch]] = []
    for candidate in candidates:
        try:
            pair = _best_match(candidate, ci)
        except (OSError, RuntimeError) as exc:
            # The index can occasionally raise on a transient I/O error
            # mid-build; logging it and treating the candidate as "no
            # match" keeps the planner moving without a visible failure.
            log.debug("codeintel prefetch lookup failed for %r: %s", candidate, exc)
            continue
        if pair is not None:
            pairs.append(pair)
    if not pairs:
        return None
    pairs.sort(key=_rank)
    chosen_query, chosen_match = pairs[0]
    try:
        result = ci.go_to_definition(chosen_query, from_path=from_path)
    except (OSError, RuntimeError) as exc:
        log.debug("codeintel prefetch definition lookup failed: %s", exc)
        return None
    if not result.matches:
        return None
    rendered = render_definitions(result)
    if not rendered:
        return None
    header = f"## Code intelligence — {chosen_match.symbol.display_name}"
    return f"{header}\n\n{rendered}"


__all__ = [
    "extract_symbol_candidates",
    "prefetch_symbol_block",
]
