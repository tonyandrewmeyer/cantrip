"""Tests for ContextManager: virtualisation, compaction, and budget messages."""

import pytest

from cantrip.agent.context.context import ContextManager, VirtualFileStore
from cantrip.llm.base import Message, Role, ToolResult, estimate_tokens
from tests.conftest import FakeProvider

# Approximate chars per token for the heuristic estimator.
_CPT = 4


class TestVirtualisation:
    """Tests for message virtualisation."""

    def _make_cm(
        self,
        store: VirtualFileStore | None = None,
        threshold: int = 100,
        preview: int = 10,
    ) -> ContextManager:
        return ContextManager(
            virtual_store=store or VirtualFileStore(),
            context_window_tokens=200_000,
            virtualisation_threshold=threshold,
            virtualisation_preview=preview,
        )

    def test_small_message_not_virtualised(self):
        """Messages below the threshold are returned unchanged."""
        cm = self._make_cm(threshold=100)
        msg = Message(role=Role.USER, content="short")
        result = cm.virtualise_message(msg)
        assert result is msg

    def test_large_message_virtualised(self):
        """Messages at or above the threshold are virtualised."""
        cm = self._make_cm(threshold=10)
        content = "x" * (_CPT * 10)  # Exactly 10 tokens.
        msg = Message(role=Role.USER, content=content)
        result = cm.virtualise_message(msg)
        assert "virtual file" in result.content.lower()
        assert "vf_1" in result.content

    def test_virtualised_preserves_role(self):
        cm = self._make_cm(threshold=10)
        msg = Message(role=Role.ASSISTANT, content="x" * (_CPT * 20))
        result = cm.virtualise_message(msg)
        assert result.role == Role.ASSISTANT

    def test_preview_included(self):
        """The virtualised message includes a preview of the content."""
        store = VirtualFileStore()
        cm = self._make_cm(store=store, threshold=10, preview=5)
        content = "abcdefghijklmnopqrstuvwxyz" * 10  # Long content.
        msg = Message(role=Role.USER, content=content)
        result = cm.virtualise_message(msg)
        preview_chars = 5 * _CPT  # 20 characters.
        assert result.content.startswith(content[:preview_chars])

    def test_virtualised_content_stored(self):
        """The full content is stored in the virtual file store."""
        store = VirtualFileStore()
        cm = self._make_cm(store=store, threshold=10)
        content = "x" * (_CPT * 20)
        msg = Message(role=Role.USER, content=content)
        cm.virtualise_message(msg)
        vf = store.get("vf_1")
        assert vf is not None
        assert vf.content == content


class TestToolResultVirtualisation:
    """Tests for tool result virtualisation within TOOL messages."""

    def _make_cm(self, threshold: int = 100) -> ContextManager:
        return ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200_000,
            virtualisation_threshold=threshold,
            virtualisation_preview=10,
        )

    def test_small_tool_result_not_virtualised(self):
        """Tool results below the threshold are not virtualised."""
        cm = self._make_cm(threshold=100)
        tr = ToolResult(tool_call_id="tc1", content="small")
        msg = Message(role=Role.TOOL, content="", tool_results=[tr])
        result = cm.virtualise_message(msg)
        assert result is msg

    def test_large_tool_result_virtualised(self):
        """Tool results at or above the threshold are virtualised."""
        cm = self._make_cm(threshold=10)
        content = "x" * (_CPT * 20)
        tr = ToolResult(tool_call_id="tc1", content=content)
        msg = Message(role=Role.TOOL, content="", tool_results=[tr])
        result = cm.virtualise_message(msg)
        assert "virtual file" in result.tool_results[0].content.lower()

    def test_mixed_tool_results(self):
        """Only oversized tool results are virtualised; small ones are kept."""
        cm = self._make_cm(threshold=10)
        small_tr = ToolResult(tool_call_id="tc1", content="small")
        large_tr = ToolResult(tool_call_id="tc2", content="x" * (_CPT * 20))
        msg = Message(role=Role.TOOL, content="", tool_results=[small_tr, large_tr])
        result = cm.virtualise_message(msg)
        # Small result unchanged.
        assert result.tool_results[0].content == "small"
        # Large result virtualised.
        assert "virtual file" in result.tool_results[1].content.lower()

    def test_error_flag_preserved(self):
        """The is_error flag is preserved on virtualised tool results."""
        cm = self._make_cm(threshold=10)
        tr = ToolResult(tool_call_id="tc1", content="x" * (_CPT * 20), is_error=True)
        msg = Message(role=Role.TOOL, content="", tool_results=[tr])
        result = cm.virtualise_message(msg)
        assert result.tool_results[0].is_error is True


