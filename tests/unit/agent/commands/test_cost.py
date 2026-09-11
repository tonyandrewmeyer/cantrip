"""Tests for ``/cost`` rollup rendering (Phase 114.1).

``format_cost`` stitches together seven independent blocks (tokens,
cache, context, replay savings, per-model, per-category, per-role) and
each one is conditional.  The tests below drive each block on and off
in isolation so a future edit that accidentally makes a block
unconditional — or drops one — fails loudly rather than silently
changing what operators see in the chat.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cantrip.agent.commands.cost import format_cost
from cantrip.agent.queue import WorkflowPhase


class _StubStore:
    """Usage-store stand-in exposing only what ``format_cost`` reads.

    ``role_rows=None`` drops ``get_usage_by_role`` from the instance
    entirely, standing in for a legacy store predating the per-role
    rollup — ``format_cost`` falls back to an empty list there.
    """

    def __init__(
        self,
        *,
        prompt: int = 0,
        completion: int = 0,
        model_rows: list[dict[str, Any]] | None = None,
        category_rows: list[dict[str, Any]] | None = None,
        role_rows: list[dict[str, Any]] | None = None,
        savings: dict[str, int] | None = None,
    ) -> None:
        self._total = {"prompt_tokens": prompt, "completion_tokens": completion}
        self._model_rows = model_rows or []
        self._category_rows = category_rows or []
        self._savings = savings or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "request_count": 0,
        }
        if role_rows is not None:
            self.get_usage_by_role = lambda: role_rows

    def get_total_usage(self) -> dict[str, int]:
        return self._total

    def get_replay_savings(self) -> dict[str, int]:
        return self._savings

    def get_usage_by_model(self) -> list[dict[str, Any]]:
        return self._model_rows

    def get_usage_by_category(self) -> list[dict[str, Any]]:
        return self._category_rows


def _agent(
    store: _StubStore | None,
    *,
    cache_read: int = 0,
    cache_write: int = 0,
    compactions: int = 0,
    emergencies: int = 0,
    strategy: str = "summarise",
    short_session: bool = False,
    tools: int = 0,
    tools_for_llm: int | None = None,
    model_name: str = "claude-sonnet-4-5",
    edit_string_misses: dict[str, int] | None = None,
) -> SimpleNamespace:
    """Assemble the smallest agent-shaped object ``format_cost`` inspects."""
    offered = tools if tools_for_llm is None else tools_for_llm
    return SimpleNamespace(
        store=store,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_write,
        context_manager=SimpleNamespace(
            compactions_attempted=compactions,
            emergencies_attempted=emergencies,
            compaction_strategy=strategy,
            short_session_mode=short_session,
        ),
        _tools=list(range(tools)),
        _tools_for_llm=lambda: list(range(offered)),
        workflow_phase=WorkflowPhase.BUILD,
        provider=SimpleNamespace(model_name=model_name),
        state=SimpleNamespace(edit_string_misses=edit_string_misses or {}),
    )


class TestEmptyStates:
    def test_no_store(self) -> None:
        assert format_cost(_agent(None)) == "_No usage data available._"

    def test_no_tokens_yet(self) -> None:
        assert format_cost(_agent(_StubStore())) == "_No tokens used yet._"

    def test_token_totals_are_thousands_separated(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1_234_567, completion=890)))
        assert "1,234,567" in text
        assert "1,235,457" in text


class TestCacheBlock:
    def test_omitted_when_no_cache_activity(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=10, completion=5)))
        assert "Cache hit" not in text

    def test_hit_rate_is_reads_over_total(self) -> None:
        text = format_cost(
            _agent(
                _StubStore(prompt=10, completion=5),
                cache_read=750,
                cache_write=250,
            )
        )
        assert "Cache hit:" in text
        assert "75%" in text

    def test_writes_only_reports_zero_percent(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=10, completion=5), cache_write=400))
        assert "0%" in text

    def test_cache_cost_lands_in_the_estimated_total(self) -> None:
        """A cache-only session still owes money, so the total must appear."""
        text = format_cost(
            _agent(
                _StubStore(prompt=10, completion=5),
                cache_read=2_000_000,
                cache_write=2_000_000,
                model_name="claude-opus-4-7",
            )
        )
        assert "_Estimated total:" in text
        assert "approximate" in text


class TestContextBlock:
    def test_strategy_always_shown(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), strategy="drop-oldest"))
        assert "**Context**" in text
        assert "Compaction strategy: drop-oldest" in text

    def test_short_session_mode_is_annotated(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), short_session=True))
        assert "(short-session)" in text

    def test_compaction_counts_hidden_when_idle(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1)))
        assert "Compactions:" not in text

    def test_compaction_count_without_emergencies(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), compactions=3))
        assert "- Compactions: 3" in text
        assert "emergency truncations" not in text

    def test_emergency_truncations_appended(self) -> None:
        text = format_cost(
            _agent(_StubStore(prompt=1, completion=1), compactions=3, emergencies=2)
        )
        assert "emergency truncations: 2" in text

    def test_curated_tool_roster_names_the_phase(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), tools=40, tools_for_llm=12))
        assert "Tools offered to model: 12 of 40" in text
        assert "build phase" in text

    def test_full_tool_roster_is_reported_plainly(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), tools=40))
        assert "Tools offered to model: 40" in text
        assert " of 40" not in text


class TestReplaySavings:
    def test_omitted_when_nothing_was_replayed(self) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1)))
        assert "Cached from checkpoint" not in text

    def test_reports_the_split(self) -> None:
        text = format_cost(
            _agent(
                _StubStore(
                    prompt=1,
                    completion=1,
                    savings={
                        "prompt_tokens": 4_000,
                        "completion_tokens": 1_000,
                        "request_count": 3,
                    },
                )
            )
        )
        assert "Cached from checkpoint: 5,000 tokens" in text
        assert "4,000 prompt" in text
        assert "3 replayed turn(s)" in text


class TestByModel:
    def test_omitted_when_no_rows(self) -> None:
        assert "**By model**" not in format_cost(_agent(_StubStore(prompt=1, completion=1)))

    def test_priced_model_shows_a_dollar_figure(self) -> None:
        store = _StubStore(
            prompt=1_000_000,
            completion=1_000_000,
            model_rows=[
                {
                    "model": "claude-sonnet-4-5",
                    "request_count": 7,
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 1_000_000,
                }
            ],
        )
        text = format_cost(_agent(store))
        assert "**By model**" in text
        assert "claude-sonnet-4-5: 2,000,000 tokens, 7 requests, $18.00" in text
        assert "_Estimated total: $18.00_" in text

    def test_unpriced_model_reads_free_and_suppresses_the_total(self) -> None:
        store = _StubStore(
            prompt=500,
            completion=500,
            model_rows=[
                {
                    "model": "local-gguf-thing",
                    "request_count": 2,
                    "prompt_tokens": 500,
                    "completion_tokens": 500,
                }
            ],
        )
        text = format_cost(_agent(store))
        assert "local-gguf-thing: 1,000 tokens, 2 requests, free" in text
        assert "_Estimated total:" not in text

    def test_missing_row_fields_fall_back_to_zero(self) -> None:
        store = _StubStore(prompt=5, completion=5, model_rows=[{}])
        text = format_cost(_agent(store))
        assert "unknown: 0 tokens, 0 requests, free" in text


class TestByCategory:
    def test_omitted_when_no_rows(self) -> None:
        assert "**By category**" not in format_cost(_agent(_StubStore(prompt=1, completion=1)))

    def test_rows_aggregate_across_models_and_sort_by_name(self) -> None:
        store = _StubStore(
            prompt=10,
            completion=10,
            category_rows=[
                {
                    "category": "research",
                    "model": "claude-sonnet-4-5",
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                    "request_count": 1,
                },
                {
                    "category": "research",
                    "model": "claude-haiku-4-5",
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                    "request_count": 2,
                },
                {
                    "category": "build",
                    "model": "local-gguf-thing",
                    "prompt_tokens": 50,
                    "completion_tokens": 50,
                    "request_count": 1,
                },
            ],
        )
        text = format_cost(_agent(store))
        lines = [line for line in text.splitlines() if line.startswith("- build:")]
        assert lines == ["- build: 100 tokens, 1 requests, free"]
        # $3.00 (sonnet) + $1.00 (haiku) per million prompt tokens.
        assert "- research: 2,000,000 tokens, 3 requests, $4.00" in text
        assert text.index("- build:") < text.index("- research:")

    def test_category_defaults_to_conversation(self) -> None:
        store = _StubStore(prompt=5, completion=5, category_rows=[{"prompt_tokens": 5}])
        assert "- conversation: 5 tokens, 0 requests, free" in format_cost(_agent(store))


class TestByRole:
    def test_omitted_when_the_store_predates_role_tracking(self) -> None:
        assert "**By role**" not in format_cost(_agent(_StubStore(prompt=1, completion=1)))

    def test_omitted_when_every_row_is_chat(self) -> None:
        """Chat-only sessions gain nothing from a one-row breakdown."""
        store = _StubStore(
            prompt=1,
            completion=1,
            role_rows=[{"role": "chat", "prompt_tokens": 1, "completion_tokens": 1}],
        )
        assert "**By role**" not in format_cost(_agent(store))

    def test_rendered_once_a_non_chat_role_appears(self) -> None:
        store = _StubStore(
            prompt=1,
            completion=1,
            role_rows=[
                {
                    "role": "chat",
                    "prompt_tokens": 900,
                    "completion_tokens": 100,
                    "request_count": 4,
                },
                {
                    "role": "embed",
                    "prompt_tokens": 2_000,
                    "completion_tokens": 0,
                    "request_count": 11,
                },
            ],
        )
        text = format_cost(_agent(store))
        assert "**By role**" in text
        assert "- chat: 1,000 tokens, 4 requests" in text
        assert "- embed: 2,000 tokens, 11 requests" in text

    def test_legacy_null_role_rolls_into_chat(self) -> None:
        store = _StubStore(
            prompt=1,
            completion=1,
            role_rows=[
                {"prompt_tokens": 10, "completion_tokens": 0, "request_count": 1},
                {"role": "rerank", "prompt_tokens": 5, "completion_tokens": 0},
            ],
        )
        text = format_cost(_agent(store))
        assert "- chat: 10 tokens, 1 requests" in text


class TestEditStringMisses:
    def test_omitted_when_every_miss_resolved(self) -> None:
        text = format_cost(
            _agent(_StubStore(prompt=1, completion=1), edit_string_misses={"src/charm.py": 0})
        )
        assert "Edit-string misses" not in text

    @pytest.mark.parametrize(
        ("misses", "expected"),
        [
            ({"src/charm.py": 2}, "2 across 1 file"),
            ({"src/charm.py": 2, "tests/test_charm.py": 1}, "3 across 2 files"),
        ],
    )
    def test_singular_and_plural_file_counts(self, misses: dict[str, int], expected: str) -> None:
        text = format_cost(_agent(_StubStore(prompt=1, completion=1), edit_string_misses=misses))
        assert expected in text
        assert "- src/charm.py: 2" in text
