"""Tests for ``BackgroundExecutor`` ↔ ``RaceCoordinator`` integration.

Covers the path where a task is dispatched to the Best-of-N race
coordinator rather than the single-subagent path: candidate spec
assembly, transcript namespacing, merge-on-winner, and the no-winner
fallback.  Uses the in-memory ``FakeAllocator`` from
``test_executor_worktree`` so tests stay fast and deterministic.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from cantrip.agent.executor import BackgroundExecutor, _candidate_id_for
from cantrip.agent.git.worktree import WorktreeHandle
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.race import race
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.support.tools import make_stub_tool as _make_tool
from tests.support.worktrees import FakeAllocator, ReleaseCall

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handle(task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle:
    """Build a worktree handle under ``<base_path>/.cantrip-worktrees/<task_id>``."""
    path = pathlib.Path(base_path) / ".cantrip-worktrees" / task_id
    return WorktreeHandle(
        task_id=task_id,
        path=path,
        branch=f"cantrip/wt/{task_id}",
        base_sha="0" * 40,
    )


def _make_allocator(base_path: pathlib.Path) -> FakeAllocator:
    """Race-tests allocator: handles land at ``base_path/.cantrip-worktrees/<id>``."""
    return FakeAllocator(root=base_path / ".cantrip-worktrees")


def _make_executor(
    allocator: FakeAllocator,
    *,
    charm_path: pathlib.Path,
    race_config: race.RaceConfig | None = None,
    light_provider: FakeProvider | None = None,
    extra_providers: list[FakeProvider] | None = None,
) -> BackgroundExecutor:
    primary = FakeProvider(responses=[Response(content="ok")])
    primary.model_name = "primary-model"
    return BackgroundExecutor(
        queue=WorkQueue(),
        tools=[_make_tool("read_file")],
        provider=primary,
        state=AgentState(charm_path=charm_path),
        worktree_allocator=allocator,
        light_provider=light_provider,
        race_config=race_config,
        extra_providers=list(extra_providers or []),
    )


def _named_provider(model_name: str) -> FakeProvider:
    provider = FakeProvider(responses=[Response(content="ok")])
    provider.model_name = model_name
    return provider


# ---------------------------------------------------------------------------
# _candidate_id_for helper
# ---------------------------------------------------------------------------


class TestCandidateIdFor:
    def test_derives_from_model_name(self) -> None:
        assert _candidate_id_for(_named_provider("claude-opus-4-7")) == "claude-opus-4-7"

    def test_collapses_punctuation(self) -> None:
        assert _candidate_id_for(_named_provider("Gemini 2.5 Pro!")) == "gemini-2-5-pro"

    def test_empty_model_name_falls_back_to_provider_name(self) -> None:
        provider = FakeProvider()
        provider.model_name = ""
        # FakeProvider.name == "fake"
        assert _candidate_id_for(provider) == "fake"


# ---------------------------------------------------------------------------
# Candidate-spec assembly
# ---------------------------------------------------------------------------


class TestCandidateSpecs:
    def test_single_provider_yields_one_spec(self, tmp_path: pathlib.Path) -> None:
        executor = _make_executor(_make_allocator(tmp_path), charm_path=tmp_path)
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model"]

    def test_primary_and_light_yield_two_specs(self, tmp_path: pathlib.Path) -> None:
        light = _named_provider("light-model")
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=light,
        )
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model", "light-model"]
        # Every spec carries the light provider as a fallback for sub-tasks.
        assert all(s.light_provider is light for s in specs)

    def test_duplicate_models_deduped(self, tmp_path: pathlib.Path) -> None:
        """A light provider that shares the primary's model name is dropped."""
        light = _named_provider("primary-model")
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=light,
        )
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model"]

    def test_extra_providers_appended_in_order(self, tmp_path: pathlib.Path) -> None:
        extras = [_named_provider("gemini-pro"), _named_provider("gpt-4o")]
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            extra_providers=extras,
        )
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model", "gemini-pro", "gpt-4o"]


# ---------------------------------------------------------------------------
# _should_race gate
# ---------------------------------------------------------------------------


