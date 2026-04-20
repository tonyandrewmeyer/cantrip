"""Best-of-N multi-model racing for high-value tasks.

Runs N candidate subagents in parallel — each in its own git worktree,
each with a different model pairing — and picks the highest-scored
candidate to merge back into the main tree.  Opt-in per ``TaskCategory``
via :class:`RaceConfig`; the default config disables racing so a
single-model run remains the norm.

Scoring combines charmlint violation counts (weighted by severity),
operational-readiness percentage, and diff size (smaller diffs score
higher, penalising unnecessary churn).  Candidates whose subagents
failed or no-oped score 0 regardless of the other signals so a
non-starter can never win the race.

This module is a library — it does not wire itself into the executor.
The executor integration and the ``/arena`` slash command land in
follow-up commits once the scoring rubric has been validated against
real charm builds.

See ROADMAP.md Phase 47 for the full design rationale.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import pathlib
import subprocess
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from cantrip.agent.queue import TaskCategory
from cantrip.agent.subagent import ExitState

if TYPE_CHECKING:
    from cantrip.agent.subagent import Subagent, SubagentResult
    from cantrip.agent.worktree import WorktreeAllocator, WorktreeHandle
    from cantrip.llm import base as llm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

# Weights sum to 1.0.  Charmlint and readiness each carry 30 % because they
# are the most load-bearing quality signals for a built charm; unit tests
# add 25 %; diff size is a 15 % tie-breaker that nudges the winner toward
# smaller, more focused changes.  Tune these in one place rather than
# scattering magic numbers through the scoring body.
_W_CHARMLINT = 0.30
_W_READINESS = 0.30
_W_TESTS = 0.25
_W_DIFF = 0.15

# Weighted charmlint penalty per severity.  Errors hurt the most because
# they are usually spec violations that break generated charms; warnings
# matter but can ship; infos are advisory.
_CHARMLINT_SEVERITY_WEIGHT: dict[str, float] = {
    "error": 3.0,
    "warning": 1.0,
    "info": 0.1,
}

# Charmlint decay constant: a weighted-penalty of this value maps to
# e⁻¹ ≈ 0.37 on the subscore.  Tuned so a candidate with no errors but a
# handful of warnings still scores well above 0.5, while a candidate with
# several errors drops below 0.3.
_CHARMLINT_DECAY = 10.0

# Diff sizes above this cap get the same penalty — a 2500-line diff is no
# worse than a 2000-line diff for the purposes of tie-breaking.
_DIFF_CAP_LINES = 2000

# A candidate that completed but produced a zero-line diff is suspicious
# (might have committed nothing) — give it a middling diff subscore
# rather than a perfect one so charmlint and readiness decide the winner.
_NO_DIFF_SUBSCORE = 0.5

# A candidate is ``is_perfect`` when its total reaches this threshold;
# used by the coordinator to cancel other candidates early when enabled.
_PERFECT_THRESHOLD = 0.999


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CandidateSpec:
    """One entrant in a race: identifier plus the provider pair driving it.

    ``candidate_id`` should be short and filesystem-safe — it ends up in a
    git branch name and a worktree path.  Typical values: ``"opus"``,
    ``"sonnet"``, ``"gemini-pro"``.
    """

    candidate_id: str
    provider: llm.LLMProvider
    light_provider: llm.LLMProvider | None = None


@dataclasses.dataclass(frozen=True)
class CandidateScore:
    """Numeric score for a single race candidate.

    ``total`` is in ``[0.0, 1.0]`` so scores are comparable across a pool
    even when different candidates hit different test counts.
    ``exit_state`` short-circuits to zero for failed or no-op runs: those
    are not viable winners regardless of how well the other signals look.
    """

    candidate_id: str
    exit_state: ExitState
    total: float
    charmlint_errors: int = 0
    charmlint_warnings: int = 0
    charmlint_infos: int = 0
    readiness_pct: int | None = None
    unit_tests_passed: int = 0
    unit_tests_total: int = 0
    diff_lines_added: int = 0
    diff_lines_removed: int = 0
    error: str | None = None

    @property
    def diff_lines(self) -> int:
        """Total lines touched (added + removed)."""
        return self.diff_lines_added + self.diff_lines_removed

    @property
    def is_viable(self) -> bool:
        """True when this candidate is allowed to win.

        Failed and no-op runs cannot win — they produced nothing useful.
        Blocked runs are still viable because they may have produced
        partial progress worth merging while the user resolves the block.
        """
        return self.exit_state in (ExitState.COMPLETED, ExitState.BLOCKED)

    @property
    def is_perfect(self) -> bool:
        """True when the total is at or above the perfect-cancel threshold."""
        return self.total >= _PERFECT_THRESHOLD


@dataclasses.dataclass(frozen=True)
class CandidateOutcome:
    """Per-candidate run artefacts before scoring.

    ``result`` is ``None`` when the candidate's subagent crashed outright;
    ``handle`` is ``None`` when worktree allocation failed.  Either
    condition forces a zero score, but the coordinator preserves the
    record so the caller can see *why* the candidate lost.
    """

    spec: CandidateSpec
    handle: WorktreeHandle | None
    result: SubagentResult | None
    error: str | None = None


@dataclasses.dataclass
class RaceConfig:
    """Opt-in configuration for Best-of-N racing.

    ``enabled_categories`` is empty by default — racing is off unless the
    caller explicitly turns it on.  ``budget_tokens`` is advisory: the
    coordinator surfaces the pre-race estimate but does not hard-cap
    per-candidate token usage (that sits with the provider / subagent).
    """

    enabled_categories: frozenset[TaskCategory] = frozenset()
    max_candidates: int = 3
    budget_tokens: int = 500_000
    cancel_on_perfect: bool = True

    def should_race(self, category: TaskCategory, candidate_count: int) -> bool:
        """True when a task of ``category`` should run a race.

        A race needs at least two candidates — one candidate is just a
        normal subagent run, not a race.
        """
        return category in self.enabled_categories and candidate_count >= 2

    def clamp_candidates(self, candidates: list[CandidateSpec]) -> list[CandidateSpec]:
        """Return at most ``max_candidates`` specs from the input list."""
        if self.max_candidates <= 0:
            return []
        return list(candidates[: self.max_candidates])


@dataclasses.dataclass(frozen=True)
class RaceResult:
    """Outcome of a full race.

    ``winner`` is the highest-scored viable candidate, or ``None`` when
    every candidate failed.  ``all_scores`` and ``all_outcomes`` preserve
    losing-candidate metadata so the caller can release their worktrees
    and record their transcripts for post-hoc review.
    """

    task_id: str
    winner: CandidateScore | None
    all_scores: list[CandidateScore]
    all_outcomes: list[CandidateOutcome]
    elapsed_seconds: float

    def outcome_for(self, candidate_id: str) -> CandidateOutcome | None:
        """Return the outcome for ``candidate_id`` if present."""
        for outcome in self.all_outcomes:
            if outcome.spec.candidate_id == candidate_id:
                return outcome
        return None

    @property
    def winner_outcome(self) -> CandidateOutcome | None:
        """Return the winning candidate's outcome, or ``None`` if no winner."""
        if self.winner is None:
            return None
        return self.outcome_for(self.winner.candidate_id)


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


