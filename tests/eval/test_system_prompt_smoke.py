"""Per-provider system-prompt smoke tests.

Renders the shipped system prompt (``cantrip.agent.prompts.system``),
sends it as the system role with a fixed test prompt to each
configured provider, and asserts basic shape invariants on the
response.

Anthropic's April 2026 Claude Code postmortem traced a 3% quality
regression to a single sentence in a system prompt that their narrow
initial eval missed; the remediation was per-model evals on every
prompt change.  Cantrip's eval harness has the same gap, only wider.
This file is the lightweight guard: a couple of provider-in-loop calls
that exercise the actual rendered prompt against each supported
backend so a tweak to ``system.md.j2`` cannot quietly degrade tool-
calling shape on Gemini while still passing on Claude (or vice versa).

Skipped per-provider when the corresponding API key is absent, so the
file stays green under ``make eval`` on a developer machine with no
LLM keys configured.

The CI gate that runs this file against a cheap model (Phase 79.3)
lives in ``.github/workflows/ci.yaml``; the per-provider matrix here
is the same shape but spans the full provider set rather than a
single cheap pick.
"""

import os

import pytest

from cantrip.agent.prompts.system import build_system_prompt
from cantrip.llm import create_provider
from cantrip.llm.base import Message, Role, Tool


def _read_file_tool() -> Tool:
    """Minimal ``read_file`` tool definition.

    The smoke test only needs the model to *target* a tool name; no
    execution happens.  ``read_file`` is the canonical name in
    ``cantrip.agent.tools.files``, so the rendered system prompt
    references it implicitly through the bundled-tools section.
    """
    return Tool(
        name="read_file",
        description="Read the contents of a file in the charm directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to charm root).",
                },
            },
            "required": ["path"],
        },
    )


def _system_and_user(user_prompt: str) -> list[Message]:
    """System-then-user message list with no priors."""
    return [
        Message(role=Role.SYSTEM, content=build_system_prompt()),
        Message(role=Role.USER, content=user_prompt),
    ]


# Provider matrix.  Each entry is (cantrip-provider-name, env-var).
# The default behaviour is "use the provider's default model" so the
# smoke test exercises what a user gets without bespoke configuration.
# Local runs and the per-provider live job both want this default-
# pinning behaviour.
#
# The cheap-model CI gate (Phase 79.3) wants a different shape: pin
# one provider to a tiny / cheap model.  Each provider therefore reads
# an optional ``CANTRIP_SMOKE_<PROVIDER>_MODEL`` env var that overrides
# the default — for example, the CI job sets
# ``CANTRIP_SMOKE_OPENROUTER_MODEL=openai/gpt-4o-mini`` to keep cost
# bounded.  The override is opt-in so a developer running the suite
# locally with their primary keys keeps testing against the same model
# they actually use.
#
# Open-weights coverage rotates through Fireworks (Kimi K2 by default)
# and OpenRouter (GPT-4o by default).  Either alone satisfies the
# Phase 79.2 "at least one open-weights model" requirement; running
# both when keys are present widens the net.
_PROVIDER_MATRIX = [
    ("claude", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("fireworks", "FIREWORKS_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
]


def _model_override(provider_name: str) -> str | None:
    """Return the optional ``CANTRIP_SMOKE_<PROVIDER>_MODEL`` override."""
    return os.environ.get(f"CANTRIP_SMOKE_{provider_name.upper()}_MODEL") or None


def _provider_params() -> list:
    """Build pytest.param entries with per-provider skipif guards."""
    params = []
    for provider_name, env_var in _PROVIDER_MATRIX:
        params.append(
            pytest.param(
                provider_name,
                marks=pytest.mark.skipif(
                    not os.environ.get(env_var),
                    reason=f"{env_var} not set",
                ),
                id=provider_name,
            )
        )
    return params


_PROVIDER_PARAMS = _provider_params()


@pytest.mark.parametrize("provider_name", _PROVIDER_PARAMS)
async def test_system_prompt_drives_tool_call(provider_name: str):
    """The model emits a ``read_file`` tool call when asked to read a file.

    The system prompt heavily nudges the agent toward tool use — when
    the user asks a question that *obviously* needs file content and a
    matching tool is in scope, every supported provider must produce a
    ``read_file`` tool call rather than guessing the answer.

    A regression here means the prompt no longer steers the model to
    its tool catalogue: the same change might pass on one provider and
    fail on another, which is exactly the per-provider gate this file
    exists to provide.
    """
    provider = create_provider(provider_name, model=_model_override(provider_name))

    response = await provider.complete(
        _system_and_user(
            "What is the project name in `pyproject.toml`?  "
            "Use the `read_file` tool to read the file before answering — "
            "do not guess."
        ),
        tools=[_read_file_tool()],
        max_tokens=512,
    )

    tool_names = [tc.name for tc in response.tool_calls]
    assert "read_file" in tool_names, (
        f"{provider_name}: expected a `read_file` tool call, got "
        f"tool_calls={tool_names!r}, content={response.content[:200]!r}"
    )


@pytest.mark.parametrize("provider_name", _PROVIDER_PARAMS)
async def test_system_prompt_returns_non_empty_response(provider_name: str):
    """A bare greeting against the rendered prompt produces non-empty content.

    The most blatant prompt regressions surface here: a 4xx from the
    provider (system prompt rejected as malformed), a Jinja2 template
    breakage that produces garbage, or a model that loops on tools
    without ever returning text.  None of those failure modes are
    visible to the static gold-standard scorer.
    """
    provider = create_provider(provider_name, model=_model_override(provider_name))

    response = await provider.complete(
        _system_and_user("Hello!  Reply with a single short sentence — no tools."),
        max_tokens=128,
    )

    # Either the model answered with text, or it tool-called.  Both are
    # acceptable shapes for "the system prompt didn't blow up"; the
    # failure mode this test catches is *neither* — empty content and
    # no tool calls, which is what a 4xx-eaten-by-the-provider-adapter
    # looks like in practice.
    assert response.content or response.tool_calls, (
        f"{provider_name}: empty response with no tool calls — "
        f"system prompt may have been rejected by the provider."
    )
