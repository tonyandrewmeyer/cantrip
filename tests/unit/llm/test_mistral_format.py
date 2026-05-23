"""Tests for Phase 109: per-provider message-format normalisation.

Covers:
  109.1  ``rewrite_messages`` hook — outbound Mistral rewriter
  109.2  Inbound parser for ``[TOOL_CALLS]…[/TOOL_CALLS]`` markers
  109.4  Family detection from snap name and ``CANTRIP_MESSAGE_FORMAT`` env var
  109.5  Recorded-trace tests pinning the wire format for complete() and stream()
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cantrip.llm.base import Message, Role, ToolCall, ToolResult
from cantrip.llm.inference_snap import InferenceSnapProvider, _detect_message_format
from cantrip.llm.mistral_format import parse_mistral_tool_call_content, rewrite_for_mistral

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Minimal async iterator for SSE-stream test mocks."""
    for item in items:
        yield item


def _make_provider(snap_name: str, *, model: str = "test-model") -> InferenceSnapProvider:
    """Build an InferenceSnapProvider with the network probe bypassed."""
    with patch.object(InferenceSnapProvider, "_probe_server"):
        return InferenceSnapProvider(
            snap_name=snap_name,
            model=model,
            base_url="http://test:8346/v1",
        )


# ---------------------------------------------------------------------------
# 109.1 — Outbound rewriter: rewrite_for_mistral()
# ---------------------------------------------------------------------------


