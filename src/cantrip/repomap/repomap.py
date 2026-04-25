"""Repo-map orchestrator — discover files, parse, rank, render, cache."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path

from cantrip.repomap.graph import FileRanking, rank_files
from cantrip.repomap.render import render
from cantrip.repomap.symbols import (
    FileSymbols,
    Symbol,
    SymbolKind,
    is_charm_metadata,
    parse_charm_metadata,
    parse_python_file,
)

log = logging.getLogger(__name__)

#: Default token budget for the rendered map.  Charm repos are
#: smaller than the codebases Aider was tuned for (1000 tokens), but
#: charmlib interfaces and dashboards are worth indexing — 1500 lands
#: between the two extremes.
DEFAULT_TOKEN_BUDGET = 1500

#: When the conversation's context budget is this fraction full, the
#: map shrinks by half to preserve room for real chat.  Matches the
#: 0.80 compaction threshold elsewhere.
_PRESSURE_SHRINK_THRESHOLD = 0.80

#: Above this fraction the map is dropped entirely — the agent is
#: better off compacting than reading another bird's-eye view.
_PRESSURE_DROP_THRESHOLD = 0.95

# Sibling of the session SQLite file at ``<charm>/.cantrip``, matching
# the ``.cantrip-audit.jsonl`` pattern.  Putting the repomap cache
# *inside* ``.cantrip/`` would collide with the SQLite file when the
# charm has an existing session — ``mkdir`` would raise
# FileExistsError on every turn.
_CACHE_FILENAME = ".cantrip-repomap.json"

# Directory names we never descend into when discovering source files,
# matched anywhere in the tree.
_SKIP_DIRECTORIES = {
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

# Relative paths from the charm root that we skip wholesale.
# ``lib/charms/`` holds vendored interface libraries pulled in via
# ``charmcraft fetch-libs`` — third-party code that's API surface but
# not what the author edits.  Indexing them swamps the map (a typical
# charm vendors ten or more libs, each contributing a class for every
# event type it defines) without giving the agent useful navigation
# targets.  ``.cantrip-worktrees/`` holds parallel subagent worktrees
# (Phase 44) and would double-count every symbol.
_SKIP_PATH_PREFIXES = (
    "lib/charms/",
    ".cantrip-worktrees/",
)


@dataclasses.dataclass
class _CacheEntry:
    """One file's parse result plus the mtime it was parsed at."""

    file: str
    mtime_ns: int
    definitions: list[Symbol]
    references: list[str]

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "mtime_ns": self.mtime_ns,
            "definitions": [
                {
                    "name": s.name,
                    "kind": s.kind.value,
                    "file": s.file,
                    "line": s.line,
                    "signature": s.signature,
                    "qualifier": s.qualifier,
                }
                for s in self.definitions
            ],
            "references": list(self.references),
        }

    @classmethod
    def from_dict(cls, data: dict) -> _CacheEntry:
        return cls(
            file=data["file"],
            mtime_ns=int(data["mtime_ns"]),
            definitions=[
                Symbol(
                    name=d["name"],
                    kind=SymbolKind(d["kind"]),
                    file=d["file"],
                    line=int(d.get("line", 0)),
                    signature=d.get("signature", ""),
                    qualifier=d.get("qualifier", ""),
                )
                for d in data.get("definitions", [])
            ],
            references=list(data.get("references", [])),
        )


