"""Tests for the LLM base interface and utility functions."""

import pytest

from cantrip.llm import base as llm


class TestEstimateTokens:
    """Tests for the character-based token estimator."""

    def test_empty_string(self):
        assert llm.estimate_tokens("") == 0

    def test_short_string(self):
        # "hello" = 5 chars → 5 // 4 = 1 token.
        assert llm.estimate_tokens("hello") == 1

    def test_longer_string(self):
        text = "a" * 100
        assert llm.estimate_tokens(text) == 25

    def test_unicode_characters(self):
        # Multi-byte chars still count as one character in len().
        text = "café résumé"
        assert llm.estimate_tokens(text) == len(text) // 4


class TestEstimateMessageTokens:
    """Tests for message-level token estimation."""

    def test_empty_messages(self):
        assert llm.estimate_message_tokens([]) == 0

    def test_single_message(self):
        msg = llm.Message(role=llm.Role.USER, content="a" * 100)
        assert llm.estimate_message_tokens([msg]) == 25

    def test_message_with_tool_calls(self):
        tc = llm.ToolCall(id="tc1", name="read_file", arguments={"path": "x"})
        msg = llm.Message(role=llm.Role.ASSISTANT, content="", tool_calls=[tc])
        tokens = llm.estimate_message_tokens([msg])
        # Should include tool call name + arguments in the estimate.
        assert tokens > 0

    def test_message_with_tool_results(self):
        tr = llm.ToolResult(tool_call_id="tc1", content="file content here")
        msg = llm.Message(role=llm.Role.TOOL, content="", tool_results=[tr])
        tokens = llm.estimate_message_tokens([msg])
        assert tokens > 0

    def test_multiple_messages(self):
        msgs = [
            llm.Message(role=llm.Role.USER, content="a" * 40),
            llm.Message(role=llm.Role.ASSISTANT, content="b" * 40),
        ]
        assert llm.estimate_message_tokens(msgs) == 20


class TestDataclasses:
    """Tests for LLM dataclass construction and defaults."""

    def test_message_defaults(self):
        msg = llm.Message(role=llm.Role.USER, content="hi")
        assert msg.tool_calls == []
        assert msg.tool_results == []
        assert msg.metadata == {}

    def test_response_defaults(self):
        resp = llm.Response(content="hello")
        assert resp.tool_calls == []
        assert resp.finish_reason == "stop"
        assert resp.usage == {}
        assert resp.metadata == {}

    def test_chunk_defaults(self):
        chunk = llm.Chunk()
        assert chunk.content == ""
        assert chunk.tool_calls == []
        assert chunk.is_final is False

    def test_tool_definition(self):
        tool = llm.Tool(name="test", description="desc", parameters={"type": "object"})
        assert tool.name == "test"

    def test_tool_call_roundtrip(self):
        tc = llm.ToolCall(id="tc1", name="read_file", arguments={"path": "/tmp"})
        assert tc.id == "tc1"
        assert tc.arguments["path"] == "/tmp"

    def test_tool_result_error_flag(self):
        tr = llm.ToolResult(tool_call_id="tc1", content="failed", is_error=True)
        assert tr.is_error is True


class TestRole:
    """Tests for the Role enum."""

    def test_role_values(self):
        assert llm.Role.SYSTEM == "system"
        assert llm.Role.USER == "user"
        assert llm.Role.ASSISTANT == "assistant"
        assert llm.Role.TOOL == "tool"

    def test_role_is_str(self):
        # StrEnum should be usable as plain strings.
        assert isinstance(llm.Role.USER, str)
        assert f"role: {llm.Role.USER}" == "role: user"


class TestExceptions:
    """Tests for provider exception hierarchy."""

    def test_rate_limit_error(self):
        with pytest.raises(llm.ProviderRateLimitError, match="quota"):
            raise llm.ProviderRateLimitError("quota exceeded")

    def test_overloaded_error(self):
        with pytest.raises(llm.ProviderOverloadedError, match="503"):
            raise llm.ProviderOverloadedError("503 overloaded")

    def test_provider_error(self):
        with pytest.raises(llm.ProviderError, match="auth"):
            raise llm.ProviderError("auth failed")

    def test_rate_limit_not_provider_error(self):
        # They are independent exception classes.
        assert not issubclass(llm.ProviderRateLimitError, llm.ProviderError)

    def test_overloaded_not_provider_error(self):
        assert not issubclass(llm.ProviderOverloadedError, llm.ProviderError)


class TestLLMProviderInterface:
    """Tests for the abstract LLMProvider interface."""

    def test_default_max_tools_is_none(self):
        """Default max_tools returns None (no limit)."""

        class StubProvider(llm.LLMProvider):
            @property
            def name(self):
                return "stub"

            @property
            def context_window_tokens(self):
                return 100000

            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                return llm.Response(content="ok")

            async def stream(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                yield llm.Chunk(content="ok", is_final=True)

        p = StubProvider()
        assert p.max_tools is None

    def test_default_count_tokens_uses_estimate(self):
        """Default count_tokens falls back to estimate_message_tokens."""

        class StubProvider(llm.LLMProvider):
            @property
            def name(self):
                return "stub"

            @property
            def context_window_tokens(self):
                return 100000

            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                return llm.Response(content="ok")

            async def stream(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                yield llm.Chunk(content="ok", is_final=True)

        p = StubProvider()
        msgs = [llm.Message(role=llm.Role.USER, content="a" * 100)]
        assert p.count_tokens(msgs) == llm.estimate_message_tokens(msgs)