class TestRewriteForMistral:
    """rewrite_for_mistral folds tool-role messages into prior assistant turns."""

    def test_identity_for_no_tool_calls(self):
        """Messages with no tool calls pass through unchanged."""
        msgs = [
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi there"),
        ]
        result = rewrite_for_mistral(msgs)
        assert result == msgs
        # Same objects — no copying needed when there is nothing to rewrite.
        assert result[0] is msgs[0]
        assert result[1] is msgs[1]

    def test_basic_tool_round_trip(self):
        """[user, assistant(tool_calls), tool(results)] → [user, assistant(markers)]."""
        msgs = [
            Message(role=Role.USER, content="What is the weather?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="get_weather", arguments={"location": "Paris"})
                ],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="tc1", content="15°C, cloudy")],
            ),
        ]
        result = rewrite_for_mistral(msgs)

        assert len(result) == 2
        assert result[0] is msgs[0]

        ast_msg = result[1]
        assert ast_msg.role == Role.ASSISTANT
        assert ast_msg.tool_calls == []  # Folded into content.
        assert "[TOOL_CALLS]" in ast_msg.content
        assert "[/TOOL_CALLS]" in ast_msg.content
        assert "[TOOL_RESULTS]" in ast_msg.content
        assert "[/TOOL_RESULTS]" in ast_msg.content
        assert "get_weather" in ast_msg.content
        assert "Paris" in ast_msg.content
        assert "15°C, cloudy" in ast_msg.content
        assert "tc1" in ast_msg.content

    def test_tool_calls_json_is_valid(self):
        """The [TOOL_CALLS] block contains parseable JSON."""
        msgs = [
            Message(role=Role.USER, content="Hello"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="x1", name="read_file", arguments={"path": "charm.py"})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="x1", content="contents here")],
            ),
        ]
        result = rewrite_for_mistral(msgs)
        content = result[1].content

        open_tag = "[TOOL_CALLS]"
        close_tag = "[/TOOL_CALLS]"
        start = content.index(open_tag) + len(open_tag)
        end = content.index(close_tag)
        calls = json.loads(content[start:end])

        assert isinstance(calls, list)
        assert len(calls) == 1
        assert calls[0]["name"] == "read_file"
        assert calls[0]["arguments"] == {"path": "charm.py"}
        assert calls[0]["id"] == "x1"

    def test_tool_results_json_is_valid(self):
        """Each [TOOL_RESULTS] block contains parseable JSON."""
        msgs = [
            Message(role=Role.USER, content="Hello"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="r1", name="juju", arguments={})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="r1", content="status ok")],
            ),
        ]
        result = rewrite_for_mistral(msgs)
        content = result[1].content

        open_tag = "[TOOL_RESULTS]"
        close_tag = "[/TOOL_RESULTS]"
        start = content.index(open_tag) + len(open_tag)
        end = content.index(close_tag)
        res_obj = json.loads(content[start:end])

        assert res_obj["content"] == "status ok"
        assert res_obj["call_id"] == "r1"

    def test_prior_assistant_content_preserved(self):
        """Existing assistant content is kept before the markers."""
        msgs = [
            Message(role=Role.USER, content="Calculate"),
            Message(
                role=Role.ASSISTANT,
                content="Let me compute that.",
                tool_calls=[ToolCall(id="c1", name="calc", arguments={"expr": "2+2"})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="c1", content="4")],
            ),
        ]
        result = rewrite_for_mistral(msgs)
        content = result[1].content

        assert content.startswith("Let me compute that.")
        assert "[TOOL_CALLS]" in content

    def test_multiple_tool_calls_and_results(self):
        """Multiple tool calls and their results are all folded in."""
        msgs = [
            Message(role=Role.USER, content="Both"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="a1", name="fn_a", arguments={}),
                    ToolCall(id="b1", name="fn_b", arguments={"x": 1}),
                ],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[
                    ToolResult(tool_call_id="a1", content="result_a"),
                    ToolResult(tool_call_id="b1", content="result_b"),
                ],
            ),
        ]
        result = rewrite_for_mistral(msgs)

        assert len(result) == 2
        content = result[1].content
        assert content.count("[TOOL_CALLS]") == 1
        assert content.count("[TOOL_RESULTS]") == 2
        assert "fn_a" in content
        assert "fn_b" in content
        assert "result_a" in content
        assert "result_b" in content

    def test_consecutive_tool_messages_absorbed(self):
        """Multiple consecutive TOOL messages after one ASSISTANT are all absorbed."""
        msgs = [
            Message(role=Role.USER, content="Hi"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="t1", name="fn", arguments={})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="t1", content="res1")],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="t1", content="res2")],
            ),
        ]
        result = rewrite_for_mistral(msgs)
        assert len(result) == 2
        assert "res1" in result[1].content
        assert "res2" in result[1].content

    def test_assistant_without_following_tool_message(self):
        """An assistant tool call with no following TOOL message still gets [TOOL_CALLS]."""
        msgs = [
            Message(role=Role.USER, content="Do it"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="x", name="fn", arguments={})],
            ),
        ]
        result = rewrite_for_mistral(msgs)
        assert len(result) == 2
        assert "[TOOL_CALLS]" in result[1].content
        assert "[TOOL_RESULTS]" not in result[1].content

    def test_system_message_preserved(self):
        """System messages pass through the rewriter untouched."""
        msgs = [
            Message(role=Role.SYSTEM, content="You are helpful."),
            Message(role=Role.USER, content="Hello"),
            Message(role=Role.ASSISTANT, content="Hi"),
        ]
        result = rewrite_for_mistral(msgs)
        assert result[0].role == Role.SYSTEM
        assert result[0].content == "You are helpful."
        assert result[0] is msgs[0]

    def test_does_not_mutate_original_messages(self):
        """Original Message objects are not modified."""
        original_tool_calls = [ToolCall(id="t1", name="fn", arguments={})]
        msgs = [
            Message(role=Role.USER, content="Hi"),
            Message(role=Role.ASSISTANT, content="", tool_calls=original_tool_calls),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="t1", content="res")],
            ),
        ]
        rewrite_for_mistral(msgs)

        # Original objects unmodified.
        assert msgs[1].tool_calls == original_tool_calls
        assert msgs[1].content == ""

    def test_multi_turn_conversation(self):
        """A multi-turn conversation with two tool-use rounds is correctly rewritten."""
        msgs = [
            Message(role=Role.USER, content="First question"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="r1", name="read_file", arguments={"path": "a.py"})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="r1", content="file contents")],
            ),
            Message(role=Role.ASSISTANT, content="Got it. Second answer."),
            Message(role=Role.USER, content="Second question"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="r2", name="write_file", arguments={"path": "b.py"})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="r2", content="written")],
            ),
        ]
        result = rewrite_for_mistral(msgs)

        # Two TOOL messages absorbed into their respective ASSISTANT messages.
        assert len(result) == 5
        assert "[TOOL_CALLS]" in result[1].content
        assert "read_file" in result[1].content
        assert result[2].content == "Got it. Second answer."
        assert "[TOOL_CALLS]" in result[4].content
        assert "write_file" in result[4].content


