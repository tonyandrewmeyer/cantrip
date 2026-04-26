"""Tests for blind A/B arena mode — Phase 47.5."""

from __future__ import annotations

import dataclasses
import pathlib
import random

import pytest

from cantrip.agent import arena
from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.llm.base import Response
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _named_provider(model_name: str, response_text: str = "ok") -> FakeProvider:
    provider = FakeProvider(responses=[Response(content=response_text)])
    provider.model_name = model_name
    return provider


def _memory_manager(tmp_path: pathlib.Path) -> MemoryManager:
    return MemoryManager(
        session_store=None,
        global_store=GlobalMemoryStore(tmp_path / "globalmem"),
    )


def _session(
    *,
    a_model: str = "claude-opus",
    b_model: str = "gemini-pro",
    a_response: str = "alpha answer",
    b_response: str = "bravo answer",
    prompt: str = "Test prompt",
) -> arena.ArenaSession:
    return arena.ArenaSession(
        prompt=prompt,
        candidates=(
            arena.ArenaCandidate(
                label="A",
                provider_name="claude",
                model_name=a_model,
                response=a_response,
            ),
            arena.ArenaCandidate(
                label="B",
                provider_name="gemini",
                model_name=b_model,
                response=b_response,
            ),
        ),
        session_id="abc12345",
    )


# ---------------------------------------------------------------------------
# parse_pick
# ---------------------------------------------------------------------------


class TestParsePick:
    @pytest.mark.parametrize("raw", ["a", "A", "  a  ", "Pick A", "left"])
    def test_a_variants_map_to_picked_a(self, raw: str) -> None:
        assert arena.parse_pick(raw) == arena.ArenaOutcome.PICKED_A

    @pytest.mark.parametrize("raw", ["b", "B", "pick B", "right"])
    def test_b_variants_map_to_picked_b(self, raw: str) -> None:
        assert arena.parse_pick(raw) == arena.ArenaOutcome.PICKED_B

    @pytest.mark.parametrize("raw", ["tie", "equal", "both", "neither", "t"])
    def test_tie_variants_map_to_tie(self, raw: str) -> None:
        assert arena.parse_pick(raw) == arena.ArenaOutcome.TIE

    @pytest.mark.parametrize("raw", ["skip", "cancel", "abort", "never mind"])
    def test_skip_variants_map_to_skipped(self, raw: str) -> None:
        assert arena.parse_pick(raw) == arena.ArenaOutcome.SKIPPED

    @pytest.mark.parametrize("raw", ["hello there", "run the tests", "a bold claim", ""])
    def test_unrecognised_returns_unrecognised(self, raw: str) -> None:
        # Multi-word messages that happen to begin with "a " or similar
        # must not be mis-classified as a pick — only exact matches win.
        assert arena.parse_pick(raw) == arena.ArenaOutcome.UNRECOGNISED


# ---------------------------------------------------------------------------
# _shuffle_labels
# ---------------------------------------------------------------------------


class TestShuffleLabels:
    def test_labels_are_always_a_and_b(self) -> None:
        first = arena.ArenaCandidate("?", "p1", "model-a", "one")
        second = arena.ArenaCandidate("?", "p2", "model-b", "two")
        labelled_a, labelled_b = arena._shuffle_labels(first, second, rng=random.Random(0))
        assert labelled_a.label == "A"
        assert labelled_b.label == "B"
        # The original responses survived.
        assert {labelled_a.response, labelled_b.response} == {"one", "two"}

    def test_deterministic_with_seeded_rng(self) -> None:
        # Same seed, same inputs → same assignment.  Different seeds
        # can produce the opposite assignment; we don't assert the
        # direction, just the determinism.
        first = arena.ArenaCandidate("?", "p1", "model-a", "one")
        second = arena.ArenaCandidate("?", "p2", "model-b", "two")
        run_one = arena._shuffle_labels(first, second, rng=random.Random(42))
        run_two = arena._shuffle_labels(first, second, rng=random.Random(42))
        assert [c.model_name for c in run_one] == [c.model_name for c in run_two]


# ---------------------------------------------------------------------------
# run_blind_arena
# ---------------------------------------------------------------------------


