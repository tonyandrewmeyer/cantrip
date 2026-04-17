"""Tests for context window management."""

import re

import pytest

from cantrip.agent.context import ContextManager, VirtualFileStore
from cantrip.llm.base import Message, Response, Role, ToolCall
from cantrip.llm.base import ToolResult as LLMToolResult
from tests.conftest import FakeProvider


class TestVirtualFileStore:
    """Tests for VirtualFileStore."""

    def test_store_and_retrieve(self):
        """Stored content can be retrieved by ID."""
        store = VirtualFileStore()
        file_id = store.store("hello world", name="test.txt", source="test")

        vf = store.get(file_id)

        assert vf is not None
        assert vf.content == "hello world"
        assert vf.name == "test.txt"
        assert vf.source == "test"

    def test_sequential_ids(self):
        """File IDs increment sequentially."""
        store = VirtualFileStore()
        id1 = store.store("a", name="a", source="test")
        id2 = store.store("b", name="b", source="test")

        assert id1 == "vf_1"
        assert id2 == "vf_2"

    def test_get_nonexistent(self):
        """Getting a nonexistent ID returns None."""
        store = VirtualFileStore()
        assert store.get("vf_999") is None

    def test_token_estimate(self):
        """Token estimate is chars // 4."""
        store = VirtualFileStore()
        file_id = store.store("A" * 400, name="big", source="test")
        vf = store.get(file_id)
        assert vf is not None
        assert vf.token_estimate == 100

    def test_get_lines(self):
        """Line-range reads return the correct slice."""
        store = VirtualFileStore()
        content = "line1\nline2\nline3\nline4\nline5"
        file_id = store.store(content, name="lines.txt", source="test")

        result = store.get_lines(file_id, 2, 5)

        assert result == "line2\nline3\nline4"

    def test_get_lines_clamped(self):
        """Out-of-range line indices are clamped."""
        store = VirtualFileStore()
        file_id = store.store("line1\nline2", name="short.txt", source="test")

        result = store.get_lines(file_id, 0, 100)

        assert result == "line1\nline2"

    def test_get_lines_nonexistent(self):
        """get_lines returns None for a nonexistent file."""
        store = VirtualFileStore()
        assert store.get_lines("vf_999", 1, 5) is None

    def test_search_single_file(self):
        """Regex search matches lines in a specific file."""
        store = VirtualFileStore()
        file_id = store.store("foo bar\nbaz qux\nfoo baz", name="f.txt", source="test")

        matches = store.search(r"foo", file_id=file_id)

        assert len(matches) == 2
        assert matches[0].line_number == 1
        assert matches[0].line == "foo bar"
        assert matches[1].line_number == 3

    def test_search_all_files(self):
        """Search across all files when no file_id is given."""
        store = VirtualFileStore()
        store.store("alpha\nbeta", name="a.txt", source="test")
        store.store("gamma\nalpha", name="b.txt", source="test")

        matches = store.search(r"alpha")

        assert len(matches) == 2

    def test_search_no_matches(self):
        """Search returns empty list when nothing matches."""
        store = VirtualFileStore()
        store.store("hello world", name="f.txt", source="test")

        matches = store.search(r"zzz")

        assert matches == []

    def test_search_invalid_regex(self):
        """Invalid regex raises re.error."""
        store = VirtualFileStore()
        store.store("test", name="f.txt", source="test")

        with pytest.raises(re.error):
            store.search(r"[invalid")

    def test_search_max_matches(self):
        """Search respects the max_matches limit."""
        store = VirtualFileStore()
        content = "\n".join(f"match_{i}" for i in range(50))
        store.store(content, name="many.txt", source="test")

        matches = store.search(r"match_", max_matches=5)

        assert len(matches) == 5

    def test_list_files(self):
        """list_files returns all stored files."""
        store = VirtualFileStore()
        store.store("a", name="a.txt", source="test")
        store.store("b", name="b.txt", source="test")

        files = store.list_files()

        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"a.txt", "b.txt"}