# ---------------------------------------------------------------------------
# 109.2 — Inbound parser: parse_mistral_tool_call_content()
# ---------------------------------------------------------------------------


class TestParseMistralToolCallContent:
    """parse_mistral_tool_call_content extracts tool calls from inline markers."""

    def test_parses_single_tool_call(self):
        """A single tool call in markers is extracted correctly."""
        content = (
            '[TOOL_CALLS][{"name": "get_weather", '
            '"arguments": {"location": "Paris"}, "id": "tc1"}][/TOOL_CALLS]'
        )
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_weather"
        assert tool_calls[0].arguments == {"location": "Paris"}
        assert tool_calls[0].id == "tc1"
        assert remainder == ""

    def test_generates_id_when_missing(self):
        """When the tool call JSON has no ``"id"`` field, a stable fallback is used."""
        content = '[TOOL_CALLS][{"name": "fn", "arguments": {}}][/TOOL_CALLS]'
        tool_calls, _ = parse_mistral_tool_call_content(content)

        assert len(tool_calls) == 1
        assert tool_calls[0].id.startswith("mistral-tc-")

    def test_parses_multiple_tool_calls(self):
        """Multiple tool calls in one array are all extracted."""
        calls = [
            {"name": "fn_a", "arguments": {"x": 1}, "id": "a"},
            {"name": "fn_b", "arguments": {"y": 2}, "id": "b"},
        ]
        content = f"[TOOL_CALLS]{json.dumps(calls)}[/TOOL_CALLS]"
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert len(tool_calls) == 2
        assert tool_calls[0].name == "fn_a"
        assert tool_calls[1].name == "fn_b"
        assert remainder == ""

    def test_empty_remainder_when_only_markers(self):
        """When content is only the markers, remainder is empty string."""
        content = '[TOOL_CALLS][{"name": "fn", "arguments": {}, "id": "x"}][/TOOL_CALLS]'
        _, remainder = parse_mistral_tool_call_content(content)
        assert remainder == ""

    def test_keeps_text_outside_markers_in_remainder(self):
        """Any text outside the markers ends up in remainder."""
        content = (
            "Some prefix. "
            '[TOOL_CALLS][{"name": "fn", "arguments": {}, "id": "x"}][/TOOL_CALLS]'
            " Some suffix."
        )
        tool_calls, remainder = parse_mistral_tool_call_content(content)
        assert len(tool_calls) == 1
        assert "Some prefix" in remainder
        assert "Some suffix" in remainder

    # -- Negative tests -------------------------------------------------------

    def test_no_markers_returns_empty_and_original_content(self):
        """When no markers are present, no tool calls are returned."""
        content = "Here is my answer without any tool calls."
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content

    def test_prose_mentioning_marker_tokens_no_false_positive(self):
        """Prose that mentions the literal tokens but holds invalid JSON is safe."""
        # The text between [TOOL_CALLS] and [/TOOL_CALLS] is plain prose, not JSON.
        content = (
            "The [TOOL_CALLS] syntax in Mistral's Tekken format is interesting. "
            "You wrap each call in [/TOOL_CALLS] markers."
        )
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content

    def test_empty_json_array_returns_no_tool_calls(self):
        """An empty array between markers does not produce tool calls."""
        content = "[TOOL_CALLS][][/TOOL_CALLS]"
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content

    def test_invalid_json_returns_original_content(self):
        """Non-JSON content between markers does not produce tool calls."""
        content = "[TOOL_CALLS]this is not json[/TOOL_CALLS]"
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content

    def test_missing_close_tag_returns_original_content(self):
        """A marker without its closing tag does not produce tool calls."""
        content = '[TOOL_CALLS][{"name": "fn", "arguments": {}}]'
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content

    def test_items_without_name_key_are_skipped(self):
        """Items in the array that lack a ``"name"`` key are silently dropped."""
        calls = [
            {"arguments": {}, "id": "bad"},
            {"name": "good_fn", "arguments": {"k": "v"}, "id": "good"},
        ]
        content = f"[TOOL_CALLS]{json.dumps(calls)}[/TOOL_CALLS]"
        tool_calls, _ = parse_mistral_tool_call_content(content)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "good_fn"

    def test_all_items_without_name_returns_empty(self):
        """If every item lacks ``"name"``, the result is empty (no false parse)."""
        calls = [{"arguments": {}, "id": "x"}]
        content = f"[TOOL_CALLS]{json.dumps(calls)}[/TOOL_CALLS]"
        tool_calls, remainder = parse_mistral_tool_call_content(content)

        assert tool_calls == []
        assert remainder == content


