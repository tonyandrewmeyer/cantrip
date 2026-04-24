"""Tests for the shared OpenAI-compatible wire-format plumbing."""

from unittest.mock import MagicMock, patch

import pytest

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import Image, Message, ProviderError, Role, Tool, ToolCall, ToolResult


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
