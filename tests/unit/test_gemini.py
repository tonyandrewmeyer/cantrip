"""Tests for Gemini LLM provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.llm.base import (
    Message,
    ProviderRateLimitError,
    Role,
    ToolCall,
)
from cantrip.llm.base import Tool as LLMTool
from cantrip.llm.base import ToolResult as LLMToolResult


def _make_provider():
    """Create a GeminiProvider with a mocked client."""
    with patch("cantrip.llm.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        from cantrip.llm.gemini import GeminiProvider

        return GeminiProvider(api_key="test-key"), mock_genai


class TestGeminiProviderMessageConversion:
    """Tests for GeminiProvider._convert_messages."""

    def test_user_message(self):
        """Test converting a simple user message."""
        provider, _ = _make_provider()
        messages = [Message(role=Role.USER, content="Hello")]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].parts[0].text == "Hello"

    def test_system_message_skipped(self):
        """Test that system messages are excluded."""
        provider, _ = _make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="You are helpful."),
            Message(role=Role.USER, content="Hi"),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0].role == "user"

    def test_assistant_text_only(self):
        """Test converting an assistant message without tool calls."""
        provider, _ = _make_provider()
        messages = [Message(role=Role.ASSISTANT, content="Sure, here you go.")]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0].role == "model"
        assert result[0].parts[0].text == "Sure, here you go."

    def test_assistant_with_tool_calls(self):
        """Test converting an assistant message with tool calls and text."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Let me check.",
                tool_calls=[
                    ToolCall(id="juju_status", name="juju_status", arguments={"model": "dev"}),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0].role == "model"
        parts = result[0].parts
        assert len(parts) == 2
        assert parts[0].text == "Let me check."
        assert parts[1].function_call.name == "juju_status"
        assert parts[1].function_call.args == {"model": "dev"}

    def test_assistant_with_tool_calls_no_text(self):
        """Test converting an assistant message with tool calls but no text."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="read_file", name="read_file", arguments={"path": "README.md"}),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        parts = result[0].parts
        # Empty content should not produce a text part.
        assert len(parts) == 1
        assert parts[0].function_call.name == "read_file"

    def test_tool_result_json(self):
        """Test converting a TOOL message with JSON content."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="juju_status",
                        content='{"status": "active"}',
                        is_error=False,
                    ),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0].role == "user"
        # The Part should be a function_response with parsed dict.
        part = result[0].parts[0]
        assert part.function_response is not None

    def test_tool_result_plain_text(self):
        """Test converting a TOOL message with non-JSON content."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="read_file",
                        content="plain text output",
                        is_error=False,
                    ),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        part = result[0].parts[0]
        # Non-JSON content should be wrapped in {"result": ...}.
        assert part.function_response is not None


class TestGeminiProviderToolConversion:
    """Tests for GeminiProvider._convert_tools."""

    def test_convert_tools(self):
        """Test converting tools to Gemini format."""
        provider, _ = _make_provider()
        tools = [
            LLMTool(
                name="juju_status",
                description="Get Juju status",
                parameters={"type": "object", "properties": {}},
            ),
        ]

        result = provider._convert_tools(tools)

        assert result is not None
        assert len(result) == 1
        declarations = result[0].function_declarations
        assert len(declarations) == 1
        assert declarations[0].name == "juju_status"
        assert declarations[0].description == "Get Juju status"

    def test_convert_tools_none(self):
        """Test that None/empty tools returns None."""
        provider, _ = _make_provider()

        assert provider._convert_tools(None) is None
        assert provider._convert_tools([]) is None


class TestGeminiProviderSystemPrompt:
    """Tests for GeminiProvider._get_system_prompt."""

    def test_system_prompt_extraction(self):
        """Test that system prompt is extracted correctly."""
        provider, _ = _make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="Be helpful."),
            Message(role=Role.USER, content="Hi"),
        ]

        system = provider._get_system_prompt(messages)
        assert system == "Be helpful."

    def test_no_system_prompt(self):
        """Test that None is returned when no system message exists."""
        provider, _ = _make_provider()
        messages = [Message(role=Role.USER, content="Hi")]

        system = provider._get_system_prompt(messages)
        assert system is None


class TestGeminiProviderComplete:
    """Tests for GeminiProvider.complete."""

    @pytest.mark.asyncio
    async def test_complete_text_response(self):
        """Test that a text response is parsed correctly."""
        provider, mock_genai = _make_provider()

        # Build a mock response with text parts.
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_part.text = "Hello there!"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Hello")]
        result = await provider.complete(messages)

        assert result.content == "Hello there!"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self):
        """Test that function_call parts produce tool_calls."""
        provider, mock_genai = _make_provider()

        mock_fc = MagicMock()
        mock_fc.name = "juju_status"
        mock_fc.args = {"model": "dev"}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_part.text = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 20
        mock_response.usage_metadata.candidates_token_count = 10

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Show status")]
        result = await provider.complete(messages)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "juju_status"
        assert result.tool_calls[0].arguments == {"model": "dev"}
        assert result.finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_complete_rate_limit_error(self):
        """Test that a 429 ClientError raises ProviderRateLimitError."""
        provider, mock_genai = _make_provider()

        from google.genai import errors as genai_errors

        error = genai_errors.ClientError(code=429, response_json={})

        provider._client.aio.models.generate_content = AsyncMock(side_effect=error)

        messages = [Message(role=Role.USER, content="Hello")]

        with pytest.raises(ProviderRateLimitError):
            await provider.complete(messages)


class TestGeminiProviderStream:
    """Tests for GeminiProvider.stream."""

    @pytest.mark.asyncio
    async def test_stream_text_chunks(self):
        """Test that text parts are yielded as chunks."""
        provider, _ = _make_provider()

        # Build mock stream chunks.
        chunk1_part = MagicMock()
        chunk1_part.function_call = None
        chunk1_part.text = "Hello "
        chunk1 = MagicMock()
        chunk1.candidates = [MagicMock()]
        chunk1.candidates[0].content.parts = [chunk1_part]

        chunk2_part = MagicMock()
        chunk2_part.function_call = None
        chunk2_part.text = "world!"
        chunk2 = MagicMock()
        chunk2.candidates = [MagicMock()]
        chunk2.candidates[0].content.parts = [chunk2_part]

        async def mock_stream(*args, **kwargs):  # noqa: ARG001
            yield chunk1
            yield chunk2

        provider._client.aio.models.generate_content_stream = mock_stream

        messages = [Message(role=Role.USER, content="Hi")]
        chunks = []
        async for c in provider.stream(messages):
            chunks.append(c)

        # Two text chunks + one final chunk.
        assert len(chunks) == 3
        assert chunks[0].content == "Hello "
        assert chunks[1].content == "world!"
        assert chunks[2].is_final is True
        assert chunks[2].tool_calls == []

    @pytest.mark.asyncio
    async def test_stream_tool_calls_accumulated(self):
        """Test that function_calls are batched into the final chunk."""
        provider, _ = _make_provider()

        mock_fc = MagicMock()
        mock_fc.name = "read_file"
        mock_fc.args = {"path": "README.md"}

        chunk_part = MagicMock()
        chunk_part.function_call = mock_fc
        chunk_part.text = None
        chunk = MagicMock()
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].content.parts = [chunk_part]

        async def mock_stream(*args, **kwargs):  # noqa: ARG001
            yield chunk

        provider._client.aio.models.generate_content_stream = mock_stream

        messages = [Message(role=Role.USER, content="Read the file")]
        chunks = []
        async for c in provider.stream(messages):
            chunks.append(c)

        # Only the final chunk should exist with tool calls.
        assert len(chunks) == 1
        assert chunks[0].is_final is True
        assert len(chunks[0].tool_calls) == 1
        assert chunks[0].tool_calls[0].name == "read_file"


class TestGeminiProviderCountTokens:
    """Tests for GeminiProvider.count_tokens."""

    def test_count_tokens_approximation(self):
        """Test that token count is chars // 4."""
        provider, _ = _make_provider()
        messages = [
            Message(role=Role.USER, content="A" * 100),
            Message(role=Role.ASSISTANT, content="B" * 200),
        ]

        result = provider.count_tokens(messages)

        assert result == 300 // 4
