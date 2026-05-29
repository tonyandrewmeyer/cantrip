"""Executor tests: errors."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.executor import (
    _MAX_CONSECUTIVE_ERRORS,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import ExitState, SubagentResult
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.unit.executor.conftest import _make_executor

# ===================================================================
# TestExitStateHandling
# ===================================================================


class TestExitStateHandling:
    """Tests for structured subagent exit state handling."""

    @pytest.mark.asyncio
    async def test_blocked_exit_blocks_task(self) -> None:
        """Subagent signalling BLOCKED causes the task to be blocked."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        on_failed = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=on_failed)

        result = SubagentResult(ExitState.BLOCKED, "Need database credentials")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.BLOCKED
        on_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_exit_fails_task(self) -> None:
        """Subagent signalling FAILED causes the task to fail."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        on_failed = MagicMock()
        executor = _make_executor(queue=queue, state=state, on_task_failed=on_failed)

        result = SubagentResult(ExitState.FAILED, "charmcraft pack error", "Full error details")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.FAILED
        assert "Full error details" in (task.result or "")
        on_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_exit_triggers_noop_handling(self) -> None:
        """Subagent signalling NOOP triggers the noop counter."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        result = SubagentResult(ExitState.NOOP, "Nothing to do")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", return_value="different"),
            patch.object(executor, "_snapshot_head", return_value="abc123"),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.PENDING
        assert task.noop_count == 1

    @pytest.mark.asyncio
    async def test_completed_exit_marks_done(self) -> None:
        """Subagent signalling COMPLETED marks the task as done."""
        state = AgentState(charm_path="/tmp/charm")
        queue = WorkQueue()
        task = AgentTask(id="r1", title="Research", category=TaskCategory.RESEARCH)
        queue.add_task(task)
        queue.set_active(task.id)

        executor = _make_executor(queue=queue, state=state)

        result = SubagentResult(ExitState.COMPLETED, "Research complete", "Found 3 sources")
        with (
            patch("cantrip.agent.executor.core.Subagent") as mock_cls,
            patch.object(executor, "_fingerprint", side_effect=["a", "b"]),
        ):
            instance = mock_cls.return_value
            instance.run = AsyncMock(return_value=result)
            await executor._execute_task(task)

        assert task.status == TaskStatus.DONE
        assert task.result == "Found 3 sources"


# ===================================================================
# TestExecutorErrorResilience
# ===================================================================


