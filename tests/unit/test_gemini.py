"""Tests for Gemini LLM provider."""

import base64
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


def _make_provider(model: str = "gemini-3-flash-preview"):
    """Create a GeminiProvider with a mocked client."""
    with patch("cantrip.llm.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        from cantrip.llm.gemini import GeminiProvider

        return GeminiProvider(api_key="test-key", model=model), mock_genai


def _make_text_part(text: str) -> MagicMock:
    """Build a mock response part that contains only text (no thought data)."""
    part = MagicMock()
    part.function_call = None
    part.text = text
    part.thought = False
    part.thought_signature = None
    return part


def _make_function_call_part(name: str, args: dict) -> MagicMock:
    """Build a mock response part that contains a function call."""
    fc = MagicMock()
    fc.name = name
    fc.args = args
    part = MagicMock()
    part.function_call = fc
    part.text = None
    part.thought = False
    part.thought_signature = None
    return part


def _make_thought_part(signature: bytes) -> MagicMock:
    """Build a mock response part that carries a thought signature."""
    part = MagicMock()
    part.function_call = None
    part.text = None
    part.thought = True
    part.thought_signature = signature
    return part


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

    def test_assistant_empty_content_no_tool_calls_omitted(self):
        """An assistant message with empty content and no tool calls is omitted."""
        provider, _ = _make_provider()
        messages = [Message(role=Role.ASSISTANT, content="")]

        result = provider._convert_messages(messages)

        # Empty content with no thought parts produces no Content entries.
        assert len(result) == 0

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

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [_make_text_part("Hello there!")]

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

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [_make_function_call_part("juju_status", {"model": "dev"})]

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

    @pytest.mark.asyncio
    async def test_complete_rate_limit_surfaces_retry_hint(self):
        """Per-day 429s include the retry delay and quota kind in the error."""
        import json as _json

        from google.genai import errors as genai_errors

        provider, _ = _make_provider()
        inner = {
            "error": {
                "code": 429,
                "message": ("You exceeded your current quota... Please retry in 14h28m39.9s."),
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": (
                                    "generativelanguage.googleapis.com/"
                                    "generate_requests_per_model_per_day"
                                )
                            }
                        ],
                    }
                ],
            }
        }
        response_json = {"message": _json.dumps(inner), "status": "Too Many Requests"}
        error = genai_errors.ClientError(code=429, response_json=response_json)

        provider._client.aio.models.generate_content = AsyncMock(side_effect=error)

        with pytest.raises(ProviderRateLimitError) as excinfo:
            await provider.complete([Message(role=Role.USER, content="Hi")])

        message = str(excinfo.value)
        assert "daily quota exhausted" in message
        assert "14h28m39.9s" in message

    @pytest.mark.asyncio
    async def test_complete_none_content_handled(self):
        """Test that a response with None candidate content does not crash."""
        provider, _ = _make_provider()

        mock_candidate = MagicMock()
        mock_candidate.content = None

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 0

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Hello")]
        result = await provider.complete(messages)

        assert result.content == ""
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_complete_none_usage_metadata_handled(self):
        """Test that a response with None usage_metadata does not crash."""
        provider, _ = _make_provider()

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [_make_text_part("Ok")]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Hello")]
        result = await provider.complete(messages)

        assert result.content == "Ok"
        assert result.usage == {"prompt_tokens": 0, "completion_tokens": 0}

    @pytest.mark.asyncio
    async def test_complete_function_call_none_args(self):
        """Test that a function call with args=None does not crash."""
        provider, _ = _make_provider()

        fc = MagicMock()
        fc.name = "test_tool"
        fc.args = None

        mock_part = MagicMock()
        mock_part.function_call = fc
        mock_part.text = None
        mock_part.thought = False
        mock_part.thought_signature = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 2

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Hello")]
        result = await provider.complete(messages)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "test_tool"
        assert result.tool_calls[0].arguments == {}

    @pytest.mark.asyncio
    async def test_complete_duplicate_tool_calls_unique_ids(self):
        """Two calls to the same tool in one response get distinct IDs."""
        provider, _ = _make_provider()

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [
            _make_function_call_part("read_file", {"path": "a.txt"}),
            _make_function_call_part("read_file", {"path": "b.txt"}),
        ]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 8

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete([Message(role=Role.USER, content="Read both")])

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].id == "read_file_0"
        assert result.tool_calls[1].id == "read_file_1"
        # Both should still carry the correct function name.
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[1].name == "read_file"
        assert result.tool_calls[0].arguments == {"path": "a.txt"}
        assert result.tool_calls[1].arguments == {"path": "b.txt"}


