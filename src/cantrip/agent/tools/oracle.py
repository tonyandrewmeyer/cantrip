"""Oracle — on-demand second-opinion model consult (Phase 70.2).

The primary agent calls ``oracle_consult`` to route one prompt to a
stronger reasoning model (default Anthropic Claude Opus with extended
thinking) and receive a one-shot answer that does *not* enter the
main session's ``state.messages``.  The transcript captures the full
exchange as a side event so audits keep nothing lost.

This sits between Phase 47 (Best-of-N racing — full subagent loops)
and ``/arena`` (Phase 47.5 — blind A/B preference capture): Oracle is
*one prompt, one answer, continue*.  The main session keeps running
on its current model.

Two budgets stop the agent burning money on the expensive model:

* ``state.oracle_max_calls_per_turn`` (default ``1``) — how many
  times Oracle may be consulted between user messages.
* ``state.oracle_max_session_cost_usd`` (default ``$2``) — cumulative
  cap across the whole session.

Either trip returns a structured tool error so the agent can
explain the cap in its summary instead of silently failing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cantrip.agent.policy.retry import complete_with_retry
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm import base as llm
from cantrip.llm import create_provider
from cantrip.llm.pricing import estimate_cost

log = logging.getLogger(__name__)


# Defaults: Claude Opus 4.7 with reasoning on.  Overridable per-session
# via ``state.oracle_provider_name`` / ``state.oracle_model`` (see
# AgentState) so a charm author who prefers Gemini-3-Pro for
# architecture questions can swap providers without touching code.
DEFAULT_ORACLE_PROVIDER = "claude"
DEFAULT_ORACLE_MODEL = "claude-opus-4-7"

# Reasoning budget for the consult.  Higher than the planner's 4 000
# because architecture / security questions reward deeper thought, and
# Oracle is rate-limited by the per-turn / per-session caps anyway.
_ORACLE_THINKING_BUDGET = 8000

# Output cap.  Generous enough for a multi-paragraph architectural
# answer with a structured recommendation but small enough that one
# runaway oracle call can't blow the session budget.
_ORACLE_MAX_TOKENS = 4096

# Temperature.  Low because charm-architecture questions reward
# consistent, well-reasoned answers over creative variation.
_ORACLE_TEMPERATURE = 0.2

# How many recent main-session messages to fold into the context
# bundle.  Six is enough to capture "the last user steering message
# plus the two most recent assistant turns and their tool results"
# without dragging in pages of noise.
_RECENT_MESSAGE_WINDOW = 6

# Cap on each individual recent-message excerpt so a single long tool
# result doesn't crowd out the question.
_RECENT_MESSAGE_EXCERPT_CHARS = 800


# Type alias for the provider-construction callable.  Tests inject a
# stub that returns a deterministic provider; production passes
# :func:`cantrip.llm.create_provider`.
ProviderFactory = Callable[[str, str], llm.LLMProvider]


# System prompt for the oracle call.  Deliberately short — the oracle
# answers a single concrete question and is told what kind of answer
# is wanted.
_ORACLE_SYSTEM = (
    "You are an architecture and security oracle for the Cantrip charm-"
    "building agent.  You receive one focused question with a small "
    "context bundle and return one careful, well-reasoned answer.\n\n"
    "Constraints:\n"
    "- Answer the question that was asked; do not propose a plan or "
    "tool calls.\n"
    "- Cite charm/Juju/ops idioms by name when relevant.\n"
    "- When a recommendation depends on assumptions, state them.\n"
    "- Keep the answer compact — multi-paragraph prose, not a "
    "step-by-step playbook.\n"
    "- UK English."
)


class OracleTool(Tool):
    """Consult a stronger reasoning model on a single hard question.

    The tool does not have access to other tools; it returns the
    raw model response plus token/cost accounting.  Budgets and
    transcript recording live on this class so swapping providers
    cannot bypass them.
    """

    def __init__(
        self,
        state: AgentState,
        *,
        store_getter: Callable[[], SessionStore | None] | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._state = state
        self._store_getter = store_getter
        self._provider_factory: ProviderFactory = provider_factory or _default_factory

    @property
    def name(self) -> str:
        return "oracle_consult"

    @property
    def description(self) -> str:
        return (
            "Route one focused question to a stronger reasoning model "
            "and return its answer without committing the main session "
            "to it.  Use for charm-architecture choices, "
            "security-relevant design, library-vs-custom-code "
            "trade-offs, and reactive→ops migration heuristics — not "
            "for syntax lookups (the docs handle those).  Bounded by a "
            "per-turn call cap and a per-session USD cap; either trip "
            "returns a tool error.  Does not enter the main "
            "conversation history; the transcript records the full "
            "exchange as a side event."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The focused architecture or design question.  "
                        "Phrase it as a complete sentence — the oracle "
                        "answers exactly what is asked."
                    ),
                },
                "context_hint": {
                    "type": "string",
                    "description": (
                        "Optional one-paragraph context the oracle "
                        "needs that isn't in the recent transcript "
                        "(e.g. a constraint from the user, a target "
                        "deployment shape, a workload quirk)."
                    ),
                    "default": "",
                },
            },
            "required": ["question"],
        }

    async def execute(self, question: str, context_hint: str = "") -> ToolResult:
        question = (question or "").strip()
        if not question:
            return ToolResult(
                success=False,
                output="",
                error="oracle_consult requires a non-empty question.",
            )

        budget_error = self._check_budget()
        if budget_error is not None:
            return budget_error

        provider_name = self._state.oracle_provider_name or DEFAULT_ORACLE_PROVIDER
        model_name = self._state.oracle_model or DEFAULT_ORACLE_MODEL

        try:
            provider = self._provider_factory(provider_name, model_name)
        except (ValueError, RuntimeError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to construct oracle provider: {exc}",
            )

        messages = self._build_messages(question, context_hint)

        try:
            response = await complete_with_retry(
                provider,
                messages,
                tools=None,
                temperature=_ORACLE_TEMPERATURE,
                max_tokens=_ORACLE_MAX_TOKENS,
                thinking_budget=_ORACLE_THINKING_BUDGET,
            )
        except (
            llm.ProviderError,
            llm.ProviderRateLimitError,
            llm.ProviderOverloadedError,
        ) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Oracle call failed: {exc}",
            )

        cost = _estimate_cost(model_name, response.usage)
        self._state.oracle_calls_this_turn += 1
        self._state.oracle_calls_total += 1
        self._state.oracle_session_cost_usd += cost

        self._record_event(
            question=question,
            context_hint=context_hint,
            provider_name=provider_name,
            model_name=model_name,
            answer=response.content,
            usage=response.usage,
            cost_usd=cost,
        )

        summary = _format_summary(
            answer=response.content,
            provider_name=provider_name,
            model_name=model_name,
            cost=cost,
            session_cost=self._state.oracle_session_cost_usd,
            session_cap=self._state.oracle_max_session_cost_usd,
        )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "answer": response.content,
                "provider": provider_name,
                "model": model_name,
                "usage": dict(response.usage),
                "cost_usd": cost,
                "session_cost_usd": self._state.oracle_session_cost_usd,
                "calls_this_turn": self._state.oracle_calls_this_turn,
                "calls_total": self._state.oracle_calls_total,
            },
            caption=f"oracle_consult({model_name})",
        )

    def _check_budget(self) -> ToolResult | None:
        per_turn_cap = max(0, self._state.oracle_max_calls_per_turn)
        if self._state.oracle_calls_this_turn >= per_turn_cap:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Oracle per-turn budget exhausted "
                    f"(used {self._state.oracle_calls_this_turn} of "
                    f"{per_turn_cap}).  Wait for the next user turn or "
                    "raise the cap via state.oracle_max_calls_per_turn."
                ),
            )
        if self._state.oracle_session_cost_usd >= self._state.oracle_max_session_cost_usd:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Oracle session cost cap reached "
                    f"(${self._state.oracle_session_cost_usd:.2f} of "
                    f"${self._state.oracle_max_session_cost_usd:.2f}).  "
                    "Raise state.oracle_max_session_cost_usd to "
                    "consult further."
                ),
            )
        return None

    def _build_messages(self, question: str, context_hint: str) -> list[llm.Message]:
        """Compose the oracle's prompt: system + compact context + question."""
        sections: list[str] = []

        active_task = _format_active_task(self._state)
        if active_task:
            sections.append(f"## Active task\n\n{active_task}")

        if context_hint.strip():
            sections.append(f"## Caller's context hint\n\n{context_hint.strip()}")

        recent = _format_recent_messages(self._state.messages)
        if recent:
            sections.append(f"## Recent conversation\n\n{recent}")

        sections.append(f"## Question\n\n{question}")

        body = "\n\n".join(sections)
        return [
            llm.Message(role=llm.Role.SYSTEM, content=_ORACLE_SYSTEM),
            llm.Message(role=llm.Role.USER, content=body),
        ]

    def _record_event(
        self,
        *,
        question: str,
        context_hint: str,
        provider_name: str,
        model_name: str,
        answer: str,
        usage: dict[str, int],
        cost_usd: float,
    ) -> None:
        if self._store_getter is None:
            return
        store = self._store_getter()
        if store is None:
            return
        try:
            store.record_event(
                "oracle_consult",
                {
                    "provider": provider_name,
                    "model": model_name,
                    "question": question,
                    "context_hint": context_hint,
                    "answer": answer,
                    "usage": dict(usage),
                    "cost_usd": cost_usd,
                    "calls_this_turn": self._state.oracle_calls_this_turn,
                    "calls_total": self._state.oracle_calls_total,
                    "session_cost_usd": self._state.oracle_session_cost_usd,
                },
            )
        except (OSError, ValueError, RuntimeError) as exc:
            # Recording failure must not break the tool — the agent
            # already has the answer.  Log loudly so audit is not lost
            # silently.
            log.warning("Failed to record oracle_consult event: %s", exc)


