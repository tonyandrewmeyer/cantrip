"""Code-intelligence indexer + query API.

Builds an in-memory index over the same Python / charm-metadata files
:mod:`cantrip.repomap` parses, then answers exact queries:

    workspace_symbols(query, *, path_scope, kinds, limit)
    go_to_definition(symbol, *, from_path)
    find_references(symbol, *, from_path, include_definition, limit)

Match policy is deterministic: exact qualified-name match first
(``MyCharm._on_install`` matches only that exact pair), then exact
unqualified (``_on_install`` matches every method by that name), then
prefix, then case-insensitive substring.  Ambiguous hits are surfaced
in :attr:`DefinitionResult.matches` rather than silently picking one.

Persistence: ``.cantrip-codeintel.json`` next to the session SQLite
file, keyed by ``mtime_ns`` so re-parses only touch files that
changed.  The cache stores the same per-file shape as the in-memory
:class:`~cantrip.repomap.symbols.FileSymbols` so a cold start can skip
parsing entirely when nothing has moved.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import pathlib
import time
import typing
from collections.abc import Iterable, Sequence

from cantrip.repomap.symbols import (
    FileSymbols,
    ReferenceLocation,
    Symbol,
    SymbolKind,
    is_charm_metadata,
    parse_charm_metadata,
    parse_python_file,
)

log = logging.getLogger(__name__)


# Sibling of the session SQLite file.  Keeping repomap and codeintel
# caches separate means the repomap snapshot can ship independently
# (it persists today) and codeintel can evolve its schema without
# colliding with repomap's compatibility story.
_CACHE_FILENAME = ".cantrip-codeintel.json"

# Schema version baked into the cache file.  Mismatches cause a quiet
# rebuild rather than a load error so older sessions stay usable.
_CACHE_VERSION = 1

# Same skip-rules as repomap.  Duplicated rather than imported because
# repomap's constants are private and tying the two together would
# couple them unnecessarily; the lists rarely change and a divergence
# would be loud (codeintel results would just include or exclude a
# vendored directory).
_SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
        "site-packages",
        ".cantrip",
        ".tox",
        "htmlcov",
    }
)

_SKIP_PATH_PREFIXES: tuple[str, ...] = (
    "lib/charms/",
    ".cantrip-worktrees/",
)

# Default snippet windows.  ``go_to_definition`` returns a small
# bounded slice around the def line so the model can decide whether
# the match is the right one without a follow-up read; the
# multi-method default of three lines either side keeps the slice
# under ~10 lines for most signatures while still showing the body's
# first statement.
_DEFINITION_SNIPPET_BEFORE = 0
_DEFINITION_SNIPPET_AFTER = 6

# Cap on workspace_symbols / find_references results.  Beyond this
# the response truncates with an honest count of how many were
# elided rather than streaming the entire repo into the prompt.
_DEFAULT_RESULT_LIMIT = 50
_ABSOLUTE_RESULT_LIMIT = 200


class SymbolMatchKind(enum.StrEnum):
    """How a workspace_symbols / definition query matched.

    Reported back to the caller so a downstream tool can decide whether
    the answer is precise enough to act on.  The order from most- to
    least-precise is also the search order: exact qualified beats
    exact unqualified beats prefix beats fuzzy.
    """

    EXACT_QUALIFIED = "exact_qualified"
    EXACT = "exact"
    PREFIX = "prefix"
    FUZZY = "fuzzy"


@dataclasses.dataclass(frozen=True)
class SymbolMatch:
    """One workspace_symbols hit.

    ``match_kind`` is how the symbol matched the query — useful for
    sorting and for the renderer's preamble ("3 exact matches plus
    12 fuzzy candidates").
    """

    symbol: Symbol
    match_kind: SymbolMatchKind = SymbolMatchKind.EXACT


@dataclasses.dataclass(frozen=True)
class Definition:
    """One go_to_definition result: the defining symbol plus a snippet."""

    symbol: Symbol
    snippet: str
    snippet_start_line: int  # 1-based first line of the snippet, or 0 if absent.


@dataclasses.dataclass(frozen=True)
class DefinitionResult:
    """Go-to-definition response.

    ``matches`` is a tuple so a caller can detect ambiguity: a single
    entry is the definitive answer; two or more is "ambiguous —
    here are all the candidates."  ``semantic`` is ``True`` when the
    answer came from the parsed index, ``False`` when codeintel had
    to fall back to a literal text search (or did not find anything
    at all).
    """

    query: str
    matches: tuple[Definition, ...]
    semantic: bool
    match_kind: SymbolMatchKind | None = None
    note: str = ""


@dataclasses.dataclass(frozen=True)
class ReferencesResult:
    """Find-references response."""

    query: str
    locations: tuple[ReferenceLocation, ...]
    truncated: int  # Number of additional locations not included.
    semantic: bool
    candidates: tuple[Symbol, ...]
    note: str = ""


# ---------------------------------------------------------------------------
# In-memory file record + cache helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FileRecord:
    """Mutable per-file index entry held in memory and on disk."""

    file: str
    mtime_ns: int
    definitions: list[Symbol]
    reference_locations: list[ReferenceLocation]
    import_aliases: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "mtime_ns": self.mtime_ns,
            "definitions": [_symbol_to_dict(s) for s in self.definitions],
            "references": [_reflocation_to_dict(r) for r in self.reference_locations],
            "import_aliases": dict(self.import_aliases),
        }

    @classmethod
    def from_dict(cls, data: dict) -> _FileRecord:
        return cls(
            file=data["file"],
            mtime_ns=int(data["mtime_ns"]),
            definitions=[_symbol_from_dict(d) for d in data.get("definitions", [])],
            reference_locations=[_reflocation_from_dict(r) for r in data.get("references", [])],
            import_aliases=dict(data.get("import_aliases", {})),
        )


def _symbol_to_dict(s: Symbol) -> dict:
    return {
        "name": s.name,
        "kind": s.kind.value,
        "file": s.file,
        "line": s.line,
        "signature": s.signature,
        "qualifier": s.qualifier,
    }


def _symbol_from_dict(data: dict) -> Symbol:
    return Symbol(
        name=data["name"],
        kind=SymbolKind(data["kind"]),
        file=data["file"],
        line=int(data.get("line", 0)),
        signature=data.get("signature", ""),
        qualifier=data.get("qualifier", ""),
    )


def _reflocation_to_dict(r: ReferenceLocation) -> dict:
    return {"name": r.name, "file": r.file, "line": r.line}


def _reflocation_from_dict(data: dict) -> ReferenceLocation:
    return ReferenceLocation(
        name=data["name"],
        file=data["file"],
        line=int(data.get("line", 0)),
    )


# ---------------------------------------------------------------------------
# Query protocol — Phase 72b.4 adapter seam
# ---------------------------------------------------------------------------


@typing.runtime_checkable
class CodeIntelQuery(typing.Protocol):
    """Read-only query surface shared by indexer + future adapters.

    The default :class:`CodeIntel` implementation answers from the
    in-process AST-derived index.  A future optional adapter (e.g.
    one-shot ``pyright`` or ``yaml-language-server`` enrichment for
    tricky cases) implements this same Protocol either as a
    replacement for, or as a wrapper around, :class:`CodeIntel` —
    delegating to the indexer when no semantic match is available.
    The adapter itself is out of scope here; the seam is the contract
    that lets one slot in without touching tool / slash / @-provider
    call sites.
    """

    @property
    def repo_root(self) -> pathlib.Path: ...

    def build(self, *, force: bool = False) -> None: ...

    def workspace_symbols(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        kinds: Sequence[SymbolKind] | None = None,
        limit: int = _DEFAULT_RESULT_LIMIT,
    ) -> tuple[list[SymbolMatch], int]: ...

    def go_to_definition(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
    ) -> DefinitionResult: ...

    def find_references(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
        include_definition: bool = False,
        limit: int = _DEFAULT_RESULT_LIMIT,
    ) -> ReferencesResult: ...


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class CodeIntel:
    """Build, cache, and query a read-only code-intelligence index.

    Lifecycle mirrors :class:`cantrip.repomap.repomap.RepoMap`:

        * :meth:`build` (re)parses any source file whose mtime has
          changed and persists the per-file records to
          ``.cantrip-codeintel.json``.
        * :meth:`workspace_symbols`, :meth:`go_to_definition`, and
          :meth:`find_references` answer queries from the in-memory
          index.

    Thread safety: the indexer is *not* thread-safe; it expects the
    same single-task discipline the rest of the agent loop follows.
    Concurrent ``build`` calls would race on the cache file.
    """

    def __init__(self, repo_root: pathlib.Path) -> None:
        self._repo_root = pathlib.Path(repo_root).resolve()
        self._records: dict[str, _FileRecord] = {}
        self._loaded_from_disk = False
        self._last_built_at: float | None = None
        # Aggregated per-name index for fast lookup.  Populated by
        # ``_rebuild_indexes`` after every successful ``build``.
        self._by_name: dict[str, list[Symbol]] = {}
        self._refs_by_name: dict[str, list[ReferenceLocation]] = {}

    # -- public surface ------------------------------------------------

    @property
    def repo_root(self) -> pathlib.Path:
        return self._repo_root

    def build(self, *, force: bool = False) -> None:
        """Refresh the index.  Re-parses only files whose mtime changed.

        ``force=True`` discards the cache and re-parses every file —
        used by the ``/symbols-refresh`` future surface and by
        whichever invalidation path the agent grows for "I just wrote
        a script that the cache won't have noticed."
        """
        if force:
            self._records.clear()
            self._loaded_from_disk = False
        elif not self._loaded_from_disk:
            self._load_cache()
            self._loaded_from_disk = True

        seen: set[str] = set()
        for path in self._discover_files():
            try:
                mtime_ns = path.stat().st_mtime_ns
            except OSError as exc:
                log.debug("codeintel: stat failed for %s: %s", path, exc)
                continue
            rel = self._relative(path)
            seen.add(rel)
            cached = self._records.get(rel)
            if cached is not None and cached.mtime_ns == mtime_ns and not force:
                continue
            symbols = self._parse_one(path)
            self._records[rel] = _FileRecord(
                file=rel,
                mtime_ns=mtime_ns,
                definitions=list(symbols.definitions),
                reference_locations=list(symbols.reference_locations),
                import_aliases=dict(symbols.import_aliases),
            )
        # Drop records for files that have disappeared.
        for stale in set(self._records) - seen:
            del self._records[stale]

        self._rebuild_indexes()
        self._last_built_at = time.time()
        self._save_cache()

    def workspace_symbols(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        kinds: Sequence[SymbolKind] | None = None,
        limit: int = _DEFAULT_RESULT_LIMIT,
    ) -> tuple[list[SymbolMatch], int]:
        """Return symbols matching *query*, plus how many were elided.

        The match policy is deterministic and layered:

        1. **Exact qualified** — ``MyCharm._on_install``: returns only
           the symbol whose ``display_name`` equals the query.
        2. **Exact unqualified** — ``_on_install``: returns every
           symbol whose bare ``name`` equals the query.
        3. **Prefix** (case-insensitive) — ``_on_inst``.
        4. **Fuzzy** (substring) — last-resort fallback.

        Each subsequent layer fires only when the previous layer has
        no hits, so ``workspace_symbols("Foo")`` doesn't drown a
        precise hit in fuzzy matches.  Ambiguity within a layer
        (multiple ``_on_install`` methods in different classes) is
        preserved — the caller is expected to surface candidates.

        ``path_scope`` filters to files whose relative POSIX path
        starts with that prefix.  ``kinds`` restricts to specific
        :class:`SymbolKind` values.  ``limit`` is capped at
        :data:`_ABSOLUTE_RESULT_LIMIT`.
        """
        capped = min(max(1, limit), _ABSOLUTE_RESULT_LIMIT)
        matches = self._collect_matches(query, path_scope=path_scope, kinds=kinds)
        if not matches:
            return [], 0
        truncated = max(0, len(matches) - capped)
        return matches[:capped], truncated

    def go_to_definition(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
    ) -> DefinitionResult:
        """Resolve *symbol* to its defining file/line plus a snippet.

        ``from_path`` is currently only used for tie-breaking among
        equally-precise matches — when several definitions match, a
        symbol defined in ``from_path`` ranks first.  More aggressive
        scope-aware resolution (import aliases, lexical scoping) is
        a follow-up; the current heuristic is enough for the common
        "where is :pyfunc:`make_layer` defined?" case while staying
        honest about ambiguity.
        """
        normalised = symbol.strip()
        if not normalised:
            return DefinitionResult(query=symbol, matches=(), semantic=False, note="empty query")
        # Resolve any import alias on the *from* file before searching
        # so ``go_to_definition('jubilant')`` from a file that did
        # ``import jubilant as j`` and uses it as ``j.deploy`` still
        # finds ``jubilant``.  Aliases are direction-only (alias ->
        # original); we never alias-rewrite the query directly.
        candidates = self._collect_matches(normalised, path_scope=None, kinds=None)
        if not candidates:
            # Try the alias map: ``j`` -> ``jubilant`` from the calling
            # file's imports.  Cheap to fold in and avoids surprising
            # nulls when the caller used a local rename.
            if from_path is not None:
                aliased = self._records.get(from_path)
                if aliased is not None:
                    target = aliased.import_aliases.get(normalised)
                    if target:
                        # ``from src.handlers import build_layer as bl``
                        # records ``bl -> src.handlers.build_layer``;
                        # the codeintel index keys on the leaf
                        # symbol name, so the leaf is what resolves.
                        # ``import foo as f`` records ``f -> foo`` —
                        # leaf and head coincide and the same lookup
                        # works.
                        leaf = target.rsplit(".", 1)[-1]
                        candidates = self._collect_matches(leaf, path_scope=None, kinds=None)
            if not candidates:
                return DefinitionResult(
                    query=symbol,
                    matches=(),
                    semantic=False,
                    note="no semantic match",
                )
        # Tie-break: definitions in ``from_path`` rank first when the
        # caller passed one and the layer's match_kind is a tie.
        if from_path is not None:
            candidates.sort(
                key=lambda m: (
                    0 if m.symbol.file == from_path else 1,
                    m.symbol.file,
                    m.symbol.line,
                )
            )
        match_kind = candidates[0].match_kind
        defs = tuple(
            Definition(
                symbol=match.symbol,
                snippet=snippet,
                snippet_start_line=start,
            )
            for match in candidates
            for snippet, start in (self._render_snippet(match.symbol),)
        )
        note = "" if len(defs) == 1 else f"{len(defs)} candidates — ambiguous"
        return DefinitionResult(
            query=symbol,
            matches=defs,
            semantic=True,
            match_kind=match_kind,
            note=note,
        )

    def find_references(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
        include_definition: bool = False,
        limit: int = _DEFAULT_RESULT_LIMIT,
    ) -> ReferencesResult:
        """Return every recorded reference to *symbol*.

        ``include_definition`` adds the defining symbol's file/line as
        an extra location at the head of the list — useful for tools
        that want to render "1 definition + N references" together.
        ``from_path`` is informational only at the moment (records
        are file-scoped already).
        """
        del from_path  # Reserved for future scope-aware resolution.
        normalised = symbol.strip()
        if not normalised:
            return ReferencesResult(
                query=symbol,
                locations=(),
                truncated=0,
                semantic=False,
                candidates=(),
                note="empty query",
            )
        # Strip leading ``self.``/``cls.`` so a query like ``self.foo``
        # resolves to references to ``foo``.  This is a heuristic, not
        # a guarantee — a literal attribute named ``self`` would still
        # be treated as the prefix.
        leaf = normalised
        for prefix in ("self.", "cls."):
            if leaf.startswith(prefix):
                leaf = leaf[len(prefix) :]
                break
        # Take the trailing dotted segment for ``Foo.bar`` queries —
        # the reference index keys on the leaf ``bar``.
        if "." in leaf:
            leaf = leaf.rsplit(".", 1)[-1]

        locations = list(self._refs_by_name.get(leaf, ()))
        candidates = tuple(self._by_name.get(leaf, ()))
        if include_definition:
            for sym in candidates:
                if sym.line:
                    locations.insert(
                        0,
                        ReferenceLocation(
                            name=sym.name,
                            file=sym.file,
                            line=sym.line,
                        ),
                    )
        if not locations:
            return ReferencesResult(
                query=symbol,
                locations=(),
                truncated=0,
                semantic=False,
                candidates=candidates,
                note="no semantic match",
            )
        capped = min(max(1, limit), _ABSOLUTE_RESULT_LIMIT)
        # Stable order: file, then line, then name (so :class:`Foo` and
        # :func:`foo` next to each other on the same line don't flap).
        locations.sort(key=lambda r: (r.file, r.line, r.name))
        truncated = max(0, len(locations) - capped)
        note = ""
        if len(candidates) > 1:
            note = f"ambiguous: {len(candidates)} candidate symbols share this name"
        elif not candidates:
            # Reference index hit but no definition hit: typical for
            # builtins (``len``, ``print``) or for symbols defined
            # outside the indexed languages.
            note = "no definition in index"
        return ReferencesResult(
            query=symbol,
            locations=tuple(locations[:capped]),
            truncated=truncated,
            semantic=True,
            candidates=candidates,
            note=note,
        )

    # -- internals ----------------------------------------------------

    def _collect_matches(
        self,
        query: str,
        *,
        path_scope: str | None,
        kinds: Sequence[SymbolKind] | None,
    ) -> list[SymbolMatch]:
        """Run the layered match policy and return matches.

        Returns the *first* non-empty layer's results — once an exact
        qualified match exists, prefix and fuzzy results are
        suppressed so the caller doesn't drown a precise answer in
        noise.  Within a layer, results are sorted by file then line
        for deterministic output.
        """
        kinds_set = set(kinds) if kinds else None
        all_symbols = self._iter_symbols(path_scope=path_scope, kinds=kinds_set)

        exact_qualified: list[Symbol] = []
        exact: list[Symbol] = []
        prefix: list[Symbol] = []
        fuzzy: list[Symbol] = []

        lowered = query.lower()
        for sym in all_symbols:
            if sym.display_name == query:
                exact_qualified.append(sym)
                continue
            if sym.name == query:
                exact.append(sym)
                continue
            if sym.name.lower().startswith(lowered):
                prefix.append(sym)
                continue
            if lowered in sym.name.lower():
                fuzzy.append(sym)

        layer = (
            (SymbolMatchKind.EXACT_QUALIFIED, exact_qualified)
            if exact_qualified
            else (SymbolMatchKind.EXACT, exact)
            if exact
            else (SymbolMatchKind.PREFIX, prefix)
            if prefix
            else (SymbolMatchKind.FUZZY, fuzzy)
        )
        kind, picks = layer
        picks.sort(key=lambda s: (s.file, s.line, s.display_name))
        return [SymbolMatch(symbol=s, match_kind=kind) for s in picks]

    def _iter_symbols(
        self,
        *,
        path_scope: str | None,
        kinds: set[SymbolKind] | None,
    ) -> Iterable[Symbol]:
        for record in self._records.values():
            if path_scope and not record.file.startswith(path_scope):
                continue
            for sym in record.definitions:
                if kinds is not None and sym.kind not in kinds:
                    continue
                yield sym

    def _rebuild_indexes(self) -> None:
        """Refresh the per-name lookup tables from ``self._records``.

        Called after :meth:`build` finishes.  The aggregation cost is
        linear in total symbol count; on a big charm repo this is well
        under a millisecond and the lookup paths read from the result.
        """
        by_name: dict[str, list[Symbol]] = {}
        refs: dict[str, list[ReferenceLocation]] = {}
        for record in self._records.values():
            for sym in record.definitions:
                by_name.setdefault(sym.name, []).append(sym)
            for ref in record.reference_locations:
                refs.setdefault(ref.name, []).append(ref)
        self._by_name = by_name
        self._refs_by_name = refs

    def _render_snippet(self, sym: Symbol) -> tuple[str, int]:
        """Read a small bounded slice around *sym.line* and return ``(text, start_line)``.

        Returns ``("", 0)`` when the file cannot be read or the symbol
        has no recorded line (YAML-derived definitions sit at line 0
        because PyYAML loses position by default).  Snippet rendering
        is best-effort by design; the caller should treat an empty
        snippet as "open the file yourself" rather than as an error.
        """
        if sym.line <= 0:
            return "", 0
        full_path = self._repo_root / sym.file
        try:
            lines = full_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            log.debug("codeintel: cannot read %s: %s", full_path, exc)
            return "", 0
        start = max(0, sym.line - 1 - _DEFINITION_SNIPPET_BEFORE)
        end = min(len(lines), sym.line + _DEFINITION_SNIPPET_AFTER)
        return "\n".join(lines[start:end]), start + 1

    def _parse_one(self, path: pathlib.Path) -> FileSymbols:
        if path.suffix == ".py":
            return parse_python_file(path, repo_root=self._repo_root)
        if is_charm_metadata(path):
            return parse_charm_metadata(path, repo_root=self._repo_root)
        return FileSymbols(file=self._relative(path))

    def _discover_files(self) -> list[pathlib.Path]:
        results: list[pathlib.Path] = []
        for path in _walk(self._repo_root, _SKIP_DIRECTORIES):
            if path.suffix != ".py" and not is_charm_metadata(path):
                continue
            rel = self._relative(path)
            if any(rel.startswith(prefix) for prefix in _SKIP_PATH_PREFIXES):
                continue
            results.append(path)
        results.sort()
        return results

    def _relative(self, path: pathlib.Path) -> str:
        try:
            return path.resolve().relative_to(self._repo_root).as_posix()
        except ValueError:
            return path.as_posix()

    # -- cache ---------------------------------------------------------

    def _cache_path(self) -> pathlib.Path:
        return self._repo_root / _CACHE_FILENAME

    def _load_cache(self) -> None:
        path = self._cache_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("codeintel: cache load failed (%s); rebuilding", exc)
            return
        if int(data.get("version", 0)) != _CACHE_VERSION:
            return
        for entry in data.get("entries", []):
            try:
                record = _FileRecord.from_dict(entry)
            except (KeyError, ValueError) as exc:
                log.debug("codeintel: skipping malformed cache entry: %s", exc)
                continue
            self._records[record.file] = record

    def _save_cache(self) -> None:
        path = self._cache_path()
        payload = {
            "version": _CACHE_VERSION,
            "generated_at": self._last_built_at,
            "entries": [record.to_dict() for record in self._records.values()],
        }
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            log.debug("codeintel: cannot write cache %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Walk helper — duplicated from repomap to keep the two stacks decoupled.
# ---------------------------------------------------------------------------


def _walk(root: pathlib.Path, skip: frozenset[str]) -> list[pathlib.Path]:
    """Recursive walk that prunes by directory name."""
    if not root.exists():
        return []
    out: list[pathlib.Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except (OSError, PermissionError) as exc:
            log.debug("codeintel: cannot list %s: %s", current, exc)
            continue
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name in skip:
                    continue
                stack.append(child)
            elif child.is_file():
                out.append(child)
    return out


# ---------------------------------------------------------------------------
# Plain-text rendering helpers used by tools / slash commands / providers.
# ---------------------------------------------------------------------------


def render_symbols(matches: Sequence[SymbolMatch], *, truncated: int = 0) -> str:
    """Render workspace_symbols hits as one line per symbol.

    Format: ``kind  qualified_name  signature  (file:line)``.  Empty
    output when *matches* is empty so the caller can switch to a
    "no matches" message instead of printing a header on its own.
    """
    if not matches:
        return ""
    lines: list[str] = []
    width = max(len(m.symbol.kind.value) for m in matches)
    for match in matches:
        sym = match.symbol
        kind = sym.kind.value.ljust(width)
        position = f"{sym.file}:{sym.line}" if sym.line else sym.file
        sig = f" {sym.signature}" if sym.signature else ""
        lines.append(f"{kind}  {sym.display_name}{sig}  ({position})")
    if truncated:
        lines.append(f"… {truncated} more elided")
    return "\n".join(lines)


def render_definitions(result: DefinitionResult) -> str:
    """Render a DefinitionResult as a multi-block string.

    Each match becomes ``file:line`` header followed by a fenced
    snippet.  Ambiguity (more than one match) is announced in the
    leading line so the caller does not silently treat the first hit
    as authoritative.
    """
    if not result.matches:
        return f"No definition found for {result.query!r}."
    out: list[str] = []
    if len(result.matches) > 1:
        out.append(f"{len(result.matches)} candidate definitions for {result.query!r}:")
    for definition in result.matches:
        sym = definition.symbol
        position = f"{sym.file}:{sym.line}" if sym.line else sym.file
        header = f"{sym.kind.value} {sym.display_name}{(' ' + sym.signature) if sym.signature else ''} ({position})"
        out.append(header)
        if definition.snippet:
            out.append("```")
            out.append(definition.snippet)
            out.append("```")
    return "\n".join(out)


def render_references(result: ReferencesResult) -> str:
    """Render a ReferencesResult as one location per line."""
    if not result.locations:
        return f"No references found for {result.query!r}."
    out: list[str] = []
    for ref in result.locations:
        position = f"{ref.file}:{ref.line}" if ref.line else ref.file
        out.append(f"{position}  {ref.name}")
    if result.truncated:
        out.append(f"… {result.truncated} more elided")
    if result.note:
        out.append(f"({result.note})")
    return "\n".join(out)


# Cross-module helpers for plumbing-free rendering.  Public so the
# tool / slash-command / @-provider layers can share one renderer.
__all__ = [
    "CodeIntel",
    "CodeIntelQuery",
    "Definition",
    "DefinitionResult",
    "ReferencesResult",
    "SymbolMatch",
    "SymbolMatchKind",
    "render_definitions",
    "render_references",
    "render_symbols",
]
