"""Tests for ``CantripAgent`` model switching and usage recording."""

import os
import pathlib
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider


class TestSwitchModel:
    """Phase 67.2 — ``CantripAgent.switch_model`` swaps the active provider."""

    def _make_fake(self, name="other", model="other-model", window=500_000):
        """Build a ``FakeProvider`` with an overridable ``name``/``model``."""
        provider = FakeProvider()
        provider.model_name = model
        provider._context_window_tokens = window
        # ``FakeProvider.name`` is a read-only property returning "fake"
        # — override via a type trick so each test gets a distinct tag.
        provider.__class__ = type(
            f"_Fake_{name}",
            (FakeProvider,),
            {"name": property(lambda _self, _n=name: _n)},
        )
        return provider

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — switch_model resolves a real light provider",
    )
    def test_switch_model_updates_provider_and_context_window(self):
        from unittest.mock import patch

        initial = FakeProvider()
        agent = CantripAgent(provider=initial)
        assert agent.provider is initial

        replacement = self._make_fake(name="claude", model="claude-sonnet-4-6", window=200_000)
        with patch("cantrip.agent.core.create_provider", return_value=replacement):
            agent.switch_model("claude")

        assert agent.provider is replacement
        assert agent.provider.model_name == "claude-sonnet-4-6"
        # Context manager tracks the new provider's window.
        assert agent._context_manager._context_window == 200_000

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — switch_model resolves a real light provider",
    )
    def test_switch_model_drops_provider_dependent_caches(self):
        from unittest.mock import patch

        agent = CantripAgent(provider=FakeProvider())
        # Prime caches so the swap has something to drop.
        agent._tools_cache = [object()]
        agent._tool_map_cache = {"x": object()}
        agent._auto_writer_cache = object()

        replacement = self._make_fake(name="claude", model="claude-sonnet-4-6")
        with patch("cantrip.agent.core.create_provider", return_value=replacement):
            agent.switch_model("claude")

        assert agent._tools_cache is None
        assert agent._tool_map_cache is None
        assert agent._auto_writer_cache is None

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — switch_model resolves a real light provider",
    )
    def test_switch_model_publishes_event(self):
        from unittest.mock import patch

        from cantrip.ui import events

        agent = CantripAgent(provider=FakeProvider())
        received = []
        agent.event_bus.subscribe(events.EventType.MODEL_SWITCHED, received.append)

        replacement = self._make_fake(name="claude", model="claude-sonnet-4-6", window=200_000)
        with patch("cantrip.agent.core.create_provider", return_value=replacement):
            agent.switch_model("claude")

        assert len(received) == 1
        ev = received[0]
        assert ev.type == events.EventType.MODEL_SWITCHED
        assert ev.payload["provider"] == "claude"
        assert ev.payload["model"] == "claude-sonnet-4-6"
        assert ev.payload["previous_provider"] == "fake"
        assert ev.payload["context_window"] == 200_000

    def test_switch_model_propagates_construction_errors(self):
        from unittest.mock import patch

        from cantrip.llm.base import ProviderError

        agent = CantripAgent(provider=FakeProvider())
        original_provider = agent.provider
        with (
            patch(
                "cantrip.agent.core.create_provider",
                side_effect=ProviderError("missing key"),
            ),
            pytest.raises(ProviderError, match="missing key"),
        ):
            agent.switch_model("claude")
        # Original provider is preserved when construction fails.
        assert agent.provider is original_provider


class TestUsageRecording:
    """Tests for token usage recording."""

    @pytest.mark.asyncio
    async def test_usage_recorded_for_simple_message(self, tmp_path: pathlib.Path) -> None:
        """Usage is recorded once for a simple (no tool call) exchange."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 10, "completion_tokens": 5})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("hello")

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 10
        assert total["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_usage_recorded_per_complete_call(self, tmp_path: pathlib.Path) -> None:
        """Each complete() call records its own usage row."""
        tool_call = ToolCall(id="tc", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[tool_call],
                    usage={"prompt_tokens": 100, "completion_tokens": 20},
                ),
                Response(
                    content="done",
                    usage={"prompt_tokens": 200, "completion_tokens": 40},
                ),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        await agent.process_message("go")

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 300
        assert total["completion_tokens"] == 60

    @pytest.mark.asyncio
    async def test_usage_recorded_in_streaming(self, tmp_path: pathlib.Path) -> None:
        """Usage is recorded during streaming message processing."""
        provider = FakeProvider(
            [Response(content="stream", usage={"prompt_tokens": 15, "completion_tokens": 8})]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        chunks = []
        async for chunk in agent.process_message_streaming("hi"):
            chunks.append(chunk)

        assert agent._store is not None
        total = agent._store.get_total_usage()
        assert total["prompt_tokens"] == 15

    @pytest.mark.asyncio
    async def test_no_store_without_charm_path(self) -> None:
        """No store is created when charm_path is not set."""
        provider = FakeProvider(
            [Response(content="hi", usage={"prompt_tokens": 1, "completion_tokens": 1})]
        )
        agent = CantripAgent(provider=provider)

        await agent.process_message("hello")

        assert agent._store is None
