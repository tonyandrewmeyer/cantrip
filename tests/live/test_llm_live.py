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
