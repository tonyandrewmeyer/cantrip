"""Tests for ``CantripAgent`` arena integration — Phase 47.5.

Covers ``begin_arena`` and ``handle_arena_pick`` end-to-end: the first
spins up a pending session and returns the blind A/B block; the second
resolves the session, writes a memory when appropriate, and clears the
state so a second ``/arena`` can start.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

if TYPE_CHECKING:
    import pathlib


def _named_provider(model_name: str, response: str = "ok") -> FakeProvider:
    p = FakeProvider(responses=[Response(content=response)])
    p.model_name = model_name
    return p


def _agent(tmp_path: pathlib.Path, *, with_light: bool = True) -> CantripAgent:
    primary = _named_provider("primary-model", response="primary says hi")
    light = _named_provider("light-model", response="light says hi") if with_light else None
    return CantripAgent(provider=primary, charm_path=tmp_path, light_provider=light)


class TestBeginArena:
    @pytest.mark.asyncio
    async def test_missing_light_provider_returns_user_message(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = _agent(tmp_path, with_light=False)
        text = await agent.begin_arena("help me choose")
        assert "light provider" in text.lower()
        assert agent.active_arena is None

    @pytest.mark.asyncio
    async def test_starts_and_renders_blind_block(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        text = await agent.begin_arena("what is ops?")
        # The agent now holds a pending session.
        assert agent.active_arena is not None
        # Block hides model names and shows both responses.
        assert "primary says hi" in text
        assert "light says hi" in text
        assert "primary-model" not in text
        assert "light-model" not in text

    @pytest.mark.asyncio
    async def test_second_arena_while_one_pending_is_rejected(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("first prompt")
        text = await agent.begin_arena("second prompt")
        assert "already in progress" in text.lower()

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_user_message(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        text = await agent.begin_arena("   ")
        assert "empty" in text.lower() or "supply text" in text.lower()
        assert agent.active_arena is None


class TestHandleArenaPick:
    @pytest.mark.asyncio
    async def test_pick_a_writes_memory_and_clears_state(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("what is ops?")
        reveal = agent.handle_arena_pick("A")
        assert reveal is not None
        assert agent.active_arena is None
        # A memory was written at global scope.
        globals_ = agent._memory_manager.list_entries(scope="global")
        assert any(e.title.startswith("arena-preference-") for e in globals_)

    @pytest.mark.asyncio
    async def test_pick_skip_clears_state_without_writing_memory(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("what is ops?")
        reveal = agent.handle_arena_pick("skip")
        assert reveal is not None
        assert agent.active_arena is None
        globals_ = agent._memory_manager.list_entries(scope="global")
        assert globals_ == []

    @pytest.mark.asyncio
    async def test_unrecognised_reply_returns_none_and_keeps_state(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("what is ops?")
        assert agent.handle_arena_pick("tell me more about ops") is None
        # State still pending — the user can still pick.
        assert agent.active_arena is not None

    def test_no_active_arena_returns_none(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        assert agent.handle_arena_pick("A") is None

    @pytest.mark.asyncio
    async def test_tie_writes_equivalence_memory(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("compare")
        reveal = agent.handle_arena_pick("tie")
        assert reveal is not None
        globals_ = agent._memory_manager.list_entries(scope="global")
        assert len(globals_) == 1
        assert "equivalent" in globals_[0].body.lower()


class TestArenaMemoryContent:
    """End-to-end check that the written memory cites both models by name."""

    @pytest.mark.asyncio
    async def test_memory_names_both_models(self, tmp_path: pathlib.Path) -> None:
        agent = _agent(tmp_path)
        await agent.begin_arena("design a counter charm")
        agent.handle_arena_pick("B")
        entries = agent._memory_manager.list_entries(scope="global")
        assert len(entries) == 1
        body = entries[0].body
        assert "primary-model" in body
        assert "light-model" in body
        # Source is 'arena' so the AutoWriter-written memories stay
        # distinguishable from manual /remember ones.
        assert entries[0].source == "arena"
