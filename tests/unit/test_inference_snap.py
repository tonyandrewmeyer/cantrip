"""Tests for the inference snap LLM provider."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cantrip.llm.base import Image, Message, ProviderError, Role, Tool, ToolCall
from cantrip.llm.base import ToolResult as LLMToolResult
from cantrip.llm.inference_snap import (
    InferenceSnapProvider,
    discover_snap_endpoint,
    list_available_snaps,
)


class TestDiscoverSnapEndpoint:
    """Tests for discover_snap_endpoint."""

    def test_parses_status_output(self):
        """Parses the openai endpoint from snap status output."""
        mock_result = MagicMock()
        mock_result.stdout = (
            "engine: nvidia-gpu-amd64\n"
            "services:\n"
            "    server: active\n"
            "endpoints:\n"
            "    openai: http://localhost:8328/v1\n"
        )
        with patch("cantrip.llm.inference_snap.subprocess.run", return_value=mock_result):
            url = discover_snap_endpoint("gemma3")
        assert url == "http://localhost:8328/v1"

    def test_falls_back_to_known_port(self):
        """Falls back to the default port when the snap command fails."""
        with patch(
            "cantrip.llm.inference_snap.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            url = discover_snap_endpoint("deepseek-r1")
        assert url == "http://localhost:8324/v1"

    def test_falls_back_for_unknown_snap(self):
        """Falls back to port 8328 for unrecognised snap names."""
        with patch(
            "cantrip.llm.inference_snap.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            url = discover_snap_endpoint("unknown-snap")
        assert url == "http://localhost:8328/v1"

    def test_preserves_snap_reported_version(self):
        """Snap reporting /v3 endpoint is used as-is."""
        mock_result = MagicMock()
        mock_result.stdout = "endpoints:\n    openai: http://localhost:8328/v3\n"
        with patch("cantrip.llm.inference_snap.subprocess.run", return_value=mock_result):
            url = discover_snap_endpoint("gemma3")
        assert url == "http://localhost:8328/v3"


class TestListAvailableSnaps:
    """Tests for list_available_snaps."""

    def test_finds_installed_snaps(self):
        """Returns only recognised inference snaps from snap list output."""
        mock_result = MagicMock()
        mock_result.stdout = (
            "Name          Version\n"
            "core22        20240101\n"
            "gemma3        v3+b73d030\n"
            "deepseek-r1   v1.0.0\n"
            "firefox       130.0\n"
        )
        with patch("cantrip.llm.inference_snap.subprocess.run", return_value=mock_result):
            snaps = list_available_snaps()
        assert "gemma3" in snaps
        assert "deepseek-r1" in snaps
        assert "firefox" not in snaps

    def test_handles_missing_snap_command(self):
        """Returns empty list when snap is not available."""
        with patch(
            "cantrip.llm.inference_snap.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert list_available_snaps() == []


class TestInferenceSnapProviderInit:
    """Tests for InferenceSnapProvider initialisation."""

    def _make_provider(self, **kwargs):
        """Create a provider with model detection and probe bypassed."""
        defaults = {
            "snap_name": "gemma3",
            "model": "test-model",
            "base_url": "http://test:8328/v1",
        }
        defaults.update(kwargs)
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(**defaults)

    def test_name(self):
        """Provider name is 'inference-snap'."""
        provider = self._make_provider()
        assert provider.name == "inference-snap"

    def test_context_window(self):
        """Context window returns the default for local models."""
        provider = self._make_provider()
        assert provider.context_window_tokens == 8_192

    def test_max_tools(self):
        """Max tools returns a small limit for local models."""
        provider = self._make_provider()
        assert provider.max_tools is not None
        assert provider.max_tools <= 15

    def test_model_name(self):
        """Model name is set from the constructor argument."""
        provider = self._make_provider(model="my-model")
        assert provider.model_name == "my-model"

    def test_base_url(self):
        """Base URL is set from the constructor argument."""
        provider = self._make_provider(base_url="http://custom:9999/v1")
        assert provider.base_url == "http://custom:9999/v1"

    def test_model_matching_snap_name_triggers_detection(self):
        """When model equals snap_name, auto-detection is used instead."""
        with patch.object(InferenceSnapProvider, "_detect_model", return_value="gemma-3-4b-it"):
            provider = InferenceSnapProvider(
                snap_name="gemma3",
                model="gemma3",
                base_url="http://test:8328/v1",
            )
        assert provider.model_name == "gemma-3-4b-it"

    def test_model_none_triggers_detection(self):
        """When model is None, auto-detection is used."""
        with patch.object(InferenceSnapProvider, "_detect_model", return_value="gemma-3-4b-it"):
            provider = InferenceSnapProvider(
                snap_name="gemma3",
                model=None,
                base_url="http://test:8328/v1",
            )
        assert provider.model_name == "gemma-3-4b-it"

    def test_explicit_model_skips_detection(self):
        """An explicit model name different from snap_name is used directly."""
        provider = self._make_provider(model="custom-model-7b")
        assert provider.model_name == "custom-model-7b"


class TestMessageConversion:
    """Tests for InferenceSnapProvider._convert_messages."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    def test_user_message(self):
        """User messages convert to OpenAI format."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hello")]
        system, result = provider._convert_messages(messages)
        assert system is None
        assert result == [{"role": "user", "content": "Hello"}]

    def test_system_message_extracted(self):
        """System messages are extracted separately."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="Be helpful."),
            Message(role=Role.USER, content="Hi"),
        ]
        system, result = provider._convert_messages(messages)
        assert system == "Be helpful."
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_assistant_with_tool_calls(self):
        """Assistant messages with tool calls include function call format."""
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
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me check."
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "juju_status"
        assert json.loads(tc["function"]["arguments"]) == {"model": "dev"}

    def test_consecutive_user_messages_merged(self):
        """Consecutive user messages are merged into one."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.USER, content="How are you?"),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "Hello" in result[0]["content"]
        assert "How are you?" in result[0]["content"]

    def test_consecutive_assistant_messages_merged(self):
        """Consecutive assistant messages without tool calls are merged."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.ASSISTANT, content="First part."),
            Message(role=Role.ASSISTANT, content="Second part."),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        assert "First part." in result[0]["content"]
        assert "Second part." in result[0]["content"]

    def test_consecutive_user_messages_empty_content_no_extra_whitespace(self):
        """Merging consecutive user messages skips empty content to avoid blank lines."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.USER, content=""),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["content"] == "Hello"

    def test_consecutive_assistant_messages_empty_content_no_extra_whitespace(self):
        """Merging consecutive assistant messages skips empty content."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.ASSISTANT, content="First."),
            Message(role=Role.ASSISTANT, content=""),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["content"] == "First."

    def test_assistant_with_tool_calls_not_merged(self):
        """Assistant messages with tool calls are not merged with subsequent ones."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="Checking.",
                tool_calls=[ToolCall(id="tc_1", name="test", arguments={})],
            ),
            Message(role=Role.ASSISTANT, content="Done."),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 2

    def test_tool_result_message(self):
        """Tool result messages convert to OpenAI tool role format."""
        provider = self._make_provider()
        messages = [
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    LLMToolResult(
                        tool_call_id="tc_1",
                        content="active: Ready",
                    ),
                ],
            ),
        ]
        _, result = provider._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc_1"
        assert result[0]["content"] == "active: Ready"


class TestInferenceSnapVision:
    """Phase 48.1: vision detection + image handling for inference snaps."""

    def _make_provider(self, snap_name: str = "qwen-vl"):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name=snap_name,
                model="test-model",
                base_url=f"http://test-{snap_name}:8326/v1",
            )

    def test_qwen_vl_is_vision_by_default(self):
        """qwen-vl is on the static vision allowlist."""
        assert self._make_provider("qwen-vl").supports_vision is True

    def test_gemma3_is_vision_by_default(self):
        """gemma3 is on the static vision allowlist."""
        assert self._make_provider("gemma3").supports_vision is True

    def test_deepseek_r1_is_not_vision(self):
        """A text-only snap does not advertise vision support."""
        assert self._make_provider("deepseek-r1").supports_vision is False

    def test_unknown_snap_is_not_vision_without_metadata(self):
        """An unrecognised snap without a capability flag stays vision-blind."""
        assert self._make_provider("some-new-snap").supports_vision is False

    def test_capability_flag_upgrades_non_allowlist_snap(self):
        """A ``/models`` response advertising ``vision`` upgrades the flag."""
        provider = self._make_provider("some-new-snap")
        assert provider.supports_vision is False
        provider._apply_model_metadata(
            {"data": [{"id": "new-vl", "capabilities": ["vision", "tool_use"]}]}
        )
        assert provider.supports_vision is True

    def test_allowlist_snap_stays_vision_without_capability(self):
        """A snap on the allowlist keeps vision=True even if metadata omits it.

        Not every backend populates ``capabilities`` reliably, so we
        never downgrade from the static seed.
        """
        provider = self._make_provider("qwen-vl")
        provider._apply_model_metadata({"data": [{"id": "qwen-vl", "capabilities": ["tool_use"]}]})
        assert provider.supports_vision is True

    def test_vision_snap_converts_user_image_to_data_uri(self):
        """A user message with an image produces OpenAI multi-part content."""
        provider = self._make_provider("qwen-vl")
        img_bytes = b"\x89PNG\r\n\x1a\nbody"
        msg = Message(
            role=Role.USER,
            content="caption",
            images=[Image(data=img_bytes, mime="image/png")],
        )

        _, api_messages = provider._convert_messages([msg])

        [entry] = api_messages
        assert entry["role"] == "user"
        image_part, text_part = entry["content"]
        assert image_part["type"] == "image_url"
        expected_uri = f"data:image/png;base64,{base64.b64encode(img_bytes).decode('ascii')}"
        assert image_part["image_url"]["url"] == expected_uri
        assert text_part == {"type": "text", "text": "caption"}

    def test_non_vision_snap_rejects_images_with_clear_error(self):
        """A vision-blind snap raises NotImplementedError, not silent drop."""
        provider = self._make_provider("deepseek-r1")
        msg = Message(
            role=Role.USER,
            content="what's in this?",
            images=[Image(data=b"x", mime="image/png")],
        )
        with pytest.raises(NotImplementedError, match="does not support image"):
            provider._convert_messages([msg])

    def test_oversized_image_raises_provider_error(self):
        """Images over the per-image cap fail client-side."""
        provider = self._make_provider("qwen-vl")
        oversized = b"\x00" * (20 * 1024 * 1024 + 1)
        msg = Message(
            role=Role.USER,
            content="huge",
            images=[Image(data=oversized, mime="image/png")],
        )
        with pytest.raises(ProviderError, match="exceeds the"):
            provider._convert_messages([msg])

    def test_plain_user_message_on_vision_snap_still_uses_string_content(self):
        """Vision capability does not change the wire format for text-only turns."""
        provider = self._make_provider("qwen-vl")
        _, api_messages = provider._convert_messages([Message(role=Role.USER, content="hi")])
        assert api_messages == [{"role": "user", "content": "hi"}]


class TestToolConversion:
    """Tests for InferenceSnapProvider._convert_tools."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    def test_convert_tools(self):
        """Tools convert to OpenAI function-calling format."""
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
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "juju_status"
        assert result[0]["function"]["description"] == "Get Juju status"

    def test_convert_tools_none(self):
        """None or empty tools returns None."""
        provider = self._make_provider()
        assert provider._convert_tools(None) is None
        assert provider._convert_tools([]) is None