class TestShouldRace:
    def test_disabled_by_default(self, tmp_path: pathlib.Path) -> None:
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light"),
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is False

    def test_enabled_with_two_candidates(self, tmp_path: pathlib.Path) -> None:
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light"),
            race_config=config,
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is True

    def test_disabled_without_charm_path(self, tmp_path: pathlib.Path) -> None:
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light"),
            race_config=config,
        )
        # Simulate no-charm-path after construction.
        executor._state.charm_path = None
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is False

    def test_disabled_with_single_candidate(self, tmp_path: pathlib.Path) -> None:
        # A race with one candidate is just a normal subagent run.
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            race_config=config,
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is False


# ---------------------------------------------------------------------------
# _dispatch_race_gate — CONFIRM task, budget downgrade, decision memoisation
# ---------------------------------------------------------------------------


class TestDispatchRaceGate:
    """The gate classifies a task and has side-effects only for CONFIRM/DOWNGRADE."""

    def test_below_threshold_returns_race(self, tmp_path: pathlib.Path) -> None:
        # baseline 75_000 × 2 candidates = 150_000 → well below 200_000.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=75_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t_race", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        gate = executor._dispatch_race_gate(task, specs)
        assert gate == race.RaceGate.RACE
        # No side-effect: no CONFIRM task added, parent stays PENDING.
        assert executor._queue.get_task(f"{race.RACE_CONFIRM_PREFIX}t_race") is None
        assert executor._queue.get_task(task.id).status == TaskStatus.PENDING

    def test_above_threshold_emits_confirm_and_blocks_parent(self, tmp_path: pathlib.Path) -> None:
        # baseline 150_000 × 2 = 300_000 → above confirm (200_000), under budget (500_000).
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=150_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t_confirm", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        gate = executor._dispatch_race_gate(task, specs)
        assert gate == race.RaceGate.CONFIRM

        confirm = executor._queue.get_task(f"{race.RACE_CONFIRM_PREFIX}t_confirm")
        assert confirm is not None
        assert confirm.category == TaskCategory.CONFIRM
        assert confirm.status == TaskStatus.BLOCKED
        # Description mentions the estimate and candidate names so the user
        # can weigh the spend rather than guessing.
        assert "300,000" in confirm.description
        assert "primary-model" in confirm.description
        assert "light-model" in confirm.description
        # Parent is blocked awaiting the confirmation.
        parent = executor._queue.get_task(task.id)
        assert parent.status == TaskStatus.BLOCKED
        assert "confirmation" in (parent.blocked_reason or "")

    def test_emit_confirm_is_idempotent(self, tmp_path: pathlib.Path) -> None:
        # Re-dispatching the same task should not duplicate the CONFIRM task.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=150_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t_idem", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        executor._dispatch_race_gate(task, specs)
        executor._dispatch_race_gate(task, specs)

        confirms = [
            t for t in executor._queue.all_tasks() if t.id.startswith(race.RACE_CONFIRM_PREFIX)
        ]
        assert len(confirms) == 1

    def test_over_budget_returns_downgrade(self, tmp_path: pathlib.Path) -> None:
        # baseline 400_000 × 2 = 800_000 → over budget (500_000).  The gate
        # returns DOWNGRADE and emits no CONFIRM task; caller falls through
        # to the single-subagent path.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=400_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t_over", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        gate = executor._dispatch_race_gate(task, specs)
        assert gate == race.RaceGate.DOWNGRADE
        assert executor._queue.get_task(f"{race.RACE_CONFIRM_PREFIX}t_over") is None
        assert executor._queue.get_task(task.id).status == TaskStatus.PENDING

    def test_prior_approval_skips_threshold_check(self, tmp_path: pathlib.Path) -> None:
        # An approved ``race_decision`` returns RACE even when the estimate
        # would normally cross the confirm threshold.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=200_000,
            confirm_threshold_tokens=100_000,
            budget_tokens=1_000_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(
            id="t_approved",
            title="Build",
            category=TaskCategory.BUILD,
            race_decision="approved",
        )
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        assert executor._dispatch_race_gate(task, specs) == race.RaceGate.RACE
        # No CONFIRM task emitted.
        assert executor._queue.get_task(f"{race.RACE_CONFIRM_PREFIX}t_approved") is None

    def test_prior_decline_returns_downgrade(self, tmp_path: pathlib.Path) -> None:
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=75_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(
            id="t_declined",
            title="Build",
            category=TaskCategory.BUILD,
            race_decision="declined",
        )
        executor._queue.add_task(task)

        specs = executor._race_candidate_specs()
        assert executor._dispatch_race_gate(task, specs) == race.RaceGate.DOWNGRADE


# ---------------------------------------------------------------------------
# _execute_task — full gate-to-coordinator integration
# ---------------------------------------------------------------------------