def _score_charmlint(errors: int, warnings: int, infos: int) -> float:
    """Map weighted charmlint violation counts to a subscore in ``[0, 1]``.

    The scoring is exponential decay: a clean charm scores 1.0; a charm
    with one error drops to roughly 0.74; a charm with three errors and
    several warnings drops below 0.25.  Errors dominate because they
    block shipping; warnings are a speed bump; infos are hints.
    """
    penalty = (
        errors * _CHARMLINT_SEVERITY_WEIGHT["error"]
        + warnings * _CHARMLINT_SEVERITY_WEIGHT["warning"]
        + infos * _CHARMLINT_SEVERITY_WEIGHT["info"]
    )
    return max(0.0, math.exp(-penalty / _CHARMLINT_DECAY))


def _score_diff(lines: int) -> float:
    """Map diff size to a subscore in ``[0, 1]`` — smaller is better.

    A zero-line diff is suspicious (the candidate may have committed
    nothing) and gets a middling :data:`_NO_DIFF_SUBSCORE` so charmlint
    and readiness decide the winner rather than rewarding inaction.
    Linear decay up to :data:`_DIFF_CAP_LINES`; diffs above the cap
    score 0.
    """
    if lines <= 0:
        return _NO_DIFF_SUBSCORE
    clamped = min(lines, _DIFF_CAP_LINES)
    return 1.0 - (clamped / _DIFF_CAP_LINES)