class TestContextManagerEstimation:
    """Tests for ContextManager.estimate_tokens."""

    def test_simple_messages(self):
        """Content-only messages produce expected estimate."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [
            Message(role=Role.USER, content="A" * 400),
            Message(role=Role.ASSISTANT, content="B" * 400),
        ]

        assert cm.estimate_tokens(messages) == 200

    def test_with_tool_calls(self):
        """Tool call names and arguments count towards the estimate."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "x"})],
            ),
        ]

        result = cm.estimate_tokens(messages)
        expected = (len("read_file") + len(str({"path": "x"}))) // 4
        assert result == expected

    def test_with_tool_results(self):
        """Tool result content counts towards the estimate."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[LLMToolResult(tool_call_id="tc1", content="X" * 800)],
            ),
        ]

        assert cm.estimate_tokens(messages) == 200


class TestContextManagerVirtualisation:
    """Tests for ContextManager.virtualise_message."""

    def test_below_threshold_unchanged(self):
        """Messages below the threshold are returned unchanged."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000, virtualisation_threshold=1000)

        msg = Message(role=Role.USER, content="short")
        result = cm.virtualise_message(msg)

        assert result is msg

    def test_above_threshold_virtualised(self):
        """Messages above the threshold get a virtual file pointer."""
        store = VirtualFileStore()
        cm = ContextManager(
            store,
            context_window_tokens=100_000,
            virtualisation_threshold=100,
            virtualisation_preview=50,
        )

        # 2000 chars = 500 tokens, well above threshold of 100.
        msg = Message(role=Role.USER, content="X" * 2000)
        result = cm.virtualise_message(msg)

        assert "vf_1" in result.content
        assert "virtual_file_read" in result.content
        # The preview should be 50 * 4 = 200 chars.
        assert result.content.startswith("X" * 200)

    def test_tool_results_virtualised_independently(self):
        """Each tool result in a TOOL message is checked independently."""
        store = VirtualFileStore()
        cm = ContextManager(
            store,
            context_window_tokens=100_000,
            virtualisation_threshold=100,
            virtualisation_preview=25,
        )

        msg = Message(
            role=Role.TOOL,
            content="",
            tool_results=[
                LLMToolResult(tool_call_id="tc1", content="small"),
                LLMToolResult(tool_call_id="tc2", content="Y" * 2000),
            ],
        )
        result = cm.virtualise_message(msg)

        # First result unchanged.
        assert result.tool_results[0].content == "small"
        # Second result virtualised.
        assert "vf_1" in result.tool_results[1].content

    def test_tool_results_below_threshold_unchanged(self):
        """TOOL messages with all small results are returned unchanged."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000, virtualisation_threshold=1000)

        msg = Message(
            role=Role.TOOL,
            content="",
            tool_results=[LLMToolResult(tool_call_id="tc1", content="ok")],
        )
        result = cm.virtualise_message(msg)

        assert result is msg


class TestContextManagerBudget:
    """Tests for ContextManager.build_budget_message."""

    def test_budget_message_format(self):
        """Budget message includes token counts and virtual file list."""
        store = VirtualFileStore()
        store.store("content", name="test.txt", source="test")
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [Message(role=Role.USER, content="A" * 400)]
        budget = cm.build_budget_message(messages)

        assert budget.role == Role.USER
        assert "[Context Budget]" in budget.content
        assert "100 / 100,000" in budget.content
        assert "vf_1" in budget.content
        assert "test.txt" in budget.content

    def test_budget_message_without_virtual_files(self):
        """Budget message works when no virtual files exist."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=50_000)

        messages = [Message(role=Role.USER, content="hello")]
        budget = cm.build_budget_message(messages)

        assert "[Context Budget]" in budget.content
        assert "Virtual files" not in budget.content