class TestExecuteTaskGateIntegration:
    """Gate + ``_execute_task`` behave as one unit."""

    @pytest.mark.asyncio
    async def test_confirm_gate_defers_race(self, tmp_path: pathlib.Path) -> None:
        # When the estimate exceeds the confirm threshold, _execute_task
        # blocks the parent and emits a CONFIRM, then returns without
        # calling the coordinator.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=150_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="td1", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        mock = AsyncMock()
        executor._race_coordinator.run = mock  # type: ignore[method-assign]
        await executor._execute_task(task)

        mock.assert_not_awaited()
        assert executor._queue.get_task(task.id).status == TaskStatus.BLOCKED
        assert executor._queue.get_task(f"{race.RACE_CONFIRM_PREFIX}td1") is not None

    @pytest.mark.asyncio
    async def test_downgrade_gate_runs_single_subagent(self, tmp_path: pathlib.Path) -> None:
        # When the estimate is over budget the coordinator is NOT called;
        # the single-subagent path runs instead.  Verify via the subagent
        # patch target rather than _execute_race.
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            baseline_tokens_per_run=400_000,
            confirm_threshold_tokens=200_000,
            budget_tokens=500_000,
        )
        executor = _make_executor(
            _make_allocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="td2", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        coord = AsyncMock()
        executor._race_coordinator.run = coord  # type: ignore[method-assign]

        subagent_mock = AsyncMock()
        subagent_mock.run = AsyncMock(
            return_value=SubagentResult(ExitState.COMPLETED, "done", "ok")
        )
        merge = AsyncMock(return_value=None)
        with (
            patch("cantrip.agent.executor.core.Subagent", return_value=subagent_mock),
            patch.object(executor, "_merge_worktree", merge),
        ):
            await executor._execute_task(task)

        # Race coordinator never called — downgrade fell through.
        coord.assert_not_awaited()
        # Subagent was constructed and run exactly once.
        subagent_mock.run.assert_awaited_once()


# ---------------------------------------------------------------------------
# _execute_race — end-to-end paths
# ---------------------------------------------------------------------------


async def _stub_coordinator_run(
    executor: BackgroundExecutor,
    result_factory: Any,
) -> AsyncMock:
    """Replace the executor's coordinator.run with an ``AsyncMock``."""
    mock = AsyncMock(side_effect=result_factory)
    executor._race_coordinator.run = mock  # type: ignore[method-assign]
    return mock


class TestExecuteRaceWinnerMerged:
    @pytest.mark.asyncio
    async def test_winner_merged_and_task_done(self, tmp_path: pathlib.Path) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        winner_handle = _handle("t1__primary-model", tmp_path)
        winner_score = race.CandidateScore(
            candidate_id="primary-model",
            exit_state=ExitState.COMPLETED,
            total=0.8,
        )
        loser_score = race.CandidateScore(
            candidate_id="light-model",
            exit_state=ExitState.FAILED,
            total=0.0,
        )
        winner_outcome = race.CandidateOutcome(
            spec=race.CandidateSpec(
                candidate_id="primary-model",
                provider=executor._provider,
            ),
            handle=winner_handle,
            result=SubagentResult(ExitState.COMPLETED, "done", "all finished"),
        )
        loser_outcome = race.CandidateOutcome(
            spec=race.CandidateSpec(
                candidate_id="light-model",
                provider=executor._provider,
            ),
            handle=None,
            result=SubagentResult(ExitState.FAILED, "oops"),
        )
        race_result = race.RaceResult(
            task_id="t1",
            winner=winner_score,
            all_scores=[winner_score, loser_score],
            all_outcomes=[winner_outcome, loser_outcome],
            elapsed_seconds=1.2,
        )

        merge = AsyncMock(return_value=None)
        await _stub_coordinator_run(executor, lambda **_: race_result)
        with patch.object(executor, "_merge_worktree", merge):
            await executor._execute_task(task)

        merge.assert_awaited_once()
        # Winner's composite worktree released, branch dropped (merge ok).
        assert ReleaseCall("t1__primary-model", False) in allocator.release_calls
        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.DONE
        assert final.result == "all finished"

    @pytest.mark.asyncio
    async def test_merge_error_blocks_and_keeps_branch(self, tmp_path: pathlib.Path) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t2", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        winner_handle = _handle("t2__primary-model", tmp_path)
        winner_score = race.CandidateScore(
            candidate_id="primary-model",
            exit_state=ExitState.COMPLETED,
            total=0.9,
        )
        winner_outcome = race.CandidateOutcome(
            spec=race.CandidateSpec(
                candidate_id="primary-model",
                provider=executor._provider,
            ),
            handle=winner_handle,
            result=SubagentResult(ExitState.COMPLETED, "done"),
        )
        race_result = race.RaceResult(
            task_id="t2",
            winner=winner_score,
            all_scores=[winner_score],
            all_outcomes=[winner_outcome],
            elapsed_seconds=0.5,
        )

        merge = AsyncMock(return_value="Main tree has uncommitted changes")
        await _stub_coordinator_run(executor, lambda **_: race_result)
        with patch.object(executor, "_merge_worktree", merge):
            await executor._execute_task(task)

        # Merge error keeps the branch.
        assert ReleaseCall("t2__primary-model", True) in allocator.release_calls
        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.BLOCKED
        assert "uncommitted changes" in (final.blocked_reason or "")


class TestExecuteRaceNoWinner:
    @pytest.mark.asyncio
    async def test_all_candidates_failed_marks_task_failed(self, tmp_path: pathlib.Path) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t3", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        race_result = race.RaceResult(
            task_id="t3",
            winner=None,
            all_scores=[
                race.CandidateScore(
                    candidate_id="primary-model",
                    exit_state=ExitState.FAILED,
                    total=0.0,
                ),
                race.CandidateScore(
                    candidate_id="light-model",
                    exit_state=ExitState.FAILED,
                    total=0.0,
                ),
            ],
            all_outcomes=[],
            elapsed_seconds=0.1,
        )

        merge = AsyncMock()
        await _stub_coordinator_run(executor, lambda **_: race_result)
        with patch.object(executor, "_merge_worktree", merge):
            await executor._execute_task(task)

        merge.assert_not_awaited()
        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_coordinator_raise_fails_task(self, tmp_path: pathlib.Path) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t4", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        def _raise(**_: Any) -> None:
            raise RuntimeError("kaboom")

        await _stub_coordinator_run(executor, _raise)
        await executor._execute_task(task)

        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.FAILED
        assert "kaboom" in (final.blocked_reason or final.result or "")