class TestGeminiToolResultNameExtraction:
    """Tests for stripping the index suffix from tool call IDs in tool results."""

    def test_tool_result_id_mapped_to_function_name(self):
        """Tool result with indexed ID is sent with the original function name."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="read_file_0",
                        content='{"data": "hello"}',
                    ),
                    LLMToolResult(
                        tool_call_id="read_file_1",
                        content='{"data": "world"}',
                    ),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        parts = result[0].parts
        assert len(parts) == 2
        # Both parts should use the function name "read_file", not the indexed ID.
        assert parts[0].function_response.name == "read_file"
        assert parts[1].function_response.name == "read_file"

    def test_tool_result_id_without_suffix_unchanged(self):
        """A tool call ID with no numeric suffix is passed through unchanged."""
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="juju_status",
                        content='{"status": "active"}',
                    ),
                ],
            ),
        ]

        result = provider._convert_messages(messages)

        parts = result[0].parts
        assert parts[0].function_response.name == "juju_status"


class TestGeminiProviderStream:
    """Tests for GeminiProvider.stream."""

    @pytest.mark.asyncio
    async def test_stream_text_chunks(self):
        """Test that text parts are yielded as chunks."""
        provider, _ = _make_provider()

        chunk1 = MagicMock()
        chunk1.candidates = [MagicMock()]
        chunk1.candidates[0].content.parts = [_make_text_part("Hello ")]

        chunk2 = MagicMock()
        chunk2.candidates = [MagicMock()]
        chunk2.candidates[0].content.parts = [_make_text_part("world!")]

        async def _stream_gen():
            yield chunk1
            yield chunk2

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

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

        chunk = MagicMock()
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].content.parts = [
            _make_function_call_part("read_file", {"path": "README.md"})
        ]

        async def _stream_gen():
            yield chunk

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

        messages = [Message(role=Role.USER, content="Read the file")]
        chunks = []
        async for c in provider.stream(messages):
            chunks.append(c)

        # Only the final chunk should exist with tool calls.
        assert len(chunks) == 1
        assert chunks[0].is_final is True
        assert len(chunks[0].tool_calls) == 1
        assert chunks[0].tool_calls[0].name == "read_file"

    @pytest.mark.asyncio
    async def test_stream_captures_usage(self):
        """Streaming captures token usage from the final chunk (41.1)."""
        provider, _ = _make_provider()

        # Intermediate chunk with partial usage; final chunk overwrites it
        # with the cumulative totals.
        chunk1 = MagicMock()
        chunk1.candidates = [MagicMock()]
        chunk1.candidates[0].content.parts = [_make_text_part("Hello ")]
        chunk1.usage_metadata.prompt_token_count = 10
        chunk1.usage_metadata.candidates_token_count = 2

        chunk2 = MagicMock()
        chunk2.candidates = [MagicMock()]
        chunk2.candidates[0].content.parts = [_make_text_part("world")]
        chunk2.usage_metadata.prompt_token_count = 10
        chunk2.usage_metadata.candidates_token_count = 5

        async def _stream_gen():
            yield chunk1
            yield chunk2

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

        chunks = []
        async for c in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(c)

        final = chunks[-1]
        assert final.is_final
        assert final.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    @pytest.mark.asyncio
    async def test_stream_none_usage_metadata_handled(self):
        """Streaming with ``usage_metadata=None`` degrades to empty usage (41.10)."""
        provider, _ = _make_provider()

        chunk = MagicMock()
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].content.parts = [_make_text_part("Hi")]
        chunk.usage_metadata = None

        async def _stream_gen():
            yield chunk

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

        chunks = []
        async for c in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(c)

        final = chunks[-1]
        assert final.is_final
        assert final.usage == {}


class TestGeminiProviderContextWindow:
    """Tests for GeminiProvider.context_window_tokens."""

    def test_known_model(self):
        """Known model returns its mapped context window size."""
        provider, _ = _make_provider()
        assert provider.context_window_tokens == 1_048_576

    def test_unknown_model_returns_default(self):
        """Unknown model falls back to the default context window."""
        provider, _ = _make_provider(model="gemini-unknown")
        assert provider.context_window_tokens == 1_048_576

    def test_gemini3_flash_context_window(self):
        """Gemini 3 flash preview has an explicit context window entry."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        assert provider.context_window_tokens == 1_048_576

    def test_gemini3_pro_context_window(self):
        """Gemini 3 pro preview has an explicit context window entry."""
        provider, _ = _make_provider(model="gemini-3-pro-preview")
        assert provider.context_window_tokens == 1_048_576

    def test_gemini2_flash_context_window(self):
        """Gemini 2.0 flash still has its context window entry."""
        provider, _ = _make_provider(model="gemini-2.0-flash")
        assert provider.context_window_tokens == 1_048_576


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

    def test_counts_tool_calls(self):
        """Tool call names and arguments contribute to the count."""
        provider, _ = _make_provider()
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
        provider, _ = _make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[LLMToolResult(tool_call_id="tc1", content="A" * 400)],
            ),
        ]
        assert provider.count_tokens(messages) == 400 // 4


