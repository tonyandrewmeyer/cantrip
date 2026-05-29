"""Tests for Phase 104 short-session mode.

Covers the provider declaration, the ContextManager threshold / strategy
/ ledger machinery, the ``--short-session`` resolver, and the
CantripAgent per-turn ephemeral collapse + in-turn ledger fold.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.context.context import (
    CompactionStrategy,
    ContextManager,
    LedgerEntry,
    VirtualFileStore,
    resolve_short_session_mode,
)
from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Message, Response, Role, ToolCall
from cantrip.llm.base import ToolResult as LLMToolResult
from cantrip.llm.inference_snap import InferenceSnapProvider
from tests.conftest import FakeProvider


class _TightContextProvider(FakeProvider):
    """A FakeProvider that advertises short-session mode (auto-detect would pick it)."""

    @property
    def short_session_mode(self) -> bool:
        return True


def _cm(short: bool, window: int = 8_000) -> ContextManager:
    return ContextManager(
        virtual_store=VirtualFileStore(),
        context_window_tokens=window,
        short_session_mode=short,
    )


def _tool_round(i: int, output: str = "ok") -> list[Message]:
    """An ``[assistant(tool_call), tool(result)]`` pair for ``read_file``."""
    tc = ToolCall(id=f"rf_{i}", name="read_file", arguments={"path": f"f{i}.py"})
    return [
        Message(role=Role.ASSISTANT, content="", tool_calls=[tc]),
        Message(
            role=Role.TOOL,
            content="",
            tool_results=[LLMToolResult(tool_call_id=f"rf_{i}", content=output)],
        ),
    ]


# ---------------------------------------------------------------------------
# 104.1 — provider declaration
# ---------------------------------------------------------------------------


class TestProviderDeclaration:
    def test_base_default_is_false(self) -> None:
        assert FakeProvider().short_session_mode is False

    def test_inference_snap_flips_below_16k(self) -> None:
        prov = object.__new__(InferenceSnapProvider)
        prov._context_window = 10_240  # gemma4-style per-slot ctx.
        assert prov.short_session_mode is True

    def test_inference_snap_off_above_16k(self) -> None:
        prov = object.__new__(InferenceSnapProvider)
        prov._context_window = 32_768  # qwen3-coder-style ctx.
        assert prov.short_session_mode is False


# ---------------------------------------------------------------------------
# 104.2 — ContextManager threshold + strategy
# ---------------------------------------------------------------------------


class TestContextManagerWiring:
    def test_threshold_default(self) -> None:
        assert _cm(short=False).compaction_threshold == pytest.approx(0.80)

    def test_threshold_short_session(self) -> None:
        cm = _cm(short=True)
        assert cm.compaction_threshold == pytest.approx(0.50)
        assert cm.short_session_mode is True
        assert cm.compaction_strategy is CompactionStrategy.LEDGER_AND_DROP

    def test_strategy_default(self) -> None:
        assert _cm(short=False).compaction_strategy is CompactionStrategy.SUMMARISE

    def test_set_short_session_round_trip(self) -> None:
        cm = _cm(short=False)
        cm.set_short_session_mode(True)
        assert cm.compaction_threshold == pytest.approx(0.50)
        assert cm.compaction_strategy is CompactionStrategy.LEDGER_AND_DROP
        cm.set_short_session_mode(False)
        assert cm.compaction_threshold == pytest.approx(0.80)
        assert cm.compaction_strategy is CompactionStrategy.SUMMARISE

    def test_should_compact_uses_tighter_threshold(self) -> None:
        # ~6 K tokens against a 10 K window: above 0.50, below 0.80.
        msgs = [Message(role=Role.USER, content="x" * 4_800) for _ in range(5)]
        assert _cm(short=False, window=10_000).should_compact(msgs) is False
        assert _cm(short=True, window=10_000).should_compact(msgs) is True


# ---------------------------------------------------------------------------
# 104.2 — ledger build / render
# ---------------------------------------------------------------------------


class TestLedger:
    def test_build_entries_from_tool_rounds(self) -> None:
        cm = _cm(short=True)
        msgs = [Message(role=Role.USER, content="go")]
        for i in range(3):
            msgs.extend(_tool_round(i, output=f"line {i}\nmore detail"))
        entries = cm.build_ledger_entries(msgs)
        assert len(entries) == 3
        assert all(e.tool == "read_file" for e in entries)
        assert entries[0].args_fingerprint == "path=f0.py"
        assert entries[0].success is True
        assert entries[0].summary == "line 0"

    def test_build_entries_marks_errors(self) -> None:
        cm = _cm(short=True)
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="x", name="charmcraft_pack", arguments={})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[LLMToolResult(tool_call_id="x", content="boom", is_error=True)],
            ),
        ]
        (entry,) = cm.build_ledger_entries(msgs)
        assert entry.success is False
        assert entry.tool == "charmcraft_pack"

    def test_render_ledger(self) -> None:
        cm = _cm(short=True)
        text = cm.render_ledger(
            [
                LedgerEntry("read_file", "path=charm.py", True, "import ops"),
                LedgerEntry("charmcraft_pack", "", False, "missing base"),
            ]
        )
        assert "2 earlier tool calls" in text
        assert "read_file(path=charm.py) → ok: import ops" in text
        assert "charmcraft_pack() → error: missing base" in text

    def test_extend_ledger_caps_oldest(self) -> None:
        from cantrip.agent.context import context as ctx_mod

        ledger: list[LedgerEntry] = []
        for i in range(ctx_mod._MAX_LEDGER_ENTRIES + 5):
            ContextManager.extend_ledger(ledger, [LedgerEntry("read_file", f"i={i}", True, "")])
        assert len(ledger) == ctx_mod._MAX_LEDGER_ENTRIES
        # The 5 oldest were evicted.
        assert ledger[0].args_fingerprint == "i=5"


# ---------------------------------------------------------------------------
# 104.2 — ledger-and-drop compaction
# ---------------------------------------------------------------------------


class TestLedgerAndDropCompaction:
    @pytest.mark.asyncio
    async def test_compaction_folds_into_ledger_and_drops_raw(self) -> None:
        cm = _cm(short=True)
        msgs: list[Message] = [Message(role=Role.USER, content="build it")]
        for i in range(6):
            msgs.extend(_tool_round(i))
        before = len(msgs)
        ledger: list[LedgerEntry] = []
        provider = FakeProvider()

        result = await cm.compact(msgs, "system prompt", provider, ledger=ledger)

        # Raw messages collapse to (at most) the protected tail.
        assert len(result) < before
        assert len(result) <= 2
        # The dropped rounds landed in the ledger on AgentState.
        assert len(ledger) >= 4
        assert all(e.tool == "read_file" for e in ledger)
        # No light-model round-trip — ledger-and-drop never calls complete().
        assert provider._call_count == 0
        # The full raw history was *not* virtualised (dropped, not stored).
        assert cm._store.list_files() == []

    @pytest.mark.asyncio
    async def test_summarise_path_unchanged_for_frontier(self) -> None:
        cm = _cm(short=False, window=200_000)
        msgs = [Message(role=Role.USER, content="m" * 800) for _ in range(8)]
        provider = FakeProvider([Response(content="a short summary")])
        result = await cm.compact(msgs, "sys", provider, ledger=[])
        # Summary message + protected tail; the light model was consulted.
        assert result[0].role == Role.SYSTEM
        assert "summary" in result[0].content.lower()
        assert provider._call_count == 1


# ---------------------------------------------------------------------------
# 104.2 — resolver
# ---------------------------------------------------------------------------


class TestResolver:
    def test_explicit_on_off(self) -> None:
        assert resolve_short_session_mode(FakeProvider(), "on") is True
        assert resolve_short_session_mode(FakeProvider(), "off") is False

    def test_auto_defers_to_provider(self) -> None:
        assert resolve_short_session_mode(FakeProvider(), "auto") is False
        assert resolve_short_session_mode(_TightContextProvider(), "auto") is True

    def test_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_SHORT_SESSION", "on")
        assert resolve_short_session_mode(FakeProvider(), None) is True
        monkeypatch.setenv("CANTRIP_SHORT_SESSION", "off")
        assert resolve_short_session_mode(_TightContextProvider(), None) is False

    def test_no_override_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_SHORT_SESSION", raising=False)
        assert resolve_short_session_mode(_TightContextProvider(), None) is True

    def test_garbage_falls_back_to_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_SHORT_SESSION", raising=False)
        assert resolve_short_session_mode(FakeProvider(), "definitely-not-valid") is False


# ---------------------------------------------------------------------------
# 104.3 — per-turn ephemeral mode through CantripAgent
# ---------------------------------------------------------------------------


class TestAgentShortSession:
    def test_agent_picks_up_override(self) -> None:
        agent = CantripAgent(
            provider=FakeProvider(context_window_tokens=4_096), short_session="on"
        )
        assert agent.context_manager.short_session_mode is True
        agent_off = CantripAgent(provider=FakeProvider(), short_session="off")
        assert agent_off.context_manager.short_session_mode is False

    @pytest.mark.asyncio
    async def test_collapse_and_fold_keep_working_set_small(self) -> None:
        # Three user → tool-loop → user cycles; each cycle the model
        # makes one read_file call then replies.
        big = "x" * 2_000  # ~500 tokens of tool output.

        def _resp_pair(i: int) -> list[Response]:
            return [
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id=f"rf_{i}", name="read_file", arguments={"path": f"f{i}.py"})
                    ],
                ),
                Response(content=f"done step {i}"),
            ]

        responses: list[Response] = []
        for i in range(3):
            responses.extend(_resp_pair(i))
        provider = FakeProvider(responses, context_window_tokens=4_096)
        agent = CantripAgent(provider=provider, short_session="on")
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output=big))

        prompt_sizes: list[int] = []
        original_build = agent._build_llm_messages

        def _spy(include_budget: bool = False) -> list[Message]:
            msgs = original_build(include_budget=include_budget)
            prompt_sizes.append(agent.context_manager.estimate_tokens(msgs))
            return msgs

        agent._build_llm_messages = _spy  # type: ignore[assignment]

        for i in range(3):
            out = await agent.process_message(f"do step {i}")
            assert out == f"done step {i}"
            # The live working set never carries more than one cycle's
            # worth of raw messages: [user, asst(tc), tool, asst(final)].
            assert len(agent.state.messages) <= 4

        # The first two cycles' read_file calls have been folded into the
        # ledger (the third cycle's fold happens on a fourth-turn collapse
        # that never comes).
        assert len(agent.state.ledger) == 2
        assert [e.tool for e in agent.state.ledger] == ["read_file", "read_file"]
        assert agent.state.ledger[0].args_fingerprint == "path=f0.py"

        # Prompt size stays bounded across cycles: the ledger grows by a
        # handful of tokens per turn, not a 500-token tool result.  Without
        # the per-turn collapse the spread would be > 1 K.
        assert max(prompt_sizes) - min(prompt_sizes) < 900

    @pytest.mark.asyncio
    async def test_ledger_rendered_into_prompt(self) -> None:
        agent = CantripAgent(
            provider=FakeProvider(context_window_tokens=4_096), short_session="on"
        )
        agent.state.ledger = [LedgerEntry("read_file", "path=charm.py", True, "import ops")]
        msgs = agent._build_llm_messages()
        # System prompt first, then the rendered ledger as a SYSTEM message.
        assert msgs[1].role == Role.SYSTEM
        assert "History Ledger" in msgs[1].content
        assert "read_file(path=charm.py)" in msgs[1].content

    @pytest.mark.asyncio
    async def test_no_ledger_message_when_not_short_session(self) -> None:
        agent = CantripAgent(provider=FakeProvider(), short_session="off")
        agent.state.ledger = [LedgerEntry("read_file", "path=x.py", True, "")]
        msgs = agent._build_llm_messages()
        assert all("History Ledger" not in (m.content or "") for m in msgs)