class TestCountTokens:
    """Tests for InferenceSnapProvider.count_tokens."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    def test_counts_content(self):
        """Content characters contribute to the count."""
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


class TestParseToolCalls:
    """Tests for InferenceSnapProvider._parse_tool_calls."""

    def test_parses_tool_calls(self):
        """Parses OpenAI-format tool calls into ToolCall objects."""
        raw = [
            {
                "id": "tc_1",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "London"}',
                },
            },
        ]
        result = InferenceSnapProvider._parse_tool_calls(raw)
        assert len(result) == 1
        assert result[0].id == "tc_1"
        assert result[0].name == "get_weather"
        assert result[0].arguments == {"city": "London"}

    def test_handles_dict_arguments(self):
        """Handles arguments already parsed as a dict."""
        raw = [
            {
                "id": "tc_1",
                "function": {"name": "test", "arguments": {"key": "value"}},
            },
        ]
        result = InferenceSnapProvider._parse_tool_calls(raw)
        assert result[0].arguments == {"key": "value"}

    def test_handles_invalid_json_arguments(self):
        """Returns empty dict for unparseable arguments."""
        raw = [
            {
                "id": "tc_1",
                "function": {"name": "test", "arguments": "not-json{"},
            },
        ]
        result = InferenceSnapProvider._parse_tool_calls(raw)
        assert result[0].arguments == {}


class TestBuildRequestBody:
    """Tests for InferenceSnapProvider._build_request_body."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    def test_basic_request(self):
        """Builds a basic request body."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hello")]
        body = provider._build_request_body(messages, None, 0.7)
        assert body["model"] == "test-model"
        assert body["temperature"] == 0.7
        assert body["stream"] is False
        assert len(body["messages"]) == 1
        assert "tools" not in body

    def test_includes_system_prompt(self):
        """System message is prepended as a system message."""
        provider = self._make_provider()
        messages = [
            Message(role=Role.SYSTEM, content="Be helpful."),
            Message(role=Role.USER, content="Hi"),
        ]
        body = provider._build_request_body(messages, None, 0.7)
        assert body["messages"][0] == {"role": "system", "content": "Be helpful."}
        assert body["messages"][1] == {"role": "user", "content": "Hi"}

    def test_includes_tools(self):
        """Tools are included in the request body."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hi")]
        tools = [
            Tool(
                name="test_tool",
                description="A test tool",
                parameters={"type": "object", "properties": {}},
            ),
        ]
        body = provider._build_request_body(messages, tools, 0.7)
        assert "tools" in body
        assert body["tools"][0]["function"]["name"] == "test_tool"

    def test_stream_flag(self):
        """Stream flag is set correctly."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hi")]
        body = provider._build_request_body(messages, None, 0.7, stream=True)
        assert body["stream"] is True

    def test_stream_options_include_usage(self):
        """stream_options with include_usage is set when streaming."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hi")]
        body = provider._build_request_body(messages, None, 0.7, stream=True)
        assert body["stream_options"] == {"include_usage": True}

    def test_no_stream_options_when_not_streaming(self):
        """stream_options is absent for non-streaming requests."""
        provider = self._make_provider()
        messages = [Message(role=Role.USER, content="Hi")]
        body = provider._build_request_body(messages, None, 0.7, stream=False)
        assert "stream_options" not in body


