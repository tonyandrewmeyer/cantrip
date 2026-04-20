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

from cantrip.agent import race
from cantrip.agent.executor import BackgroundExecutor, _candidate_id_for
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.worktree import WorktreeHandle
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str) -> Tool:
    class _Stub(Tool):
        @property
        def name(self) -> str:
            return name

        @property
        def description(self) -> str:
            return name

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            return ToolResult(success=True, output="ok")

    return _Stub()


def _handle(task_id: str, base_path: pathlib.Path | str) -> WorktreeHandle:
    path = pathlib.Path(base_path) / ".cantrip-worktrees" / task_id
    return WorktreeHandle(
        task_id=task_id,
        path=path,
        branch=f"cantrip/wt/{task_id}",
        base_sha="0" * 40,
    )


class FakeAllocator:
    """In-memory worktree allocator shared by every race test in this module.

    Accepts allocate calls keyed by any string (the coordinator passes
    composite ``{task_id}__{candidate_id}`` keys), and records every
    release for assertion.  Returns a handle unless allocation is
    disabled — non-git scenarios are covered elsewhere.
    """

    def __init__(self, base_path: pathlib.Path) -> None:
        self._base = base_path
        self._handles: dict[str, WorktreeHandle] = {}
        self.alloc_calls: list[str] = []
        self.release_calls: list[tuple[str, bool]] = []

    async def allocate(
        self,
        task_id: str,
        base_path: pathlib.Path | str,  # noqa: ARG002
    ) -> WorktreeHandle | None:
        self.alloc_calls.append(task_id)
        handle = _handle(task_id, self._base)
        handle.path.mkdir(parents=True, exist_ok=True)
        self._handles[task_id] = handle
        return handle

    async def release(self, task_id: str, *, keep_branch: bool = False) -> None:
        self.release_calls.append((task_id, keep_branch))
        self._handles.pop(task_id, None)

    def get(self, task_id: str) -> WorktreeHandle | None:
        return self._handles.get(task_id)

    def all_worktrees(self) -> dict[str, WorktreeHandle]:
        return dict(self._handles)

    async def reap_orphans(self, active_task_ids: set[str]) -> int:  # noqa: ARG002
        return 0


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
        executor = _make_executor(FakeAllocator(tmp_path), charm_path=tmp_path)
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model"]

    def test_primary_and_light_yield_two_specs(self, tmp_path: pathlib.Path) -> None:
        light = _named_provider("light-model")
        executor = _make_executor(
            FakeAllocator(tmp_path),
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
            FakeAllocator(tmp_path),
            charm_path=tmp_path,
            light_provider=light,
        )
        specs = executor._race_candidate_specs()
        assert [s.candidate_id for s in specs] == ["primary-model"]

    def test_extra_providers_appended_in_order(self, tmp_path: pathlib.Path) -> None:
        extras = [_named_provider("gemini-pro"), _named_provider("gpt-4o")]
        executor = _make_executor(
            FakeAllocator(tmp_path),
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
            FakeAllocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light"),
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is False

    def test_enabled_with_two_candidates(self, tmp_path: pathlib.Path) -> None:
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            FakeAllocator(tmp_path),
            charm_path=tmp_path,
            light_provider=_named_provider("light"),
            race_config=config,
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is True

    def test_disabled_without_charm_path(self, tmp_path: pathlib.Path) -> None:
        config = race.RaceConfig(enabled_categories=frozenset({TaskCategory.BUILD}))
        executor = _make_executor(
            FakeAllocator(tmp_path),
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
            FakeAllocator(tmp_path),
            charm_path=tmp_path,
            race_config=config,
        )
        task = AgentTask(title="Build it", category=TaskCategory.BUILD)
        assert executor._should_race(task, executor._race_candidate_specs()) is False


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
        allocator = FakeAllocator(tmp_path)
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
        assert ("t1__primary-model", False) in allocator.release_calls
        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.DONE
        assert final.result == "all finished"

    @pytest.mark.asyncio
    async def test_merge_error_blocks_and_keeps_branch(self, tmp_path: pathlib.Path) -> None:
        allocator = FakeAllocator(tmp_path)
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
        assert ("t2__primary-model", True) in allocator.release_calls
        final = executor._queue.get_task(task.id)
        assert final.status == TaskStatus.BLOCKED
        assert "uncommitted changes" in (final.blocked_reason or "")


class TestExecuteRaceNoWinner:
    @pytest.mark.asyncio
    async def test_all_candidates_failed_marks_task_failed(self, tmp_path: pathlib.Path) -> None:
        allocator = FakeAllocator(tmp_path)
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
        allocator = FakeAllocator(tmp_path)
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


class TestExecuteRaceBlockedWinner:
    @pytest.mark.asyncio
    async def test_blocked_winner_preserves_branch_does_not_merge(
        self, tmp_path: pathlib.Path
    ) -> None:
        allocator = FakeAllocator(tmp_path)
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
        assert ("t5__primary-model", True) in allocator.release_calls
        assert executor._queue.get_task(task.id).status == TaskStatus.BLOCKED


# ---------------------------------------------------------------------------
# Transcript namespacing via the subagent factory
# ---------------------------------------------------------------------------


class TestSubagentFactoryTranscript:
    @pytest.mark.asyncio
    async def test_factory_gives_candidate_its_own_task_id(self, tmp_path: pathlib.Path) -> None:
        """The shadow task id is ``parent__candidate`` so each candidate's
        subagent_messages land in their own partition of the store."""
        allocator = FakeAllocator(tmp_path)
        executor = _make_executor(allocator, charm_path=tmp_path)
        parent = AgentTask(id="p1", title="Build", category=TaskCategory.BUILD)

        factory = executor._build_race_subagent_factory(parent)
        spec = race.CandidateSpec(
            candidate_id="gemini-pro",
            provider=executor._provider,
        )
        with patch("cantrip.agent.executor.Subagent") as mock_cls:
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
        executor = _make_executor(FakeAllocator(tmp_path), charm_path=tmp_path)
        parent = AgentTask(id="p2", title="Build", category=TaskCategory.BUILD)
        snapshot = dataclasses.asdict(parent)

        factory = executor._build_race_subagent_factory(parent)
        spec = race.CandidateSpec(candidate_id="m1", provider=executor._provider)
        with patch("cantrip.agent.executor.Subagent"):
            await factory(spec, tmp_path, None)

        assert dataclasses.asdict(parent) == snapshot
