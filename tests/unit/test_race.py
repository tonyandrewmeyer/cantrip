"""Unit tests for the Best-of-N racing harness.

Covers the pure scoring primitives, the :class:`RaceConfig` gate, and
:func:`pick_winner` tie-breaking.  Live-worktree scoring
(:func:`score_candidate`) is covered by an integration-style test that
stands up a real git worktree with known charmlint/readiness inputs —
see ``test_score_candidate_against_real_worktree``.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess

import pytest

from cantrip.agent import race
from cantrip.agent.queue import TaskCategory
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.agent.worktree import WorktreeHandle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FakeProvider:
    """Minimal LLMProvider stand-in for CandidateSpec construction."""

    model_name: str = "fake-model"


def _spec(candidate_id: str) -> race.CandidateSpec:
    """Build a ``CandidateSpec`` whose provider is an inert stand-in."""
    return race.CandidateSpec(candidate_id=candidate_id, provider=_FakeProvider())


def _outcome(
    candidate_id: str,
    *,
    exit_state: ExitState = ExitState.COMPLETED,
    summary: str = "",
    detail: str = "",
    handle: WorktreeHandle | None = None,
    error: str | None = None,
    crashed: bool = False,
) -> race.CandidateOutcome:
    """Construct a ``CandidateOutcome`` for scoring tests."""
    result = (
        None
        if crashed
        else SubagentResult(
            exit_state=exit_state,
            summary=summary or f"{candidate_id} ran",
            detail=detail,
        )
    )
    return race.CandidateOutcome(
        spec=_spec(candidate_id),
        handle=handle,
        result=result,
        error=error,
    )


# ---------------------------------------------------------------------------
# Subscore primitives
# ---------------------------------------------------------------------------


class TestSubscores:
    """The private ``_score_*`` helpers back every public score — test them."""

    def test_charmlint_clean_charm_scores_one(self) -> None:
        assert race._score_charmlint(0, 0, 0) == pytest.approx(1.0)

    def test_charmlint_errors_hurt_more_than_warnings(self) -> None:
        errors_only = race._score_charmlint(1, 0, 0)
        warnings_only = race._score_charmlint(0, 1, 0)
        assert errors_only < warnings_only

    def test_charmlint_score_monotonically_decreasing_in_errors(self) -> None:
        prior = race._score_charmlint(0, 0, 0)
        for n in range(1, 6):
            current = race._score_charmlint(n, 0, 0)
            assert current < prior, f"{n} errors should score below {n - 1}"
            prior = current

    def test_charmlint_score_clamped_at_zero(self) -> None:
        # Exponential decay never goes negative, but an absurd violation
        # count should still approach zero.
        assert race._score_charmlint(100, 0, 0) < 0.01
        assert race._score_charmlint(100, 0, 0) >= 0.0

    def test_diff_zero_lines_is_suspicious_not_perfect(self) -> None:
        # Zero diff usually means the candidate did nothing — middling
        # score lets other signals decide.
        assert race._score_diff(0) == race._NO_DIFF_SUBSCORE
        assert race._score_diff(0) < 1.0

    def test_diff_smaller_scores_higher(self) -> None:
        assert race._score_diff(50) > race._score_diff(500)
        assert race._score_diff(500) > race._score_diff(2000)

    def test_diff_above_cap_scores_zero(self) -> None:
        assert race._score_diff(race._DIFF_CAP_LINES) == pytest.approx(0.0)
        assert race._score_diff(race._DIFF_CAP_LINES * 10) == pytest.approx(0.0)

    def test_tests_no_suite_scores_full(self) -> None:
        # Absent test suite should not penalise — the subagent shouldn't
        # have to invent tests just to compete.
        assert race._score_tests(0, 0) == 1.0

    def test_tests_all_pass_scores_full(self) -> None:
        assert race._score_tests(10, 10) == 1.0

    def test_tests_partial_scores_fractional(self) -> None:
        assert race._score_tests(3, 10) == pytest.approx(0.3)

    def test_tests_more_passed_than_total_is_clamped(self) -> None:
        # A miscount shouldn't push the subscore above 1.0.
        assert race._score_tests(100, 10) == 1.0

    def test_readiness_none_scores_zero(self) -> None:
        # A worktree that isn't a charm shouldn't beat one that is.
        assert race._score_readiness(None) == 0.0

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [(0, 0.0), (50, 0.5), (100, 1.0), (-5, 0.0), (120, 1.0)],
    )
    def test_readiness_clamped_to_unit_interval(self, pct: int, expected: float) -> None:
        assert race._score_readiness(pct) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# compute_score — exit-state gating and composition
# ---------------------------------------------------------------------------


class TestComputeScore:
    """Direct coverage for ``compute_score`` with no I/O."""

    def test_failed_exit_zeroes_total_regardless_of_signals(self) -> None:
        score = race.compute_score(
            candidate_id="opus",
            exit_state=ExitState.FAILED,
            charmlint_errors=0,
            readiness_pct=100,
            unit_tests_passed=10,
            unit_tests_total=10,
            diff_lines_added=50,
        )
        assert score.total == 0.0
        assert score.exit_state is ExitState.FAILED
        # But the raw counts survive so the transcript can show why.
        assert score.readiness_pct == 100
        assert score.unit_tests_passed == 10

    def test_noop_exit_zeroes_total(self) -> None:
        score = race.compute_score(
            candidate_id="sonnet",
            exit_state=ExitState.NOOP,
            readiness_pct=95,
            diff_lines_added=0,
        )
        assert score.total == 0.0

    def test_completed_clean_charm_scores_near_perfect(self) -> None:
        score = race.compute_score(
            candidate_id="opus",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=0,
            charmlint_warnings=0,
            charmlint_infos=0,
            readiness_pct=100,
            unit_tests_passed=10,
            unit_tests_total=10,
            diff_lines_added=100,
            diff_lines_removed=50,
        )
        # 150 lines is well below the diff cap; score should still be
        # strongly positive.
        assert score.total > 0.9
        assert score.is_viable

    def test_completed_messy_charm_scores_below_clean(self) -> None:
        clean = race.compute_score(
            candidate_id="a",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=0,
            readiness_pct=100,
            unit_tests_passed=10,
            unit_tests_total=10,
            diff_lines_added=100,
        )
        messy = race.compute_score(
            candidate_id="b",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=5,
            readiness_pct=60,
            unit_tests_passed=7,
            unit_tests_total=10,
            diff_lines_added=1500,
        )
        assert messy.total < clean.total

    def test_blocked_exit_is_viable(self) -> None:
        score = race.compute_score(
            candidate_id="opus",
            exit_state=ExitState.BLOCKED,
            readiness_pct=80,
            diff_lines_added=50,
        )
        assert score.is_viable
        assert score.total > 0

    def test_total_is_rounded_to_four_places(self) -> None:
        score = race.compute_score(
            candidate_id="x",
            exit_state=ExitState.COMPLETED,
            readiness_pct=33,
            diff_lines_added=123,
        )
        assert score.total == round(score.total, 4)


# ---------------------------------------------------------------------------
# pick_winner — tie-breaking
# ---------------------------------------------------------------------------


class TestPickWinner:
    def test_empty_pool_returns_none(self) -> None:
        assert race.pick_winner([]) is None

    def test_all_failed_returns_none(self) -> None:
        scores = [
            race.compute_score(candidate_id="a", exit_state=ExitState.FAILED),
            race.compute_score(candidate_id="b", exit_state=ExitState.NOOP),
        ]
        assert race.pick_winner(scores) is None

    def test_picks_highest_total(self) -> None:
        high = race.compute_score(
            candidate_id="opus",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=0,
            readiness_pct=100,
            unit_tests_passed=10,
            unit_tests_total=10,
            diff_lines_added=100,
        )
        mid = race.compute_score(
            candidate_id="sonnet",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=2,
            readiness_pct=70,
            diff_lines_added=500,
        )
        winner = race.pick_winner([mid, high])
        assert winner is not None
        assert winner.candidate_id == "opus"

    def test_ties_break_on_smaller_diff(self) -> None:
        # Construct two candidates with identical totals but different
        # diff sizes.  Smaller diff wins.
        small = race.compute_score(
            candidate_id="small",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=0,
            readiness_pct=80,
            diff_lines_added=100,
        )
        big = race.compute_score(
            candidate_id="big",
            exit_state=ExitState.COMPLETED,
            charmlint_errors=0,
            readiness_pct=80,
            diff_lines_added=100,
        )
        # Force the tie explicitly so we test the tie-breaker, not a
        # coincidental inequality.
        big = dataclasses.replace(big, total=small.total, diff_lines_added=small.diff_lines + 500)
        winner = race.pick_winner([big, small])
        assert winner is not None
        assert winner.candidate_id == "small"

    def test_ties_break_stably_on_candidate_id(self) -> None:
        # Same total, same diff → lexicographic id order.
        a = race.compute_score(
            candidate_id="b-candidate",
            exit_state=ExitState.COMPLETED,
            readiness_pct=80,
            diff_lines_added=100,
        )
        b = race.compute_score(
            candidate_id="a-candidate",
            exit_state=ExitState.COMPLETED,
            readiness_pct=80,
            diff_lines_added=100,
        )
        winner = race.pick_winner([a, b])
        assert winner is not None
        assert winner.candidate_id == "a-candidate"

    def test_zero_score_candidates_filtered_out(self) -> None:
        # Completed but all-zero (no charmcraft.yaml found) should not win
        # over a lower-but-nonzero score.
        zero = race.compute_score(
            candidate_id="empty",
            exit_state=ExitState.COMPLETED,
            readiness_pct=None,
            charmlint_errors=0,
            diff_lines_added=0,
        )
        # Force score to zero (contrived — readiness None + zero diff
        # without the suspicious-zero bonus).  Real scoring tends to
        # produce low-but-nonzero values, so this is the explicit case.
        zero = dataclasses.replace(zero, total=0.0)

        some = race.compute_score(
            candidate_id="real",
            exit_state=ExitState.COMPLETED,
            readiness_pct=30,
            diff_lines_added=200,
        )
        winner = race.pick_winner([zero, some])
        assert winner is not None
        assert winner.candidate_id == "real"


# ---------------------------------------------------------------------------
# RaceConfig
# ---------------------------------------------------------------------------


class TestRaceConfig:
    def test_default_disables_racing(self) -> None:
        cfg = race.RaceConfig()
        assert cfg.should_race(TaskCategory.BUILD, candidate_count=3) is False

    def test_enabled_category_allows_race(self) -> None:
        cfg = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        assert cfg.should_race(TaskCategory.BUILD, candidate_count=3) is True

    def test_disabled_category_refuses_race(self) -> None:
        cfg = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        assert cfg.should_race(TaskCategory.DEPLOY, candidate_count=3) is False

    def test_single_candidate_never_races(self) -> None:
        cfg = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        assert cfg.should_race(TaskCategory.BUILD, candidate_count=1) is False

    def test_clamp_candidates_respects_max(self) -> None:
        cfg = race.RaceConfig(max_candidates=2)
        specs = [_spec("a"), _spec("b"), _spec("c"), _spec("d")]
        clamped = cfg.clamp_candidates(specs)
        assert len(clamped) == 2
        assert [s.candidate_id for s in clamped] == ["a", "b"]

    def test_clamp_candidates_handles_zero_cap(self) -> None:
        cfg = race.RaceConfig(max_candidates=0)
        assert cfg.clamp_candidates([_spec("a"), _spec("b")]) == []


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


class TestEstimateRaceTokens:
    def test_scales_linearly_with_candidates(self) -> None:
        assert race.estimate_race_tokens(baseline_tokens_per_run=1000, candidate_count=3) == 3000

    def test_zero_baseline_returns_zero(self) -> None:
        assert race.estimate_race_tokens(baseline_tokens_per_run=0, candidate_count=5) == 0

    def test_negative_inputs_clamped_to_zero(self) -> None:
        assert race.estimate_race_tokens(baseline_tokens_per_run=-100, candidate_count=3) == 0
        assert race.estimate_race_tokens(baseline_tokens_per_run=100, candidate_count=-3) == 0


# ---------------------------------------------------------------------------
# score_candidate — end-to-end with injected worktree
# ---------------------------------------------------------------------------


class TestScoreCandidate:
    @pytest.mark.asyncio
    async def test_crashed_candidate_scores_zero(self) -> None:
        outcome = _outcome("opus", crashed=True, error="provider exploded")
        score = await race.score_candidate(outcome)
        assert score.total == 0.0
        assert score.exit_state is ExitState.FAILED
        assert score.error == "provider exploded"

    @pytest.mark.asyncio
    async def test_failed_candidate_scores_zero(self) -> None:
        outcome = _outcome(
            "sonnet",
            exit_state=ExitState.FAILED,
            summary="hit rate limit",
        )
        score = await race.score_candidate(outcome)
        assert score.total == 0.0
        assert score.exit_state is ExitState.FAILED
        assert "hit rate limit" in (score.error or "")

    @pytest.mark.asyncio
    async def test_noop_candidate_scores_zero(self) -> None:
        outcome = _outcome("haiku", exit_state=ExitState.NOOP, summary="nothing to do")
        score = await race.score_candidate(outcome)
        assert score.total == 0.0
        assert score.exit_state is ExitState.NOOP

    @pytest.mark.asyncio
    async def test_missing_worktree_and_charm_dir_scores_zero(self) -> None:
        # Completed but the coordinator couldn't allocate a worktree and
        # no explicit charm dir was passed.
        outcome = _outcome("opus", exit_state=ExitState.COMPLETED, handle=None)
        score = await race.score_candidate(outcome, charm_dir=None)
        assert score.total == 0.0
        assert score.error == "no worktree available for scoring"
        # Exit state survives so the caller can tell "ran but unscorable"
        # from "crashed".
        assert score.exit_state is ExitState.COMPLETED

    @pytest.mark.asyncio
    async def test_completed_against_empty_dir_scores_but_readiness_none(
        self, tmp_path: pathlib.Path
    ) -> None:
        # A completed candidate with no charmcraft.yaml yields
        # readiness=None but charmlint and diff still run.  The score
        # should be non-zero (charmlint subscore is 1.0 on empty dir)
        # but below a charm with real readiness.
        outcome = _outcome("opus", exit_state=ExitState.COMPLETED, handle=None)
        score = await race.score_candidate(outcome, charm_dir=tmp_path)
        # No readiness, empty dir → charmlint clean, readiness 0,
        # tests full (no suite), diff middling.  Total > 0 but well
        # below 1.0.
        assert 0.0 < score.total < 1.0
        assert score.readiness_pct is None


# ---------------------------------------------------------------------------
# Live worktree integration — real git + real scoring tools
# ---------------------------------------------------------------------------


def _git(cwd: pathlib.Path, *args: str) -> None:
    """Run git with standard identity so commits succeed in CI."""
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin",
        },
    )


# ---------------------------------------------------------------------------
# RaceCoordinator
# ---------------------------------------------------------------------------


class _FakeAllocator:
    """In-memory worktree allocator for coordinator tests.

    Satisfies the :class:`WorktreeAllocator` protocol shape without
    touching git or the filesystem — every allocation hands out a
    unique path under ``tmp_path`` and every release records the key.
    """

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self._tmp_path = tmp_path
        self._handles: dict[str, WorktreeHandle] = {}
        self.released: list[tuple[str, bool]] = []  # (task_id, keep_branch)
        self.allocate_fail_for: set[str] = set()
        self.release_raise = False

    async def allocate(self, task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle | None:
        if task_id in self.allocate_fail_for:
            return None
        path = self._tmp_path / "worktrees" / task_id
        path.mkdir(parents=True, exist_ok=True)
        handle = WorktreeHandle(
            task_id=task_id,
            path=path,
            branch=f"cantrip/wt/{task_id}",
            base_sha="0" * 40,
        )
        self._handles[task_id] = handle
        return handle

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        if self.release_raise:
            raise RuntimeError("simulated release failure")
        self._handles.pop(task_id, None)
        self.released.append((task_id, keep_branch))

    def get(self, task_id: str) -> WorktreeHandle | None:
        return self._handles.get(task_id)

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        return dict(self._handles)

    async def reap_orphans(self, active_task_ids: set[str]) -> int:
        return 0


class _FakeSubagent:
    """Subagent double that returns a pre-programmed result."""

    def __init__(self, result: SubagentResult | None, raise_on_run: Exception | None = None):
        self._result = result
        self._raise = raise_on_run

    async def run(self) -> SubagentResult:
        if self._raise is not None:
            raise self._raise
        if self._result is None:
            # None result is distinct from "crashed" — tests that want a
            # crash pass ``raise_on_run``.
            raise RuntimeError("unexpected None")
        return self._result


def _fake_factory(results_by_candidate: dict[str, SubagentResult | Exception]):
    """Build a :class:`SubagentFactory` that hands out pre-programmed subagents."""

    async def factory(
        spec: race.CandidateSpec,
        _work_path: pathlib.Path,
        _handle: WorktreeHandle | None,
    ):
        entry = results_by_candidate.get(spec.candidate_id)
        if isinstance(entry, Exception):
            return _FakeSubagent(None, raise_on_run=entry)
        return _FakeSubagent(entry)

    return factory


class TestRaceCoordinator:
    @pytest.mark.asyncio
    async def test_requires_at_least_one_candidate(self, tmp_path: pathlib.Path) -> None:
        coord = race.RaceCoordinator(
            allocator=_FakeAllocator(tmp_path),
            config=race.RaceConfig(),
        )
        with pytest.raises(ValueError, match="requires at least one"):
            await coord.run(
                task_id="t1",
                base_path=tmp_path,
                specs=[],
                build_subagent=_fake_factory({}),
            )

    @pytest.mark.asyncio
    async def test_picks_best_of_n(self, tmp_path: pathlib.Path) -> None:
        # Two candidates: "good" completes, "bad" fails.  Good wins.
        allocator = _FakeAllocator(tmp_path)
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results = {
            "good": SubagentResult(ExitState.COMPLETED, summary="done", detail=""),
            "bad": SubagentResult(ExitState.FAILED, summary="broke", detail=""),
        }
        specs = [_spec("good"), _spec("bad")]

        result = await coord.run(
            task_id="t1",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        assert result.winner is not None
        assert result.winner.candidate_id == "good"
        assert len(result.all_scores) == 2
        assert len(result.all_outcomes) == 2
        assert result.elapsed_seconds >= 0

    @pytest.mark.asyncio
    async def test_releases_losing_worktrees_and_keeps_winner(
        self, tmp_path: pathlib.Path
    ) -> None:
        allocator = _FakeAllocator(tmp_path)
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results = {
            "winner": SubagentResult(ExitState.COMPLETED, summary="yes", detail=""),
            "loser1": SubagentResult(ExitState.FAILED, summary="no", detail=""),
            "loser2": SubagentResult(ExitState.NOOP, summary="nothing", detail=""),
        }
        specs = [_spec("winner"), _spec("loser1"), _spec("loser2")]

        result = await coord.run(
            task_id="t2",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        # Each candidate key is namespaced by (task_id, candidate_id).
        released_map = dict(allocator.released)
        assert released_map["t2__winner"] is True  # keep_branch
        assert released_map["t2__loser1"] is False
        assert released_map["t2__loser2"] is False
        assert result.winner is not None
        assert result.winner.candidate_id == "winner"

    @pytest.mark.asyncio
    async def test_all_failed_returns_no_winner(self, tmp_path: pathlib.Path) -> None:
        allocator = _FakeAllocator(tmp_path)
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results = {
            "a": SubagentResult(ExitState.FAILED, summary="no", detail=""),
            "b": SubagentResult(ExitState.FAILED, summary="no", detail=""),
        }
        specs = [_spec("a"), _spec("b")]

        result = await coord.run(
            task_id="t3",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        assert result.winner is None
        # Both worktrees released with keep_branch=False since nobody won.
        assert all(keep is False for _, keep in allocator.released)

    @pytest.mark.asyncio
    async def test_candidate_crash_becomes_failed_outcome(self, tmp_path: pathlib.Path) -> None:
        allocator = _FakeAllocator(tmp_path)
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results: dict[str, SubagentResult | Exception] = {
            "good": SubagentResult(ExitState.COMPLETED, summary="done", detail=""),
            "crashed": RuntimeError("kaboom"),
        }
        specs = [_spec("good"), _spec("crashed")]

        result = await coord.run(
            task_id="t4",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        # Good wins; crashed candidate is recorded but scores zero.
        assert result.winner is not None
        assert result.winner.candidate_id == "good"

        crashed_outcome = result.outcome_for("crashed")
        assert crashed_outcome is not None
        assert crashed_outcome.result is None
        assert "kaboom" in (crashed_outcome.error or "")

        crashed_score = next(s for s in result.all_scores if s.candidate_id == "crashed")
        assert crashed_score.total == 0.0
        assert crashed_score.exit_state is ExitState.FAILED

    @pytest.mark.asyncio
    async def test_clamps_candidate_pool_to_max(self, tmp_path: pathlib.Path) -> None:
        allocator = _FakeAllocator(tmp_path)
        config = race.RaceConfig(max_candidates=2)
        coord = race.RaceCoordinator(allocator=allocator, config=config)
        results = {
            "a": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
            "b": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
            "c": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
        }
        specs = [_spec("a"), _spec("b"), _spec("c")]

        result = await coord.run(
            task_id="t5",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        assert len(result.all_outcomes) == 2
        assert {o.spec.candidate_id for o in result.all_outcomes} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_allocation_failure_still_runs_candidate(self, tmp_path: pathlib.Path) -> None:
        allocator = _FakeAllocator(tmp_path)
        # Force allocation to fail for "a" — coordinator should fall
        # back to running "a" in base_path.
        allocator.allocate_fail_for.add("t6__a")
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results = {
            "a": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
            "b": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
        }
        specs = [_spec("a"), _spec("b")]

        result = await coord.run(
            task_id="t6",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )

        # Both outcomes exist; "a" has no handle, "b" has one.
        a_outcome = result.outcome_for("a")
        b_outcome = result.outcome_for("b")
        assert a_outcome is not None
        assert a_outcome.handle is None
        assert b_outcome is not None
        assert b_outcome.handle is not None

    @pytest.mark.asyncio
    async def test_release_failure_does_not_crash_race(self, tmp_path: pathlib.Path) -> None:
        allocator = _FakeAllocator(tmp_path)
        allocator.release_raise = True
        coord = race.RaceCoordinator(allocator=allocator, config=race.RaceConfig())
        results = {
            "a": SubagentResult(ExitState.COMPLETED, summary="", detail=""),
            "b": SubagentResult(ExitState.FAILED, summary="", detail=""),
        }
        specs = [_spec("a"), _spec("b")]

        # Should not raise — release failures are logged and swallowed.
        result = await coord.run(
            task_id="t7",
            base_path=tmp_path,
            specs=specs,
            build_subagent=_fake_factory(results),
        )
        assert result.winner is not None


@pytest.mark.asyncio
async def test_score_candidate_against_real_worktree(tmp_path: pathlib.Path) -> None:
    """Drive :func:`score_candidate` against a real git tree so the diff
    measurement and the charmlint/readiness toolchain all fire.

    This is slower than the pure-function tests and depends on the git
    binary being available; the CI image already has it.  Skip if it's
    not — contributors on stripped-down environments shouldn't be
    forced to install git to run the unit suite.
    """
    if subprocess.run(["which", "git"], capture_output=True, check=False).returncode != 0:
        pytest.skip("git not available")

    # Set up a fresh repo with a minimal charmcraft.yaml so operational
    # readiness has something to evaluate.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")

    charmcraft_yaml = tmp_path / "charmcraft.yaml"
    charmcraft_yaml.write_text(
        "name: test-charm\ntype: charm\nsummary: A test charm\ndescription: For scoring tests\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "charmcraft.yaml")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Simulate a candidate: add a file and commit, then score.
    (tmp_path / "README.md").write_text("# Test Charm\n\nA charm.\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "add readme")

    handle = WorktreeHandle(
        task_id="t1__opus",
        path=tmp_path,
        branch="cantrip/wt/t1__opus",
        base_sha=base_sha,
    )
    outcome = _outcome("opus", exit_state=ExitState.COMPLETED, handle=handle)

    score = await race.score_candidate(outcome)

    assert score.exit_state is ExitState.COMPLETED
    assert score.total > 0.0
    # We added a README.md (2 non-empty lines) — diff measurement
    # should pick that up, and the score should reflect real data.
    assert score.diff_lines_added >= 1
    # Readiness should have computed *something* (a value in 0..100)
    # because we have a charmcraft.yaml.
    assert score.readiness_pct is not None
    assert 0 <= score.readiness_pct <= 100
