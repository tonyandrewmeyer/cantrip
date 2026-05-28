"""Tests for ``CantripAgent`` save_state / load_state with the session store."""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm import base as llm
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

    def test_resume_rehydrates_cache_token_accumulators(self, tmp_path: pathlib.Path) -> None:
        """Prompt-cache totals survive a resume so /cost stays accurate.

        The cache cost and hit-rate are read from in-memory accumulators;
        persisting the per-request cache counts and rehydrating them on
        resume keeps those surfaces correct across a restart.
        """
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "my-charm"
        agent.save_state()
        # Persist two requests' worth of cache usage.
        assert agent.store is not None
        agent.store.record_usage(
            "claude",
            "claude-opus-4-7",
            100,
            50,
            cache_read_tokens=8000,
            cache_creation_tokens=3000,
        )
        agent.store.record_usage(
            "claude", "claude-opus-4-7", 80, 40, cache_read_tokens=5000, cache_creation_tokens=0
        )

        # A fresh agent resuming the same session starts with zeroed
        # accumulators, then rehydrates them from the store on load.
        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        assert agent2.cache_read_tokens == 0
        assert agent2.cache_creation_tokens == 0

        assert agent2.load_state() is True
        assert agent2.cache_read_tokens == 13000
        assert agent2.cache_creation_tokens == 3000

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


class _SlowFakeProvider(FakeProvider):
    """:class:`FakeProvider` clamped to a slow-path ``conversation_temperature``.

    Phase 102.2 routes any provider whose ``conversation_temperature`` is
    below 0.7 through ``stream()`` instead of ``complete()`` so partial
    tokens land on disk during a long generation.  This double inherits
    the base streaming implementation (which yields per-word chunks) and
    counts which path the executor took so the routing tests can pin the
    contract.
    """

    @property
    def conversation_temperature(self) -> float:
        return 0.2

    def __init__(self, responses: list[llm.Response] | None = None) -> None:
        super().__init__(responses=responses)
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.complete_calls += 1
        return await super().complete(*args, **kwargs)

    async def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.stream_calls += 1
        async for chunk in super().stream(*args, **kwargs):
            yield chunk


class TestSlowPathStreamingWriteback:
    """Phase 102.2: slow providers route through stream() with partial writeback."""

    @pytest.mark.asyncio
    async def test_slow_provider_uses_streaming_path(self, tmp_path: pathlib.Path) -> None:
        """A ``conversation_temperature < 0.7`` provider goes through ``stream()``."""
        provider = _SlowFakeProvider([llm.Response(content="hello world")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("hi")

        assert result == "hello world"
        assert provider.stream_calls == 1
        assert provider.complete_calls == 0

    @pytest.mark.asyncio
    async def test_partial_row_cleaned_up_after_success(self, tmp_path: pathlib.Path) -> None:
        """The placeholder partial row is removed once streaming completes.

        The conversation loop's canonical ``_record_message`` writes the
        final assistant row, so leaving the placeholder behind would
        produce a duplicate transcript line.  After the turn we expect
        exactly two persisted messages (user + assistant).
        """
        provider = _SlowFakeProvider([llm.Response(content="reply")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("hello")

        assert agent._store is not None
        rows = agent._store.load_active_branch()
        assert [r["role"] for r in rows] == ["user", "assistant"]
        # The canonical assistant row carries no ``partial`` flag.
        assistant_row = rows[1]
        assistant_metadata = assistant_row.get("metadata") or {}
        assert assistant_metadata.get("partial") is None

    @pytest.mark.asyncio
    async def test_fast_provider_still_uses_complete(self, tmp_path: pathlib.Path) -> None:
        """A frontier-temperature provider keeps the existing ``complete()`` path."""
        provider = FakeProvider([llm.Response(content="ok")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("hi")

        # ``FakeProvider`` defaults to 0.7, so the routing skips streaming.
        assert agent._store is not None
        rows = agent._store.load_active_branch()
        assert [r["role"] for r in rows] == ["user", "assistant"]
