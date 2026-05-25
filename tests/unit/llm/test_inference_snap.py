"""Tests for the inference snap LLM provider."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cantrip.llm.base import Image, Message, ProviderError, Role, Tool, ToolCall
from cantrip.llm.base import ToolResult as LLMToolResult
from cantrip.llm.inference_snap import (
    _SNAP_DEFAULTS,
    _TOOL_CAPABLE_SNAP_NAMES,
    InferenceSnapProvider,
    _detect_message_format,
    _resolve_read_timeout,
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


class TestQwen3_14bPreset:
    """Phase 105.2: ``qwen3-14b`` is a documented preset.

    The provider-level defaults (``max_tools=12``,
    ``conversation_temperature=0.2``, openai message format) already
    apply uniformly to every inference-snap snap, so the load-bearing
    code change for the preset is just the ``_SNAP_DEFAULTS`` port
    entry — without it ``discover_snap_endpoint`` would fall back to
    the unrelated 8328 default port instead of the 8340 the smoke
    server and the post-Phase-105.3 packaged snap will both listen on.
    """

    def test_default_port_is_8340(self):
        """``_SNAP_DEFAULTS["qwen3-14b"]`` lands at port 8340."""
        assert _SNAP_DEFAULTS.get("qwen3-14b") == 8340

    def test_discover_falls_back_to_documented_port(self):
        """No-snap-installed fallback resolves to ``localhost:8340/v1``."""
        with patch(
            "cantrip.llm.inference_snap.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            url = discover_snap_endpoint("qwen3-14b")
        assert url == "http://localhost:8340/v1"

    def test_is_tool_capable(self):
        """The preset stays in the tool-capable allowlist."""
        assert "qwen3-14b" in _TOOL_CAPABLE_SNAP_NAMES

    def test_uses_openai_message_format(self):
        """``qwen3-14b`` is OpenAI-shaped (not Mistral folded-tool-calls)."""
        assert _detect_message_format("qwen3-14b") == "openai"

    def test_provider_inherits_max_tools_12(self):
        """The preset reuses the provider-wide max_tools=12 cap."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="qwen3-14b",
                model="test-model",
                base_url="http://test:8340/v1",
            )
        assert provider.max_tools == 12

    def test_provider_inherits_conversation_temperature_0_2(self):
        """The preset reuses the provider-wide 0.2 conversation temperature."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="qwen3-14b",
                model="test-model",
                base_url="http://test:8340/v1",
            )
        assert provider.conversation_temperature == 0.2


class TestResolveReadTimeout:
    """Phase 102.1: ``_resolve_read_timeout`` precedence (arg > env > default)."""

    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv("CANTRIP_SNAP_READ_TIMEOUT", "999")
        # Caller-supplied positive value beats both env and default.
        assert _resolve_read_timeout(60.0) == 60.0

    def test_env_used_when_no_argument(self, monkeypatch):
        monkeypatch.setenv("CANTRIP_SNAP_READ_TIMEOUT", "300")
        assert _resolve_read_timeout(None) == 300.0

    def test_default_when_no_argument_and_no_env(self, monkeypatch):
        monkeypatch.delenv("CANTRIP_SNAP_READ_TIMEOUT", raising=False)
        assert _resolve_read_timeout(None) == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS

    def test_zero_or_negative_argument_falls_back(self, monkeypatch):
        """A non-positive caller value is treated as "use default"."""
        monkeypatch.delenv("CANTRIP_SNAP_READ_TIMEOUT", raising=False)
        assert _resolve_read_timeout(0) == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS
        assert _resolve_read_timeout(-1) == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS

    def test_invalid_env_logs_and_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("CANTRIP_SNAP_READ_TIMEOUT", "💥")
        with caplog.at_level("WARNING"):
            assert (
                _resolve_read_timeout(None) == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS
            )
        assert "CANTRIP_SNAP_READ_TIMEOUT" in caplog.text


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

    def test_conversation_temperature_is_clamped(self):
        """Local snaps need a low conversation temperature for stable tool calls.

        The default 0.7 makes qwen3-coder fall out of the OpenAI
        tool-call envelope at conversation rounds and emit raw
        ``<function=...>`` chat-template scaffolding inside ``content``.
        This test pins the override below the frontier-default 0.7 so a
        future regression cannot silently restore the lossy default.
        """
        provider = self._make_provider()
        assert provider.conversation_temperature < 0.7
        assert 0.0 <= provider.conversation_temperature <= 0.5

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

    def test_default_read_timeout(self):
        """No explicit timeout falls back to the documented default."""
        provider = self._make_provider()
        assert provider.read_timeout == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS

    def test_explicit_read_timeout(self):
        """``read_timeout`` argument wins over env / default."""
        provider = self._make_provider(read_timeout=120.0)
        assert provider.read_timeout == 120.0

    def test_env_read_timeout(self, monkeypatch):
        """``CANTRIP_SNAP_READ_TIMEOUT`` is consulted when no explicit value."""
        monkeypatch.setenv("CANTRIP_SNAP_READ_TIMEOUT", "300")
        provider = self._make_provider()
        assert provider.read_timeout == 300.0

    def test_invalid_env_falls_back_to_default(self, monkeypatch, caplog):
        """A non-numeric env value logs a warning and falls back."""
        monkeypatch.setenv("CANTRIP_SNAP_READ_TIMEOUT", "not-a-number")
        with caplog.at_level("WARNING"):
            provider = self._make_provider()
        assert provider.read_timeout == InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS
        assert "CANTRIP_SNAP_READ_TIMEOUT" in caplog.text

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

    def test_gemma4_is_vision_by_default(self):
        """gemma4 (Gemma 3n E4B) is on the static vision allowlist."""
        assert self._make_provider("gemma4").supports_vision is True

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

    def test_multimodal_capability_upgrades_vision(self):
        """``multimodal`` is llama.cpp's image-capable advertisement.

        gemma4 reports ``capabilities: ["completion", "multimodal"]``
        rather than the OpenAI-style ``vision`` flag, so the upgrade
        path has to recognise it.
        """
        provider = self._make_provider("some-new-snap")
        assert provider.supports_vision is False
        provider._apply_model_metadata(
            {
                "models": [{"name": "x", "capabilities": ["completion", "multimodal"]}],
                "data": [{"id": "x"}],
            }
        )
        assert provider.supports_vision is True

    def test_capabilities_picked_up_from_parallel_models_array(self):
        """llama.cpp emits a parallel ``models`` array alongside ``data``.

        Capabilities surface on the ``models`` entries rather than on
        ``data``; both should be merged before the negative-inference
        and vision-upgrade branches run.
        """
        provider = self._make_provider("qwen3-coder")
        provider._apply_model_metadata(
            {
                "models": [{"name": "x", "capabilities": ["completion"]}],
                "data": [{"id": "x"}],
            }
        )
        # qwen3-coder is on the tool-capable allowlist, so the parallel
        # capability list does not disable tools.
        assert provider._supports_tools is True

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
        mock_resp.is_error = False
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
        mock_resp.is_error = False
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
        mock_resp.is_error = False
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

    def test_detects_nested_n_ctx_train_for_llamacpp(self):
        """llama.cpp nests model parameters under ``data[0].meta``.

        gemma4's ``/models`` reports ``n_ctx_train: 131_072`` inside
        ``meta`` rather than at the top of the model entry; the
        previous flat-only lookup missed it and fell back to the
        8 KiB default.
        """
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma4", model="test-model", base_url="http://test:8336/v1"
            )
        provider._apply_model_metadata(
            {"data": [{"id": "test", "meta": {"n_ctx_train": 131_072}}]}
        )
        assert provider.context_window_tokens == 131_072

    def test_nested_meta_takes_precedence_over_flat(self):
        """When both shapes are present, nested meta wins.

        That matches llama.cpp's behaviour — the nested value is the
        trained context, while any flat key would be a coarser hint.
        """
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma4", model="test-model", base_url="http://test:8336/v1"
            )
        provider._apply_model_metadata(
            {
                "data": [
                    {
                        "id": "test",
                        "context_length": 4_096,
                        "meta": {"n_ctx_train": 131_072},
                    }
                ]
            }
        )
        assert provider.context_window_tokens == 131_072

    def test_non_dict_meta_falls_back_to_flat(self):
        """A malformed ``meta`` field doesn't crash detection."""
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="gemma4", model="test-model", base_url="http://test:8336/v1"
            )
        provider._apply_model_metadata(
            {"data": [{"id": "test", "meta": "garbage", "context_length": 16_384}]}
        )
        assert provider.context_window_tokens == 16_384