# ---------------------------------------------------------------------------
# 109.4 — Family detection and CANTRIP_MESSAGE_FORMAT env var
# ---------------------------------------------------------------------------


class TestFamilyDetection:
    """_detect_message_format picks the right format from the snap name."""

    def test_mistral_nemo_prefix(self):
        assert _detect_message_format("mistral-nemo-12b") == "mistral"

    def test_mistral_nemo_exact(self):
        assert _detect_message_format("mistral-nemo") == "mistral"

    def test_magistral_prefix(self):
        assert _detect_message_format("magistral-8b") == "mistral"

    def test_qwen_family_is_openai(self):
        assert _detect_message_format("qwen3-14b") == "openai"

    def test_gemma_family_is_openai(self):
        assert _detect_message_format("gemma3") == "openai"

    def test_deepseek_family_is_openai(self):
        assert _detect_message_format("deepseek-r1") == "openai"

    def test_unknown_snap_is_openai(self):
        assert _detect_message_format("some-unknown-model") == "openai"


class TestMessageFormatEnvVar:
    """CANTRIP_MESSAGE_FORMAT overrides snap-name family detection."""

    def test_env_mistral_forces_mistral_even_for_non_mistral_snap(self, monkeypatch):
        monkeypatch.setenv("CANTRIP_MESSAGE_FORMAT", "mistral")
        provider = _make_provider("qwen3-14b")
        assert provider._message_format == "mistral"

    def test_env_openai_forces_openai_even_for_mistral_snap(self, monkeypatch):
        monkeypatch.setenv("CANTRIP_MESSAGE_FORMAT", "openai")
        provider = _make_provider("mistral-nemo-12b")
        assert provider._message_format == "openai"

    def test_env_unset_uses_snap_detection_mistral(self, monkeypatch):
        monkeypatch.delenv("CANTRIP_MESSAGE_FORMAT", raising=False)
        provider = _make_provider("mistral-nemo-12b")
        assert provider._message_format == "mistral"

    def test_env_unset_uses_snap_detection_openai(self, monkeypatch):
        monkeypatch.delenv("CANTRIP_MESSAGE_FORMAT", raising=False)
        provider = _make_provider("qwen3-14b")
        assert provider._message_format == "openai"

    def test_unrecognised_env_value_logs_warning_and_falls_back(self, monkeypatch, caplog):
        monkeypatch.setenv("CANTRIP_MESSAGE_FORMAT", "llama")
        with caplog.at_level("WARNING"):
            provider = _make_provider("mistral-nemo-12b")
        assert "CANTRIP_MESSAGE_FORMAT" in caplog.text
        # Falls back to snap-name detection → mistral.
        assert provider._message_format == "mistral"

    def test_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("CANTRIP_MESSAGE_FORMAT", "MISTRAL")
        provider = _make_provider("qwen3-14b")
        assert provider._message_format == "mistral"


# ---------------------------------------------------------------------------
# 109.5 — Recorded-trace tests (wire-format pins for complete() and stream())
# ---------------------------------------------------------------------------


