"""Tests for Claude LLM provider."""

from unittest.mock import MagicMock, patch

import pytest

from cantrip.llm.base import Message, ProviderRateLimitError, Role, ToolCall
from cantrip.llm.base import ToolResult as LLMToolResult


class TestClaudeProviderContextWindow:
    """Tests for ClaudeProvider.context_window_tokens."""

    def _make_provider(self, model: str = "claude-sonnet-4-5-20250929"):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key", model=model)

    def test_known_model(self):
        """Known model returns its mapped context window size."""
        provider = self._make_provider("claude-sonnet-4-5-20250929")
        assert provider.context_window_tokens == 200_000

    def test_unknown_model_returns_default(self):
        """Unknown model falls back to the default context window."""
        provider = self._make_provider("claude-unknown-model")
        assert provider.context_window_tokens == 200_000

    def test_sonnet_4_6(self):
        """Sonnet 4.6 is recognised."""
        provider = self._make_provider("claude-sonnet-4-6")
        assert provider.context_window_tokens == 200_000

    def test_opus_4_7(self):
        """Opus 4.7 is recognised."""
        provider = self._make_provider("claude-opus-4-7")
        assert provider.context_window_tokens == 200_000


class TestClaudeProviderCountTokens:
    """Tests for ClaudeProvider.count_tokens with tool data."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    def test_counts_content_only(self):
        """Basic content-only messages are counted."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.USER, content="A" * 100),
            Message(role=Role.ASSISTANT, content="B" * 200),
        ]
        assert provider.count_tokens(messages) == 300 // 4

    def test_counts_tool_calls(self):
        """Tool call names and arguments contribute to the count."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "x"})],
            ),
        ]
        result = provider.count_tokens(messages)
        expected = (len("read_file") + len(str({"path": "x"}))) // 4
        assert result == expected

    def test_counts_tool_results(self):
        """Tool result content contributes to the count."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[LLMToolResult(tool_call_id="tc1", content="A" * 400)],
            ),
        ]
        assert provider.count_tokens(messages) == 400 // 4


class TestClaudeProviderMessageConversion:
    """Tests for ClaudeProvider._convert_messages."""

    def _make_provider(self):
        """Create a ClaudeProvider with a mocked client."""
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    def test_user_message(self):
        """Test converting a simple user message."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hello")]

        result = provider._convert_messages(messages)

        assert result == [{"role": "user", "content": "Hello"}]

    def test_system_message_skipped(self):
        """Test that system messages are excluded."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="You are helpful."),
            Message(role=Role.USER, content="Hi"),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_assistant_with_tool_calls(self):
        """Test converting an assistant message with tool calls."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Let me check.",
                tool_calls=[
                    ToolCall(id="tc_1", name="juju_status", arguments={"model": "dev"}),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Let me check."}
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "tc_1"
        assert content[1]["name"] == "juju_status"

    def test_tool_result_message(self):
        """Test converting a TOOL message with results."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="tc_1",
                        content="active: Ready",
                        is_error=False,
                    ),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "tool_result"
        assert content[0]["tool_use_id"] == "tc_1"
        assert content[0]["content"] == "active: Ready"
        assert content[0]["is_error"] is False

    def test_system_prompt_extraction(self):
        """Test that system prompt is extracted correctly."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="Be helpful."),
            Message(role=Role.USER, content="Hi"),
        ]

        system = provider._get_system_prompt(messages)
        assert system == "Be helpful."

    def test_no_system_prompt(self):
        """Test that None is returned when no system message exists."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hi")]

        system = provider._get_system_prompt(messages)
        assert system is None


class TestClaudeProviderToolConversion:
    """Tests for ClaudeProvider._convert_tools."""

    def _make_provider(self):
        """Create a ClaudeProvider with a mocked client."""
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    def test_convert_tools(self):
        """Test converting tools to Anthropic format."""
        from cantrip.llm.base import Tool

        provider = self._make_provider()
        tools = [
            Tool(
                name="juju_status",
                description="Get Juju status",
                parameters={"type": "object", "properties": {}},
            ),
        ]

        result = provider._convert_tools(tools)

        assert len(result) == 1
        assert result[0]["name"] == "juju_status"
        assert result[0]["description"] == "Get Juju status"
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_convert_tools_none(self):
        """Test that None tools returns None."""
        provider = self._make_provider()

        assert provider._convert_tools(None) is None
        assert provider._convert_tools([]) is None


class TestClaudeProviderStream:
    """Tests for ClaudeProvider.stream error handling."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            mock_anthropic.RateLimitError = type("RateLimitError", (Exception,), {})
            mock_anthropic.InternalServerError = type(
                "InternalServerError", (Exception,), {"status_code": 503}
            )
            mock_anthropic.APIError = type("APIError", (Exception,), {})
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key"), mock_anthropic

    @pytest.mark.asyncio
    async def test_stream_rate_limit_during_iteration(self):
        """Rate limit errors during stream iteration are caught and re-raised."""
        import anthropic as real_anthropic

        provider, _ = self._make_provider()

        class _MockStreamCM:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise real_anthropic.RateLimitError(
                    message="rate limited",
                    response=MagicMock(status_code=429),
                    body=None,
                )

        provider.client.messages.stream = MagicMock(return_value=_MockStreamCM())

        with pytest.raises(ProviderRateLimitError):
            async for _ in provider.stream([Message(role=Role.USER, content="Hi")]):
                pass

    @pytest.mark.asyncio
    async def test_stream_captures_usage(self):
        """Streaming captures token usage from the final message."""
        provider, _ = self._make_provider()

        # Build a mock usage object matching the Anthropic SDK structure.
        mock_usage = MagicMock()
        mock_usage.input_tokens = 42
        mock_usage.output_tokens = 17
        mock_usage.cache_creation_input_tokens = 5
        mock_usage.cache_read_input_tokens = 3

        mock_final_message = MagicMock()
        mock_final_message.usage = mock_usage

        events = [
            MagicMock(
                type="content_block_start",
                content_block=MagicMock(type="text"),
            ),
            MagicMock(
                type="content_block_delta",
                delta=MagicMock(type="text_delta", text="hello"),
            ),
            MagicMock(type="content_block_stop"),
        ]

        class _MockStream:
            """Mock stream yielding events then providing a final message."""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return _EventIter(events)

            async def get_final_message(self):
                return mock_final_message

        class _EventIter:
            def __init__(self, items):
                self._items = iter(items)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration from None

        provider.client.messages.stream = MagicMock(return_value=_MockStream())

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        final = chunks[-1]
        assert final.is_final
        assert final.usage["prompt_tokens"] == 42
        assert final.usage["completion_tokens"] == 17
        assert final.usage["cache_creation_input_tokens"] == 5
        assert final.usage["cache_read_input_tokens"] == 3
