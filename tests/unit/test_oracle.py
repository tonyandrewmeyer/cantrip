"""Tests for the Oracle tool — Phase 70.2."""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.oracle import (
    DEFAULT_ORACLE_MODEL,
    DEFAULT_ORACLE_PROVIDER,
    OracleTool,
)
from cantrip.llm.base import Message, Response, Role
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _oracle_provider(
    *, content: str = "Architecture answer.", usage: dict | None = None
) -> FakeProvider:
    """Return a FakeProvider impersonating the oracle model.

    ``model_name`` is set so the cost estimator picks the Opus pricing
    bracket — tests that care about cost rely on a known-priced model.
    """
    response = Response(content=content, usage=dict(usage or {}))
    provider = FakeProvider(responses=[response])
    provider.model_name = DEFAULT_ORACLE_MODEL
    return provider


def _build_tool(
    state: AgentState,
    *,
    provider: FakeProvider | None = None,
    store: SessionStore | None = None,
) -> tuple[OracleTool, dict[str, FakeProvider]]:
    """Build an OracleTool with a captured provider factory.

    Returns the tool and a dict that the test can read after calling
    ``execute()`` — ``constructed["provider"]`` is the FakeProvider the
    factory handed back, ``constructed["calls"]`` is the list of
    ``(name, model)`` pairs the factory was called with.
    """
    fake = provider if provider is not None else _oracle_provider()
    constructed: dict[str, FakeProvider | list] = {"provider": fake, "calls": []}

    def factory(provider_name: str, model: str) -> FakeProvider:
        calls = constructed["calls"]
        assert isinstance(calls, list)
        calls.append((provider_name, model))
        provider_obj = constructed["provider"]
        assert isinstance(provider_obj, FakeProvider)
        return provider_obj

    tool = OracleTool(
        state,
        store_getter=(lambda: store) if store is not None else None,
        provider_factory=factory,
    )
    return tool, constructed


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_returns_answer_with_provenance_footer(self) -> None:
        state = AgentState(charm_name="myflask", charm_type="k8s", framework="flask")
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        provider = _oracle_provider(content="Use a sidecar.", usage=usage)
        tool, constructed = _build_tool(state, provider=provider)

        result = await tool.execute(question="Sidecar or separate charm for the LDAP bridge?")

        assert result.success is True
        assert "Use a sidecar." in result.output
        assert DEFAULT_ORACLE_MODEL in result.output
        # The output footer cites the cost cap so the agent sees the
        # remaining budget at a glance.
        assert "session ≈" in result.output
        # Default provider/model used when state has no override.
        assert constructed["calls"] == [(DEFAULT_ORACLE_PROVIDER, DEFAULT_ORACLE_MODEL)]

    @pytest.mark.asyncio
    async def test_increments_call_counters_and_cost(self) -> None:
        state = AgentState()
        usage = {"prompt_tokens": 2000, "completion_tokens": 1000}
        provider = _oracle_provider(usage=usage)
        tool, _ = _build_tool(state, provider=provider)

        await tool.execute(question="Do we need ops-tracing?")

        # Opus 4-7 prices: $15/M prompt, $75/M completion → 2000*15e-6 + 1000*75e-6 = $0.105.
        assert state.oracle_calls_this_turn == 1
        assert state.oracle_calls_total == 1
        assert state.oracle_session_cost_usd == pytest.approx(0.105, rel=1e-6)

    @pytest.mark.asyncio
    async def test_state_overrides_provider_and_model(self) -> None:
        state = AgentState()
        state.oracle_provider_name = "gemini"
        state.oracle_model = "gemini-3-pro-preview"
        tool, constructed = _build_tool(state)

        await tool.execute(question="Architecture question")

        assert constructed["calls"] == [("gemini", "gemini-3-pro-preview")]

    @pytest.mark.asyncio
    async def test_data_payload_carries_full_accounting(self) -> None:
        state = AgentState()
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        tool, _ = _build_tool(state, provider=_oracle_provider(usage=usage))

        result = await tool.execute(question="Why?")

        assert result.data["provider"] == DEFAULT_ORACLE_PROVIDER
        assert result.data["model"] == DEFAULT_ORACLE_MODEL
        assert result.data["usage"] == usage
        assert result.data["calls_this_turn"] == 1
        assert result.data["calls_total"] == 1
        assert result.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# No main-context contamination
# ---------------------------------------------------------------------------