def _score_tests(passed: int, total: int) -> float:
    """Map unit-test pass/total to a subscore in ``[0, 1]``.

    When no tests exist (``total == 0``) we return 1.0 — a candidate
    shouldn't be penalised for working in a test-free area.  Tuning
    note: once we start scoring against a baseline test count,
    candidates that ran fewer tests than the baseline should score
    proportionally lower; for now we normalise per-candidate.
    """
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, passed / total))


def _score_readiness(pct: int | None) -> float:
    """Map operational-readiness percentage (0–100) to ``[0, 1]``.

    ``None`` means the tool couldn't run (e.g. no ``charmcraft.yaml`` in
    the worktree) — treat it as zero rather than half so a candidate
    that isn't actually a charm loses to one that is.
    """
    if pct is None:
        return 0.0
    return max(0.0, min(1.0, pct / 100.0))


def compute_score(
    *,
    candidate_id: str,
    exit_state: ExitState,
    charmlint_errors: int = 0,
    charmlint_warnings: int = 0,
    charmlint_infos: int = 0,
    readiness_pct: int | None = None,
    unit_tests_passed: int = 0,
    unit_tests_total: int = 0,
    diff_lines_added: int = 0,
    diff_lines_removed: int = 0,
    error: str | None = None,
) -> CandidateScore:
    """Compose subscores into a :class:`CandidateScore`.

    Pure function — no I/O.  ``score_candidate`` wraps this with worktree
    measurement; tests can call this directly with synthetic counts.
    """
    # Non-viable exit → forced zero.  The subscores would be misleading
    # (e.g. a failed candidate with a clean charmlint because it never
    # changed anything), so we publish zero explicitly.
    if exit_state in (ExitState.FAILED, ExitState.NOOP):
        return CandidateScore(
            candidate_id=candidate_id,
            exit_state=exit_state,
            total=0.0,
            charmlint_errors=charmlint_errors,
            charmlint_warnings=charmlint_warnings,
            charmlint_infos=charmlint_infos,
            readiness_pct=readiness_pct,
            unit_tests_passed=unit_tests_passed,
            unit_tests_total=unit_tests_total,
            diff_lines_added=diff_lines_added,
            diff_lines_removed=diff_lines_removed,
            error=error,
        )

    total = (
        _W_CHARMLINT * _score_charmlint(charmlint_errors, charmlint_warnings, charmlint_infos)
        + _W_READINESS * _score_readiness(readiness_pct)
        + _W_TESTS * _score_tests(unit_tests_passed, unit_tests_total)
        + _W_DIFF * _score_diff(diff_lines_added + diff_lines_removed)
    )
    return CandidateScore(
        candidate_id=candidate_id,
        exit_state=exit_state,
        total=round(total, 4),
        charmlint_errors=charmlint_errors,
        charmlint_warnings=charmlint_warnings,
        charmlint_infos=charmlint_infos,
        readiness_pct=readiness_pct,
        unit_tests_passed=unit_tests_passed,
        unit_tests_total=unit_tests_total,
        diff_lines_added=diff_lines_added,
        diff_lines_removed=diff_lines_removed,
        error=error,
    )


def pick_winner(scores: list[CandidateScore]) -> CandidateScore | None:
    """Return the viable candidate with the highest total, or ``None``.

    Ties break on lower diff-line count (smaller change wins) and then on
    ``candidate_id`` for stable ordering, so repeated races with the same
    pool produce the same winner when the underlying measurements agree.
    """
    viable = [s for s in scores if s.is_viable and s.total > 0]
    if not viable:
        return None
    viable.sort(key=lambda s: (-s.total, s.diff_lines, s.candidate_id))
    return viable[0]


# ---------------------------------------------------------------------------
# Worktree measurement
# ---------------------------------------------------------------------------