class TestShouldCompact:
    """Tests for the compaction trigger."""

    def _make_cm(self, window: int = 1000) -> ContextManager:
        return ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=window,
            compaction_threshold=0.80,
        )

    def test_few_messages_no_compact(self):
        """Never compacts with <= 4 messages (not enough for summary + recent)."""
        cm = self._make_cm(window=100)
        # Even if messages are huge, 4 or fewer shouldn't compact.
        msgs = [Message(role=Role.USER, content="x" * 400)] * 4
        assert cm.should_compact(msgs) is False

    def test_five_messages_above_threshold(self):
        """Compacts with 5+ messages when tokens exceed 80% of window."""
        cm = self._make_cm(window=100)
        # Each message: 400 chars / 4 = 100 tokens. 5 messages = 500 tokens > 80.
        msgs = [Message(role=Role.USER, content="x" * 400)] * 5
        assert cm.should_compact(msgs) is True

    def test_five_messages_below_threshold(self):
        """Does not compact when tokens are below 80% of window."""
        cm = self._make_cm(window=100_000)
        msgs = [Message(role=Role.USER, content="hello")] * 5
        assert cm.should_compact(msgs) is False


class TestCompact:
    """Tests for the compaction process."""

    @pytest.mark.asyncio
    async def test_compact_returns_summary_plus_recent(self):
        """Compaction returns [summary] + last 4 messages."""
        store = VirtualFileStore()
        cm = ContextManager(
            virtual_store=store,
            context_window_tokens=200_000,
        )
        provider = FakeProvider()

        # Use realistic-size messages so that summarising them actually
        # shrinks the context.  The post-compaction size-validation check
        # falls back to emergency_truncate if the summary is larger than
        # the input, which can happen with trivially-small synthetic
        # messages.
        filler = "conversation content that takes up several tokens " * 20
        msgs = [Message(role=Role.USER, content=f"message {i} {filler}") for i in range(10)]
        result = await cm.compact(msgs, "system prompt", provider)

        # summary + 4 recent = 5 messages.
        assert len(result) == 5
        assert "Conversation Summary" in result[0].content
        # Last 4 messages preserved.
        for i, msg in enumerate(result[1:]):
            assert msg.content == f"message {10 - 4 + i} {filler}"

    @pytest.mark.asyncio
    async def test_compact_stores_full_history(self):
        """Full conversation history is saved as a virtual file."""
        store = VirtualFileStore()
        cm = ContextManager(virtual_store=store, context_window_tokens=200_000)
        provider = FakeProvider()

        msgs = [Message(role=Role.USER, content=f"msg {i}") for i in range(6)]
        await cm.compact(msgs, "prompt", provider)

        files = store.list_files()
        history_files = [f for f in files if f.source == "compaction"]
        assert len(history_files) == 1
        assert "msg 0" in history_files[0].content

    @pytest.mark.asyncio
    async def test_compact_summary_references_virtual_file(self):
        """The summary message references the virtual file ID."""
        store = VirtualFileStore()
        cm = ContextManager(virtual_store=store, context_window_tokens=200_000)
        provider = FakeProvider()

        filler = "conversation content that takes up several tokens " * 20
        msgs = [Message(role=Role.USER, content=f"msg {i} {filler}") for i in range(6)]
        result = await cm.compact(msgs, "prompt", provider)

        assert "vf_1" in result[0].content

    @pytest.mark.asyncio
    async def test_compact_logs_effective_ratio_as_info(self, caplog):
        """A well-compressing run logs an INFO line with the ratio (41.7)."""
        import logging

        cm = ContextManager(virtual_store=VirtualFileStore(), context_window_tokens=200_000)
        filler = "conversation content that takes up several tokens " * 40
        msgs = [Message(role=Role.USER, content=f"msg {i} {filler}") for i in range(10)]

        with caplog.at_level(logging.INFO, logger="cantrip.agent.context.context"):
            await cm.compact(msgs, "prompt", FakeProvider())

        info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("Compaction reduced context" in m for m in info_messages)

    @pytest.mark.asyncio
    async def test_compact_logs_warning_on_ineffective_compression(self, caplog):
        """Compaction that barely shrinks the context warns the operator (41.7)."""
        import logging

        # Tiny window forces the post-size-validation fallback to emergency
        # truncate, but the compression ratio is evaluated on the final
        # result. To exercise the *ineffective* branch specifically, use a
        # medium window and messages whose content nearly matches the
        # summary length so post ≥ 0.9 × pre.
        cm = ContextManager(virtual_store=VirtualFileStore(), context_window_tokens=2_000)
        msgs = [Message(role=Role.USER, content=f"msg {i}") for i in range(8)]

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.context.context"):
            await cm.compact(msgs, "prompt", FakeProvider())

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        # Either the ratio warning fires, or the size-validation fallback
        # logged its own warning — both indicate ineffective compression
        # and either is acceptable evidence of the monitoring wire-up.
        assert any(
            "only reduced context" in m or "did not reduce context size" in m for m in warnings
        )


