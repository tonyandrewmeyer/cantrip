"""Tests for ContextManager: virtualisation, compaction, and budget messages."""

import pytest

from cantrip.agent.context import ContextManager, VirtualFileStore
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

        msgs = [Message(role=Role.USER, content=f"message {i}") for i in range(10)]
        result = await cm.compact(msgs, "system prompt", provider)

        # summary + 4 recent = 5 messages.
        assert len(result) == 5
        assert "Conversation Summary" in result[0].content
        # Last 4 messages preserved.
        for i, msg in enumerate(result[1:]):
            assert msg.content == f"message {10 - 4 + i}"

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

        msgs = [Message(role=Role.USER, content=f"msg {i}") for i in range(6)]
        result = await cm.compact(msgs, "prompt", provider)

        assert "vf_1" in result[0].content


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