async def _run_git_numstat(
    worktree: pathlib.Path,
    base_sha: str,
) -> tuple[int, int]:
    """Return (added, removed) line counts for ``base_sha..HEAD`` in ``worktree``.

    Returns ``(0, 0)`` on any git failure — a broken measurement
    shouldn't crash the whole race.  The ``..HEAD`` spec compares
    committed changes only, so uncommitted files the scorer wrote
    (e.g. an OPERATIONAL_READINESS.md report) do not inflate the count.
    """

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "diff", "--numstat", f"{base_sha}..HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug("git numstat failed in %s: %s", worktree, exc)
        return (0, 0)

    if proc.returncode != 0:
        log.debug(
            "git numstat non-zero in %s: %s",
            worktree,
            proc.stderr.strip() or proc.stdout.strip(),
        )
        return (0, 0)

    added = removed = 0
    for line in proc.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        # Binary files show '-' in both columns; skip those.
        try:
            added += int(parts[0])
            removed += int(parts[1])
        except ValueError:
            continue
    return (added, removed)


async def _run_charmlint(charm_dir: pathlib.Path) -> dict[str, int]:
    """Return charmlint counts for ``charm_dir``: errors, warnings, infos.

    Uses the existing :class:`CharmlintTool` so the Rust-vs-Python
    backend selection stays in one place.  Returns zeroed counts on any
    failure — scoring should degrade gracefully when the linter isn't
    available, not crash the race.
    """
    from cantrip.agent.tools.charmlint_tool import CharmlintTool

    tool = CharmlintTool()
    try:
        result = await tool.execute(path=str(charm_dir))
    except (OSError, RuntimeError) as exc:
        log.debug("charmlint raised in %s: %s", charm_dir, exc)
        return {"errors": 0, "warnings": 0, "infos": 0}

    if not result.success:
        return {"errors": 0, "warnings": 0, "infos": 0}

    data = result.data or {}
    return {
        "errors": int(data.get("errors", 0) or 0),
        "warnings": int(data.get("warnings", 0) or 0),
        # The Rust binary's JSON uses ``info`` (singular), the Python
        # path also emits ``info``; be lenient about both spellings.
        "infos": int(data.get("info", data.get("infos", 0)) or 0),
    }


async def _run_readiness(charm_dir: pathlib.Path) -> int | None:
    """Return the operational-readiness percentage for ``charm_dir``.

    Calls the :class:`OperationalReadinessTool` directly.  As a side
    effect the tool writes an ``OPERATIONAL_READINESS.md`` file into the
    worktree; that's fine for scoring because we measure the diff
    against HEAD first and the report is uncommitted (so it does not
    propagate on merge).  Returns ``None`` when the tool can't evaluate
    the directory (e.g. no ``charmcraft.yaml``).
    """
    from cantrip.agent.tools.operational_readiness import OperationalReadinessTool

    tool = OperationalReadinessTool()
    try:
        result = await tool.execute(path=str(charm_dir))
    except (OSError, RuntimeError) as exc:
        log.debug("operational_readiness raised in %s: %s", charm_dir, exc)
        return None

    if not result.success:
        return None
    data = result.data or {}
    score = data.get("overall_score")
    if score is None:
        return None
    return int(score)


