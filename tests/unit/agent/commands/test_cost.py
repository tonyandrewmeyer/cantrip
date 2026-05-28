"""Tests for ``format_cost`` (the ``/cost`` body builder).

``test_slash.py`` covers the dispatch wiring and the no-data / category
paths; this file targets the rollup branches that only fire with richer
usage data — the cache-hit line, the per-model and per-role tables, the
context-management counters, and the estimated-total footer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from cantrip.agent.commands.cost import format_cost
from cantrip.agent.queue import WorkflowPhase


def _store(
    *,
    total: dict | None = None,
    by_model: list | None = None,
    by_category: list | None = None,
    by_role: list | None = None,
    savings: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.get_total_usage.return_value = total or {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
    }
    store.get_usage_by_model.return_value = by_model or []
    store.get_usage_by_category.return_value = by_category or []
    store.get_replay_savings.return_value = savings or {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "request_count": 0,
    }
    store.get_usage_by_role.return_value = by_role or []
    return store


def _agent(
    store: MagicMock | None,
    *,
    cache_read: int = 0,
    cache_write: int = 0,
    model_name: str = "claude-opus-4",
    tools: int = 0,
    tools_for_llm: int = 0,
    compactions: int = 0,
    emergencies: int = 0,
    short_session: bool = False,
    workflow_phase: WorkflowPhase = WorkflowPhase.BUILD,
    edit_string_misses: dict[str, int] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        store=store,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_write,
        provider=SimpleNamespace(model_name=model_name),
        _tools=list(range(tools)),
        _tools_for_llm=lambda: list(range(tools_for_llm)),
        context_manager=SimpleNamespace(
            compactions_attempted=compactions,
            emergencies_attempted=emergencies,
            compaction_strategy="summarise",
            short_session_mode=short_session,
        ),
        workflow_phase=workflow_phase,
        state=SimpleNamespace(edit_string_misses=edit_string_misses or {}),
    )


def test_no_store_returns_placeholder() -> None:
    assert "No usage data" in format_cost(_agent(None))


def test_cache_hit_line_shown_when_cache_tokens_present() -> None:
    agent = _agent(_store(), cache_read=750, cache_write=250)
    text = format_cost(agent)
    # 750 / (750 + 250) = 75%.
    assert "Cache hit:" in text
    assert "75%" in text


def test_compactions_and_short_session_note() -> None:
    agent = _agent(_store(), compactions=3, emergencies=1, short_session=True)
    text = format_cost(agent)
    assert "(short-session)" in text
    assert "Compactions: 3" in text
    assert "emergency truncations: 1" in text


def test_curated_tool_count_when_fewer_offered() -> None:
    agent = _agent(_store(), tools=40, tools_for_llm=12)
    text = format_cost(agent)
    assert "Tools offered to model: 12 of 40" in text
    assert "build phase" in text


def test_full_tool_count_when_none_curated() -> None:
    agent = _agent(_store(), tools=10, tools_for_llm=10)
    text = format_cost(agent)
    assert "Tools offered to model: 10" in text
    assert " of 10" not in text


def test_by_model_table_and_estimated_total() -> None:
    by_model = [
        {
            "model": "claude-opus-4",
            "request_count": 2,
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        }
    ]
    agent = _agent(_store(by_model=by_model))
    text = format_cost(agent)
    assert "**By model**" in text
    assert "claude-opus-4: 1,500 tokens, 2 requests" in text
    # A priced model produces a non-zero estimated total footer.
    assert "Estimated total:" in text
    assert "approximate" in text


def test_cache_cost_added_to_total() -> None:
    # Cache tokens alone (no per-model rows) still produce an estimated
    # total via the cache-cost branch.
    agent = _agent(_store(), cache_read=100000, cache_write=50000)
    text = format_cost(agent)
    assert "Estimated total:" in text


def test_by_role_table_when_non_chat_role_present() -> None:
    by_role = [
        {"role": "chat", "prompt_tokens": 100, "completion_tokens": 50, "request_count": 1},
        {"role": "embed", "prompt_tokens": 200, "completion_tokens": 0, "request_count": 4},
    ]
    agent = _agent(_store(by_role=by_role))
    text = format_cost(agent)
    assert "**By role**" in text
    assert "embed: 200 tokens, 4 requests" in text


def test_by_role_table_omitted_when_only_chat() -> None:
    by_role = [
        {"role": "chat", "prompt_tokens": 100, "completion_tokens": 50, "request_count": 1},
    ]
    agent = _agent(_store(by_role=by_role))
    text = format_cost(agent)
    assert "**By role**" not in text