class TestRunBlindArena:
    @pytest.mark.asyncio
    async def test_runs_both_providers_and_returns_session(self) -> None:
        a = _named_provider("claude-opus", response_text="claude speaks")
        b = _named_provider("gemini-pro", response_text="gemini speaks")
        session = await arena.run_blind_arena(provider_a=a, provider_b=b, prompt="How are you?")
        # Both labels populated, both responses present somewhere.
        responses = {c.response for c in session.candidates}
        assert responses == {"claude speaks", "gemini speaks"}
        # Session id is a short hex string, not empty.
        assert session.session_id
        assert all(ch in "0123456789abcdef" for ch in session.session_id)

    @pytest.mark.asyncio
    async def test_identical_providers_raise_arena_error(self) -> None:
        a = _named_provider("same-model")
        b = _named_provider("same-model")
        with pytest.raises(arena.ArenaError, match="distinct"):
            await arena.run_blind_arena(provider_a=a, provider_b=b, prompt="hello")

    @pytest.mark.asyncio
    async def test_empty_prompt_raises_arena_error(self) -> None:
        a = _named_provider("m1")
        b = _named_provider("m2")
        with pytest.raises(arena.ArenaError, match="empty"):
            await arena.run_blind_arena(provider_a=a, provider_b=b, prompt="   ")

    @pytest.mark.asyncio
    async def test_labels_alternate_with_different_seeds(self) -> None:
        # With a deterministic RNG we can verify the shuffle actually
        # flips the assignment across runs rather than always picking
        # the same side.
        a = _named_provider("alpha", response_text="A-content")
        b = _named_provider("beta", response_text="B-content")
        seen_a_models = set()
        for seed in range(10):
            a_resp = _named_provider("alpha", response_text="A-content")
            b_resp = _named_provider("beta", response_text="B-content")
            s = await arena.run_blind_arena(
                provider_a=a_resp,
                provider_b=b_resp,
                prompt="ping",
                rng=random.Random(seed),
            )
            seen_a_models.add(s.candidate_a.model_name)
        # Over ten different seeds we should see both sides land on A.
        assert seen_a_models == {"alpha", "beta"}, (
            f"shuffle never flipped — only saw {seen_a_models}"
        )
        # Silence unused-variable warnings for the top-level providers.
        _ = (a, b)


# ---------------------------------------------------------------------------
# format_blind_arena
# ---------------------------------------------------------------------------


class TestFormatBlindArena:
    def test_renders_both_responses_and_hides_model_names(self) -> None:
        session = _session(
            a_model="secret-alpha-v2",
            b_model="secret-bravo-v3",
            a_response="alpha answer",
            b_response="bravo answer",
        )
        text = arena.format_blind_arena(session)
        assert "alpha answer" in text
        assert "bravo answer" in text
        # Model names must not leak into the blind presentation.
        assert "secret-alpha" not in text
        assert "secret-bravo" not in text
        # The reply instructions are present so the user knows the verbs.
        for verb in ("**A**", "**B**", "**tie**", "**skip**"):
            assert verb in text


# ---------------------------------------------------------------------------
# record_preference
# ---------------------------------------------------------------------------


class TestRecordPreference:
    def test_picked_a_writes_directional_memory(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        session = _session(a_model="claude-opus", b_model="gemini-pro")
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.PICKED_A)
        assert entry is not None
        assert entry.kind == "fact"
        assert "claude-opus" in entry.body
        assert "gemini-pro" in entry.body
        assert "preferred" in entry.body

    def test_picked_b_writes_directional_memory(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        session = _session(a_model="claude-opus", b_model="gemini-pro")
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.PICKED_B)
        assert entry is not None
        # B is the winner, so B's model should precede A's in the body.
        winner_idx = entry.body.index("gemini-pro")
        loser_idx = entry.body.index("claude-opus")
        assert winner_idx < loser_idx

    def test_tie_writes_equivalence_memory(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        session = _session()
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.TIE)
        assert entry is not None
        assert "equivalent" in entry.body.lower()

    def test_skipped_outcome_writes_nothing(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        session = _session()
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.SKIPPED)
        assert entry is None
        assert manager.list_entries(scope="global") == []

    def test_unrecognised_outcome_writes_nothing(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        session = _session()
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.UNRECOGNISED)
        assert entry is None

    def test_prompt_excerpt_truncated_at_200_chars(self, tmp_path: pathlib.Path) -> None:
        manager = _memory_manager(tmp_path)
        long_prompt = "word " * 100  # ~500 chars
        session = dataclasses.replace(_session(), prompt=long_prompt)
        entry = arena.record_preference(manager, session, arena.ArenaOutcome.PICKED_A)
        assert entry is not None
        # Body includes the ellipsis that marks truncation.
        assert "…" in entry.body


# ---------------------------------------------------------------------------
# format_reveal
# ---------------------------------------------------------------------------


class TestFormatReveal:
    def test_picked_a_reveal_names_a_winner(self) -> None:
        session = _session(a_model="claude-opus", b_model="gemini-pro")
        reveal = arena.format_reveal(session, arena.ArenaOutcome.PICKED_A)
        assert "claude-opus" in reveal
        # The reveal always unmasks both mappings.
        assert "gemini-pro" in reveal
        assert "You picked **A**" in reveal

    def test_tie_reveal_names_both_without_a_winner(self) -> None:
        session = _session(a_model="claude-opus", b_model="gemini-pro")
        reveal = arena.format_reveal(session, arena.ArenaOutcome.TIE)
        assert "equivalent" in reveal.lower()
        assert "claude-opus" in reveal and "gemini-pro" in reveal

    def test_skipped_reveal_mentions_skip(self) -> None:
        session = _session()
        reveal = arena.format_reveal(session, arena.ArenaOutcome.SKIPPED)
        assert "skipped" in reveal.lower()
        # Skipped reveals must NOT claim a memory was recorded.
        assert "global-scope memory" not in reveal