class TestExecutorErrorResilience:
    """Tests for the executor's self-healing behaviour under unexpected errors."""

    @pytest.mark.asyncio
    async def test_survives_unexpected_exception(self) -> None:
        """The executor continues running after an unexpected exception type."""
        executor = _make_executor()
        call_count = 0

        original_route = None

        async def _patched_run_loop() -> None:
            """Simulate a loop that raises TypeError once then stops."""
            nonlocal call_count
            # Re-use the real _run_loop but patch `route` to raise once.
            from cantrip.agent.executor import core as mod

            nonlocal original_route
            original_route = mod.route

            def _bad_route(snapshot: Any) -> Any:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise TypeError("unexpected type error")
                # Stop the loop after surviving the error.
                executor._running = False
                return original_route(snapshot)

            with (
                patch.object(mod, "route", side_effect=_bad_route),
                patch("cantrip.agent.executor.core._ERROR_COOLDOWN", 0),
            ):
                await executor._run_loop()

        executor._running = True
        await _patched_run_loop()

        # The loop ran at least twice — it survived the first error.
        assert call_count >= 2
        assert executor._consecutive_errors == 0  # Reset on success.

    @pytest.mark.asyncio
    async def test_consecutive_errors_stops_loop(self) -> None:
        """The executor stops after reaching the max consecutive error threshold."""
        executor = _make_executor()

        from cantrip.agent.executor import core as mod

        def _always_fail(snapshot: Any) -> Any:  # noqa: ARG001
            raise ValueError("persistent failure")

        executor._running = True
        with (
            patch.object(mod, "route", side_effect=_always_fail),
            patch("cantrip.agent.executor.core._ERROR_COOLDOWN", 0),
        ):
            await executor._run_loop()

        assert executor._consecutive_errors >= _MAX_CONSECUTIVE_ERRORS
        # The loop should have broken out; _running may still be True
        # because the loop exited via break, not by setting _running = False.

    @pytest.mark.asyncio
    async def test_consecutive_errors_reset_on_success(self) -> None:
        """The error counter resets to zero after a successful iteration."""
        executor = _make_executor()

        from cantrip.agent.executor import core as mod

        call_count = 0

        def _fail_then_succeed(snapshot: Any) -> Any:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RuntimeError("transient error")
            # Stop the loop on success.
            executor._running = False
            return mod.routing.RoutingDecision(
                action=mod.RouteAction.IDLE,
            )

        executor._running = True
        with (
            patch.object(mod, "route", side_effect=_fail_then_succeed),
            patch("cantrip.agent.executor.core._ERROR_COOLDOWN", 0),
            patch("cantrip.agent.executor.core._POLL_INTERVAL", 0),
        ):
            await executor._run_loop()

        # Counter was reset on the successful iteration.
        assert executor._consecutive_errors == 0
        assert call_count == 4

    def test_healthy_property_true_when_running(self) -> None:
        """Healthy is True when running with no errors."""
        executor = _make_executor()
        executor._running = True
        executor._consecutive_errors = 0
        assert executor.healthy is True

    def test_healthy_property_false_when_not_running(self) -> None:
        """Healthy is False when the executor is not running."""
        executor = _make_executor()
        assert executor.healthy is False

    def test_healthy_property_false_at_error_threshold(self) -> None:
        """Healthy is False when consecutive errors reach the threshold."""
        executor = _make_executor()
        executor._running = True
        executor._consecutive_errors = _MAX_CONSECUTIVE_ERRORS
        assert executor.healthy is False

    def test_healthy_property_true_below_threshold(self) -> None:
        """Healthy is True when errors are below the threshold."""
        executor = _make_executor()
        executor._running = True
        executor._consecutive_errors = _MAX_CONSECUTIVE_ERRORS - 1
        assert executor.healthy is True


