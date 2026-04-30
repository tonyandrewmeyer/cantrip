"""Live LLM tests.

Small suite that verifies each provider produces sensible responses
for known prompts. Guards against prompt regressions. Skipped when
the corresponding API key is absent.
"""

import math
import os
import pathlib

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
    async def test_gemini_analyse_framework_call(self, tmp_path: pathlib.Path):
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
    async def test_gemini_responds_to_greeting(self, tmp_path: pathlib.Path):
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
    async def test_claude_analyse_framework_call(self, tmp_path: pathlib.Path):
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
    async def test_claude_responds_to_greeting(self, tmp_path: pathlib.Path):
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


class TestOpenCodeZenLive:
    """Tests using a real OpenCode Zen provider.

    Mirrors the Gemini and Claude live shape — one tool-call check
    against a tiny Flask repo, one greeting check — so a provider
    regression on the OpenAI-compatible code path surfaces here.
    Skipped unless ``OPENCODE_ZEN_API_KEY`` (or the legacy
    ``ZEN_API_KEY`` alias) is in the environment.
    """

    pytestmark = pytest.mark.skipif(
        not (os.environ.get("OPENCODE_ZEN_API_KEY") or os.environ.get("ZEN_API_KEY")),
        reason="OPENCODE_ZEN_API_KEY not set",
    )

    @pytest.mark.asyncio
    async def test_opencode_zen_analyse_framework_call(self, tmp_path: pathlib.Path):
        """Send a prompt about a Flask app; verify an analyse_framework tool call."""
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

        provider = create_provider("opencode-zen")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message(
            "Analyse the Flask app in the current directory using analyse_framework."
        )

        tool_calls_made = [tc.name for msg in agent.state.messages for tc in msg.tool_calls]
        assert "analyse_framework" in tool_calls_made, (
            f"Expected analyse_framework call, got: {tool_calls_made}"
        )

    @pytest.mark.asyncio
    async def test_opencode_zen_responds_to_greeting(self, tmp_path: pathlib.Path):
        """Send 'hello'; verify a non-empty text response."""
        provider = create_provider("opencode-zen")
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Hello! Just say hi back briefly.")

        assert len(result) > 0


class TestVoyageLive:
    """Live smoke for Voyage embed and rerank providers (Phase 72.3).

    Voyage's free tier is capped at 3 RPM, so this class keeps its
    API footprint deliberately small: one embed call and one rerank
    call.  The assertions cover the response-decoding path
    (vectors, dimensions, token usage, indices, scores) plus a
    semantic ordering check that protects against silent model swaps
    or input-type regressions.
    """

    pytestmark = pytest.mark.skipif(
        not os.environ.get("VOYAGE_API_KEY"),
        reason="VOYAGE_API_KEY not set",
    )

    @pytest.mark.asyncio
    async def test_voyage_embed_returns_aligned_vectors(self):
        """Embed a small batch; verify shape, token usage, and semantic ordering."""
        from cantrip.llm.voyage import VoyageEmbedProvider

        provider = VoyageEmbedProvider()
        docs = [
            "Juju models applications and their integrations.",
            "Charms are operators packaged for Juju.",
            "Bananas grow on trees in tropical climates.",
        ]
        # One API call — keeps us within Voyage's free-tier 3 RPM cap.
        result = await provider.embed(docs, input_type="document")

        assert result.model == "voyage-3"
        assert len(result.vectors) == len(docs)
        assert result.dimensions > 0
        assert all(len(v) == result.dimensions for v in result.vectors)
        assert result.input_tokens > 0, (
            "Voyage should report a non-zero token count for non-empty input"
        )

        # Semantic sanity: the two Juju docs should be closer to each
        # other than either is to the banana doc.  Catches a silent
        # model regression or a transposed-vector bug.
        def cos(a: tuple[float, ...], b: tuple[float, ...]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        juju_to_charms = cos(result.vectors[0], result.vectors[1])
        juju_to_banana = cos(result.vectors[0], result.vectors[2])
        assert juju_to_charms > juju_to_banana, (
            f"Juju↔charms similarity ({juju_to_charms:.3f}) should beat "
            f"Juju↔banana ({juju_to_banana:.3f})"
        )

    @pytest.mark.asyncio
    async def test_voyage_rerank_orders_by_relevance(self):
        """Rerank picks a Juju-relevant doc as the top hit."""
        from cantrip.llm.voyage import VoyageRerankProvider

        provider = VoyageRerankProvider()
        docs = [
            "Bananas grow on trees in tropical climates.",
            "Charms are operators packaged for Juju that manage applications.",
            "Python is a high-level programming language.",
            "Juju deploys, configures, and manages charmed applications.",
        ]
        result = await provider.rerank("How does Juju manage applications?", docs, top_k=3)

        assert result.model == "rerank-2"
        assert len(result.indices) == len(result.scores) <= 3
        assert result.input_tokens > 0
        # Top hit must be one of the two Juju docs (indices 1 or 3).
        assert result.indices[0] in (1, 3), (
            f"expected a Juju-relevant doc on top, got index {result.indices[0]}: "
            f"{docs[result.indices[0]]!r}"
        )
        # Scores must be monotonically non-increasing.
        assert list(result.scores) == sorted(result.scores, reverse=True)