class TestGemini3ThinkingConfig:
    """Tests for Gemini 3 thinking configuration."""

    def test_is_gemini_3_flash(self):
        """Gemini 3 flash is detected as a Gemini 3 model."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        assert provider._is_gemini_3() is True

    def test_is_gemini_3_pro(self):
        """Gemini 3 pro is detected as a Gemini 3 model."""
        provider, _ = _make_provider(model="gemini-3-pro-preview")
        assert provider._is_gemini_3() is True

    def test_is_not_gemini_3(self):
        """Gemini 2 models are not Gemini 3."""
        provider, _ = _make_provider(model="gemini-2.0-flash")
        assert provider._is_gemini_3() is False

    def test_gemini3_thinking_config_in_build_config(self):
        """Gemini 3 models get ThinkingConfig with include_thoughts=False."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        config = provider._build_config(
            temperature=0.7,
            system_prompt=None,
            gemini_tools=None,
        )
        assert config.thinking_config is not None
        assert config.thinking_config.include_thoughts is False

    def test_gemini2_no_thinking_config(self):
        """Gemini 2 models do not get a ThinkingConfig."""
        provider, _ = _make_provider(model="gemini-2.0-flash")
        config = provider._build_config(
            temperature=0.7,
            system_prompt=None,
            gemini_tools=None,
        )
        assert config.thinking_config is None

    def test_gemini3_temperature_override(self):
        """Gemini 3 forces temperature to 1.0 regardless of the caller value."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        config = provider._build_config(
            temperature=0.3,
            system_prompt=None,
            gemini_tools=None,
        )
        assert config.temperature == 1.0

    def test_gemini2_temperature_passthrough(self):
        """Gemini 2 uses the caller-supplied temperature."""
        provider, _ = _make_provider(model="gemini-2.0-flash")
        config = provider._build_config(
            temperature=0.3,
            system_prompt=None,
            gemini_tools=None,
        )
        assert config.temperature == 0.3

    @pytest.mark.asyncio
    async def test_gemini3_complete_uses_thinking_config(self):
        """Verify complete() passes ThinkingConfig for Gemini 3 models."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [_make_text_part("OK")]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 2

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await provider.complete([Message(role=Role.USER, content="Hi")])

        call_kwargs = provider._client.aio.models.generate_content.call_args
        config = call_kwargs.kwargs["config"]
        assert config.thinking_config is not None
        assert config.thinking_config.include_thoughts is False
        assert config.temperature == 1.0


