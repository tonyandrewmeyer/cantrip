"""Tests for Claude LLM provider."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from cantrip.llm.base import (
    Image,
    Message,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Role,
    ToolCall,
)
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


class TestClaudeProviderAccurateTokenCount:
    """Phase 41.5: ClaudeProvider.count_tokens_accurate via the Anthropic API."""

    @pytest.mark.asyncio
    async def test_api_returns_input_tokens(self):
        """The API's input_tokens value is returned on success."""
        fake_result = MagicMock()
        fake_result.input_tokens = 1234

        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            provider = ClaudeProvider(api_key="test-key", model="claude-sonnet-4-6")

            async def fake_count(**_kwargs):
                return fake_result

            provider.client.messages.count_tokens = fake_count

            result = await provider.count_tokens_accurate(
                [Message(role=Role.USER, content="Hello there")]
            )
            assert result == 1234

    @pytest.mark.asyncio
    async def test_empty_messages_uses_heuristic(self):
        """Empty messages list should not make a doomed API call."""
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            provider = ClaudeProvider(api_key="test-key", model="claude-sonnet-4-6")
            called = {"count": 0}

            async def fake_count(**_kwargs):
                called["count"] += 1
                return MagicMock(input_tokens=999)

            provider.client.messages.count_tokens = fake_count

            result = await provider.count_tokens_accurate([])
            assert result == 0
            assert called["count"] == 0

    @pytest.mark.asyncio
    async def test_api_error_falls_back_to_heuristic(self):
        """An APIError drops to the char/4 heuristic rather than raising."""
        import anthropic as real_anthropic

        with patch("cantrip.llm.claude.anthropic", real_anthropic):
            from cantrip.llm.claude import ClaudeProvider

            provider = ClaudeProvider(api_key="test-key", model="claude-sonnet-4-6")

            async def raising(**_kwargs):
                raise real_anthropic.APIError(message="nope", request=MagicMock(), body=None)

            provider.client.messages.count_tokens = raising

            msgs = [Message(role=Role.USER, content="A" * 100)]
            result = await provider.count_tokens_accurate(msgs)
            # Heuristic: 100 chars // 4 = 25.
            assert result == 25


class TestClaudeProviderCacheEligibility:
    """Phase 41.3: warn once when the system prompt is too short for caching."""

    def _make_provider(self, model: str = "claude-sonnet-4-6"):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key", model=model)

    def test_short_prompt_logs_warning(self, caplog):
        """Sonnet/Haiku warn when system prompt is below 1024 tokens."""
        import logging

        provider = self._make_provider("claude-sonnet-4-6")
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility("tiny prompt")

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("1024-token minimum" in m for m in warnings)

    def test_short_prompt_logs_warning_opus(self, caplog):
        """Opus warns at its higher 2048-token threshold."""
        import logging

        provider = self._make_provider("claude-opus-4-7")
        # ~1500 tokens — fine for Sonnet but below Opus's 2048 threshold.
        prompt = "x" * (1500 * 4)
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility(prompt)

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("2048-token minimum" in m for m in warnings)

    def test_long_prompt_does_not_warn(self, caplog):
        """A prompt well over the threshold produces no warning."""
        import logging

        provider = self._make_provider("claude-sonnet-4-6")
        # ~2000 tokens — comfortably above 1024.
        prompt = "x" * (2000 * 4)
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility(prompt)

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("caching" in m.lower() for m in warnings)

    def test_warning_logs_only_once(self, caplog):
        """Repeated short-prompt calls emit the warning only once per provider."""
        import logging

        provider = self._make_provider("claude-sonnet-4-6")
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility("tiny")
            provider._check_cache_eligibility("tiny")
            provider._check_cache_eligibility("tiny")

        warnings = [r for r in caplog.records if "1024-token minimum" in r.getMessage()]
        assert len(warnings) == 1

    def test_short_prompt_logs_warning_haiku(self, caplog):
        """Haiku models warn at the 2048-token threshold, not 1024.

        Anthropic's documented Haiku minimum is 2048 tokens (Sonnet
        uses 1024).  A live bisect against ``claude-haiku-4-5`` showed
        the API silently ignores the ``cache_control`` hint below that
        threshold — the call goes through with ``cache_creation_input_tokens=0``
        and no error.  Treating Haiku like Sonnet here used to make the
        warning under-fire, so an operator with a 1500-token Haiku
        system prompt thought they were caching when they weren't.
        """
        import logging

        provider = self._make_provider("claude-haiku-4-5-20251001")
        # ~1500 tokens — fine for Sonnet but below Haiku's 2048 threshold.
        prompt = "x" * (1500 * 4)
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility(prompt)

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("2048-token minimum" in m for m in warnings)

    def test_haiku_long_prompt_does_not_warn(self, caplog):
        """A Haiku prompt well over 2048 tokens produces no warning."""
        import logging

        provider = self._make_provider("claude-haiku-4-5-20251001")
        # ~3000 tokens — over Haiku's 2048-token floor.
        prompt = "x" * (3000 * 4)
        with caplog.at_level(logging.WARNING, logger="cantrip.llm.claude"):
            provider._check_cache_eligibility(prompt)

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("caching" in m.lower() for m in warnings)


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