async def score_candidate(
    outcome: CandidateOutcome,
    *,
    charm_dir: pathlib.Path | None = None,
) -> CandidateScore:
    """Score a candidate by inspecting its worktree after the subagent ran.

    Measurement order matters: diff is taken first against committed
    history, then charmlint (read-only), then readiness (which writes an
    uncommitted report file).  ``charm_dir`` overrides the default of
    the worktree path — useful when the subagent wrote to a
    subdirectory.
    """
    spec = outcome.spec
    result = outcome.result

    if result is None:
        return CandidateScore(
            candidate_id=spec.candidate_id,
            exit_state=ExitState.FAILED,
            total=0.0,
            error=outcome.error or "subagent crashed",
        )

    # Short-circuit on non-viable exit states — their subscores are
    # misleading (a failed candidate may have clean charmlint because it
    # didn't write anything).
    if result.exit_state in (ExitState.FAILED, ExitState.NOOP):
        return CandidateScore(
            candidate_id=spec.candidate_id,
            exit_state=result.exit_state,
            total=0.0,
            error=result.detail or result.summary,
        )

    worktree = outcome.handle.path if outcome.handle else None
    target = charm_dir or worktree
    if target is None:
        return CandidateScore(
            candidate_id=spec.candidate_id,
            exit_state=result.exit_state,
            total=0.0,
            error="no worktree available for scoring",
        )

    # Measure diff first so an uncommitted readiness report doesn't
    # inflate the count.  When no handle is available we don't have a
    # base_sha to compare against, so fall back to zero lines.
    if outcome.handle is not None:
        added, removed = await _run_git_numstat(worktree, outcome.handle.base_sha)
    else:
        added, removed = 0, 0

    charmlint = await _run_charmlint(target)
    readiness_pct = await _run_readiness(target)

    return compute_score(
        candidate_id=spec.candidate_id,
        exit_state=result.exit_state,
        charmlint_errors=charmlint["errors"],
        charmlint_warnings=charmlint["warnings"],
        charmlint_infos=charmlint["infos"],
        readiness_pct=readiness_pct,
        diff_lines_added=added,
        diff_lines_removed=removed,
    )


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def estimate_race_tokens(
    *,
    baseline_tokens_per_run: int,
    candidate_count: int,
) -> int:
    """Estimate total tokens a race will consume.

    Multiplies the single-run baseline by the candidate count — races
    are embarrassingly parallel so there is no shared context between
    candidates.  Callers compare this against :attr:`RaceConfig.budget_tokens`
    to gate the race behind a CONFIRM task when the cost is high.
    """
    return max(0, baseline_tokens_per_run) * max(0, candidate_count)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


# Factory passed by the executor: given a candidate spec and the
# worktree path the candidate should run in, build and return a
# ready-to-run :class:`Subagent`.  Keeping this as a callback means the
# coordinator doesn't need to know about tools, SubagentContext, or the
# executor's plumbing — tests can pass a trivial fake factory.
SubagentFactory = Callable[
    ["CandidateSpec", pathlib.Path, "WorktreeHandle | None"],
    Awaitable["Subagent"],
]


