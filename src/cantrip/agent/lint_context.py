"""Project-wide lint diagnostics as pre-turn context (Phase 72.4).

Phase 71.4 surfaces ``ruff`` / ``ty`` / ``charmlint`` results *after*
each edit so the agent reacts in the same turn.  This module covers
the complementary case — *before* a turn starts.  Two callers:

* ``/diagnostics`` slash command — the user types it to see what's
  broken right now.
* The subagent dispatcher — when a BUILD or DEBUG task is about to
  launch, the briefing inherits a compact diagnostics block so the
  subagent starts already knowing what's wrong.

Same external tools as Phase 71.4; the runners are imported from
:mod:`cantrip.agent.tools.post_edit_lint` so the wire format
(``ruff check --output-format json``, ``ty check --output-format
concise``, charmlint Rust binary with Python fallback) lives in one
place.  The new piece here is project-wide aggregation, severity
grouping, a token-budget truncation tail, and a 30-second TTL cache
keyed on charm path.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import TYPE_CHECKING

from cantrip.agent.tools.post_edit_lint import (
    DiagnosticsReport,
    FileDiagnostic,
    _run_charmlint,
    _run_ruff,
    _run_ty,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterable

log = logging.getLogger(__name__)

# Severity ordering for grouping and truncation.  Higher = drop later.
_SEVERITY_RANK: dict[str, int] = {"error": 3, "warning": 2, "info": 1}

# Default character cap on the rendered block.  ~6000 chars ≈ 1500
# tokens at the conventional 4-chars-per-token estimate, matching the
# Phase 72.4 spec.  Renderer drops the lowest-severity tail until the
# block fits and reports the count it had to suppress.
DEFAULT_MAX_CHARS: int = 6000

# Cache TTL in seconds.  Spec calls for "repeated ``@problems`` in the
# same turn doesn't re-run the linters" — 30 s covers an interactive
# turn comfortably without trapping stale results across edits.
DEFAULT_CACHE_TTL_SECONDS: float = 30.0

# Subprocess wall clock for the project-wide invocation.  Per-edit
# lint uses 10 s for a single file; project sweeps need more headroom
# because ``ty`` in particular re-walks the dependency graph.
DEFAULT_TIMEOUT_SECONDS: float = 30.0


@dataclasses.dataclass(frozen=True)
class DiagnosticsBlock:
    """An aggregated, truncation-aware view of project diagnostics.

    ``diagnostics`` is the *kept* set after any truncation; ``truncated``
    counts how many additional issues were elided to fit the cap so
    the rendered footer can say "N more suppressed" honestly.
    ``skipped`` propagates the per-tool failure notes from
    :class:`~cantrip.agent.tools.post_edit_lint.DiagnosticsReport` so
    a missing ``ty`` binary doesn't silently look like "all clear".
    """

    diagnostics: tuple[FileDiagnostic, ...] = ()
    skipped: tuple[str, ...] = ()
    truncated: int = 0

    def is_empty(self) -> bool:
        """Return ``True`` when there is nothing for the agent to see."""
        return not self.diagnostics and not self.skipped

    def counts_by_severity(self) -> dict[str, int]:
        """Count kept diagnostics by severity (errors / warnings / info)."""
        counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for d in self.diagnostics:
            counts[d.severity] = counts.get(d.severity, 0) + 1
        return counts

    def to_text(self, *, header: str = "Current diagnostics") -> str:
        """Render the block as a compact, severity-grouped text block.

        Suitable for both the subagent prompt and ``/diagnostics``
        slash output — bold-marker asterisks render plainly in either
        surface and Markdown renderers pick them up as emphasis.
        """
        if self.is_empty():
            return f"{header}: no issues found."

        counts = self.counts_by_severity()
        summary_bits = [
            f"{counts[k]} {k}{'s' if counts[k] != 1 else ''}"
            for k in ("error", "warning", "info")
            if counts[k]
        ]
        summary = ", ".join(summary_bits) if summary_bits else "no kept issues"
        lines: list[str] = [f"{header} ({summary}):"]

        for severity in ("error", "warning", "info"):
            group = [d for d in self.diagnostics if d.severity == severity]
            if not group:
                continue
            lines.append(f"  **{severity}s**:")
            lines.extend(f"    {_format_diagnostic(d)}" for d in group)

        if self.truncated:
            lines.append(
                f"  …{self.truncated} more issue"
                f"{'s' if self.truncated != 1 else ''} suppressed; "
                "run `cantrip lint` for the full list."
            )

        lines.extend(f"  [skipped] {note}" for note in self.skipped)

        return "\n".join(lines)


def _format_diagnostic(d: FileDiagnostic) -> str:
    """Render one diagnostic as ``[tool] path:line:col code message``."""
    location = d.file
    if d.line is not None:
        location = f"{location}:{d.line}"
        if d.column is not None:
            location = f"{location}:{d.column}"
    code = f"{d.code} " if d.code else ""
    return f"[{d.tool}] {location} {code}{d.message}".strip()


def _sort_key(d: FileDiagnostic) -> tuple[int, str, int, str]:
    """Order diagnostics by severity (high first), then file, then line."""
    return (
        -_SEVERITY_RANK.get(d.severity, 0),
        d.file,
        d.line if d.line is not None else 0,
        d.tool,
    )


def _aggregate(reports: Iterable[DiagnosticsReport], *, max_chars: int) -> DiagnosticsBlock:
    """Merge per-tool reports, sort, and truncate to fit *max_chars*.

    Truncation drops the lowest-priority tail (lowest severity, then
    later files) until the rendered text fits.  The dropped count is
    surfaced via :attr:`DiagnosticsBlock.truncated` so callers can
    show "N more suppressed" rather than silently swallowing issues.
    """
    diagnostics: list[FileDiagnostic] = []
    skipped: list[str] = []
    for r in reports:
        diagnostics.extend(r.diagnostics)
        skipped.extend(r.skipped)

    diagnostics.sort(key=_sort_key)

    # Iteratively shrink until the rendered text fits.  Re-rendering
    # each pass is O(n²) but n is small (tens to low hundreds in
    # practice) and the alternative — predictive size accounting —
    # would lie about prefix lines like the summary header.
    truncated = 0
    candidate = DiagnosticsBlock(
        diagnostics=tuple(diagnostics),
        skipped=tuple(skipped),
        truncated=truncated,
    )
    while len(candidate.to_text()) > max_chars and diagnostics:
        diagnostics.pop()
        truncated += 1
        candidate = DiagnosticsBlock(
            diagnostics=tuple(diagnostics),
            skipped=tuple(skipped),
            truncated=truncated,
        )
    return candidate


class DiagnosticsCache:
    """Thread-safe TTL cache keyed on charm path.

    Single-instance: the slash command, the planner, and any tests
    can share one so a ``/diagnostics`` immediately followed by a
    BUILD task spawn doesn't pay for the linters twice.  Uses an
    asyncio-friendly ``time.monotonic`` clock so the TTL doesn't
    drift with wall-clock changes.
    """

    def __init__(self, *, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[pathlib.Path, tuple[float, DiagnosticsBlock]] = {}
        self._lock = asyncio.Lock()

    def _now(self) -> float:
        return time.monotonic()

    async def get(self, key: pathlib.Path) -> DiagnosticsBlock | None:
        """Return the cached block for *key* if still fresh."""
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            timestamp, block = entry
            if self._now() - timestamp > self._ttl:
                # Lazy eviction: keep the cache from growing across
                # long sessions where the user wanders between charms.
                del self._entries[key]
                return None
            return block

    async def put(self, key: pathlib.Path, block: DiagnosticsBlock) -> None:
        """Store *block* against *key* with the current timestamp."""
        async with self._lock:
            self._entries[key] = (self._now(), block)

    async def clear(self) -> None:
        """Drop every entry — useful for tests and ``/diagnostics --refresh``."""
        async with self._lock:
            self._entries.clear()


# Module-level default cache so the slash command and the planner
# share state.  Tests pass an explicit cache to keep state isolated.
_DEFAULT_CACHE = DiagnosticsCache()


def default_cache() -> DiagnosticsCache:
    """Return the process-wide default cache."""
    return _DEFAULT_CACHE


def _python_targets(charm_path: pathlib.Path) -> list[pathlib.Path]:
    """Pick directories worth feeding to ``ruff`` / ``ty``.

    Prefer ``src/`` and ``tests/`` to keep the sweep cheap and avoid
    venvs / build artefacts at the charm root.  Falls back to the
    charm root if neither exists, which covers the early-scaffold
    case where the agent is editing a directory that doesn't yet
    have the conventional layout.
    """
    candidates = [charm_path / "src", charm_path / "tests"]
    existing = [p for p in candidates if p.is_dir()]
    return existing if existing else [charm_path]


def _has_charm_metadata(charm_path: pathlib.Path) -> bool:
    """Return ``True`` if *charm_path* looks like a charm to charmlint.

    Skips the charmlint pass on directories that have no charm
    metadata so a generic Python project doesn't get a confusing
    ``[skipped] charmlint`` note in its diagnostics block.
    """
    return any((charm_path / name).is_file() for name in ("metadata.yaml", "charmcraft.yaml"))


async def gather_project_diagnostics(
    charm_path: pathlib.Path,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cache: DiagnosticsCache | None = None,
    force_refresh: bool = False,
) -> DiagnosticsBlock:
    """Run ``ruff`` + ``ty`` + ``charmlint`` over *charm_path* and aggregate.

    Returns a :class:`DiagnosticsBlock` whose ``to_text()`` is suitable
    for both the slash command output and the subagent briefing.  Tools
    run concurrently; missing binaries, timeouts, and parse failures
    surface as ``skipped`` notes rather than raising — same contract
    as Phase 71.4.

    The result is cached for :data:`DEFAULT_CACHE_TTL_SECONDS` keyed on
    the resolved *charm_path*.  Pass ``force_refresh=True`` (or call
    :meth:`DiagnosticsCache.clear`) to bypass.
    """
    cache = cache if cache is not None else _DEFAULT_CACHE
    key = charm_path.resolve()

    if not force_refresh:
        cached = await cache.get(key)
        if cached is not None:
            return cached

    py_targets = _python_targets(charm_path)
    coros = [
        _run_ruff(py_targets, timeout=timeout),
        _run_ty(py_targets, timeout=timeout),
    ]
    if _has_charm_metadata(charm_path):
        coros.append(_run_charmlint(charm_path, timeout=timeout))

    results = await asyncio.gather(*coros, return_exceptions=True)

    reports: list[DiagnosticsReport] = []
    for outcome in results:
        if isinstance(outcome, BaseException):
            log.warning("Diagnostics task failed: %s", outcome)
            reports.append(DiagnosticsReport(skipped=[f"diagnostics task crashed: {outcome}"]))
            continue
        reports.append(outcome)

    block = _aggregate(reports, max_chars=max_chars)
    await cache.put(key, block)
    return block
