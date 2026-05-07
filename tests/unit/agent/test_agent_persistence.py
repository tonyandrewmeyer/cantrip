"""Tests for ``CantripAgent`` save_state / load_state with the session store."""

import pathlib

from cantrip.agent.core import CantripAgent
from tests.conftest import FakeProvider


class TestStoreBackedPersistence:
    """Tests for save_state / load_state with the session store."""

    def test_save_and_load_state(self, tmp_path: pathlib.Path) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        agent.state.charm_name = "my-charm"
        agent.state.charm_type = "k8s"
        agent.state.add_decision("path", "12-factor", reason="Flask")
        agent.save_state()

        # Create a fresh agent pointing at the same path.
        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        assert agent2.state.charm_name == "my-charm"
        assert agent2.state.charm_type == "k8s"
        assert len(agent2.state.decisions) == 1

    def test_load_state_returns_false_when_empty(self, tmp_path: pathlib.Path) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        assert agent.load_state() is False

    def test_save_state_noop_without_store(self) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        # Should not raise.
        agent.save_state()

    def test_load_state_returns_false_without_store(self) -> None:
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        assert agent.load_state() is False

    def test_load_state_skips_persisted_tasks_already_in_queue(
        self, tmp_path: pathlib.Path
    ) -> None:
        # Background workers (e.g. issue triage) may add tasks with
        # deterministic IDs to the work queue before ``load_state``
        # gets a chance to run.  Loading a persisted task that
        # collides on ID must not crash the whole resume — the
        # in-memory copy stays, the persisted copy is skipped with a
        # warning.
        from cantrip.agent.queue import AgentTask, TaskCategory

        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        # Seed a state snapshot with one task so a session row exists.
        agent.state.charm_name = "demo"
        seeded = AgentTask(
            id="triage-issue-150",
            title="Persisted version",
            category=TaskCategory.RESEARCH,
        )
        agent._work_queue.add_task(seeded)
        agent.save_state()
        # Wipe the in-memory queue and re-seed with a *fresh* version
        # of the same id to simulate the race: a background worker
        # added it before ``load_state`` runs.
        agent._work_queue.clear()
        racing = AgentTask(
            id="triage-issue-150",
            title="Fresh from triage",
            category=TaskCategory.RESEARCH,
        )
        agent._work_queue.add_task(racing)

        # load_state must not raise.
        assert agent.load_state() is True
        # The fresh in-memory copy is what's in the queue.
        tasks = agent._work_queue.all_tasks()
        ids = {t.id for t in tasks}
        assert "triage-issue-150" in ids
        # Exactly one — no duplicate.
        assert sum(1 for t in tasks if t.id == "triage-issue-150") == 1
        # And it's the racing copy, not the persisted one.
        match = next(t for t in tasks if t.id == "triage-issue-150")
        assert match.title == "Fresh from triage"
