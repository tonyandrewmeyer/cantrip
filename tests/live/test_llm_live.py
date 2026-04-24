"""Live LLM tests.

Small suite that verifies each provider produces sensible responses
for known prompts. Guards against prompt regressions. Skipped when
the corresponding API key is absent.
"""

import os
from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider

pytestmark = pytest.mark.live


class TestGeminiLive:
    """Tests using a real Gemini provider."""

    pytestmark = pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    )

    @pytest.mark.asyncio
    async def test_gemini_analyse_framework_call(self, tmp_path: Path):
        """Send a prompt about a Flask app; verify an analyse_framework tool call."""
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

        provider = create_provider("gemini")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message(
            "Analyse the Flask app in the current directory using analyse_framework."
        )

        tool_calls_made = [tc.name for msg in agent.state.messages for tc in msg.tool_calls]
        assert "analyse_framework" in tool_calls_made, (
            f"Expected analyse_framework call, got: {tool_calls_made}"
        )

    @pytest.mark.asyncio
    async def test_gemini_responds_to_greeting(self, tmp_path: Path):
        """Send 'hello'; verify a non-empty text response with no tool calls."""
        provider = create_provider("gemini")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Hello! Just say hi back briefly.")

        assert len(result) > 0


class TestClaudeLive:
    """Tests using a real Claude provider."""

    pytestmark = pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set",
    )

    @pytest.mark.asyncio
    async def test_claude_analyse_framework_call(self, tmp_path: Path):
        """Send a prompt about a Flask app; verify an analyse_framework tool call."""
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

        provider = create_provider("claude")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message(
            "Analyse the Flask app in the current directory using analyse_framework."
        )

        tool_calls_made = [tc.name for msg in agent.state.messages for tc in msg.tool_calls]
        assert "analyse_framework" in tool_calls_made, (
            f"Expected analyse_framework call, got: {tool_calls_made}"
        )

    @pytest.mark.asyncio
    async def test_claude_responds_to_greeting(self, tmp_path: Path):
        """Send 'hello'; verify a non-empty text response with no tool calls."""
        provider = create_provider("claude")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Hello! Just say hi back briefly.")

        assert len(result) > 0


class TestFireworksKimiReasoning:
    """Phase 77 live smoke — Kimi K2 on Fireworks surfaces ``reasoning_content``.

    Kimi K2 emits chain-of-thought as ``delta.reasoning_content`` before the
    final answer.  Before Phase 77, the shared OpenAI-compat helper silently
    dropped those deltas, so short ``max_tokens`` budgets produced an empty
    string.  These smoke tests confirm the reasoning round-trips through
    ``Response.metadata["_thinking_content"]`` and that ``thinking_budget``
    leaves headroom for a real answer.
    """

    pytestmark = pytest.mark.skipif(
        not os.environ.get("FIREWORKS_API_KEY"),
        reason="FIREWORKS_API_KEY not set",
    )

    @pytest.mark.asyncio
    async def test_reasoning_content_round_trips_to_metadata(self):
        """A direct ``complete()`` call surfaces reasoning alongside the answer."""
        from cantrip.llm.base import Message, Role

        provider = create_provider("fireworks")
        response = await provider.complete(
            [Message(role=Role.USER, content="What is 2 + 2? Answer in one word.")],
            max_tokens=2048,
        )

        reasoning = response.metadata.get("_thinking_content", "")
        # Kimi K2 reliably emits a reasoning block on prompts like this.
        # An empty reasoning field means the shared helper is dropping
        # ``reasoning_content`` again — the exact regression Phase 77 closed.
        assert reasoning, (
            "Kimi K2 returned no reasoning_content; the helper may be dropping "
            "``delta.reasoning_content`` again."
        )
        assert response.content, (
            f"Kimi K2 returned empty content despite 2048-token budget: reasoning={reasoning!r}"
        )

    @pytest.mark.asyncio
    async def test_thinking_budget_leaves_room_for_answer(self):
        """``thinking_budget=2000`` must prevent reasoning from starving the reply.

        Even when the caller sets ``max_tokens=30`` — the exact shape that
        produced ``completion_tokens=30`` with an empty reply before
        Phase 77 — a ``thinking_budget`` kicker should raise the effective
        budget high enough for a real answer.
        """
        from cantrip.llm.base import Message, Role

        provider = create_provider("fireworks")
        response = await provider.complete(
            [Message(role=Role.USER, content="What is 2 + 2? Answer in one word.")],
            max_tokens=30,
            thinking_budget=2000,
        )
        assert response.content, (
            "thinking_budget=2000 did not leave headroom for an answer; "
            "effective max_tokens may still be too small."
        )