class TestSlotContextProbe:
    """Tests for the per-slot ``/slots`` context-window probe.

    llama.cpp servers split their KV cache across ``--parallel`` slots,
    so a model with ``n_ctx_train: 131072`` may only accept 4 KiB per
    request.  ``/v1/models`` reports the trained value; ``/slots`` is
    the only authoritative source for the per-request budget.
    """

    def _make_provider(self, snap_name: str = "gemma4"):
        with patch.object(InferenceSnapProvider, "_probe_server"):
            return InferenceSnapProvider(
                snap_name=snap_name,
                model="test-model",
                base_url=f"http://test-{snap_name}:8336/v1",
            )

    def _mock_client(self, slots_payload, status: int = 200):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        if status >= 400:
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "http://t/slots"),
                response=httpx.Response(status, request=httpx.Request("GET", "http://t/slots")),
            )
        else:
            mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = slots_payload
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp
        return client

    def test_smaller_per_slot_downgrades_window(self):
        """When /slots reports a smaller n_ctx, the window is tightened."""
        provider = self._make_provider()
        provider._context_window = 131_072
        client = self._mock_client(
            [
                {"id": 0, "n_ctx": 4096},
                {"id": 1, "n_ctx": 4096},
                {"id": 2, "n_ctx": 4096},
                {"id": 3, "n_ctx": 4096},
            ]
        )
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 4096

    def test_takes_minimum_across_slots(self):
        """Heterogeneous slots use the smallest as the worst-case cap."""
        provider = self._make_provider()
        provider._context_window = 131_072
        client = self._mock_client([{"id": 0, "n_ctx": 8192}, {"id": 1, "n_ctx": 4096}])
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 4096

    def test_larger_per_slot_does_not_upgrade(self):
        """A per-slot value larger than the current window is left alone.

        ``_apply_model_metadata`` may have already settled on a value
        from ``n_ctx_train`` that is the model's ceiling; per-slot
        values should only ever tighten, never widen.
        """
        provider = self._make_provider()
        provider._context_window = 8_192
        client = self._mock_client([{"id": 0, "n_ctx": 131_072}])
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 8_192

    def test_endpoint_404_leaves_window_untouched(self):
        """vLLM/OVMS don't expose /slots; the existing value survives."""
        provider = self._make_provider()
        provider._context_window = 32_768
        client = self._mock_client(slots_payload=None, status=404)
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 32_768

    def test_empty_slots_array_leaves_window_untouched(self):
        """A response with no slots is a no-op rather than a crash."""
        provider = self._make_provider()
        provider._context_window = 32_768
        client = self._mock_client([])
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 32_768

    def test_non_int_n_ctx_ignored(self):
        """Malformed slot entries are filtered, not propagated."""
        provider = self._make_provider()
        provider._context_window = 32_768
        client = self._mock_client([{"id": 0, "n_ctx": "garbage"}, {"id": 1, "n_ctx": -1}])
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 32_768

    def test_non_json_response_does_not_raise(self):
        """A snap returning HTML on /slots must not crash provider init."""
        provider = self._make_provider()
        provider._context_window = 32_768
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 32_768

    def test_props_fallback_when_slots_missing(self):
        """When /slots 404s, /props supplies the runtime n_ctx.

        Some snap builds gate ``/slots`` behind a startup flag but
        still publish ``default_generation_settings.n_ctx`` on
        ``/props``.  The probe must consult both before giving up,
        otherwise large stale values from ``n_ctx_train`` keep the
        compaction threshold too high.
        """
        provider = self._make_provider()
        provider._context_window = 262_144
        slots_resp = MagicMock()
        slots_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "http://t/slots"),
            response=httpx.Response(404, request=httpx.Request("GET", "http://t/slots")),
        )
        props_resp = MagicMock()
        props_resp.raise_for_status = MagicMock()
        props_resp.json.return_value = {
            "default_generation_settings": {"n_ctx": 32_768},
            "total_slots": 4,
        }
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = lambda path: slots_resp if path == "/slots" else props_resp
        provider._probe_slot_context(client)
        assert provider.context_window_tokens == 32_768

    def test_root_url_strips_v1(self):
        """``_root_url`` peels the OpenAI-compat ``/v1`` prefix off ``base_url``.

        ``/slots`` and ``/props`` live at the snap server root; without
        the strip the probes 404 and the runtime context stays at the
        trained value (the bug this guards against).
        """
        provider = self._make_provider()
        provider.base_url = "http://test:8332/v1"
        assert provider._root_url() == "http://test:8332"


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

    def test_tool_capable_allowlist_overrides_negative_inference(self):
        """Allowlisted snaps keep tools on even when ``capabilities`` omits tool flags.

        llama.cpp's ``/v1/models`` reports ``capabilities: ["completion"]``
        for any chat model — that's the task type, not a tool-support
        flag.  Without the allowlist, the negative-inference branch
        would drop ``tools=[...]`` from the request body and the model
        would emit tool-call markup as plain ``content``.
        """
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="qwen3-coder",
                model="test-model",
                base_url="http://test:8332/v1",
            )
        provider._apply_model_metadata({"data": [{"id": "test", "capabilities": ["completion"]}]})
        assert provider._supports_tools is True

    def test_thinking_disabled_in_request_body(self):
        """Request body carries ``chat_template_kwargs.enable_thinking=False``.

        Qwen3-family snaps served via llama.cpp ``--jinja`` otherwise
        burn the whole completion budget on ``reasoning_content`` and
        emit an empty turn; pinning this stops a regression from
        re-enabling chain-of-thought on a tight per-slot context.
        """
        with patch.object(InferenceSnapProvider, "_probe_server"):
            provider = InferenceSnapProvider(
                snap_name="qwen3-14b", model="test-model", base_url="http://test:8340/v1"
            )
        body = provider._build_request_body([Message(role=Role.USER, content="hi")], None, 0.2)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}

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

    @pytest.mark.asyncio
    async def test_non_json_response_does_not_crash(self):
        """A broken snap returning HTML must not crash the listing tool.

        ``except httpx.HTTPError`` doesn't catch ``json.JSONDecodeError``
        (which is a ``ValueError`` subclass), so a snap whose ``/models``
        endpoint returns an error page used to take the entire listing
        tool down with it.
        """
        from cantrip.agent.tools.inference import ListInferenceSnapsTool

        tool = ListInferenceSnapsTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp

        with (
            patch(
                "cantrip.agent.tools.inference.list_available_snaps",
                return_value=["broken-snap"],
            ),
            patch(
                "cantrip.agent.tools.inference.discover_snap_endpoint",
                return_value="http://localhost:8080/v1",
            ),
            patch("cantrip.agent.tools.inference.httpx.Client", return_value=mock_client),
        ):
            result = await tool.execute()

        assert result.success is True
        assert "broken-snap" in result.output
        # Failed to read /models → counted as unreachable.
        assert "unreachable" in result.output
        assert "0 running" in result.caption