def _default_factory(provider_name: str, model: str) -> llm.LLMProvider:
    """Production provider factory — calls :func:`create_provider`."""
    return create_provider(provider_name, model)


def _estimate_cost(model_name: str, usage: dict[str, int]) -> float:
    """Estimate USD cost from a Response's usage payload."""
    if not usage:
        return 0.0
    return estimate_cost(
        model_name,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )


def _format_active_task(state: AgentState) -> str:
    """Render a one-paragraph summary of the charm under construction."""
    bits: list[str] = []
    if state.charm_name:
        bits.append(f"charm: {state.charm_name}")
    if state.charm_type:
        bits.append(f"type: {state.charm_type}")
    if state.framework:
        bits.append(f"framework: {state.framework}")
    if state.dev_model:
        bits.append(f"dev model: {state.dev_model}")
    if state.cos_model:
        bits.append(f"cos model: {state.cos_model}")
    if not bits:
        return ""
    return ", ".join(bits)


def _format_recent_messages(messages: list[llm.Message]) -> str:
    """Render the last few main-session messages as a compact transcript."""
    if not messages:
        return ""
    tail = messages[-_RECENT_MESSAGE_WINDOW:]
    rendered: list[str] = []
    for msg in tail:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        content = msg.content or ""
        if not content.strip() and msg.tool_calls:
            content = ", ".join(f"{tc.name}(...)" for tc in msg.tool_calls)
        if len(content) > _RECENT_MESSAGE_EXCERPT_CHARS:
            content = content[: _RECENT_MESSAGE_EXCERPT_CHARS - 1] + "…"
        rendered.append(f"**{role}:** {content.strip()}")
    return "\n\n".join(rendered)


def _format_summary(
    *,
    answer: str,
    provider_name: str,
    model_name: str,
    cost: float,
    session_cost: float,
    session_cap: float,
) -> str:
    """Render the tool's text output: answer with a one-line provenance footer."""
    footer = (
        f"\n\n— Oracle ({provider_name}/{model_name}); cost ≈ ${cost:.4f}; "
        f"session ≈ ${session_cost:.4f} of ${session_cap:.2f} cap."
    )
    return answer.strip() + footer


__all__ = [
    "DEFAULT_ORACLE_MODEL",
    "DEFAULT_ORACLE_PROVIDER",
    "OracleTool",
    "ProviderFactory",
]