class TestExecuteRaceBudgetMidflight:
    """Phase 47.4 follow-up — mid-flight budget cancellation downgrades cleanly."""

    @pytest.mark.asyncio
    async def test_cancelled_for_budget_resets_task_and_records_event(
        self, tmp_path: pathlib.Path
    ) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            budget_tokens=500_000,
        )
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        events: list[tuple[str, dict[str, str]]] = []

        class _FakeStateService:
            def record_event(self, name: str, payload: dict[str, str]) -> None:
                events.append((name, payload))

            def save_tasks(self, _tasks: list[object]) -> None:  # noqa: ARG002
                pass

        executor._state_service = _FakeStateService()

        task = AgentTask(id="t-mid", title="Build a thing", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        race_result = race.RaceResult(
            task_id="t-mid",
            winner=None,
            all_scores=[],
            all_outcomes=[],
            elapsed_seconds=0.1,
            cancelled_for_budget=True,
            total_tokens_at_cancel=750_000,
        )
        await _stub_coordinator_run(executor, lambda **_: race_result)

        merge = AsyncMock()
        with patch.object(executor, "_merge_worktree", merge):
            await executor._execute_task(task)

        merge.assert_not_awaited()
        final = executor._queue.get_task(task.id)
        # Task is *not* failed — it's reset to PENDING for the executor
        # to re-pick up under the single-subagent path.
        assert final.status == TaskStatus.PENDING
        # ``race_decision`` flipped to ``declined`` so the next pass
        # through ``_dispatch_race_gate`` falls straight through to
        # ``RaceGate.DOWNGRADE`` without re-prompting the user.
        assert final.race_decision == "declined"
        # A downgrade event was recorded with the mid-flight reason and
        # the actual aggregate token count (not the dispatch estimate).
        downgrade_events = [(n, p) for n, p in events if n == "race_downgraded"]
        assert len(downgrade_events) == 1
        _, payload = downgrade_events[0]
        assert payload["reason"] == "over_budget_midflight"
        assert payload["estimate_tokens"] == "750000"
        assert payload["budget_tokens"] == "500000"

    @pytest.mark.asyncio
    async def test_non_cancelled_run_takes_normal_path(self, tmp_path: pathlib.Path) -> None:
        """A race that completes normally (cancelled_for_budget=False) follows the no-winner path."""
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(
            enabled_categories=frozenset({TaskCategory.BUILD}),
            budget_tokens=1_000_000,
        )
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t-ok", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        # A regular no-winner result (every candidate FAILED) must
        # still drive the task to FAILED — not get caught by the new
        # cancelled-for-budget branch.
        race_result = race.RaceResult(
            task_id="t-ok",
            winner=None,
            all_scores=[
                race.CandidateScore(
                    candidate_id="primary-model",
                    exit_state=ExitState.FAILED,
                    total=0.0,
                ),
            ],
            all_outcomes=[],
            elapsed_seconds=0.1,
            cancelled_for_budget=False,
        )
        await _stub_coordinator_run(executor, lambda **_: race_result)

        await executor._execute_task(task)

        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.FAILED


class TestExecuteRaceBlockedWinner:
    @pytest.mark.asyncio
    async def test_blocked_winner_preserves_branch_does_not_merge(
        self, tmp_path: pathlib.Path
    ) -> None:
        allocator = _make_allocator(tmp_path)
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            allocator,
            charm_path=tmp_path,
            light_provider=_named_provider("light-model"),
            race_config=config,
        )
        task = AgentTask(id="t5", title="Build", category=TaskCategory.BUILD)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        winner_handle = _handle("t5__primary-model", tmp_path)
        winner_score = race.CandidateScore(
            candidate_id="primary-model",
            exit_state=ExitState.BLOCKED,
            total=0.3,
        )
        winner_outcome = race.CandidateOutcome(
            spec=race.CandidateSpec(
                candidate_id="primary-model",
                provider=executor._provider,
            ),
            handle=winner_handle,
            result=SubagentResult(ExitState.BLOCKED, "need more info"),
        )
        race_result = race.RaceResult(
            task_id="t5",
            winner=winner_score,
            all_scores=[winner_score],
            all_outcomes=[winner_outcome],
            elapsed_seconds=0.3,
        )

        merge = AsyncMock()
        await _stub_coordinator_run(executor, lambda **_: race_result)
        with patch.object(executor, "_merge_worktree", merge):
            await executor._execute_task(task)

        merge.assert_not_awaited()
        # Keep the branch so the user can inspect the blocked work.
        assert ReleaseCall("t5__primary-model", True) in allocator.release_calls
        assert executor._queue.get_task(task.id).status == TaskStatus.BLOCKED


