"""Tests for light model resolution and provider routing."""

from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import _LIGHT_PURPOSES, CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm import resolve_light_model
from cantrip.llm.base import Message, Response, Role, ToolCall
from tests.conftest import FakeProvider


class TestResolveLightModel:
    """Tests for resolve_light_model()."""

    def test_claude_sonnet_resolves_to_haiku(self):
        """Claude Sonnet maps to Haiku."""
        result = resolve_light_model("claude", "claude-sonnet-4-5-20250929")
        assert result == "claude-haiku-4-5-20251001"

    def test_claude_opus_resolves_to_sonnet(self):
        """Claude Opus maps to Sonnet."""
        result = resolve_light_model("claude", "claude-opus-4-6-20250917")
        assert result == "claude-sonnet-4-5-20250929"

    def test_gemini_pro_resolves_to_flash(self):
        """Gemini Pro maps to Flash."""
        result = resolve_light_model("gemini", "gemini-3-pro-preview")
        assert result == "gemini-3-flash-preview"

    def test_unknown_model_falls_back_to_itself(self):
        """An unknown model returns itself (no savings, no breakage)."""
        result = resolve_light_model("gemini", "gemini-3-flash-preview")
        assert result == "gemini-3-flash-preview"

    def test_completely_unknown_model(self):
        """A model not in the map at all returns itself."""
        result = resolve_light_model("other", "some-custom-model")
        assert result == "some-custom-model"


class TestProviderRouting:
    """Tests for CantripAgent._get_provider()."""

    def test_compaction_routed_to_light_provider(self):
        """Compaction purpose uses the light provider when available."""
        main = FakeProvider()
        main.model_name = "main-model"
        light = FakeProvider()
        light.model_name = "light-model"

        agent = CantripAgent(provider=main, light_provider=light)

        assert agent._get_provider("compaction") is light

    def test_compaction_falls_back_without_light(self):
        """Without a light provider, compaction uses the main provider."""
        main = FakeProvider()
        agent = CantripAgent(provider=main)

        assert agent._get_provider("compaction") is main

    def test_conversation_always_uses_main(self):
        """Non-light purposes always use the main provider."""
        main = FakeProvider()
        light = FakeProvider()
        agent = CantripAgent(provider=main, light_provider=light)

        assert agent._get_provider("conversation") is main

    def test_light_purposes_contains_compaction(self):
        """Compaction is in the set of light purposes."""
        assert "compaction" in _LIGHT_PURPOSES


class TestCompactionUsesLightProvider:
    """Integration tests verifying compaction routes to the light provider."""

    @pytest.mark.asyncio
    async def test_compaction_calls_light_provider(self):
        """When compaction triggers, the light provider's complete() is called."""
        # Main provider: first call returns a tool call so the loop executes
        # (compaction is only checked inside the tool-call loop), second
        # call returns the final text response.
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        main = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="all done"),
            ]
        )
        main.model_name = "main-model"

        light = FakeProvider(
            [
                Response(content="compacted summary"),
            ]
        )
        light.model_name = "light-model"

        agent = CantripAgent(provider=main, light_provider=light)

        # Stub tool execution so the tool call succeeds.
        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=True, output="ok"),
        )

        # Tiny context window so compaction triggers after the tool round.
        agent._context_manager._context_window = 50
        agent._context_manager._compaction_threshold = 0.01

        # Seed enough conversation history to exceed the threshold.
        for i in range(6):
            role = Role.USER if i % 2 == 0 else Role.ASSISTANT
            agent.state.messages.append(Message(role=role, content=f"message {i}" * 20))

        await agent.process_message("trigger compaction")

        # The light provider should have been called for compaction.
        assert light._call_count == 1
        # The main provider handles the initial call + post-compaction call.
        assert main._call_count == 2

    @pytest.mark.asyncio
    async def test_compaction_uses_main_when_no_light(self):
        """Without a light provider, compaction uses the main provider."""
        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        main = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="compacted summary"),
                Response(content="all done"),
            ]
        )
        main.model_name = "main-model"

        agent = CantripAgent(provider=main)

        agent._execute_tool = AsyncMock(
            return_value=ToolResult(success=True, output="ok"),
        )

        # Set tiny context window to force compaction.
        agent._context_manager._context_window = 50
        agent._context_manager._compaction_threshold = 0.01

        for i in range(6):
            role = Role.USER if i % 2 == 0 else Role.ASSISTANT
            agent.state.messages.append(Message(role=role, content=f"message {i}" * 20))

        await agent.process_message("trigger compaction")

        # Main provider handles initial call + compaction + post-compaction.
        assert main._call_count == 3
