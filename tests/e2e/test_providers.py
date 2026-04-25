"""End-to-end tests that exercise each supported LLM provider.

These tests prove every provider Cantrip ships with can complete a
real tool-call round trip through the agent loop.  Each test is gated
on the corresponding API key — when a key is absent the parameter is
skipped, so the suite is safe to run in any environment.

The scenario is deliberately minimal (analyse a tiny Flask app) so the
suite stays cheap to run across four providers; the heavier multi-turn
charm-build scenarios live in their own files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cantrip.agent.core import CantripAgent

from . import harness


def _all_provider_params() -> list[pytest.param]:
    """Build a parametrize list with one entry per supported provider.

    Each parameter is gated by ``pytest.mark.skipif`` on its env var so
    a single missing key skips just that provider, never the whole
    test.
    """
    params = []
    for name, env in harness.PROVIDER_KEY_ENV.items():
        params.append(
            pytest.param(
                name,
                marks=pytest.mark.skipif(
                    not os.environ.get(env),
                    reason=f"{env} not set",
                ),
                id=name,
            )
        )
    return params


@pytest.mark.e2e
class TestAllProviders:
    """One round-trip per provider — proves every API key works."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_name", _all_provider_params())
    async def test_provider_completes_tool_call(self, provider_name: str, tmp_path: Path) -> None:
        """Ask the agent to analyse a tiny Flask app and verify it tool-calls.

        Confirms each provider is wired up correctly: the API key works,
        the tool schema is accepted, and the model returns at least one
        tool call (typically ``analyse_framework`` or ``read_file``).
        """
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")
        (tmp_path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

        provider = harness.make_provider(provider_name)
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message(
            "Analyse the Flask app in the current directory using analyse_framework."
        )

        tool_calls = [tc.name for msg in agent.state.messages for tc in msg.tool_calls]
        assert tool_calls, (
            f"{provider_name}: expected at least one tool call, got none. "
            f"Messages: {[m.role.value for m in agent.state.messages]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_name", _all_provider_params())
    async def test_provider_responds_to_greeting(self, provider_name: str, tmp_path: Path) -> None:
        """A bare 'hello' returns non-empty text from every provider.

        Cheaper than the tool-call test — confirms the provider can
        complete a turn at all, which catches auth or model-name
        breakage even when the tool path is broken.
        """
        provider = harness.make_provider(provider_name)
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Hello! Just say hi back briefly.")

        assert result and result.strip(), (
            f"{provider_name}: expected non-empty response, got {result!r}"
        )