class TestUsageRecordingProviderIdentity:
    """Usage recording should reflect the actual provider used, not always the primary."""

    def test_record_usage_uses_metadata_provider(self) -> None:
        """When the response has _provider_name/_provider_model metadata, use those."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        executor = _make_executor(store=store)

        response = Response(
            content="done",
            usage={"prompt_tokens": 100, "completion_tokens": 20},
            metadata={
                "_provider_name": "claude",
                "_provider_model": "claude-haiku-4-5-20251001",
            },
        )
        executor._record_usage(response)

        store.record_usage.assert_called_once_with(
            provider="claude",
            model="claude-haiku-4-5-20251001",
            prompt_tokens=100,
            completion_tokens=20,
            category=None,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )

    def test_record_usage_falls_back_to_primary(self) -> None:
        """Without metadata, falls back to the primary provider identity."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        primary = FakeProvider(responses=[Response(content="done")])
        executor = _make_executor(store=store, provider=primary)

        response = Response(
            content="done",
            usage={"prompt_tokens": 50, "completion_tokens": 10},
        )
        executor._record_usage(response)

        store.record_usage.assert_called_once_with(
            provider=primary.name,
            model=primary.model_name,
            prompt_tokens=50,
            completion_tokens=10,
            category=None,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )

    def test_record_usage_passes_task_category(self) -> None:
        """The subagent stamps ``_task_category`` into metadata (Phase 31.4)."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        executor = _make_executor(store=store)

        response = Response(
            content="done",
            usage={"prompt_tokens": 100, "completion_tokens": 20},
            metadata={
                "_provider_name": "claude",
                "_provider_model": "claude-haiku-4-5-20251001",
                "_task_category": "build",
            },
        )
        executor._record_usage(response)

        store.record_usage.assert_called_once_with(
            provider="claude",
            model="claude-haiku-4-5-20251001",
            prompt_tokens=100,
            completion_tokens=20,
            category="build",
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )

    def test_record_usage_ignores_non_string_category(self) -> None:
        """Metadata may be round-tripped from JSON; defensively reject non-strings."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        primary = FakeProvider(responses=[Response(content="done")])
        executor = _make_executor(store=store, provider=primary)

        response = Response(
            content="done",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            metadata={"_task_category": 42},  # Not a string — treat as None.
        )
        executor._record_usage(response)

        assert store.record_usage.call_args.kwargs["category"] is None

    def test_record_usage_persists_and_forwards_cache_tokens(self) -> None:
        """Subagent prompt-cache tokens are persisted and folded into the session totals."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        folded: list[tuple[int, int]] = []
        executor = _make_executor(
            store=store,
            on_cache_usage=lambda creation, read: folded.append((creation, read)),
        )

        response = Response(
            content="done",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cache_read_input_tokens": 7000,
                "cache_creation_input_tokens": 1500,
            },
            metadata={"_provider_name": "claude", "_provider_model": "claude-opus-4-7"},
        )
        executor._record_usage(response)

        # Persisted to the store with the cache breakdown.
        kwargs = store.record_usage.call_args.kwargs
        assert kwargs["cache_read_tokens"] == 7000
        assert kwargs["cache_creation_tokens"] == 1500
        # Folded into the session accumulators as (creation, read).
        assert folded == [(1500, 7000)]

    def test_record_usage_skips_cache_callback_when_no_cache(self) -> None:
        """A turn with no cache activity does not invoke the cache callback."""
        store = MagicMock()
        store.record_event = MagicMock()
        store.record_usage = MagicMock()
        store.save_tasks = MagicMock()

        folded: list[tuple[int, int]] = []
        executor = _make_executor(
            store=store,
            on_cache_usage=lambda creation, read: folded.append((creation, read)),
        )

        response = Response(content="done", usage={"prompt_tokens": 10, "completion_tokens": 5})
        executor._record_usage(response)

        assert folded == []


class TestPermissionCallbackErrorSwallowing:
    """``_on_permission_decided`` must never let a UI-callback bug crash the loop.

    The contract is documented on the method itself: a broken hook can
    never propagate, only log.  Without this regression test, narrowing
    the catch (or removing it altogether) would silently re-introduce
    the crash.
    """

    def _decision(self):
        from cantrip.agent.safety.permissions import PermissionDecision, PermissionOutcome

        return PermissionDecision(outcome=PermissionOutcome.ALLOW, reason="test")

    def test_no_callback_is_a_noop(self) -> None:
        executor = _make_executor()
        # Default is no callback; method must not raise.
        executor._on_permission_decided("read_file", self._decision(), {"path": "x"})

    def test_callback_typeerror_is_swallowed(self, caplog) -> None:
        import logging

        executor = _make_executor()

        def _broken(_tool, _decision, _args):
            raise TypeError("bad signature")

        executor.set_permission_callback(_broken)
        with caplog.at_level(logging.ERROR, logger="cantrip.agent.executor.core"):
            executor._on_permission_decided("read_file", self._decision(), {"path": "x"})

        assert any("permission_callback raised" in r.getMessage() for r in caplog.records)

    def test_callback_runtimeerror_is_swallowed(self, caplog) -> None:
        import logging

        executor = _make_executor()

        def _broken(_tool, _decision, _args):
            raise RuntimeError("hook lost its mind")

        executor.set_permission_callback(_broken)
        with caplog.at_level(logging.ERROR, logger="cantrip.agent.executor.core"):
            executor._on_permission_decided("read_file", self._decision(), {"path": "x"})

        assert any("permission_callback raised" in r.getMessage() for r in caplog.records)