class TestComplete:
    """Tests for InferenceSnapProvider.complete."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    @pytest.mark.asyncio
    async def test_complete_text_response(self):
        """Parses a text-only completion response."""
        provider = self._make_provider()
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Hello!"},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        provider.client = MagicMock()
        provider.client.post = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Hi")]
        response = await provider.complete(messages)

        assert response.content == "Hello!"
        assert response.tool_calls == []
        assert response.finish_reason == "stop"
        assert response.usage["prompt_tokens"] == 10

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self):
        """Parses a response containing tool calls."""
        provider = self._make_provider()
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "tc_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city": "London"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            },
        )
        provider.client = MagicMock()
        provider.client.post = AsyncMock(return_value=mock_response)

        messages = [Message(role=Role.USER, content="Weather?")]
        response = await provider.complete(messages)

        assert response.content == ""
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "London"}
        assert response.finish_reason == "tool_calls"


class TestStream:
    """Tests for InferenceSnapProvider.stream."""

    def _make_provider(self):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

    @pytest.mark.asyncio
    async def test_stream_captures_usage(self):
        """Usage data from the final SSE chunk is captured."""
        provider = self._make_provider()

        # Simulate SSE lines: one content chunk, then a usage chunk, then [DONE].
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        provider.client = MagicMock()
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        # Should have a content chunk and a final chunk with usage.
        assert any(c.content == "Hello" for c in chunks)
        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].usage == {"prompt_tokens": 10, "completion_tokens": 5}

    @pytest.mark.asyncio
    async def test_stream_handles_empty_choices_frame(self):
        """A frame with ``"choices": []`` (e.g. usage-only) must not crash."""
        provider = self._make_provider()

        # Some OpenAI-compatible servers send a final frame with an empty
        # choices list alongside usage; the streamer must cope.
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        provider.client = MagicMock()
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        assert any(c.content == "Hi" for c in chunks)
        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].usage == {"prompt_tokens": 3, "completion_tokens": 1}

    @pytest.mark.asyncio
    async def test_stream_empty_usage_when_not_provided(self):
        """Usage is empty dict when the server doesn't include it."""
        provider = self._make_provider()

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        provider.client = MagicMock()
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        final = [c for c in chunks if c.is_final]
        assert len(final) == 1
        assert final[0].usage == {}