class RepoMap:
    """Build, cache, and render a graph-ranked map of a charm repo.

    Lifecycle:
        * :meth:`build` (re)parses any source file whose mtime has
          changed, runs PageRank over the resulting graph, and caches
          the per-file parse results to ``.cantrip/repomap.json``.
        * :meth:`render_for_prompt` returns the rendered text bounded
          by a token budget, automatically shrinking under pressure.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._token_budget = token_budget
        # Per-file parse cache, keyed by relative POSIX path.
        self._entries: dict[str, _CacheEntry] = {}
        self._rankings: list[FileRanking] = []
        self._loaded_from_disk = False
        self._last_built_at: float | None = None

    # -- public surface ------------------------------------------------

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def rankings(self) -> list[FileRanking]:
        return list(self._rankings)

    def build(self, *, force: bool = False) -> list[FileRanking]:
        """Refresh the map.  Re-parses only files whose mtime changed.

        ``force=True`` re-parses everything and discards any cache —
        the ``/map-refresh`` slash command sets it.
        """
        if force:
            self._entries.clear()
            self._loaded_from_disk = False
        elif not self._loaded_from_disk:
            self._load_cache()
            self._loaded_from_disk = True

        seen: set[str] = set()
        for path in self._discover_files():
            try:
                mtime_ns = path.stat().st_mtime_ns
            except OSError as exc:
                log.debug("repomap: stat failed for %s: %s", path, exc)
                continue
            rel = self._relative(path)
            seen.add(rel)
            cached = self._entries.get(rel)
            if cached is not None and cached.mtime_ns == mtime_ns and not force:
                continue
            symbols = self._parse_one(path)
            self._entries[rel] = _CacheEntry(
                file=rel,
                mtime_ns=mtime_ns,
                definitions=symbols.definitions,
                references=symbols.references,
            )
        # Drop entries for files that have disappeared.
        for stale in set(self._entries) - seen:
            del self._entries[stale]

        files = [
            FileSymbols(
                file=entry.file,
                definitions=list(entry.definitions),
                references=list(entry.references),
            )
            for entry in self._entries.values()
        ]
        self._rankings = rank_files(files)
        self._last_built_at = time.time()
        self._save_cache()
        return list(self._rankings)

    def render_for_prompt(
        self,
        *,
        context_pressure: float | None = None,
    ) -> str:
        """Render the map for injection into the system prompt.

        ``context_pressure`` is the fraction of the conversation's
        context window already consumed (0.0 = fresh session, 1.0 =
        full).  Above 0.80 the map shrinks by half; above 0.95 it
        drops entirely so the agent isn't carrying a bird's-eye view
        into a near-full window.
        """
        if not self._rankings:
            return ""
        budget = self._budget_for_pressure(context_pressure)
        if budget <= 0:
            return ""
        return render(self._rankings, token_budget=budget)

    def render_full(self) -> str:
        """Render the map at the full configured budget — used by ``/map``."""
        if not self._rankings:
            return ""
        return render(self._rankings, token_budget=self._token_budget)

    # -- internals -----------------------------------------------------

    def _budget_for_pressure(self, pressure: float | None) -> int:
        if pressure is None:
            return self._token_budget
        if pressure >= _PRESSURE_DROP_THRESHOLD:
            return 0
        if pressure >= _PRESSURE_SHRINK_THRESHOLD:
            return max(1, self._token_budget // 2)
        return self._token_budget

    def _parse_one(self, path: Path) -> FileSymbols:
        if path.suffix == ".py":
            return parse_python_file(path, repo_root=self._repo_root)
        if is_charm_metadata(path):
            return parse_charm_metadata(path, repo_root=self._repo_root)
        return FileSymbols(file=self._relative(path))

    def _discover_files(self) -> list[Path]:
        results: list[Path] = []
        for path in _walk(self._repo_root, _SKIP_DIRECTORIES):
            if path.suffix != ".py" and not is_charm_metadata(path):
                continue
            rel = self._relative(path)
            if any(rel.startswith(prefix) for prefix in _SKIP_PATH_PREFIXES):
                continue
            results.append(path)
        results.sort()
        return results

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._repo_root).as_posix()
        except ValueError:
            return path.as_posix()

    # -- cache ---------------------------------------------------------

    def _cache_path(self) -> Path:
        return self._repo_root / _CACHE_FILENAME

    def _load_cache(self) -> None:
        path = self._cache_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.debug("repomap: cache load failed (%s); rebuilding", exc)
            return
        for entry in data.get("entries", []):
            try:
                cached = _CacheEntry.from_dict(entry)
            except (KeyError, ValueError) as exc:
                log.debug("repomap: skipping malformed cache entry: %s", exc)
                continue
            self._entries[cached.file] = cached

    def _save_cache(self) -> None:
        path = self._cache_path()
        payload = {
            "version": 1,
            "generated_at": self._last_built_at,
            "entries": [entry.to_dict() for entry in self._entries.values()],
        }
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            log.debug("repomap: cannot write cache %s: %s", path, exc)


def _walk(root: Path, skip: set[str]) -> list[Path]:
    """Recursive walk that prunes by directory name."""
    if not root.exists():
        return []
    out: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except (OSError, PermissionError) as exc:
            log.debug("repomap: cannot list %s: %s", current, exc)
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