# ---------------------------------------------------------------------------
# Transcript namespacing via the subagent factory
# ---------------------------------------------------------------------------


class TestSubagentFactoryTranscript:
    @pytest.mark.asyncio
    async def test_factory_gives_candidate_its_own_task_id(self, tmp_path: pathlib.Path) -> None:
        """The shadow task id is ``parent__candidate`` so each candidate's
        subagent_messages land in their own partition of the store."""
        allocator = _make_allocator(tmp_path)
        executor = _make_executor(allocator, charm_path=tmp_path)
        parent = AgentTask(id="p1", title="Build", category=TaskCategory.BUILD)

        factory = executor._build_race_subagent_factory(parent)
        spec = race.CandidateSpec(
            candidate_id="gemini-pro",
            provider=executor._provider,
        )
        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_cls.return_value = object()
            await factory(spec, tmp_path, None)

        # The Subagent was constructed with a context whose task.id is the
        # composite id, so the subagent's record_subagent_message calls
        # land under that id.
        context = mock_cls.call_args[0][0]
        assert context.task.id == "p1__gemini-pro"
        # The parent task is unchanged.
        assert parent.id == "p1"

    @pytest.mark.asyncio
    async def test_factory_does_not_mutate_parent_task(self, tmp_path: pathlib.Path) -> None:
        """``dataclasses.replace`` must not alter the queue's parent task."""
        executor = _make_executor(_make_allocator(tmp_path), charm_path=tmp_path)
        parent = AgentTask(id="p2", title="Build", category=TaskCategory.BUILD)
        snapshot = dataclasses.asdict(parent)

        factory = executor._build_race_subagent_factory(parent)
        spec = race.CandidateSpec(candidate_id="m1", provider=executor._provider)
        with patch("cantrip.agent.executor.core.Subagent"):
            await factory(spec, tmp_path, None)

        assert dataclasses.asdict(parent) == snapshot