async def _async_iter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


class TestContextWindowTuning:
    """Tests for dynamic context window detection from /models."""

    def test_default_context_window(self):
        """Default context window is used when /models has no metadata."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        assert provider.context_window_tokens == 8_192

    def test_detects_n_ctx_train(self):
        """Context window is read from n_ctx_train in /models response."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata({"data": [{"id": "test", "n_ctx_train": 32_768}]})
        assert provider.context_window_tokens == 32_768

    def test_detects_context_length(self):
        """Falls back to context_length when n_ctx_train is absent."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata({"data": [{"id": "test", "context_length": 16_384}]})
        assert provider.context_window_tokens == 16_384

    def test_detects_max_model_len(self):
        """Falls back to max_model_len as a last resort."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata({"data": [{"id": "test", "max_model_len": 4_096}]})
        assert provider.context_window_tokens == 4_096

    def test_ignores_invalid_context_values(self):
        """Zero or negative values are ignored."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata({"data": [{"id": "test", "n_ctx_train": 0}]})
        assert provider.context_window_tokens == 8_192


class TestConnectionHealth:
    """Tests for connection health checking."""

    def test_connect_error_raises_provider_error(self):
        """ProviderError is raised with helpful message when snap is unreachable."""
        from cantrip.llm.base import ProviderError

        with patch("cantrip.llm.inference_snap.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_cls.return_value = mock_client

            with pytest.raises(ProviderError, match="Cannot connect"):
                InferenceSnapProvider(
                    snap_name="gemma3", model=None, base_url="http://localhost:8328/v1"
                )

    def test_probe_raises_on_connect_error(self):
        """_probe_server raises ProviderError when server is unreachable."""
        from cantrip.llm.base import ProviderError

        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )

        with patch("cantrip.llm.inference_snap.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_cls.return_value = mock_client

            with pytest.raises(ProviderError, match="sudo snap start"):
                provider._probe_server()


class TestGracefulDegradation:
    """Tests for graceful tool support degradation."""

    def test_tools_omitted_when_unsupported(self):
        """Tools are not sent in request body when model lacks tool support."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._supports_tools = False

        messages = [Message(role=Role.USER, content="Hello")]
        tools = [
            Tool(
                name="test_tool",
                description="A test",
                parameters={"type": "object", "properties": {}},
            ),
        ]
        body = provider._build_request_body(messages, tools, 0.7)
        assert "tools" not in body

    def test_tools_included_when_supported(self):
        """Tools are included when model supports them (default)."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        assert provider._supports_tools is True

        messages = [Message(role=Role.USER, content="Hello")]
        tools = [
            Tool(
                name="test_tool",
                description="A test",
                parameters={"type": "object", "properties": {}},
            ),
        ]
        body = provider._build_request_body(messages, tools, 0.7)
        assert "tools" in body

    def test_capability_detection_disables_tools(self):
        """Models advertising capabilities without tool_use disable tools."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata(
            {"data": [{"id": "test", "capabilities": ["text_generation"]}]}
        )
        assert provider._supports_tools is False

    def test_capability_detection_keeps_tools(self):
        """Models advertising tool_use capability keep tools enabled."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata(
            {"data": [{"id": "test", "capabilities": ["text_generation", "tool_use"]}]}
        )
        assert provider._supports_tools is True

    def test_no_capabilities_field_keeps_tools(self):
        """Missing capabilities field defaults to tools enabled."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma3", model="test-model", base_url="http://test:8328/v1"
            )
        provider._apply_model_metadata({"data": [{"id": "test"}]})
        assert provider._supports_tools is True


