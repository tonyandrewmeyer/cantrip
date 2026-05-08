"""Integration tests: agent state persistence.

These tests verify that CantripAgent correctly persists and restores
state through the SQLite-backed SessionStore.
"""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response
from tests.conftest import FakeProvider


@pytest.mark.integration
class TestAgentStatePersistence:
    """Verify state round-trips through save_state/load_state."""

    def test_save_load_preserves_decisions(self, tmp_path: pathlib.Path):
        """Decisions survive a save/load cycle."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        agent.state.add_decision("path", "12-factor", reason="Flask detected")
        agent.state.add_decision("framework", "flask")
        agent.save_state()

        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        assert len(agent2.state.decisions) == 2
        assert agent2.state.decisions[0].type == "path"
        assert agent2.state.decisions[0].choice == "12-factor"
        assert agent2.state.decisions[0].reason == "Flask detected"
        assert agent2.state.decisions[1].type == "framework"

    @pytest.mark.asyncio
    async def test_usage_persists_across_instances(self, tmp_path: pathlib.Path):
        """Token usage recorded in one agent instance is visible after reload."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 50, "completion_tokens": 25})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        await agent.process_message("hello")
        agent.save_state()

        # New agent at the same path should see the usage.
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent2._ensure_store()
        total = agent2._store.get_total_usage()
        assert total["prompt_tokens"] == 50
        assert total["completion_tokens"] == 25

    @pytest.mark.asyncio
    async def test_messages_persisted_across_sessions(self, tmp_path: pathlib.Path):
        """Messages survive a save/load cycle (Phase 31.11)."""
        provider = FakeProvider([Response(content="Reply")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        await agent.process_message("Hello")
        assert len(agent.state.messages) == 2
        agent.save_state()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent2.load_state()
        assert len(agent2.state.messages) == 2
        assert agent2.state.messages[0].content == "Hello"
        assert agent2.state.messages[1].content == "Reply"

    def test_goal_budget_round_trips_via_slash(self, tmp_path: pathlib.Path):
        """Phase 99.2: ``/budget`` caps survive ``cantrip resume``.

        Drives the real slash handler so the test catches a regression
        if a future refactor wires save/load past ``handle_budget`` —
        e.g. by stamping the budget on a transient field instead of
        ``state.goal_budget``.
        """
        from cantrip.agent.commands.budget import handle_budget

        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        # Set caps via the same surface the operator uses.
        handle_budget(agent, "--max-iterations 50")
        handle_budget(agent, "--max-prompt-tokens 1000")
        handle_budget(agent, "--max-completion-tokens 500")
        agent.save_state()

        original_started_at = agent.state.goal_budget.started_at

        # Fresh agent at the same path picks up the caps without the
        # CLI flags being re-supplied.
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        loaded = agent2.load_state()
        assert loaded is True
        assert agent2.state.goal_budget is not None
        assert agent2.state.goal_budget.max_iterations == 50
        assert agent2.state.goal_budget.max_prompt_tokens == 1000
        assert agent2.state.goal_budget.max_completion_tokens == 500
        # ``started_at`` must round-trip exactly so spend totals
        # measured against ``token_usage`` keep the same window.
        assert agent2.state.goal_budget.started_at == original_started_at

        # The live ``/budget`` (no-arg) summary must reflect the
        # restored caps, matching the exit criterion from ROADMAP 99.2.
        summary = handle_budget(agent2, "")
        assert "iterations 0/50" in summary
        assert "prompt 0/1,000" in summary
        assert "completion 0/500" in summary

    def test_objective_round_trips_via_slash(self, tmp_path: pathlib.Path):
        """Phase 99.3: ``/goal <text>`` survives ``cantrip resume``.

        Drives the live slash handler so a future refactor that
        side-stepped ``state.objective`` would surface immediately —
        Ralph re-feed pulls the same field, so a missed wire-up here
        would silently break the iterate-until-green loop.
        """
        from cantrip.agent.commands.goal import handle_goal

        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        handle_goal(agent, "build a Postgres charm with COS plus Pebble notices")
        agent.save_state()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        loaded = agent2.load_state()
        assert loaded is True
        assert agent2.state.objective == ("build a Postgres charm with COS plus Pebble notices")

        # And the live ``/goal`` (no-arg) summary reflects the
        # restored value, matching what a user would see.
        summary = handle_goal(agent2, "")
        assert "build a Postgres charm with COS plus Pebble notices" in summary

    def test_objective_clear_round_trips_as_none(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands.goal import handle_goal

        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        handle_goal(agent, "first version of the goal")
        agent.save_state()
        handle_goal(agent, "clear")
        agent.save_state()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent2.load_state()
        assert agent2.state.objective is None

    def test_goal_budget_clear_round_trips_as_none(self, tmp_path: pathlib.Path):
        """``/budget --clear`` after a save zeroes the persisted caps.

        Without this the next resume would silently re-establish caps
        the operator just cleared.
        """
        from cantrip.agent.commands.budget import handle_budget

        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        handle_budget(agent, "--max-iterations 10")
        agent.save_state()
        handle_budget(agent, "--clear")
        agent.save_state()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent2.load_state()
        assert agent2.state.goal_budget is None