class RaceCoordinator:
    """Run N candidate subagents in parallel and select a winner.

    Allocates a per-candidate worktree via the injected
    :class:`WorktreeAllocator` (with a composite key so multiple
    candidates for the same task don't collide), spawns each subagent
    concurrently, scores the outcomes, and returns a :class:`RaceResult`.
    Losing worktrees are released automatically; the winning worktree
    is *kept* (branch preserved) so the caller can merge it back into
    the main tree via their existing merge path.

    The coordinator itself does not merge — that responsibility belongs
    to the executor, which already has merge plumbing via
    ``_merge_worktree``.  This keeps the coordinator testable without
    needing a real git repo beyond what the allocator requires.
    """

    def __init__(
        self,
        *,
        allocator: WorktreeAllocator,
        config: RaceConfig,
    ) -> None:
        self._allocator = allocator
        self._config = config

    async def run(
        self,
        *,
        task_id: str,
        base_path: pathlib.Path,
        specs: list[CandidateSpec],
        build_subagent: SubagentFactory,
    ) -> RaceResult:
        """Race *specs* against each other on *task_id*.

        Returns a :class:`RaceResult` whose ``winner_outcome.handle`` is
        the worktree the caller should merge back.  Losing worktrees
        have already been released by the time this returns.  When every
        candidate fails, ``winner`` is ``None`` and all worktrees are
        released — the caller has nothing to merge.
        """
        if not specs:
            raise ValueError("race requires at least one candidate")

        clamped = self._config.clamp_candidates(specs)
        if len(clamped) < len(specs):
            log.info(
                "Race for task %s clamped from %d → %d candidates (max_candidates=%d)",
                task_id,
                len(specs),
                len(clamped),
                self._config.max_candidates,
            )

        start = time.monotonic()

        # Run each candidate concurrently.  ``return_exceptions=True``
        # keeps one crashing candidate from cancelling the others —
        # we'll record it as a failed outcome and let the pool continue.
        coros = [self._run_candidate(task_id, base_path, spec, build_subagent) for spec in clamped]
        outcomes: list[CandidateOutcome] = await asyncio.gather(*coros, return_exceptions=False)

        # Score every outcome.  Scoring is cheap and parallelisable but
        # touches disk through charmlint/readiness; run concurrently so a
        # slow subagent doesn't stall the whole scoring phase either.
        score_coros = [score_candidate(outcome) for outcome in outcomes]
        scores: list[CandidateScore] = await asyncio.gather(*score_coros)

        winner = pick_winner(scores)

        # Release losing worktrees (and any that don't have a handle,
        # which is a no-op).  Preserve the winning branch so the caller
        # can merge it.
        await self._release_losers(outcomes, winner)

        elapsed = time.monotonic() - start
        log.info(
            "Race for task %s finished in %.1fs: %d/%d candidates viable, winner=%s (%.3f)",
            task_id,
            elapsed,
            sum(1 for s in scores if s.is_viable),
            len(scores),
            winner.candidate_id if winner else "<none>",
            winner.total if winner else 0.0,
        )
        return RaceResult(
            task_id=task_id,
            winner=winner,
            all_scores=scores,
            all_outcomes=outcomes,
            elapsed_seconds=round(elapsed, 3),
        )

    async def _run_candidate(
        self,
        task_id: str,
        base_path: pathlib.Path,
        spec: CandidateSpec,
        build_subagent: SubagentFactory,
    ) -> CandidateOutcome:
        """Allocate a worktree for *spec*, build its subagent, run it, collect."""
        alloc_key = f"{task_id}__{spec.candidate_id}"
        handle: WorktreeHandle | None = None
        try:
            handle = await self._allocator.allocate(alloc_key, base_path)
        except (OSError, ValueError) as exc:
            log.warning(
                "Race candidate %s/%s: worktree allocation failed: %s",
                task_id,
                spec.candidate_id,
                exc,
            )
            # Fall through with handle=None so the candidate can still
            # attempt to run in base_path (matching non-race behaviour).

        work_path = handle.path if handle is not None else base_path

        subagent: Subagent
        try:
            subagent = await build_subagent(spec, work_path, handle)
        except (OSError, RuntimeError, ValueError) as exc:
            log.exception(
                "Race candidate %s/%s: build_subagent failed",
                task_id,
                spec.candidate_id,
            )
            if handle is not None:
                await self._safe_release(handle, keep_branch=False)
            return CandidateOutcome(
                spec=spec,
                handle=None,
                result=None,
                error=f"failed to build subagent: {exc}",
            )

        try:
            result: SubagentResult = await subagent.run()
        except asyncio.CancelledError:
            if handle is not None:
                await self._safe_release(handle, keep_branch=False)
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            log.exception(
                "Race candidate %s/%s: subagent.run() raised",
                task_id,
                spec.candidate_id,
            )
            return CandidateOutcome(
                spec=spec,
                handle=handle,
                result=None,
                error=f"subagent crashed: {exc}",
            )

        return CandidateOutcome(spec=spec, handle=handle, result=result)

    async def _release_losers(
        self,
        outcomes: list[CandidateOutcome],
        winner: CandidateScore | None,
    ) -> None:
        """Release worktrees for losing candidates; keep the winner's."""
        for outcome in outcomes:
            if outcome.handle is None:
                continue
            is_winner = winner is not None and outcome.spec.candidate_id == winner.candidate_id
            # Keep the winner's branch so the caller can merge it; drop
            # the branch for every other candidate.
            await self._safe_release(outcome.handle, keep_branch=is_winner)

    async def _safe_release(self, handle: WorktreeHandle, *, keep_branch: bool) -> None:
        """Release *handle* without propagating allocator failures.

        Release is best-effort — a failure here should not crash the
        race, and an orphaned worktree will be reaped on next startup
        via ``reap_disk_orphans``.
        """
        try:
            await self._allocator.release(handle.task_id, keep_branch=keep_branch)
        except (OSError, RuntimeError) as exc:
            log.warning(
                "Race: failed to release worktree %s (keep_branch=%s): %s",
                handle.task_id,
                keep_branch,
                exc,
            )


__all__ = [
    "CandidateOutcome",
    "CandidateScore",
    "CandidateSpec",
    "RaceConfig",
    "RaceCoordinator",
    "RaceResult",
    "SubagentFactory",
    "compute_score",
    "estimate_race_tokens",
    "pick_winner",
    "score_candidate",
]
