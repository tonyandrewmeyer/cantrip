"""Tests for the Phase 55.3 per-goal goal_budget primitive."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest

from cantrip.agent.goal_budget import (
    BudgetUsage,
    GoalBudget,
    check_budget,
    format_summary,
    measure_usage,
)
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore

if TYPE_CHECKING:
    import pathlib


@pytest.fixture
def store(tmp_path: pathlib.Path) -> SessionStore:
    db = tmp_path / ".cantrip"
    store = SessionStore(db)
    store.open()
    # Seed a baseline session row so ``record_usage`` can associate.
    store.save_session(AgentState(charm_name="x", charm_path=tmp_path))
    return store


def _t(offset_seconds: int) -> str:
    """Return a ``datetime('now')``-shaped timestamp *offset_seconds* from 2026-01-01."""
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return (base + datetime.timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")


class TestGoalBudgetDataclass:
    def test_defaults_have_no_caps(self) -> None:
        budget = GoalBudget()
        assert budget.max_iterations is None
        assert budget.max_prompt_tokens is None
        assert budget.max_completion_tokens is None

    def test_started_at_matches_sqlite_shape(self) -> None:
        """``started_at`` must match SQLite's ``datetime('now')`` format
        so ``WHERE timestamp >= ?`` comparisons against the
        token_usage table work lexicographically."""
        budget = GoalBudget()
        # Parseable with the exact SQLite-compatible strftime format.
        datetime.datetime.strptime(budget.started_at, "%Y-%m-%d %H:%M:%S")

    def test_is_mutable(self) -> None:
        """Callers raise caps in place via ``/budget`` — no new instance."""
        budget = GoalBudget(max_iterations=10)
        budget.max_iterations = 50
        assert budget.max_iterations == 50


class TestMeasureUsage:
    def test_returns_usage_snapshot(self, store: SessionStore) -> None:
        budget = GoalBudget(started_at=_t(0))
        store.record_usage(
            provider="fake",
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
        )
        store.record_usage(
            provider="fake",
            model="fake-model",
            prompt_tokens=200,
            completion_tokens=80,
        )
        usage = measure_usage(store, budget)
        assert usage == BudgetUsage(iterations=2, prompt_tokens=300, completion_tokens=130)

    def test_empty_store_returns_zero(self, store: SessionStore) -> None:
        budget = GoalBudget(started_at=_t(0))
        usage = measure_usage(store, budget)
        assert usage == BudgetUsage(iterations=0, prompt_tokens=0, completion_tokens=0)


class TestCheckBudget:
    def test_no_caps_never_trips(self, store: SessionStore) -> None:
        budget = GoalBudget(started_at=_t(0))
        for _ in range(5):
            store.record_usage(
                provider="fake",
                model="fake-model",
                prompt_tokens=10_000,
                completion_tokens=10_000,
            )
        assert check_budget(store, budget) is None

    def test_iteration_cap_trips(self, store: SessionStore) -> None:
        budget = GoalBudget(max_iterations=3, started_at=_t(0))
        for _ in range(3):
            store.record_usage(
                provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
            )
        reason = check_budget(store, budget)
        assert reason is not None
        assert "iterations" in reason.lower()
        assert "3" in reason

    def test_iteration_cap_clears_below(self, store: SessionStore) -> None:
        budget = GoalBudget(max_iterations=5, started_at=_t(0))
        for _ in range(2):
            store.record_usage(
                provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
            )
        assert check_budget(store, budget) is None

    def test_prompt_token_cap_trips(self, store: SessionStore) -> None:
        budget = GoalBudget(max_prompt_tokens=100, started_at=_t(0))
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=150, completion_tokens=10
        )
        reason = check_budget(store, budget)
        assert reason is not None
        assert "prompt" in reason.lower()

    def test_completion_token_cap_trips(self, store: SessionStore) -> None:
        budget = GoalBudget(max_completion_tokens=50, started_at=_t(0))
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=10, completion_tokens=100
        )
        reason = check_budget(store, budget)
        assert reason is not None
        assert "completion" in reason.lower()

    def test_raising_cap_clears_trip(self, store: SessionStore) -> None:
        """Once the operator raises the cap via ``/budget``, the next
        check passes — the whole point of the "raise clears" flow."""
        budget = GoalBudget(max_iterations=1, started_at=_t(0))
        store.record_usage(
            provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
        )
        assert check_budget(store, budget) is not None

        budget.max_iterations = 10
        assert check_budget(store, budget) is None

    def test_usage_before_started_at_is_ignored(self, store: SessionStore) -> None:
        """A new goal budget only counts work done since it started.

        Without this, resuming a session with a budget would
        immediately trip on work done under the previous run — the
        whole point of the per-goal scope.
        """
        # Record a lot of usage with the store's ``datetime('now')``
        # default timestamp — treated as "before" the budget below.
        import time as time_mod

        for _ in range(10):
            store.record_usage(
                provider="fake", model="fake-model", prompt_tokens=1, completion_tokens=1
            )
        # Sleep one second so SQLite ``datetime('now')`` advances past
        # the budget start we stamp next.
        time_mod.sleep(1.1)
        started = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        budget = GoalBudget(max_iterations=2, started_at=started)
        # No usage after ``started``, so the cap is not tripped even
        # though historical usage would blow it.
        assert check_budget(store, budget) is None


class TestFormatSummary:
    def test_uncapped_axes_labelled(self) -> None:
        budget = GoalBudget()
        usage = BudgetUsage(iterations=3, prompt_tokens=100, completion_tokens=50)
        summary = format_summary(budget, usage)
        assert "uncapped" in summary
        assert "3" in summary

    def test_capped_axes_show_ratio(self) -> None:
        budget = GoalBudget(
            max_iterations=10,
            max_prompt_tokens=5000,
            max_completion_tokens=2500,
        )
        usage = BudgetUsage(iterations=4, prompt_tokens=2000, completion_tokens=1000)
        summary = format_summary(budget, usage)
        assert "4/10" in summary
        assert "2,000/5,000" in summary
        assert "1,000/2,500" in summary


class TestStateHasGoalBudget:
    """Phase 55.3: ``AgentState`` carries the optional budget."""

    def test_default_state_has_no_budget(self) -> None:
        assert AgentState().goal_budget is None

    def test_state_accepts_budget(self) -> None:
        budget = GoalBudget(max_iterations=10)
        state = AgentState(goal_budget=budget)
        assert state.goal_budget is budget


class TestEventFactory:
    def test_goal_budget_exceeded_event(self) -> None:
        from cantrip.ui.events import EventType, goal_budget_exceeded

        event = goal_budget_exceeded(task_id="t-42", reason="budget blown")
        assert event.type is EventType.GOAL_BUDGET_EXCEEDED
        assert event.payload == {"task_id": "t-42", "reason": "budget blown"}

    def test_policy_rate_limited_event(self) -> None:
        """Phase 80.3: the rate-limit event carries count / cap / policy."""
        from cantrip.ui.events import EventType, policy_rate_limited

        event = policy_rate_limited(
            task_id="t-7", tool_calls_made=50, cap=25, policy_name="org-wide+sprint"
        )
        assert event.type is EventType.POLICY_RATE_LIMITED
        assert event.payload == {
            "task_id": "t-7",
            "tool_calls_made": 50,
            "cap": 25,
            "policy_name": "org-wide+sprint",
        }


class TestFromCliArgs:
    """Phase 55.3: ``--max-iterations`` / ``--max-tokens`` / env-var wiring."""

    def test_no_flags_no_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_MAX_ITERATIONS", raising=False)
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        assert from_cli_args() is None

    def test_cli_iterations_sets_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_MAX_ITERATIONS", raising=False)
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        budget = from_cli_args(max_iterations=20)
        assert budget is not None
        assert budget.max_iterations == 20

    def test_env_iterations_sets_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_MAX_ITERATIONS", "50")
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        budget = from_cli_args()
        assert budget is not None
        assert budget.max_iterations == 50

    def test_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_MAX_ITERATIONS", "10")
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        budget = from_cli_args(max_iterations=100)
        assert budget is not None
        assert budget.max_iterations == 100

    def test_max_tokens_splits_evenly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_MAX_ITERATIONS", raising=False)
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        budget = from_cli_args(max_tokens=10_000)
        assert budget is not None
        assert budget.max_prompt_tokens == 5_000
        # Sum rounds back to the original for odd values too.
        assert (budget.max_prompt_tokens or 0) + (budget.max_completion_tokens or 0) == 10_000

    def test_non_integer_env_var_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_MAX_ITERATIONS", "not-a-number")
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        # Returns None because the only candidate (env var) was unparseable.
        assert from_cli_args() is None

    def test_negative_env_var_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_MAX_ITERATIONS", "-5")
        monkeypatch.delenv("CANTRIP_MAX_TOKENS", raising=False)
        from cantrip.agent.goal_budget import from_cli_args

        assert from_cli_args() is None