class TestListInferenceSnapsTool:
    """Tests for the ListInferenceSnapsTool agent tool."""

    @pytest.mark.asyncio
    async def test_no_snaps_installed(self):
        """Returns helpful message when no snaps are found."""
        from cantrip.agent.tools.inference import ListInferenceSnapsTool

        tool = ListInferenceSnapsTool()
        with patch("cantrip.agent.tools.inference.list_available_snaps", return_value=[]):
            result = await tool.execute()
        assert result.success is True
        assert "No inference snaps found" in result.output
        assert "sudo snap install" in result.output

    @pytest.mark.asyncio
    async def test_lists_installed_snaps(self):
        """Returns status information for installed snaps."""
        from cantrip.agent.tools.inference import ListInferenceSnapsTool

        tool = ListInferenceSnapsTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "gemma-3-4b-it"}]}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with (
            patch(
                "cantrip.agent.tools.inference.list_available_snaps",
                return_value=["gemma3"],
            ),
            patch(
                "cantrip.agent.tools.inference.discover_snap_endpoint",
                return_value="http://localhost:8328/v1",
            ),
            patch("cantrip.agent.tools.inference.httpx.Client", return_value=mock_client),
        ):
            result = await tool.execute()

        assert result.success is True
        assert "gemma3" in result.output
        assert "running" in result.output
        assert "gemma-3-4b-it" in result.output
        assert result.data["snaps"] == ["gemma3"]