class TestMistralWireFormatComplete:
    """Pin the Mistral wire format emitted by InferenceSnapProvider.complete()."""

    def _make_mistral_provider(self) -> InferenceSnapProvider:
        return _make_provider("mistral-nemo-12b", model="Mistral-Nemo-12B-Q4.gguf")

    def _fake_complete_response(self, content: str = "15°C, cloudy.") -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://test:8346/v1/chat/completions"),
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            },
        )

    @pytest.mark.asyncio
    async def test_tool_round_trip_body_has_no_tool_role(self):
        """The wire body must not contain any ``"tool"`` role messages."""
        provider = self._make_mistral_provider()

        captured: dict = {}

        async def fake_post(_url, *, json=None, **_kw):
            captured.update(json or {})
            return self._fake_complete_response()

        provider.client.post = fake_post

        messages = [
            Message(role=Role.USER, content="What is the weather?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="get_weather", arguments={"location": "Paris"})
                ],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="tc1", content="15°C, cloudy")],
            ),
        ]
        await provider.complete(messages)

        api_msgs = captured["messages"]
        roles = [m["role"] for m in api_msgs]
        assert "tool" not in roles, f"Unexpected 'tool' role in {roles}"

    @pytest.mark.asyncio
    async def test_tool_round_trip_assistant_carries_markers(self):
        """The rewritten assistant message contains both Mistral marker pairs."""
        provider = self._make_mistral_provider()

        captured: dict = {}

        async def fake_post(_url, *, json=None, **_kw):
            captured.update(json or {})
            return self._fake_complete_response()

        provider.client.post = fake_post

        messages = [
            Message(role=Role.USER, content="Weather?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="get_weather", arguments={"location": "Paris"})
                ],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="tc1", content="15°C, cloudy")],
            ),
        ]
        await provider.complete(messages)

        ast_msgs = [m for m in captured["messages"] if m["role"] == "assistant"]
        assert len(ast_msgs) == 1
        content = ast_msgs[0]["content"]
        assert "[TOOL_CALLS]" in content
        assert "[/TOOL_CALLS]" in content
        assert "[TOOL_RESULTS]" in content
        assert "[/TOOL_RESULTS]" in content
        assert "get_weather" in content
        assert "Paris" in content
        assert "15°C, cloudy" in content

    @pytest.mark.asyncio
    async def test_non_mistral_snap_keeps_tool_role(self):
        """For non-Mistral snaps the tool role is forwarded to the API unchanged."""
        provider = _make_provider("qwen3-14b")

        captured: dict = {}

        async def fake_post(_url, *, json=None, **_kw):
            captured.update(json or {})
            return self._fake_complete_response()

        provider.client.post = fake_post

        messages = [
            Message(role=Role.USER, content="Weather?"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[ToolCall(id="tc1", name="get_weather", arguments={})],
            ),
            Message(
                role=Role.TOOL,
                content="",
                tool_results=[ToolResult(tool_call_id="tc1", content="sunny")],
            ),
        ]
        await provider.complete(messages)

        roles = [m["role"] for m in captured["messages"]]
        assert "tool" in roles


class TestInboundParserOnComplete:
    """InferenceSnapProvider.complete() applies the inbound Mistral parser."""

    def _make_mistral_provider(self) -> InferenceSnapProvider:
        return _make_provider("mistral-nemo-12b", model="Mistral-Nemo.gguf")

    @pytest.mark.asyncio
    async def test_content_markers_become_tool_calls(self):
        """When the server returns [TOOL_CALLS] in content, they become tool_calls."""
        provider = self._make_mistral_provider()

        raw_content = (
            '[TOOL_CALLS][{"name": "read_file", '
            '"arguments": {"path": "charm.py"}, "id": "rc1"}][/TOOL_CALLS]'
        )
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test:8346/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": raw_content},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Read the file.")])

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "charm.py"}
        assert response.tool_calls[0].id == "rc1"
        assert response.content == ""

    @pytest.mark.asyncio
    async def test_plain_content_passes_through_unchanged(self):
        """When content has no markers, it is returned as a plain assistant reply."""
        provider = self._make_mistral_provider()

        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test:8346/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "It is 15°C."},
                    }
                ],
                "usage": {},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Weather?")])

        assert response.content == "It is 15°C."
        assert response.tool_calls == []

    @pytest.mark.asyncio
    async def test_openai_tool_calls_take_priority_over_content_parser(self):
        """When the server returns a proper tool_calls array, the content parser is skipped."""
        provider = self._make_mistral_provider()

        # Server correctly handled --jinja: tool_calls populated, content empty.
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test:8346/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "server-tc1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"location": "London"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Weather?")])

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].id == "server-tc1"
        assert response.tool_calls[0].name == "get_weather"

    @pytest.mark.asyncio
    async def test_non_mistral_provider_does_not_apply_inbound_parser(self):
        """For OpenAI-format snaps, content with markers is kept as plain text."""
        provider = _make_provider("qwen3-14b")

        # A hypothetical Qwen model that happened to say "[TOOL_CALLS]" in text.
        raw_content = '[TOOL_CALLS][{"name": "fn", "arguments": {}}][/TOOL_CALLS]'
        mock_response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://test:8346/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": raw_content},
                    }
                ],
                "usage": {},
            },
        )
        provider.client.post = AsyncMock(return_value=mock_response)

        response = await provider.complete([Message(role=Role.USER, content="Hi")])

        # qwen3-14b does not use the inbound parser; raw content passes through.
        assert raw_content in response.content
        assert response.tool_calls == []