class TestClaudeProviderVision:
    """Phase 48.1: Claude accepts image attachments on user messages."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    def test_supports_vision_is_true(self):
        """Claude models all advertise vision support."""
        assert self._make_provider().supports_vision is True

    def test_user_message_with_image_produces_content_blocks(self):
        """A user message with an image converts to image + text blocks."""
        provider = self._make_provider()
        img_bytes = b"\x89PNG\r\n\x1a\nfake-png-body"
        msg = Message(
            role=Role.USER,
            content="describe this",
            images=[Image(data=img_bytes, mime="image/png")],
        )

        [entry] = provider._convert_messages([msg])

        assert entry["role"] == "user"
        # Image block precedes the text block so the model sees the
        # visual before the instruction referencing it.
        [image_block, text_block] = entry["content"]
        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "base64"
        assert image_block["source"]["media_type"] == "image/png"
        assert base64.b64decode(image_block["source"]["data"]) == img_bytes
        assert text_block == {"type": "text", "text": "describe this"}

    def test_user_message_with_image_only_omits_text_block(self):
        """An image-only user message produces just the image block."""
        provider = self._make_provider()
        msg = Message(
            role=Role.USER,
            content="",
            images=[Image(data=b"jpgbytes", mime="image/jpeg")],
        )

        [entry] = provider._convert_messages([msg])

        assert len(entry["content"]) == 1
        assert entry["content"][0]["type"] == "image"
        assert entry["content"][0]["source"]["media_type"] == "image/jpeg"

    def test_oversized_image_raises_provider_error(self):
        """Images over 5 MB fail client-side with a clear error."""
        provider = self._make_provider()
        # 5 MB + one byte.
        oversized = b"\x00" * (5 * 1024 * 1024 + 1)
        msg = Message(
            role=Role.USER,
            content="too big",
            images=[Image(data=oversized, mime="image/png")],
        )

        with pytest.raises(ProviderError, match="exceeds Claude's"):
            provider._convert_messages([msg])

    def test_plain_user_message_still_uses_string_content(self):
        """No-image user messages are unchanged — preserves old wire format."""
        provider = self._make_provider()
        [entry] = provider._convert_messages([Message(role=Role.USER, content="hi")])
        assert entry == {"role": "user", "content": "hi"}

    def test_tool_result_with_images_emits_image_content_blocks(self):
        """Phase 48.2b: tool results with images emit image + text blocks."""
        provider = self._make_provider()
        img_bytes = b"\x89PNGrendered-bytes"
        tool_msg = Message(
            role=Role.TOOL,
            content="",
            tool_results=[
                LLMToolResult(
                    tool_call_id="tc_42",
                    content="Rendered panel 7.",
                    images=[Image(data=img_bytes, mime="image/png")],
                )
            ],
        )

        [entry] = provider._convert_messages([tool_msg])

        assert entry["role"] == "user"
        [block] = entry["content"]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tc_42"
        # Image block precedes the text caption inside the tool_result
        # content list so the model sees the visual before the caption.
        image_block, text_block = block["content"]
        assert image_block["type"] == "image"
        assert image_block["source"]["media_type"] == "image/png"
        assert base64.b64decode(image_block["source"]["data"]) == img_bytes
        assert text_block == {"type": "text", "text": "Rendered panel 7."}

    def test_tool_result_without_images_still_uses_string_content(self):
        """Image-free tool results keep the plain-string content format."""
        provider = self._make_provider()
        tool_msg = Message(
            role=Role.TOOL,
            content="",
            tool_results=[LLMToolResult(tool_call_id="tc_1", content="plain text")],
        )
        [entry] = provider._convert_messages([tool_msg])
        [block] = entry["content"]
        assert block["content"] == "plain text"

    def test_tool_result_image_enforces_size_cap(self):
        """Oversize images in tool results fail the same client-side check."""
        provider = self._make_provider()
        oversized = b"\x00" * (5 * 1024 * 1024 + 1)
        tool_msg = Message(
            role=Role.TOOL,
            content="",
            tool_results=[
                LLMToolResult(
                    tool_call_id="tc_1",
                    content="too big",
                    images=[Image(data=oversized, mime="image/png")],
                )
            ],
        )
        with pytest.raises(ProviderError, match="exceeds Claude's"):
            provider._convert_messages([tool_msg])


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

    def test_convert_tools_marks_last_tool_for_caching(self):
        """The final tool gets cache_control so the tools block joins the cached prefix."""
        from cantrip.llm.base import Tool

        provider = self._make_provider()
        tools = [
            Tool(name="a", description="A", parameters={"type": "object"}),
            Tool(name="b", description="B", parameters={"type": "object"}),
            Tool(name="c", description="C", parameters={"type": "object"}),
        ]

        result = provider._convert_tools(tools)

        assert result is not None
        assert "cache_control" not in result[0]
        assert "cache_control" not in result[1]
        assert result[-1]["cache_control"] == {"type": "ephemeral"}

    def test_convert_tools_single_tool_marked(self):
        """A single tool is still marked — the cached prefix covers system + that tool."""
        from cantrip.llm.base import Tool

        provider = self._make_provider()
        tools = [Tool(name="solo", description="Solo", parameters={"type": "object"})]

        result = provider._convert_tools(tools)

        assert result is not None
        assert result[0]["cache_control"] == {"type": "ephemeral"}


class TestClaudeProviderMessageHistoryCaching:
    """Phase: extend the cached prefix across the conversation history."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key", model="claude-sonnet-4-6")

    def test_empty_messages_no_op(self):
        """An empty message list does not crash and adds nothing."""
        provider = self._make_provider()
        api_messages: list[dict] = []

        provider._mark_last_message_for_caching(api_messages)

        assert api_messages == []

    def test_string_content_upgraded_to_text_block(self):
        """Plain user-string content is converted to a text block carrying cache_control."""
        provider = self._make_provider()
        api_messages = [{"role": "user", "content": "Hello"}]

        provider._mark_last_message_for_caching(api_messages)

        assert api_messages[0]["content"] == [
            {
                "type": "text",
                "text": "Hello",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_only_last_message_marked(self):
        """Earlier messages are untouched; only the trailing message gets the marker."""
        provider = self._make_provider()
        api_messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ]

        provider._mark_last_message_for_caching(api_messages)

        assert api_messages[0]["content"] == "first"
        assert api_messages[1]["content"] == "second"
        assert api_messages[2]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_block_list_marks_final_block(self):
        """When content is already a list of blocks, mark the last one in place."""
        provider = self._make_provider()
        api_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tc_1", "content": "ok"},
                    {"type": "tool_result", "tool_use_id": "tc_2", "content": "ok"},
                ],
            }
        ]

        provider._mark_last_message_for_caching(api_messages)

        blocks = api_messages[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_build_kwargs_marks_last_message(self):
        """The wire payload from _build_kwargs carries the cache marker on the trailing message."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="You are helpful."),
            Message(role=Role.USER, content="hi"),
        ]

        kwargs = provider._build_kwargs(messages, tools=None, temperature=0.7, max_tokens=None)

        last = kwargs["messages"][-1]
        assert last["content"][-1]["cache_control"] == {"type": "ephemeral"}


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

        chunks = [
            chunk async for chunk in provider.stream([Message(role=Role.USER, content="Hi")])
        ]

        final = chunks[-1]
        assert final.is_final
        assert final.usage["prompt_tokens"] == 42
        assert final.usage["completion_tokens"] == 17
        assert final.usage["cache_creation_input_tokens"] == 5
        assert final.usage["cache_read_input_tokens"] == 3


class TestClaudeProviderThinkingBudgetWire:
    """Phase 78.4: assert ``thinking`` payload lands on the outgoing wire.

    The April 23 postmortem showed that a silently-dropped field can
    cascade for a week before anyone notices.  These tests pin the
    wire shape so a regression fails at unit-test time rather than in
    production.
    """

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key", model="claude-sonnet-4-6")

    @pytest.mark.asyncio
    async def test_complete_sends_thinking_kwarg(self):
        """When ``thinking_budget`` is set, ``messages.create`` gets the field."""
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(input_tokens=1, output_tokens=1)
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0

        captured: dict = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return mock_response

        provider.client.messages.create = fake_create

        await provider.complete(
            [Message(role=Role.USER, content="Hi")],
            thinking_budget=8192,
        )

        assert captured["thinking"] == {"type": "enabled", "budget_tokens": 8192}
        # Temperature must be 1 when extended thinking is enabled.
        assert captured["temperature"] == 1
        # max_tokens must include the thinking budget plus Claude's 4096
        # output headroom.
        assert captured["max_tokens"] >= 8192 + 4096

    @pytest.mark.asyncio
    async def test_complete_omits_thinking_when_budget_none(self):
        """When ``thinking_budget`` is None, no ``thinking`` key is sent."""
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.content = []
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock(input_tokens=1, output_tokens=1)
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0

        captured: dict = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return mock_response

        provider.client.messages.create = fake_create

        await provider.complete([Message(role=Role.USER, content="Hi")])

        assert "thinking" not in captured
        # Caller-supplied temperature must pass through unchanged.
        assert captured["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_stream_sends_thinking_kwarg(self):
        """When ``thinking_budget`` is set, ``messages.stream`` gets the field."""
        provider = self._make_provider()

        captured: dict = {}

        class _MockStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def get_final_message(self):
                final = MagicMock()
                final.usage = None
                return final

        def fake_stream(**kwargs):
            captured.update(kwargs)
            return _MockStream()

        provider.client.messages.stream = fake_stream

        async for _ in provider.stream(
            [Message(role=Role.USER, content="Hi")],
            thinking_budget=4096,
        ):
            pass

        assert captured["thinking"] == {"type": "enabled", "budget_tokens": 4096}
        assert captured["temperature"] == 1
        assert captured["max_tokens"] >= 4096 + 4096

    @pytest.mark.asyncio
    async def test_stream_omits_thinking_when_budget_none(self):
        """Streaming without a budget omits the ``thinking`` key entirely."""
        provider = self._make_provider()

        captured: dict = {}

        class _MockStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def get_final_message(self):
                final = MagicMock()
                final.usage = None
                return final

        def fake_stream(**kwargs):
            captured.update(kwargs)
            return _MockStream()

        provider.client.messages.stream = fake_stream

        async for _ in provider.stream([Message(role=Role.USER, content="Hi")]):
            pass

        assert "thinking" not in captured
        assert captured["temperature"] == 0.7


class TestClaudeProviderCompleteErrors:
    """Anthropic SDK errors raised inside ``complete()`` map to typed exceptions."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            import anthropic as real_anthropic

            mock_anthropic.RateLimitError = real_anthropic.RateLimitError
            mock_anthropic.InternalServerError = real_anthropic.InternalServerError
            mock_anthropic.APIError = real_anthropic.APIError
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_rate_limit_maps_to_provider_rate_limit_error(self):
        """``RateLimitError`` from ``messages.create`` becomes ``ProviderRateLimitError``."""
        import anthropic as real_anthropic

        provider = self._make_provider()
        provider.client.messages.create = MagicMock(
            side_effect=real_anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        )

        with pytest.raises(ProviderRateLimitError, match="rate limit"):
            await provider.complete([Message(role=Role.USER, content="Hi")])

    @pytest.mark.asyncio
    async def test_internal_server_error_maps_to_overloaded(self):
        """``InternalServerError`` becomes ``ProviderOverloadedError``."""
        import anthropic as real_anthropic

        provider = self._make_provider()
        provider.client.messages.create = MagicMock(
            side_effect=real_anthropic.InternalServerError(
                message="overloaded",
                response=MagicMock(status_code=503),
                body=None,
            )
        )

        with pytest.raises(ProviderOverloadedError, match="temporarily unavailable"):
            await provider.complete([Message(role=Role.USER, content="Hi")])

    @pytest.mark.asyncio
    async def test_generic_api_error_maps_to_provider_error(self):
        """A generic ``APIError`` becomes ``ProviderError``."""
        import anthropic as real_anthropic

        provider = self._make_provider()
        provider.client.messages.create = MagicMock(
            side_effect=real_anthropic.APIError(
                message="boom",
                request=MagicMock(),
                body=None,
            )
        )

        with pytest.raises(ProviderError, match="Claude API error"):
            await provider.complete([Message(role=Role.USER, content="Hi")])


class TestClaudeProviderStreamErrors:
    """Server-side errors during ``stream()`` map to the same typed exceptions."""

    def _make_provider(self):
        with patch("cantrip.llm.claude.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = MagicMock()
            import anthropic as real_anthropic

            mock_anthropic.RateLimitError = real_anthropic.RateLimitError
            mock_anthropic.InternalServerError = real_anthropic.InternalServerError
            mock_anthropic.APIError = real_anthropic.APIError
            from cantrip.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key="test-key")

    def _stream_cm_raising(self, error: Exception):
        """Build an async context manager whose iterator raises ``error``."""

        class _CM:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *args):
                pass

            def __aiter__(self_inner):
                return self_inner

            async def __anext__(self_inner):
                raise error

        return _CM()

    @pytest.mark.asyncio
    async def test_stream_internal_server_error_maps_to_overloaded(self):
        """A 5xx during stream iteration surfaces as ``ProviderOverloadedError``."""
        import anthropic as real_anthropic

        provider = self._make_provider()
        error = real_anthropic.InternalServerError(
            message="overloaded",
            response=MagicMock(status_code=503),
            body=None,
        )
        provider.client.messages.stream = MagicMock(return_value=self._stream_cm_raising(error))

        with pytest.raises(ProviderOverloadedError, match="temporarily unavailable"):
            async for _ in provider.stream([Message(role=Role.USER, content="Hi")]):
                pass

    @pytest.mark.asyncio
    async def test_stream_generic_api_error_maps_to_provider_error(self):
        """A generic ``APIError`` during stream iteration surfaces as ``ProviderError``."""
        import anthropic as real_anthropic

        provider = self._make_provider()
        error = real_anthropic.APIError(
            message="boom",
            request=MagicMock(),
            body=None,
        )
        provider.client.messages.stream = MagicMock(return_value=self._stream_cm_raising(error))

        with pytest.raises(ProviderError, match="Claude API error"):
            async for _ in provider.stream([Message(role=Role.USER, content="Hi")]):
                pass
