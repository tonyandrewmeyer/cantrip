"""Shared slash-command dispatcher.

Each UI surface (CLI, TUI, Web) owns its own output channel, but they
all delegate to :func:`dispatch` for the command-to-text mapping so
behaviour stays identical.

Returning a :class:`SlashResult` with a ``followup`` coroutine lets
surfaces render an immediate "working..." message and then append the
real result once the async work (e.g. a marketplace fetch) finishes —
keeping the UI responsive without forcing the dispatcher itself to be
async.

Surface-native commands that need more than text (the CLI's Rich
tables for ``/tasks`` and ``/status``, the TUI's Textual worker for
``/feelings``) stay in their respective surfaces; this dispatcher is
deliberately limited to commands that reduce to a string response.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cantrip.agent import mcp_commands, memory_commands
from cantrip.llm import pricing

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


SHARED_VERBS: frozenset[str] = frozenset(
    {"/help", "?", "/memory", "/remember", "/forget", "/mcp", "/cost"}
)


@dataclass
class SlashResult:
    """Outcome of a dispatched slash command.

    ``text`` is the immediate response to render (may be a prelude like
    ``"Loading ..."`` when ``followup`` is set).  When ``followup`` is
    set the caller should render ``text`` now, await the coroutine, and
    render its result when ready.  Callers MUST await or close the
    ``followup`` — leaving it unawaited warns.
    """

    text: str
    followup: Awaitable[str] | None = None


def dispatch(agent: CantripAgent, message: str) -> SlashResult | None:
    """Route *message* to a shared handler.

    Returns ``None`` when *message* is not a slash command handled
    here — the caller decides whether to try a surface-specific
    handler or pass the message to the LLM.
    """
    verb, _, args = message.partition(" ")
    verb = verb.lower()
    if verb in {"/help", "?"}:
        return SlashResult(text=help_text())
    if verb == "/memory":
        text = memory_commands.handle_memory(
            agent._memory_manager, args, charm_path=agent.state.charm_path
        )
        return SlashResult(text=text)
    if verb == "/remember":
        return SlashResult(text=memory_commands.handle_remember(agent._memory_manager, args))
    if verb == "/forget":
        return SlashResult(text=memory_commands.handle_forget(agent._memory_manager, args))
    if verb == "/mcp":
        if mcp_commands.is_marketplace_subcommand(args):
            followup = mcp_commands.handle_mcp_async(
                agent.mcp_registry,
                agent.mcp_marketplace_sources,
                agent.mcp_marketplace_loader,
                args,
            )
            return SlashResult(text="Loading MCP marketplaces...", followup=followup)
        return SlashResult(text=mcp_commands.handle_mcp(agent.mcp_registry, args))
    if verb == "/cost":
        return SlashResult(text=format_cost(agent))
    return None


def help_text() -> str:
    """Return help for the shared slash commands.

    Surface-native commands (e.g. the CLI's ``/tasks``) are appended
    by each surface on top of this text.
    """
    return (
        "**Slash commands**\n\n"
        "- `/help`, `?` — show this help message.\n"
        "- `/memory [scope]` — list memories. Run `/memory help` for subcommands.\n"
        "- `/remember <kind> [scope] -- <title> -- <body>` — write a memory.\n"
        "- `/forget <title>` — delete a memory by title.\n"
        "- `/mcp` — list configured MCP servers. Run `/mcp help` for subcommands.\n"
        "- `/cost` — show token usage and estimated cost."
    )


def format_cost(agent: CantripAgent) -> str:
    """Render token usage and estimated cost as plain text.

    Mirrors the CLI's legacy ``_print_cost`` output so the same block
    is useful in the TUI and Web as a system message.
    """
    store = agent.store
    if not store:
        return "_No usage data available._"

    total = store.get_total_usage()
    prompt = int(total.get("prompt_tokens", 0) or 0)
    completion = int(total.get("completion_tokens", 0) or 0)
    total_tokens = prompt + completion

    if total_tokens == 0:
        return "_No tokens used yet._"

    lines = [
        "**Token usage**",
        f"- Prompt:     {prompt:>10,}",
        f"- Completion: {completion:>10,}",
        f"- Total:      {total_tokens:>10,}",
    ]

    if agent.cache_creation_tokens or agent.cache_read_tokens:
        cache_total = agent.cache_creation_tokens + agent.cache_read_tokens
        hit_pct = agent.cache_read_tokens / cache_total * 100 if cache_total else 0
        lines.append(f"- Cache hit:  {hit_pct:>9.0f}%")

    by_model = store.get_usage_by_model()
    total_cost = 0.0
    if by_model:
        lines.append("")
        lines.append("**By model**")
        for row in by_model:
            model = row.get("model", "unknown")
            reqs = int(row.get("request_count", 0) or 0)
            prompt_t = int(row.get("prompt_tokens", 0) or 0)
            completion_t = int(row.get("completion_tokens", 0) or 0)
            tokens = prompt_t + completion_t
            cost = pricing.estimate_cost(
                str(model),
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
            )
            total_cost += cost
            cost_str = pricing.format_cost(cost) if cost > 0 else "free"
            lines.append(f"- {model}: {tokens:,} tokens, {reqs} requests, {cost_str}")

    if agent.cache_read_tokens or agent.cache_creation_tokens:
        cache_cost = pricing.estimate_cost(
            agent.provider.model_name,
            cache_read_tokens=agent.cache_read_tokens,
            cache_write_tokens=agent.cache_creation_tokens,
        )
        total_cost += cache_cost

    if total_cost > 0:
        lines.append("")
        lines.append(f"_Estimated total: {pricing.format_cost(total_cost)}_")
        lines.append("_(approximate; published list prices, may drift)_")

    return "\n".join(lines)


__all__ = [
    "SHARED_VERBS",
    "SlashResult",
    "dispatch",
    "format_cost",
    "help_text",
]