class TestCompactionSafety:
    """Phase 40: cycle detection, retry budgets, post-compaction validation."""

    # Realistic-size messages so compaction actually shrinks and each fire
    # exercises the full compact() path.
    _FILLER = "conversation content that takes up several tokens " * 20

    def _messages(self, count: int) -> list[Message]:
        return [
            Message(role=Role.USER, content=f"message {i} {self._FILLER}") for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_compaction_counter_increments(self):
        store = VirtualFileStore()
        cm = ContextManager(virtual_store=store, context_window_tokens=200_000)
        assert cm.compactions_attempted == 0
        await cm.compact(self._messages(10), "prompt", FakeProvider())
        assert cm.compactions_attempted == 1

    @pytest.mark.asyncio
    async def test_should_compact_is_one_shot_after_compaction(self):
        """Phase 78.3: compaction is one-shot per turn.

        Walks the exact turn sequence called out in the roadmap:
        1) fill the context past the compaction threshold, 2) run
        compaction, 3) assert ``should_compact()`` is False on the
        compacted output before the new context has any chance to
        refill.  Protects against a re-entry bug where a quirk of the
        threshold-check logic could let the next turn immediately
        fire again, burning tokens on back-to-back summaries.
        """
        cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200_000,
            compaction_threshold=0.8,
        )
        # Build 80%+-of-window worth of content.  ~_CPT chars/token and
        # we need ~160k tokens of filler, so 800 long messages do it.
        heavy = [Message(role=Role.USER, content="x" * 800) for _ in range(800)]
        assert cm.should_compact(heavy) is True

        compacted = await cm.compact(heavy, "prompt", FakeProvider())

        # Immediately after compaction the summary + recent tail must
        # fit well below the threshold; should_compact() must be False.
        assert cm.should_compact(compacted) is False

    @pytest.mark.asyncio
    async def test_budget_exhausted_stops_compacting(self):
        """Once the compaction budget is spent, should_compact returns False
        and a warning is queued for the user."""
        store = VirtualFileStore()
        cm = ContextManager(
            virtual_store=store,
            context_window_tokens=200_000,
            max_compactions=2,
        )
        provider = FakeProvider()

        msgs = self._messages(10)
        await cm.compact(msgs, "prompt", provider)
        await cm.compact(msgs, "prompt", provider)
        assert cm.compactions_attempted == 2

        # Force the threshold to fire by using a tiny context window.
        small_cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200,
            max_compactions=2,
        )
        small_cm.restore_safety_state(2, 0)
        assert small_cm.should_compact(self._messages(10)) is False
        assert small_cm.budget_exhausted is True
        warning = small_cm.consume_safety_warning()
        assert warning is not None
        assert "budget exhausted" in warning.lower()
        # Warning is consumed — a second call returns None.
        assert small_cm.consume_safety_warning() is None

    @pytest.mark.asyncio
    async def test_cycle_detection_latches(self):
        """Three compactions in quick succession with no progress should
        trip cycle detection and queue a user-visible warning."""
        # Tiny window so the summary response never gets us below threshold.
        cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200,
        )
        provider = FakeProvider()

        msgs = self._messages(10)
        for _ in range(3):
            await cm.compact(msgs, "prompt", provider)

        assert cm.cycle_detected is True
        assert cm.should_compact(msgs) is False
        warning = cm.consume_safety_warning()
        assert warning is not None
        assert "growing faster" in warning.lower()

    @pytest.mark.asyncio
    async def test_post_compaction_size_validation_falls_back(self):
        """When the summary doesn't shrink the context, compact() should
        fall back to emergency_truncate on the original messages."""
        # Tiny window: the fixed summary overhead dwarfs any synthetic input,
        # so post >= pre and the fallback fires.
        cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200,
        )
        msgs = [Message(role=Role.USER, content=f"msg {i}") for i in range(8)]
        result = await cm.compact(msgs, "prompt", FakeProvider())
        assert cm.emergencies_attempted == 1
        # The result should not contain the summary header because emergency
        # truncate was used instead.
        assert not result[0].content.startswith("[Conversation Summary]")

    def test_emergency_truncate_counts_and_warns_when_budget_exceeded(self):
        cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=1000,
            max_emergencies=1,
        )
        msgs = self._messages(20)
        cm.emergency_truncate(msgs)
        cm.emergency_truncate(msgs)
        assert cm.emergencies_attempted == 2
        warning = cm.consume_safety_warning()
        assert warning is not None
        assert "emergency" in warning.lower()

    def test_restore_safety_state_round_trip(self):
        cm = ContextManager(virtual_store=VirtualFileStore(), context_window_tokens=200_000)
        cm.restore_safety_state(7, 2)
        assert cm.safety_state() == (7, 2, False, False)
        # Negative inputs are clamped to zero.
        cm.restore_safety_state(-1, -5)
        assert cm.safety_state() == (0, 0, False, False)

    def test_restore_safety_state_round_trips_stop_flags(self):
        """Phase 78.3: cycle_detected / budget_exhausted survive restore."""
        cm = ContextManager(virtual_store=VirtualFileStore(), context_window_tokens=200_000)
        cm.restore_safety_state(3, 1, cycle_detected=True, budget_exhausted=True)
        assert cm.safety_state() == (3, 1, True, True)
        assert cm.cycle_detected is True
        assert cm.budget_exhausted is True

    def test_restored_stop_flag_blocks_should_compact(self):
        """A session resumed with cycle_detected=True doesn't compact again.

        Without persistence, the flag reset to False on resume and the
        next full context window would re-enter the ineffective
        compaction loop — the Phase 78.3 motivation.
        """
        cm = ContextManager(
            virtual_store=VirtualFileStore(),
            context_window_tokens=200,
        )
        cm.restore_safety_state(5, 0, cycle_detected=True)
        # Build an oversized message list that would otherwise trigger
        # compaction.
        msgs = self._messages(20)
        assert cm.should_compact(msgs) is False