class TestContextManagerCompaction:
    """Tests for ContextManager.should_compact and compact."""

    def test_should_compact_below_threshold(self):
        """Returns False when usage is below the threshold."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000, compaction_threshold=0.80)

        messages = [Message(role=Role.USER, content="short")]

        assert cm.should_compact(messages) is False

    def test_should_compact_above_threshold(self):
        """Returns True when usage exceeds the threshold."""
        store = VirtualFileStore()
        # Context window of 100 tokens, threshold at 80%.
        cm = ContextManager(store, context_window_tokens=100, compaction_threshold=0.80)

        # 400 chars = 100 tokens = 100% > 80%.
        messages = [
            Message(role=Role.USER, content="A" * 100),
            Message(role=Role.ASSISTANT, content="B" * 100),
            Message(role=Role.USER, content="C" * 100),
            Message(role=Role.ASSISTANT, content="D" * 100),
            Message(role=Role.USER, content="E" * 100),
        ]

        assert cm.should_compact(messages) is True

    def test_should_compact_too_few_messages(self):
        """Returns False when there are too few messages to compact."""
        store = VirtualFileStore()
        # Even though tokens would exceed, we need more than _KEEP_RECENT messages.
        cm = ContextManager(store, context_window_tokens=10, compaction_threshold=0.80)

        messages = [
            Message(role=Role.USER, content="A" * 400),
        ]

        assert cm.should_compact(messages) is False

    @pytest.mark.asyncio
    async def test_compact_creates_virtual_file(self):
        """Compaction saves history as a virtual file and shortens messages."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        # Realistic-size content so compaction is a genuine shrink — the
        # post-compaction size-validation check falls back to
        # emergency_truncate when the summary isn't smaller than the input.
        filler = "padding to make each message substantial " * 20
        messages = [
            Message(role=Role.USER, content=f"first question {filler}"),
            Message(role=Role.ASSISTANT, content=f"first answer {filler}"),
            Message(role=Role.USER, content=f"second question {filler}"),
            Message(role=Role.ASSISTANT, content=f"second answer {filler}"),
            Message(role=Role.USER, content=f"third question {filler}"),
            Message(role=Role.ASSISTANT, content=f"third answer {filler}"),
        ]

        provider = FakeProvider(
            [
                Response(content="This is a summary of the conversation."),
            ]
        )

        result = await cm.compact(messages, system_prompt="You are helpful.", provider=provider)

        # Should have: summary + last 4 messages.
        assert len(result) == 5
        assert "[Conversation Summary]" in result[0].content
        assert "vf_1" in result[0].content

        # messages[-4:] = second question, second answer, third question, third answer.
        assert result[1].content == f"second question {filler}"
        assert result[2].content == f"second answer {filler}"
        assert result[3].content == f"third question {filler}"
        assert result[4].content == f"third answer {filler}"

        # Virtual file should exist.
        vf = store.get("vf_1")
        assert vf is not None
        assert vf.source == "compaction"

    @pytest.mark.asyncio
    async def test_compact_preserves_recent_messages(self):
        """Compaction keeps the most recent exchange pair."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        filler = "padding to make each message substantial " * 20
        messages = [Message(role=Role.USER, content=f"msg_{i} {filler}") for i in range(10)]

        provider = FakeProvider([Response(content="summary")])
        result = await cm.compact(messages, system_prompt="test", provider=provider)

        # summary + last 4.
        assert len(result) == 5
        assert result[1].content == f"msg_6 {filler}"
        assert result[4].content == f"msg_9 {filler}"

    @pytest.mark.asyncio
    async def test_compact_failure_does_not_crash(self):
        """A failed compaction should not propagate when called via the fallback path."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [
            Message(role=Role.USER, content="first question"),
            Message(role=Role.ASSISTANT, content="first answer"),
            Message(role=Role.USER, content="second question"),
            Message(role=Role.ASSISTANT, content="second answer"),
            Message(role=Role.USER, content="third question"),
            Message(role=Role.ASSISTANT, content="third answer"),
        ]

        provider = FakeProvider([])

        # Patch the provider to raise on complete().
        async def _exploding_complete(_msgs, **_kwargs):
            raise RuntimeError("rate limit exceeded")

        provider.complete = _exploding_complete  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="rate limit"):
            await cm.compact(messages, system_prompt="test", provider=provider)

        # The caller (core.py) catches this and falls back to emergency_truncate.
        result = cm.emergency_truncate(messages)
        assert len(result) > 0
        # Most recent message is preserved.
        assert result[-1].content == "third answer"


class TestEmergencyTruncate:
    """Tests for ContextManager.emergency_truncate."""

    def test_preserves_system_and_recent_messages(self):
        """System message is kept and recent messages are preserved."""
        store = VirtualFileStore()
        # Tiny context window so truncation is forced.
        # 50 tokens * 0.80 = 40 token budget; system="system" ~2 tokens,
        # so ~38 tokens left for non-system messages.
        cm = ContextManager(store, context_window_tokens=50)

        messages = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="A" * 200),  # 50 tokens
            Message(role=Role.ASSISTANT, content="B" * 200),  # 50 tokens
            Message(role=Role.USER, content="C" * 40),  # 10 tokens
            Message(role=Role.ASSISTANT, content="D" * 40),  # 10 tokens
        ]

        result = cm.emergency_truncate(messages)

        # System message must be first.
        assert result[0].role == Role.SYSTEM
        assert result[0].content == "system"
        # Most recent messages should be kept, oldest dropped.
        assert result[-1].content == "D" * 40
        assert result[-2].content == "C" * 40
        # Old messages should be dropped (total non-system kept < original).
        assert len(result) < len(messages)

    def test_no_system_message(self):
        """Works correctly when there is no system message."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=50)

        messages = [
            Message(role=Role.USER, content="A" * 100),
            Message(role=Role.ASSISTANT, content="B" * 100),
            Message(role=Role.USER, content="C" * 40),
        ]

        result = cm.emergency_truncate(messages)

        # Most recent message should always be kept.
        assert result[-1].content == "C" * 40
        assert all(m.role != Role.SYSTEM for m in result)

    def test_keeps_at_least_one_message(self):
        """Even with a very tiny budget, at least one message is kept."""
        store = VirtualFileStore()
        # Budget so small nothing really fits.
        cm = ContextManager(store, context_window_tokens=1)

        messages = [
            Message(role=Role.USER, content="A" * 400),
            Message(role=Role.ASSISTANT, content="B" * 400),
        ]

        result = cm.emergency_truncate(messages)

        # Must keep at least the most recent message.
        assert len(result) >= 1
        assert result[-1].content == "B" * 400

    def test_all_messages_fit(self):
        """When all messages fit in the budget, none are dropped."""
        store = VirtualFileStore()
        cm = ContextManager(store, context_window_tokens=100_000)

        messages = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content="hi"),
        ]

        result = cm.emergency_truncate(messages)

        assert len(result) == 3