class TestNoMainContextContamination:
    @pytest.mark.asyncio
    async def test_state_messages_unchanged_after_call(self) -> None:
        existing = [
            Message(role=Role.USER, content="Build me a charm."),
            Message(role=Role.ASSISTANT, content="Sure."),
        ]
        state = AgentState()
        state.messages.extend(existing)
        original_ids = [id(m) for m in state.messages]
        tool, _ = _build_tool(state)

        await tool.execute(question="Where should the leader run?")

        assert len(state.messages) == len(existing)
        assert [id(m) for m in state.messages] == original_ids

    @pytest.mark.asyncio
    async def test_recent_messages_are_read_not_mutated(self) -> None:
        state = AgentState()
        original = Message(role=Role.USER, content="hello")
        state.messages.append(original)
        tool, _ = _build_tool(state)

        await tool.execute(question="Why?")

        assert state.messages[0] is original
        assert state.messages[0].content == "hello"


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_per_turn_cap_blocks_second_call(self) -> None:
        state = AgentState()
        state.oracle_max_calls_per_turn = 1
        tool, _ = _build_tool(state)

        first = await tool.execute(question="Question 1")
        assert first.success is True

        # Second call in the same turn — must be refused.
        second = await tool.execute(question="Question 2")
        assert second.success is False
        assert second.error is not None
        assert "per-turn" in second.error
        # Counter is unchanged on the failed call.
        assert state.oracle_calls_this_turn == 1

    @pytest.mark.asyncio
    async def test_cap_resets_when_state_resets(self) -> None:
        state = AgentState()
        state.oracle_max_calls_per_turn = 1
        provider = FakeProvider(
            responses=[Response(content="A"), Response(content="B")],
        )
        provider.model_name = DEFAULT_ORACLE_MODEL
        tool, _ = _build_tool(state, provider=provider)

        await tool.execute(question="Q1")
        # Simulate the agent's per-turn reset — happens at the top of
        # ``_run_conversation_loop`` between user messages.
        state.oracle_calls_this_turn = 0

        result = await tool.execute(question="Q2")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_session_cost_cap_blocks_call(self) -> None:
        state = AgentState()
        state.oracle_max_session_cost_usd = 0.01
        # Pre-load a cost over the cap so the very first call refuses.
        state.oracle_session_cost_usd = 0.05
        tool, _ = _build_tool(state)

        result = await tool.execute(question="Q")

        assert result.success is False
        assert result.error is not None
        assert "session cost cap" in result.error
        # No call was actually made — counter remained at zero.
        assert state.oracle_calls_total == 0

    @pytest.mark.asyncio
    async def test_empty_question_returns_error(self) -> None:
        state = AgentState()
        tool, _ = _build_tool(state)

        result = await tool.execute(question="   ")

        assert result.success is False
        assert result.error is not None
        assert "non-empty" in result.error
        # Budget counters untouched.
        assert state.oracle_calls_total == 0


# ---------------------------------------------------------------------------
# Transcript side-event recording
# ---------------------------------------------------------------------------


class TestTranscriptRecording:
    @pytest.mark.asyncio
    async def test_records_event_when_store_present(self, tmp_path: pathlib.Path) -> None:
        store = SessionStore(tmp_path / "session.db")
        state = AgentState(charm_name="db-charm")
        provider = _oracle_provider(content="Pick option A.")
        tool, _ = _build_tool(state, provider=provider, store=store)

        await tool.execute(
            question="A or B?",
            context_hint="The user wants minimal ops burden.",
        )

        events = store.load_events(event_type="oracle_consult")
        assert len(events) == 1
        detail = events[0]["detail"]
        assert isinstance(detail, dict)
        assert detail["question"] == "A or B?"
        assert detail["context_hint"] == "The user wants minimal ops burden."
        assert detail["answer"] == "Pick option A."
        assert detail["provider"] == DEFAULT_ORACLE_PROVIDER
        assert detail["model"] == DEFAULT_ORACLE_MODEL
        assert detail["calls_this_turn"] == 1
        assert "cost_usd" in detail

    @pytest.mark.asyncio
    async def test_no_store_means_no_event_but_no_failure(self) -> None:
        state = AgentState()
        tool, _ = _build_tool(state)  # store_getter=None

        result = await tool.execute(question="Q")

        # The call still succeeds; transcript-recording is best-effort.
        assert result.success is True

    @pytest.mark.asyncio
    async def test_failed_calls_do_not_record_event(self, tmp_path: pathlib.Path) -> None:
        store = SessionStore(tmp_path / "session.db")
        state = AgentState()
        # Cap at zero so the first call is refused.
        state.oracle_max_calls_per_turn = 0
        tool, _ = _build_tool(state, store=store)

        await tool.execute(question="Q")

        events = store.load_events(event_type="oracle_consult")
        assert events == []
