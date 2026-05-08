"""``/flow`` slash-command handler (Phase 69.4).

Flows live under :mod:`cantrip.agent.flows`; this module owns the
dispatch glue:

* No-arg / ``help`` — print the catalogue and per-flow detail so users
  can discover what's available without leaving the chat.
* Named invocation — render the parsed flow as a structured agent
  prompt and feed it through the primary conversation loop.  The
  agent walks the diagram and emits ``BRANCH: <label>`` lines at
  decision nodes so the user can follow its reasoning.

Flows are *agent-walked*, not runtime-walked: the runtime validates
the diagram up front (so a typo never reaches the model) and renders
a prompt that names every node and its instructions, but it does not
gate the agent's traversal step-by-step.  That keeps the
implementation simple and matches the Kimi shape — a Mermaid skill
the agent reads, not a state machine the runtime drives.

The ``/flow:<name>`` colon-suffixed form is recognised alongside
``/flow <name>`` so authors who already use ``/flow:charm-cos-enable``
in transcripts have it land cleanly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cantrip.agent import flows

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent


# ---------------------------------------------------------------------------
# Catalogue / help rendering
# ---------------------------------------------------------------------------


def _format_flow_help(flow: flows.Flow) -> str:
    """Detail page for a single flow."""
    lines = [f"**`/flow {flow.name}`** — {flow.description}", ""]
    if flow.intro_prose:
        lines.append(flow.intro_prose)
        lines.append("")

    lines.append(
        f"**Entry node:** `{flow.entry_node}`.  "
        f"{len(flow.nodes)} node(s), {len(flow.edges)} edge(s)."
    )
    lines.append("")
    decision_nodes = [n for n in flow.nodes if n.kind is flows.NodeKind.DECISION]
    terminal_nodes = [n for n in flow.nodes if n.kind is flows.NodeKind.TERMINAL]
    if decision_nodes:
        lines.append("**Decision nodes:**")
        for node in decision_nodes:
            branches = ", ".join(f"`{e.label}`" for e in flow.outgoing(node.id) if e.label)
            lines.append(f"- `{node.id}` ({node.label}) — branches: {branches}")
        lines.append("")
    if terminal_nodes:
        lines.append("**Terminal nodes:**")
        for node in terminal_nodes:
            lines.append(f"- `{node.id}` — {node.label}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_catalogue(registry: flows.FlowRegistry) -> str:
    """No-arg ``/flow`` listing."""
    if not registry.flows:
        return (
            "_No flows loaded._  Drop a markdown file into "
            "`.cantrip-flows/` (repo) or `~/.config/cantrip/flows/` "
            "(user) — see `design/SKILLS.md` (Flow skills section) "
            "for the schema."
        )
    lines = ["**Flows**", ""]
    for flow in registry.flows:
        lines.append(f"- `/flow {flow.name}` — {flow.description}")
    lines.append("")
    lines.append(
        "Run `/flow <name> --help` for the parameter list and node "
        "summary.  Invoke with `/flow <name>` (or "
        "`/flow:<name>` — the colon form is the same)."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_HELP_TOKENS = frozenset({"help", "--help", "-h"})


def _tokens_from_verb_and_args(verb: str, args: str) -> list[str]:
    """Flatten ``/flow:<name>`` and ``/flow <args>`` into a single token list.

    The colon form is desugared by treating ``/flow:<name>`` as the
    first positional token followed by the remaining argv.  Bare
    ``/flow`` returns whatever was in *args*.  Empty tokens are
    dropped so a stray double-space doesn't drift the parse.
    """
    tokens: list[str] = []
    if verb.startswith("/flow:"):
        suffix = verb[len("/flow:") :].strip()
        if suffix:
            tokens.append(suffix)
    return tokens + args.split()


def handle_flow(agent: CantripAgent, verb: str, args: str) -> SlashResult:
    """Dispatch ``/flow`` from :func:`cantrip.agent.commands.slash.dispatch`.

    *verb* may be ``/flow`` or ``/flow:<name>``; the colon form bundles
    the flow name into the verb token, which the dispatcher parser
    splits before the args.  *args* is everything after the verb token.

    Recognised shapes:

    * ``/flow`` → catalogue.
    * ``/flow help`` (and ``--help`` / ``-h``) → catalogue.
    * ``/flow help <name>`` → that flow's detail page.
    * ``/flow <name>`` (and ``/flow:<name>``) → run the flow.
    * ``/flow <name> --help`` → that flow's detail page.
    * ``/flow <name> anything-else`` → refusal pointing at ``/recipe``.
    """
    from cantrip.agent.commands.slash import SlashResult

    registry = getattr(agent, "flows", None)
    if not isinstance(registry, flows.FlowRegistry):
        return SlashResult(text="_`/flow` is unavailable — agent has no flow registry._")

    tokens = _tokens_from_verb_and_args(verb, args)

    if not tokens:
        return SlashResult(text=_format_catalogue(registry), markdown=True)

    head = tokens[0]
    rest = tokens[1:]

    if head in _HELP_TOKENS:
        if not rest:
            return SlashResult(text=_format_catalogue(registry), markdown=True)
        if len(rest) > 1:
            return SlashResult(
                text="_`/flow help` takes at most one flow name._",
                markdown=True,
            )
        target = rest[0]
        flow = registry.get(target)
        if flow is None:
            return SlashResult(text=f"_No flow named `{target}`._", markdown=True)
        return SlashResult(text=_format_flow_help(flow), markdown=True)

    flow = registry.get(head)
    if flow is None:
        return SlashResult(
            text=f"_No flow named `{head}`._  Run `/flow` to list available flows.",
            markdown=True,
        )

    if rest and rest[0] in _HELP_TOKENS:
        return SlashResult(text=_format_flow_help(flow), markdown=True)

    if rest:
        return SlashResult(
            text=(
                f"_`/flow {flow.name}` does not accept arguments._  Flows "
                "are agent-walked, not parameterised — use `/recipe "
                f"{flow.name}` if you want a parameterised execution."
            ),
            markdown=True,
        )

    prelude = f"Walking flow `{flow.name}`…"

    async def _run() -> str:
        prompt = flows.render_flow_prompt(flow)
        return await agent.process_message(prompt)

    return SlashResult(text=prelude, followup=_run())


__all__ = ["handle_flow"]