class TestThoughtSignatureRoundTrip:
    """Tests for preserving thought signatures across the Gemini round-trip."""

    @pytest.mark.asyncio
    async def test_thought_signature_preserved_in_response(self):
        """Response metadata contains thought parts from the Gemini response."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        sig = b"\x01\x02\x03\x04"

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [
            _make_thought_part(sig),
            _make_text_part("Hello!"),
        ]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete([Message(role=Role.USER, content="Hi")])

        assert "_gemini_thought_parts" in result.metadata
        thought_parts = result.metadata["_gemini_thought_parts"]
        assert len(thought_parts) == 1
        # Signature should be base64-encoded.
        assert base64.b64decode(thought_parts[0]["thought_signature"]) == sig
        # Text should still be parsed normally.
        assert result.content == "Hello!"

    @pytest.mark.asyncio
    async def test_no_thought_parts_means_no_metadata_key(self):
        """When there are no thought parts the metadata key is absent."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [_make_text_part("Just text")]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 3

        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await provider.complete([Message(role=Role.USER, content="Hi")])

        assert "_gemini_thought_parts" not in result.metadata

    def test_thought_signature_restored_in_convert_messages(self):
        """Assistant messages with thought metadata are round-tripped to Gemini parts."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        sig = b"\xaa\xbb\xcc"
        encoded_sig = base64.b64encode(sig).decode("ascii")

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Let me check.",
                tool_calls=[
                    ToolCall(id="read_file", name="read_file", arguments={"path": "x"}),
                ],
                metadata={
                    "_gemini_thought_parts": [{"thought_signature": encoded_sig}],
                },
            ),
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        parts = result[0].parts
        # First part should be the thought signature, then text, then function call.
        assert len(parts) == 3
        assert parts[0].thought is True
        assert parts[0].thought_signature == sig
        assert parts[1].text == "Let me check."
        assert parts[2].function_call.name == "read_file"

    def test_text_only_message_with_thought_metadata(self):
        """Text-only assistant message with thought metadata prepends thought parts."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        sig = b"\x01\x02"
        encoded_sig = base64.b64encode(sig).decode("ascii")

        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Sure thing.",
                metadata={
                    "_gemini_thought_parts": [{"thought_signature": encoded_sig}],
                },
            ),
        ]

        result = provider._convert_messages(messages)

        parts = result[0].parts
        assert len(parts) == 2
        assert parts[0].thought is True
        assert parts[0].thought_signature == sig
        assert parts[1].text == "Sure thing."

    @pytest.mark.asyncio
    async def test_stream_rate_limit_during_iteration(self):
        """Rate limit errors during stream iteration are caught and re-raised."""
        from google.genai import errors as genai_errors

        provider, _ = _make_provider()
        error = genai_errors.ClientError(code=429, response_json={})

        async def _failing_stream():
            yield MagicMock(candidates=None)
            raise error

        provider._client.aio.models.generate_content_stream = AsyncMock(
            return_value=_failing_stream()
        )

        with pytest.raises(ProviderRateLimitError):
            async for _ in provider.stream([Message(role=Role.USER, content="Hi")]):
                pass

    @pytest.mark.asyncio
    async def test_stream_duplicate_tool_calls_unique_ids(self):
        """Parallel calls to the same tool in a stream get distinct IDs."""
        provider, _ = _make_provider()

        chunk = MagicMock()
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].content.parts = [
            _make_function_call_part("read_file", {"path": "a.txt"}),
            _make_function_call_part("read_file", {"path": "b.txt"}),
        ]

        async def _stream_gen():
            yield chunk

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

        chunks = []
        async for c in provider.stream([Message(role=Role.USER, content="Read both")]):
            chunks.append(c)

        final = chunks[-1]
        assert final.is_final is True
        assert len(final.tool_calls) == 2
        assert final.tool_calls[0].id == "read_file_0"
        assert final.tool_calls[1].id == "read_file_1"
        assert final.tool_calls[0].name == "read_file"
        assert final.tool_calls[1].name == "read_file"

    @pytest.mark.asyncio
    async def test_stream_collects_thought_parts(self):
        """Thought parts from streamed chunks appear in the final chunk metadata."""
        provider, _ = _make_provider(model="gemini-3-flash-preview")
        sig = b"\xde\xad"

        chunk1 = MagicMock()
        chunk1.candidates = [MagicMock()]
        chunk1.candidates[0].content.parts = [
            _make_thought_part(sig),
            _make_text_part("Hi"),
        ]

        async def _stream_gen():
            yield chunk1

        provider._client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())

        chunks = []
        async for c in provider.stream([Message(role=Role.USER, content="Hey")]):
            chunks.append(c)

        # Final chunk should carry thought metadata.
        final = chunks[-1]
        assert final.is_final is True
        assert "_gemini_thought_parts" in final.metadata
        assert (
            base64.b64decode(final.metadata["_gemini_thought_parts"][0]["thought_signature"])
            == sig
        )
