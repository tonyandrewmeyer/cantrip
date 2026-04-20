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

import pathlib
import shlex
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cantrip.agent import mcp_commands, memory_commands
from cantrip.llm import pricing

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


@dataclass(frozen=True)
class CommandInfo:
    """A slash-command verb plus a short summary for UI autocomplete.

    ``verb`` includes the leading slash (``/help``).  ``summary`` is a
    one-line description suitable for a suggestion popup — terser than
    the ``/help`` text, which carries argument syntax and examples.
    """

    verb: str
    summary: str


# Core slash commands shared across surfaces (CLI, TUI, Web).  Order is
# the order surfaces should list them in — help and discovery first,
# destructive/exit commands last.  Surface-native commands (the TUI's
# ``/feelings``, the CLI's ``/tasks`` / ``/status``) are added to this
# list by each surface at render time; see ``_shared_command_catalogue``
# in ``cantrip.tui.app`` for the TUI composition.
COMMAND_CATALOGUE: tuple[CommandInfo, ...] = (
    CommandInfo("/help", "Show command help"),
    CommandInfo("/memory", "List memories"),
    CommandInfo("/remember", "Save a memory"),
    CommandInfo("/forget", "Delete a memory"),
    CommandInfo("/mcp", "Manage MCP servers"),
    CommandInfo("/cost", "Show token usage and cost"),
    CommandInfo("/arena", "Blind A/B compare two models"),
    CommandInfo("/export", "Export the live session transcript"),
    CommandInfo("/quit", "Leave Cantrip"),
    CommandInfo("/exit", "Leave Cantrip"),
)


# Authoritative verb set accepted by :func:`dispatch`.  ``?`` is an
# alias for ``/help`` and is deliberately absent from
# :data:`COMMAND_CATALOGUE` — a suggestion popup that surfaces ``?``
# beside ``/help`` would just add noise.  New verbs must be added to
# both sets; the ``test_slash_commands`` drift test enforces this.
SHARED_VERBS: frozenset[str] = frozenset({cmd.verb for cmd in COMMAND_CATALOGUE} | {"?"})


@dataclass
class SlashResult:
    """Outcome of a dispatched slash command.

    ``text`` is the immediate response to render (may be a prelude like
    ``"Loading ..."`` when ``followup`` is set).  When ``followup`` is
    set the caller should render ``text`` now, await the coroutine, and
    render its result when ready.  Callers MUST await or close the
    ``followup`` — leaving it unawaited warns.

    ``quit`` signals that the surface should terminate after rendering
    ``text``.  Surfaces that can cleanly shut down (CLI REPL, TUI) act
    on it; the Web surface ignores it.
    """

    text: str
    followup: Awaitable[str] | None = None
    quit: bool = False


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
    if verb == "/arena":
        if not args.strip():
            return SlashResult(
                text=(
                    "Usage: ``/arena <prompt>`` — runs two models blind on "
                    "*prompt* and asks you to pick a winner.  Reply **A**, "
                    "**B**, **tie**, or **skip** when the responses arrive."
                )
            )
        return SlashResult(
            text="Arena: running A and B side by side…",
            followup=agent.begin_arena(args),
        )
    if verb == "/export":
        return SlashResult(text=export_transcript(agent, args))
    if verb in {"/quit", "/exit"}:
        return SlashResult(text="Goodbye!", quit=True)
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
        "- `/cost` — show token usage and estimated cost.\n"
        "- `/arena <prompt>` — run two models blind on *prompt* and pick"
        " a winner; the preference is recorded as a global-scope memory.\n"
        "- `/export [html|jsonl|markdown] [path]` — export the live"
        " transcript without leaving the session (default: html to"
        " `<charm>/transcript.html`).\n"
        "- `/quit`, `/exit` — leave cantrip cleanly."
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


_EXPORT_FORMATS: dict[str, str] = {
    "html": ".html",
    "jsonl": ".jsonl",
    "markdown": ".md",
}


def export_transcript(agent: CantripAgent, args: str) -> str:
    """Export the live session transcript to a file.

    ``args`` is the whitespace-separated remainder of the slash command;
    a leading token matching an entry in :data:`_EXPORT_FORMATS` selects
    the format, and a trailing token is treated as the output path.  Any
    token that is neither is reported as an error so the user does not
    silently overwrite an unintended file.
    """
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return "_Cannot export: no charm path for this session._"
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return f"_Cannot export: no `.cantrip` file at {charm_path}._"

    try:
        tokens = shlex.split(args)
    except ValueError as exc:
        return f"_Could not parse arguments: {exc}._"

    fmt = "html"
    output: pathlib.Path | None = None
    if tokens and tokens[0].lower() in _EXPORT_FORMATS:
        fmt = tokens.pop(0).lower()
    if tokens:
        output = pathlib.Path(tokens.pop(0)).expanduser()
    if tokens:
        return "_Usage: `/export [html|jsonl|markdown] [path]` — unexpected extra arguments._"

    suffix = _EXPORT_FORMATS[fmt]
    destination = output or (charm_path / f"transcript{suffix}")

    # Import lazily so the slash module stays importable in environments
    # where the transcript renderers' optional dependencies are unusual.
    from cantrip.transcript import export as transcript_export

    data = transcript_export.load_transcript(db_path)

    if fmt == "html":
        from cantrip.transcript.html import render_html

        content = render_html(data)
    elif fmt == "jsonl":
        from cantrip.transcript.jsonl import render_jsonl

        content = render_jsonl(data)
    else:
        from cantrip.transcript.markdown import render_markdown

        content = render_markdown(data)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    except OSError as exc:
        return f"_Failed to write {destination}: {exc}._"

    return f"Exported transcript ({fmt}) to `{destination}`."


__all__ = [
    "COMMAND_CATALOGUE",
    "CommandInfo",
    "SHARED_VERBS",
    "SlashResult",
    "dispatch",
    "export_transcript",
    "format_cost",
    "help_text",
]
