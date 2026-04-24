"""Tests for the shared OpenAI-compatible wire-format plumbing."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import Image, Message, ProviderError, Role, Tool, ToolCall, ToolResult


async def _async_iter(items):
    """Async iterator helper used by SSE-stream tests."""
    for item in items:
        yield item


class _DummyProvider(OpenAICompatBase):
    """Minimal concrete subclass for exercising the shared logic."""

    @property
    def name(self) -> str:
        return "dummy"

    def __init__(self, *, supports_vision: bool = False, supports_tools: bool = True) -> None:
        # No real HTTP work — the conversion helpers are pure.
        self.client = MagicMock()
        self.model_name = "dummy-model"
        self.base_url = "http://dummy/v1"
        self._context_window = 32_768
        self._supports_tools = supports_tools
        self._supports_vision = supports_vision


class TestConvertMessages:
    """Message-shape conversion mirrors the OpenAI chat-completions API."""

    def test_extracts_system_prompt_separately(self):
        p = _DummyProvider()
        system, msgs = p._convert_messages(
            [
                Message(role=Role.SYSTEM, content="You are helpful."),
                Message(role=Role.USER, content="Hi"),
            ]
        )
        assert system == "You are helpful."
        assert msgs == [{"role": "user", "content": "Hi"}]

    def test_merges_consecutive_user_messages(self):
        """Some local backends reject consecutive same-role turns."""
        p = _DummyProvider()
        _, msgs = p._convert_messages(
            [
                Message(role=Role.USER, content="first"),
                Message(role=Role.USER, content="second"),
            ]
        )
        assert msgs == [{"role": "user", "content": "first\n\nsecond"}]

    def test_tool_call_turn_serialises_arguments_as_json(self):
        p = _DummyProvider()
        _, msgs = p._convert_messages(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(id="call-1", name="read_file", arguments={"path": "foo.py"}),
                    ],
                ),
            ]
        )
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"][0]["function"]["name"] == "read_file"
        # Arguments must be a JSON string per the OpenAI wire format.
        assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"path": "foo.py"}'

    def test_tool_result_becomes_tool_role_message(self):
        p = _DummyProvider()
        _, msgs = p._convert_messages(
            [
                Message(
                    role=Role.TOOL,
                    content="",
                    tool_results=[
                        ToolResult(tool_call_id="call-1", content="42 lines"),
                    ],
                ),
            ]
        )
        assert msgs == [{"role": "tool", "tool_call_id": "call-1", "content": "42 lines"}]

    def test_vision_blind_provider_rejects_images(self):
        p = _DummyProvider(supports_vision=False)
        with pytest.raises(NotImplementedError, match="does not support image"):
            p._convert_messages(
                [
                    Message(
                        role=Role.USER,
                        content="what is this",
                        images=[Image(data=b"\x89PNG", mime="image/png")],
                    ),
                ]
            )

    def test_vision_provider_embeds_image_as_data_uri(self):
        p = _DummyProvider(supports_vision=True)
        _, msgs = p._convert_messages(
            [
                Message(
                    role=Role.USER,
                    content="what is this",
                    images=[Image(data=b"\x89PNG", mime="image/png")],
                ),
            ]
        )
        parts = msgs[0]["content"]
        assert parts[0]["type"] == "image_url"
        assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert parts[1] == {"type": "text", "text": "what is this"}


class TestConvertTools:
    """Tool-schema conversion produces OpenAI function-calling format."""

    def test_wraps_each_tool_in_function_envelope(self):
        tools = [
            Tool(name="ls", description="list files", parameters={"type": "object"}),
        ]
        converted = OpenAICompatBase._convert_tools(tools)
        assert converted == [
            {
                "type": "function",
                "function": {
                    "name": "ls",
                    "description": "list files",
                    "parameters": {"type": "object"},
                },
            }
        ]

    def test_none_and_empty_become_none(self):
        assert OpenAICompatBase._convert_tools(None) is None
        assert OpenAICompatBase._convert_tools([]) is None


class TestParseToolCalls:
    """Tool-call response parsing handles the OpenAI wire format."""

    def test_decodes_json_arguments(self):
        parsed = OpenAICompatBase._parse_tool_calls(
            [
                {
                    "id": "call-1",
                    "function": {"name": "read_file", "arguments": '{"path": "foo.py"}'},
                },
            ]
        )
        assert parsed[0].id == "call-1"
        assert parsed[0].name == "read_file"
        assert parsed[0].arguments == {"path": "foo.py"}

    def test_invalid_json_arguments_fall_back_to_empty(self):
        parsed = OpenAICompatBase._parse_tool_calls(
            [
                {
                    "id": "call-1",
                    "function": {"name": "read_file", "arguments": "not json"},
                },
            ]
        )
        assert parsed[0].arguments == {}


class TestFireworksProbe:
    """FireworksProvider lifts capability flags from /models."""

    def test_populates_flags_from_catalogue_entry(self):
        from cantrip.llm.fireworks import FireworksProvider

        payload = {
            "data": [
                {
                    "id": "accounts/fireworks/models/kimi-k2p6",
                    "context_length": 262144,
                    "supports_tools": True,
                    "supports_image_input": True,
                }
            ]
        }

        with (
            patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}),
            patch("cantrip.llm.fireworks.httpx.Client") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.json.return_value = payload
            mock_resp.raise_for_status.return_value = None
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__enter__.return_value = mock_client

            provider = FireworksProvider()

        assert provider.context_window_tokens == 262144
        assert provider.supports_vision is True
        assert provider._supports_tools is True

    def test_falls_back_when_probe_fails(self):
        from cantrip.llm.fireworks import _FALLBACK_CONTEXT_WINDOW, FireworksProvider

        # Probe failure is caught upstream by httpx.HTTPError; simulate
        # that by patching the method directly to a no-op.
        with (
            patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}),
            patch.object(FireworksProvider, "_probe_capabilities"),
        ):
            provider = FireworksProvider()

        assert provider.context_window_tokens == _FALLBACK_CONTEXT_WINDOW


class TestOpenRouterProbe:
    """OpenRouterProvider reads OpenRouter's nested ``/models`` schema."""

    def test_populates_flags_from_architecture_and_supported_parameters(self):
        from cantrip.llm.openrouter import OpenRouterProvider

        payload = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "context_length": 128000,
                    "architecture": {
                        "input_modalities": ["text", "image", "file"],
                    },
                    "supported_parameters": [
                        "temperature",
                        "tools",
                        "tool_choice",
                    ],
                }
            ]
        }

        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}),
            patch("cantrip.llm.openrouter.httpx.Client") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.json.return_value = payload
            mock_resp.raise_for_status.return_value = None
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__enter__.return_value = mock_client

            provider = OpenRouterProvider()

        assert provider.context_window_tokens == 128_000
        assert provider.supports_vision is True
        assert provider._supports_tools is True

    def test_missing_tools_in_supported_parameters_disables_tools(self):
        """When /models lists supported_parameters without 'tools', the provider flips off."""
        from cantrip.llm.openrouter import OpenRouterProvider

        payload = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "context_length": 128000,
                    "architecture": {"input_modalities": ["text"]},
                    "supported_parameters": ["temperature", "top_p"],
                }
            ]
        }

        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}),
            patch("cantrip.llm.openrouter.httpx.Client") as mock_client_cls,
        ):
            mock_resp = MagicMock()
            mock_resp.json.return_value = payload
            mock_resp.raise_for_status.return_value = None
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__enter__.return_value = mock_client

            provider = OpenRouterProvider()

        assert provider._supports_tools is False
        assert provider.supports_vision is False


