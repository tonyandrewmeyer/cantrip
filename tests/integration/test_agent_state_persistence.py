"""Integration tests: agent state persistence.

These tests verify that CantripAgent correctly persists and restores
state through the SQLite-backed SessionStore.
"""

from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response
from tests.conftest import FakeProvider


@pytest.mark.integration
class TestAgentStatePersistence:
    """Verify state round-trips through save_state/load_state."""

    def test_save_load_preserves_decisions(self, tmp_path: Path):
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
    async def test_usage_persists_across_instances(self, tmp_path: Path):
        """Token usage recorded in one agent instance is visible after reload."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 50, "completion_tokens": 25})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        await agent.process_message("hello")
        agent.save_state()

        # New agent at the same path should see the usage.
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        total = agent2._store.get_total_usage()
        assert total["prompt_tokens"] == 50
        assert total["completion_tokens"] == 25

    @pytest.mark.asyncio
    async def test_messages_not_persisted(self, tmp_path: Path):
        """Messages are not persisted across sessions (by design)."""
        provider = FakeProvider([Response(content="Reply")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        await agent.process_message("Hello")
        assert len(agent.state.messages) == 2
        agent.save_state()

        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent2.load_state()
        assert len(agent2.state.messages) == 0