class TestBudgetMessage:
    """Tests for the context budget message."""

    def test_budget_message_shows_usage(self):
        store = VirtualFileStore()
        cm = ContextManager(virtual_store=store, context_window_tokens=100_000)
        msgs = [Message(role=Role.USER, content="x" * 400)]
        budget = cm.build_budget_message(msgs)
        assert "100" in budget.content  # token count
        assert "100,000" in budget.content  # window size

    def test_budget_message_lists_virtual_files(self):
        store = VirtualFileStore()
        store.store("content", name="test.txt", source="test")
        cm = ContextManager(virtual_store=store, context_window_tokens=100_000)
        budget = cm.build_budget_message([])
        assert "vf_1" in budget.content
        assert "test.txt" in budget.content


class TestEstimateTokens:
    """Extra edge cases for token estimation."""

    def test_empty_message_zero_tokens(self):
        assert estimate_tokens("") == 0

    def test_boundary_exact_threshold(self):
        """Content at exactly the virtualisation threshold boundary."""
        store = VirtualFileStore()
        cm = ContextManager(
            virtual_store=store,
            context_window_tokens=200_000,
            virtualisation_threshold=10,
        )
        # 9 tokens = 36 chars → just below threshold.
        content_below = "x" * (_CPT * 9)
        msg_below = Message(role=Role.USER, content=content_below)
        assert cm.virtualise_message(msg_below) is msg_below

        # 10 tokens = 40 chars → at threshold.
        content_at = "x" * (_CPT * 10)
        msg_at = Message(role=Role.USER, content=content_at)
        result_at = cm.virtualise_message(msg_at)
        assert "virtual file" in result_at.content.lower()