class TestOpenAICompatibleConstruction:
    """OpenAICompatibleProvider enforces its required arguments."""

    def test_missing_api_key_raises(self):
        from cantrip.llm.openai_compatible import OpenAICompatibleProvider

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ProviderError, match="OPENAI_COMPATIBLE_API_KEY"),
        ):
            OpenAICompatibleProvider(model="some-model", base_url="https://example.com/v1")

    def test_caller_supplied_context_window_skips_probe(self):
        from cantrip.llm.openai_compatible import OpenAICompatibleProvider

        with (
            patch.dict("os.environ", {"OPENAI_COMPATIBLE_API_KEY": "test-key"}),
            patch.object(OpenAICompatibleProvider, "_probe_context_window") as mock_probe,
        ):
            provider = OpenAICompatibleProvider(
                model="m",
                base_url="https://example.com/v1",
                context_window=128_000,
            )

        mock_probe.assert_not_called()
        assert provider.context_window_tokens == 128_000


class TestReasoningContent:
    """reasoning_content round-trips onto Response / Chunk metadata.

    Kimi K2, DeepSeek-R1, and other open-weights models emit
    chain-of-thought as ``reasoning_content`` alongside the final
    ``content``.  The shared helper must surface it on the same
    ``_thinking_content`` metadata key Claude uses so downstream
    renderers don't need a second code path.
    """

    @pytest.mark.asyncio
    async def test_complete_captures_reasoning_content_on_metadata(self):
        provider = _DummyProvider()
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://dummy/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "The answer is 42.",
                            "reasoning_content": "The user asked a question; 42 is canonical.",
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Hi")])

        assert response.content == "The answer is 42."
        assert response.metadata == {
            "_thinking_content": "The user asked a question; 42 is canonical.",
        }

    @pytest.mark.asyncio
    async def test_complete_omits_metadata_when_no_reasoning(self):
        provider = _DummyProvider()
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://dummy/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Hi"},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Hi")])
        assert response.metadata == {}

    @pytest.mark.asyncio
    async def test_stream_accumulates_reasoning_onto_final_chunk(self):
        provider = _DummyProvider()

        sse_lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"Let me "}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":"think..."}}]}',
            'data: {"choices":[{"delta":{"content":"42"}}]}',
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        content_chunks = [c for c in chunks if c.content]
        assert [c.content for c in content_chunks] == ["42"]

        finals = [c for c in chunks if c.is_final]
        assert len(finals) == 1
        assert finals[0].metadata == {"_thinking_content": "Let me think..."}
        assert finals[0].usage == {"prompt_tokens": 3, "completion_tokens": 2}

    @pytest.mark.asyncio
    async def test_stream_reasoning_only_turn_yields_no_content_chunks(self):
        """Short max_tokens + Kimi K2 can produce a reasoning-only turn.

        The shared helper must still surface the reasoning on the
        final chunk rather than hiding it behind an empty response.
        """
        provider = _DummyProvider()

        sse_lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"Budget exhausted."}}]}',
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":3,"completion_tokens":30}}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        assert [c for c in chunks if c.content] == []
        finals = [c for c in chunks if c.is_final]
        assert finals[0].metadata == {"_thinking_content": "Budget exhausted."}

    def test_thinking_budget_raises_max_tokens_floor(self):
        """``thinking_budget`` bumps ``max_tokens`` to leave room for reasoning.

        Kimi K2 and other reasoning models spend reasoning tokens
        from the same budget as the final answer.  When the caller
        signals a thinking budget, the wire body must carry a
        ``max_tokens`` large enough to fit reasoning + a real reply.
        """
        p = _DummyProvider()
        body = p._build_request_body(
            [Message(role=Role.USER, content="Hi")],
            None,
            0.7,
            max_tokens=30,
            thinking_budget=4000,
        )
        assert body["max_tokens"] == 4000 + 4096

    def test_thinking_budget_respects_caller_max_when_already_generous(self):
        p = _DummyProvider()
        body = p._build_request_body(
            [Message(role=Role.USER, content="Hi")],
            None,
            0.7,
            max_tokens=32_000,
            thinking_budget=4000,
        )
        assert body["max_tokens"] == 32_000

    def test_thinking_budget_without_explicit_max_uses_floor(self):
        p = _DummyProvider()
        body = p._build_request_body(
            [Message(role=Role.USER, content="Hi")],
            None,
            0.7,
            thinking_budget=4000,
        )
        assert body["max_tokens"] == 4000 + 4096

    @pytest.mark.asyncio
    async def test_stream_without_reasoning_leaves_metadata_empty(self):
        provider = _DummyProvider()

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hi"}}]}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        provider.client.stream = MagicMock(return_value=mock_resp)

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Hi")]):
            chunks.append(chunk)

        finals = [c for c in chunks if c.is_final]
        assert finals[0].metadata == {}