class TestMistralWireFormatStream:
    """Pin the Mistral wire format for InferenceSnapProvider.stream()."""

    def _make_mistral_provider(self) -> InferenceSnapProvider:
        return _make_provider("mistral-nemo-12b", model="Mistral-Nemo.gguf")

    def _make_sse_mock(self, lines: list[str]) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.is_error = False
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    @pytest.mark.asyncio
    async def test_stream_plain_text_response_passes_through(self):
        """A plain-text Mistral stream yields the text content on the final chunk."""
        provider = self._make_mistral_provider()

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"It is "}}]}',
            'data: {"choices":[{"delta":{"content":"15°C."}}]}',
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":5,"completion_tokens":4}}',
            "data: [DONE]",
        ]
        provider.client.stream = MagicMock(return_value=self._make_sse_mock(sse_lines))

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Weather?")]):
            chunks.append(chunk)

        # Content is buffered and re-yielded as a single chunk.
        content_chunks = [c for c in chunks if c.content]
        full_text = "".join(c.content for c in content_chunks)
        assert "It is " in full_text
        assert "15°C." in full_text

        finals = [c for c in chunks if c.is_final]
        assert len(finals) == 1
        assert finals[0].usage == {"prompt_tokens": 5, "completion_tokens": 4}

    @pytest.mark.asyncio
    async def test_stream_inline_tool_calls_in_content_are_parsed(self):
        """When --jinja fails and markers appear in content, they become tool_calls."""
        provider = self._make_mistral_provider()

        # Build the SSE JSON properly so inner quotes in the call JSON are escaped.
        raw_call = json.dumps([{"name": "write_file", "arguments": {"path": "f.py"}, "id": "wf1"}])
        content_text = f"[TOOL_CALLS]{raw_call}[/TOOL_CALLS]"
        content_line = "data: " + json.dumps({"choices": [{"delta": {"content": content_text}}]})

        sse_lines = [
            content_line,
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":8,"completion_tokens":20}}',
            "data: [DONE]",
        ]
        provider.client.stream = MagicMock(return_value=self._make_sse_mock(sse_lines))

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Write it.")]):
            chunks.append(chunk)

        finals = [c for c in chunks if c.is_final]
        assert len(finals) == 1
        assert len(finals[0].tool_calls) == 1
        assert finals[0].tool_calls[0].name == "write_file"
        assert finals[0].tool_calls[0].arguments == {"path": "f.py"}

        # The raw marker text must not appear as content.
        content_chunks = [c for c in chunks if c.content]
        assert all("[TOOL_CALLS]" not in c.content for c in content_chunks)

    @pytest.mark.asyncio
    async def test_stream_server_tool_calls_take_priority(self):
        """When --jinja works and returns tool_calls SSE deltas, the parser is skipped."""
        provider = self._make_mistral_provider()

        # Two SSE frames building up the "juju" tool call incrementally.
        frame1 = json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "srv1",
                                    "function": {"name": "juju", "arguments": "{"},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        frame2 = json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"model": "prod"}'}}
                            ]
                        }
                    }
                ]
            }
        )
        sse_lines = [
            f"data: {frame1}",
            f"data: {frame2}",
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":3,"completion_tokens":5}}',
            "data: [DONE]",
        ]
        provider.client.stream = MagicMock(return_value=self._make_sse_mock(sse_lines))

        chunks = []
        async for chunk in provider.stream([Message(role=Role.USER, content="Juju status")]):
            chunks.append(chunk)

        finals = [c for c in chunks if c.is_final]
        assert len(finals) == 1
        # The server-supplied tool call is present; the inbound parser was not needed.
        assert finals[0].tool_calls[0].name == "juju"