class TestFireworksNonStreamingCap:
    """FireworksProvider auto-streams past the 4096-token non-stream cap.

    Fireworks returns 400 Bad Request for non-streaming requests with
    ``max_tokens > 4096``.  The ``thinking_budget`` bump from Phase 77
    lands above that cap whenever callers signal reasoning headroom,
    so ``complete()`` has to route through ``stream()`` transparently.
    """

    def test_effective_max_tokens_applies_thinking_floor(self):
        from cantrip.llm.fireworks import FireworksProvider

        # Matches OpenAICompatBase._build_request_body's floor formula.
        assert FireworksProvider._effective_max_tokens(None, 2000) == 6096
        assert FireworksProvider._effective_max_tokens(30, 2000) == 6096
        assert FireworksProvider._effective_max_tokens(10_000, 2000) == 10_000
        assert FireworksProvider._effective_max_tokens(None, None) is None
        assert FireworksProvider._effective_max_tokens(500, None) == 500

    @pytest.mark.asyncio
    async def test_complete_auto_streams_when_budget_exceeds_cap(self):
        """``thinking_budget`` high enough to exceed 4096 routes through stream()."""
        from cantrip.llm.base import Chunk
        from cantrip.llm.fireworks import FireworksProvider

        with (
            patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}),
            patch.object(FireworksProvider, "_probe_capabilities"),
        ):
            provider = FireworksProvider()

        async def _fake_stream(*_args, **_kwargs):
            yield Chunk(content="Four.")
            yield Chunk(
                is_final=True,
                usage={"prompt_tokens": 5, "completion_tokens": 2},
                metadata={"_thinking_content": "2+2 is 4."},
            )

        with patch.object(
            FireworksProvider,
            "stream",
            side_effect=lambda *_a, **_kw: _fake_stream(),
        ) as mock_stream:
            response = await provider.complete(
                [Message(role=Role.USER, content="2+2?")],
                thinking_budget=2000,
            )

        mock_stream.assert_called_once()
        assert response.content == "Four."
        assert response.metadata == {"_thinking_content": "2+2 is 4."}
        assert response.usage == {"prompt_tokens": 5, "completion_tokens": 2}

    @pytest.mark.asyncio
    async def test_complete_uses_parent_when_under_cap(self):
        """A normal request stays on the POST path."""
        import httpx as httpx_mod

        from cantrip.llm.fireworks import FireworksProvider

        with (
            patch.dict("os.environ", {"FIREWORKS_API_KEY": "test-key"}),
            patch.object(FireworksProvider, "_probe_capabilities"),
        ):
            provider = FireworksProvider()

        mock_response = httpx_mod.Response(
            200,
            request=httpx_mod.Request("POST", "http://dummy/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hi"},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        with patch.object(FireworksProvider, "stream") as mock_stream:
            response = await provider.complete(
                [Message(role=Role.USER, content="Hi")],
                max_tokens=1024,
            )

        mock_stream.assert_not_called()
        assert response.content == "hi"
