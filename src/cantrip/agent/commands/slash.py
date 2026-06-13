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

import dataclasses
import logging
import pathlib
from collections.abc import Awaitable
from typing import TYPE_CHECKING

from cantrip import diagnostics
from cantrip.agent.commands import charms, modes, review, session
from cantrip.agent.commands import custom as custom_commands
from cantrip.agent.commands import mcp as mcp_commands
from cantrip.agent.commands.budget import handle_budget
from cantrip.agent.commands.codeintel import (
    handle_definition,
    handle_references,
    handle_symbols,
)
from cantrip.agent.commands.cost import format_cost
from cantrip.agent.commands.flows import handle_flow
from cantrip.agent.commands.goal import handle_goal
from cantrip.agent.commands.map import handle_map, handle_map_refresh
from cantrip.agent.commands.recipes import handle_recipe
from cantrip.agent.commands.transcript import _handle_copy, _handle_share, export_transcript
from cantrip.agent.memory import commands as memory_commands
from cantrip.agent.policy import declarative_retry
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.safety import sandbox

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


@dataclasses.dataclass(frozen=True)
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
    CommandInfo("/budget", "Show or raise the per-goal iteration / token budget"),
    CommandInfo("/goal", "Show, set, or clear the user-prose session objective"),
    CommandInfo("/arena", "Blind A/B compare two models"),
    CommandInfo("/model", "Show or switch the active model"),
    CommandInfo("/export", "Export the live session transcript"),
    CommandInfo("/share", "Upload the session as a secret GitHub gist"),
    CommandInfo("/copy", "Copy a chat message to the system clipboard"),
    CommandInfo("/update", "Check PyPI for a newer release"),
    CommandInfo("/sandbox", "Show subprocess sandbox status"),
    CommandInfo("/hooks", "List configured hooks and invocation stats"),
    CommandInfo("/undo", "Roll back the last user turn (files + messages)"),
    CommandInfo("/redo", "Re-apply the most recently undone turn"),
    CommandInfo("/branch", "Rewind to a prior turn and start a new branch"),
    CommandInfo("/tree", "Show the session as a tree of turns and branches"),
    CommandInfo("/plan", "Enter read-only plan mode (no file edits or shells)"),
    CommandInfo("/build", "Leave plan mode and resume executing changes"),
    CommandInfo("/architect", "Toggle architect/editor two-model split"),
    CommandInfo("/auto-commit", "Toggle per-turn auto-commit of agent edits"),
    CommandInfo("/yolo", "Toggle unattended mode — auto-approve asks and print-mode CONFIRMs"),
    CommandInfo("/pause", "Pause the autonomous loop (chat and CONFIRM tasks keep working)"),
    CommandInfo("/resume", "Resume a paused autonomous loop"),
    CommandInfo("/ralph", "Run a bounded iterate-until-green loop (Ralph)"),
    CommandInfo("/recipe", "Run a parameterised recipe (`/recipe` lists available)"),
    CommandInfo("/flow", "Walk a Mermaid decision tree (`/flow` lists available)"),
    CommandInfo("/map", "Show top-ranked repository files (`/map full` for everything)"),
    CommandInfo("/map-refresh", "Rebuild the repository map and reprint"),
    CommandInfo("/symbols", "Search workspace symbols by name (read-only code intel)"),
    CommandInfo("/definition", "Resolve a symbol to its defining file/line + snippet"),
    CommandInfo("/references", "List every recorded callsite for a symbol"),
    CommandInfo("/diagnostics", "Show ruff/ty/charmlint issues across the active charm"),
    CommandInfo("/review", "Run prompt-based review checks (judgment-based rules)"),
    CommandInfo("/search-charms", "Search Charmhub and Launchpad for existing charms"),
    CommandInfo("/icon", "Generate a Charmhub-style icon.svg with the Painter"),
    CommandInfo("/quit", "Leave Cantrip"),
    CommandInfo("/exit", "Leave Cantrip"),
)


# Authoritative verb set accepted by :func:`dispatch`.  ``?`` is an
# alias for ``/help`` and is deliberately absent from
# :data:`COMMAND_CATALOGUE` — a suggestion popup that surfaces ``?``
# beside ``/help`` would just add noise.  New verbs must be added to
# both sets; the ``test_slash_commands`` drift test enforces this.
SHARED_VERBS: frozenset[str] = frozenset({cmd.verb for cmd in COMMAND_CATALOGUE} | {"?"})


def catalogue_for(
    agent: CantripAgent | None = None,
) -> tuple[CommandInfo, ...]:
    """Return :data:`COMMAND_CATALOGUE` plus the agent's custom commands.

    Phase 68.3: TUI autocomplete and ``/help`` both call this so
    user-defined markdown commands in ``.cantrip/commands/`` show
    up alongside the built-ins without each surface re-implementing
    the merge.  ``agent`` may be ``None`` when a caller just wants
    the built-in list (useful in tests and in the CLI's startup
    banner before the agent is fully initialised).
    """
    if agent is None:
        return COMMAND_CATALOGUE
    custom = getattr(agent, "custom_commands", None)
    if not isinstance(custom, custom_commands.CustomCommandRegistry):
        return COMMAND_CATALOGUE
    if not custom.commands:
        return COMMAND_CATALOGUE
    extras = tuple(CommandInfo(c.verb, c.description) for c in custom.commands)
    return COMMAND_CATALOGUE + extras


@dataclasses.dataclass
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

    ``markdown`` requests that the surface render ``text`` as
    Markdown instead of literal text — bold, code spans, fenced
    code blocks, lists.  Default ``False`` keeps every existing
    handler on the literal-text path; opt in by handlers that
    specifically want formatting (``/map``).

    ``clipboard_text`` is the Phase 76 system-clipboard payload.
    Surfaces with a clipboard channel (TUI uses Textual's OSC 52
    helper; CLI writes OSC 52 to the controlling tty; the Web UI
    has no equivalent server-pushed channel and ignores it) copy
    the value when set.  ``text`` still renders as a confirmation
    so the user sees something happened even when the clipboard
    write is silently discarded by the terminal.
    """

    text: str
    followup: Awaitable[str] | None = None
    quit: bool = False
    markdown: bool = False
    clipboard_text: str | None = None


def dispatch(agent: CantripAgent, message: str) -> SlashResult | None:
    """Route *message* to a shared handler.

    Returns ``None`` when *message* is not a slash command handled
    here — the caller decides whether to try a surface-specific
    handler or pass the message to the LLM.

    Any exception raised by an individual handler is caught here,
    persisted to the diagnostics log via
    :func:`cantrip.diagnostics.report_internal_error`, and replaced
    with a friendly chat string.  This is the last line of defence
    so a slash bug never crashes the surface even if the
    individual handler forgot its own try/except.
    """
    verb = message.partition(" ")[0].lower()
    try:
        return _dispatch_inner(agent, message)
    except Exception as exc:  # noqa: BLE001 — last-resort safety net.
        chat_message = diagnostics.report_internal_error(verb or "slash dispatch", exc)
        return SlashResult(text=chat_message)


#: Bare verb shared between the ``/flow`` and ``/flow:<name>`` shapes.
#: Building the colon prefix at runtime keeps the slash-catalogue drift
#: test from spotting a second literal that isn't actually a verb.
_FLOW_VERB = "/flow"


def _dispatch_inner(agent: CantripAgent, message: str) -> SlashResult | None:
    """Route *message* to the matching slash handler — see :func:`dispatch`."""
    verb, _, args = message.partition(" ")
    verb = verb.lower()
    if verb in {"/help", "?"}:
        return SlashResult(text=help_text(agent))
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
        return SlashResult(text=format_cost(agent), markdown=True)
    if verb == "/budget":
        return SlashResult(text=handle_budget(agent, args))
    if verb == "/goal":
        return SlashResult(text=handle_goal(agent, args))
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
    if verb == "/model":
        return modes._handle_model(agent, args)
    if verb == "/export":
        return SlashResult(text=export_transcript(agent, args))
    if verb == "/share":
        return _handle_share(agent)
    if verb == "/copy":
        return _handle_copy(agent, args)
    if verb == "/update":
        return session._handle_update(args)
    if verb == "/sandbox":
        return SlashResult(text=format_sandbox_status())
    if verb == "/hooks":
        return SlashResult(text=format_hooks_status(agent))
    if verb == "/undo":
        return SlashResult(text=session.handle_undo(agent))
    if verb == "/redo":
        return SlashResult(text=session.handle_redo(agent))
    if verb == "/branch":
        return SlashResult(text=session.handle_branch(agent, args))
    if verb == "/tree":
        return SlashResult(text=session.handle_tree(agent, args), markdown=True)
    if verb == "/plan":
        return SlashResult(text=modes.handle_plan(agent))
    if verb == "/build":
        return SlashResult(text=modes.handle_build(agent))
    if verb == "/architect":
        return SlashResult(text=modes.handle_architect(agent, args))
    if verb == "/auto-commit":
        return SlashResult(text=modes.handle_auto_commit(agent, args))
    if verb == "/yolo":
        return SlashResult(text=modes.handle_yolo(agent, args))
    if verb == "/pause":
        return SlashResult(text=modes.handle_pause(agent, args))
    if verb == "/resume":
        return SlashResult(text=modes.handle_resume(agent, args))
    if verb == "/ralph":
        return SlashResult(text=modes.handle_ralph(agent, args))
    if verb == "/recipe":
        return handle_recipe(agent, args)
    # ``/flow`` and ``/flow:<name>`` both route to the flow dispatcher;
    # the colon-suffix carries the flow name when authors prefer that
    # shape.  Building the prefix string from the bare verb keeps the
    # catalogue drift test happy (only ``/flow`` is a literal here).
    if verb == _FLOW_VERB or verb.startswith(_FLOW_VERB + ":"):
        return handle_flow(agent, verb, args)
    if verb == "/map":
        return SlashResult(text=handle_map(agent, args), markdown=True)
    if verb == "/map-refresh":
        return SlashResult(text=handle_map_refresh(agent, args), markdown=True)
    if verb == "/symbols":
        return SlashResult(text=handle_symbols(agent, args), markdown=True)
    if verb == "/definition":
        return SlashResult(text=handle_definition(agent, args), markdown=True)
    if verb == "/references":
        return SlashResult(text=handle_references(agent, args), markdown=True)
    if verb == "/diagnostics":
        return _handle_diagnostics(agent, args)
    if verb == "/review":
        return review._handle_review(agent, args)
    if verb == "/search-charms":
        return charms._handle_search_charms(agent, args)
    if verb == "/icon":
        return charms._handle_icon(agent, args)
    if verb in {"/quit", "/exit"}:
        return SlashResult(text="Goodbye!", quit=True)
    # Phase 68.3: fall through to user-defined commands discovered
    # from ``.cantrip/commands/*.md`` + ``~/.config/cantrip/commands/*.md``.
    # ``isinstance`` guards against the ``MagicMock``-backed agents
    # used in TUI / Web tests: without it, ``getattr`` would return a
    # Mock that answers affirmatively to ``.get(verb)`` and send the
    # dispatch loop down the wrong path.
    custom = getattr(agent, "custom_commands", None)
    if isinstance(custom, custom_commands.CustomCommandRegistry):
        match = custom.get(verb)
        if match is not None:
            return _handle_custom_command(agent, match, args)
    return None


def _handle_custom_command(
    agent: CantripAgent,
    command: custom_commands.CustomCommand,
    args: str,
) -> SlashResult:
    """Expand a user-defined slash command and hand off to the agent.

    Expansion is async because ``!`cmd` `` references may park on
    the Phase 68.2 permission manager.  The caller (TUI / Web /
    CLI) already supports ``SlashResult.followup`` coroutines, so
    we render a "running..." prelude and attach the expansion-plus-
    dispatch coroutine as the followup.  ``subtask: true`` routes
    the prompt onto the work queue; ``primary`` (the default) feeds
    it through ``agent.process_message`` like a typed user message.
    """
    prelude = f"Running `{command.verb}`…"

    async def _run() -> str:
        try:
            prompt = await custom_commands.expand(
                command,
                args,
                repo_root=agent.state.charm_path,
                permissions=(agent.executor.permissions if agent.executor else None),
                permission_manager=(agent.executor.permission_manager if agent.executor else None),
            )
        except custom_commands.CustomCommandError as exc:
            return f"`{command.verb}` failed to expand: {exc}"
        if command.subtask or command.agent != custom_commands.DEFAULT_AGENT:
            # Route through the work queue for non-primary commands —
            # the executor will spawn a subagent under the chosen
            # category.  For v1 we map the category name 1:1 and let
            # the work-queue validation catch typos.
            try:
                category = _coerce_task_category(command.agent)
            except ValueError:
                return (
                    f"`{command.verb}` names unknown agent {command.agent!r}; "
                    "expected 'primary' or a subagent category "
                    "(research, build, deploy, test, debug, infra)."
                )
            agent._work_queue.add_task(
                AgentTask(
                    title=f"Custom command: {command.verb}",
                    category=category,
                    description=prompt,
                )
            )
            return (
                f"Queued `{command.verb}` as a {category.value} task.  "
                "Check the task panel for progress."
            )
        if command.retry is not None:
            return await _run_primary_with_retry(agent, command, prompt)
        return await agent.process_message(prompt)

    return SlashResult(text=prelude, followup=_run())


async def _run_primary_with_retry(
    agent: CantripAgent,
    command: custom_commands.CustomCommand,
    prompt: str,
) -> str:
    """Drive ``agent.process_message`` through the declarative-retry runner.

    Reports a one-paragraph summary at the end so the user sees how
    many attempts ran, whether the run converged, and which checks
    failed if it didn't.  The full final response is the body of
    that summary so callers can still read what the model said.
    """
    assert command.retry is not None  # narrow for type checker
    executor = agent.executor
    outcome = await declarative_retry.run_with_retry(
        agent.process_message,
        prompt,
        config=command.retry,
        repo_root=agent.state.charm_path,
        permissions=executor.permissions if executor else None,
        permission_manager=executor.permission_manager if executor else None,
        agent_name=command.agent,
    )
    if outcome.converged:
        if outcome.attempts == 1:
            return outcome.output
        return outcome.output + f"\n\n_Retry: converged after {outcome.attempts} attempts._"

    failure_lines = [f"  - {result.label}: {result.detail}" for result in outcome.failures]
    summary = (
        f"\n\n_Retry: did not converge after {outcome.attempts} attempt(s)"
        + (" (timed out)" if outcome.timed_out else "")
        + "; failed checks:_\n"
        + "\n".join(failure_lines)
    )
    if outcome.on_failure_ran:
        summary += "\n_on_failure cleanup ran._"
    return outcome.output + summary


def _coerce_task_category(name: str) -> TaskCategory:
    """Map a string like ``"research"`` onto :class:`TaskCategory`.

    Raises :class:`ValueError` on unknown names so the custom-command
    handler can render a clear error instead of blowing up inside the
    work-queue validator.
    """
    try:
        return TaskCategory(name)
    except ValueError as exc:
        raise ValueError(f"unknown task category {name!r}") from exc


def help_text(agent: CantripAgent | None = None) -> str:
    """Return help for the shared slash commands.

    Surface-native commands (e.g. the CLI's ``/tasks``) are appended
    by each surface on top of this text.  When *agent* is provided,
    Phase 68.3 user-defined commands from ``.cantrip/commands/`` are
    appended after the built-ins so ``/help`` reflects the live
    catalogue.
    """
    base = (
        "**Slash commands**\n\n"
        "- `/help`, `?` — show this help message.\n"
        "- `/memory [scope]` — list memories. Run `/memory help` for subcommands.\n"
        "- `/remember <kind> [scope] -- <title> -- <body>` — write a memory.\n"
        "- `/forget <title>` — delete a memory by title.\n"
        "- `/mcp` — list configured MCP servers. Run `/mcp help` for subcommands.\n"
        "- `/cost` — show token usage and estimated cost.\n"
        "- `/arena <prompt>` — run two models blind on *prompt* and pick"
        " a winner; the preference is recorded as a global-scope memory.\n"
        "- `/model [provider[/model]]` — show the active model, or swap"
        " the provider mid-session (e.g. `/model claude`, `/model"
        " claude/claude-sonnet-4-6`).\n"
        "- `/export [html|jsonl|markdown] [path]` — export the live"
        " transcript without leaving the session (default: html to"
        " `<charm>/transcript.html`).\n"
        "- `/share` — upload the HTML transcript as a secret GitHub"
        " gist via `gh` and return the URL.  Falls back to a local"
        " path + the exact `gh` command when `gh` is unavailable.\n"
        "- `/copy [last|N]` — copy a chat message to the system"
        " clipboard.  Bare `/copy` grabs the last assistant message;"
        " `/copy last` grabs the last message of any role; `/copy 7`"
        " grabs message 7 (1-based, matches `/export markdown`).\n"
        "- `/update` — check PyPI for a newer Cantrip release right"
        " now (cache-bypassing).  `/update --no-check` disables the"
        " auto-check; `/update --check` re-enables it.\n"
        "- `/sandbox` — show which subprocess sandbox mechanism is"
        " active on this host and what `run_command` enforces.\n"
        "- `/undo` — roll back the last user turn: restore the working"
        " tree from the snapshot taken before that turn, and remove"
        " the messages that came from it.  Stacks: run again to"
        " unwind further.\n"
        "- `/redo` — re-apply the most recently undone turn."
        "  Cleared the moment a new user turn arrives.\n"
        "- `/branch [turn-id]` — rewind to a prior turn and start a new"
        " branch.  No argument forks before the most recent user turn"
        " (handy after a bad steering message); off-branch messages stay"
        " in the store and remain reachable.\n"
        "- `/tree` — render the session as an indented tree of turns,"
        " marking the active branch with `*` and showing turn ids you"
        " can pass to `/branch`.\n"
        "- `/plan` — enter read-only plan mode.  The agent can "
        "inspect files, git history, Juju state, and the web, but "
        "cannot edit or run shells.\n"
        "- `/build` — leave plan mode and resume executing changes."
        "  Re-feeds the last *Proposed changes* summary as context.\n"
        "- `/architect [on|off] [provider[/model]]` — toggle the "
        "architect/editor two-model split.  Each turn runs as "
        "*propose → edit*: the architect (main model) emits a plain-"
        "prose plan, then the editor (cheaper model) consumes the "
        "plan and produces tool calls.  Both passes appear "
        "separately in `/cost`.  Optional second token overrides the "
        "editor (e.g. `/architect on claude/claude-haiku-4-5-20251001`).\n"
        "- `/auto-commit [on|off]` — toggle per-turn auto-commit.  "
        "When on, every turn that mutates files lands as a discrete "
        "git commit with a Cantrip co-author trailer; pre-existing "
        "dirty work commits separately as `chore(pre-cantrip)`.  "
        "`--no-auto-commit` on the command line disables it at "
        "startup.\n"
        "- `/yolo [on|off]` — toggle unattended mode: every `ask` "
        "permission auto-approves for the rest of the session, and "
        "in `--print` runs any work-queue CONFIRM task still pending "
        "after the drain is auto-resolved.  `deny` rules still "
        "block.  `--yolo` on the command line enables it at "
        "startup.\n"
        "- `/pause` — stop the autonomous loop picking new tasks.  "
        "Chat and CONFIRM tasks keep working; in-flight tasks run "
        "to completion.  Run `/resume` to restart.\n"
        "- `/resume` — resume a paused autonomous loop.\n"
        "- `/ralph [N|off]` — bounded iterate-until-green loop "
        "(Ralph).  Re-feeds the goal up to N times until the agent "
        "emits `STOP` or stall detection trips.  Engages inside "
        "`cantrip run --print --ralph N`.\n"
        "- `/recipe` — list recipes from `.cantrip-recipes/*.yaml` "
        "(repo) or `~/.config/cantrip/recipes/*.yaml` (user).  "
        "`/recipe <name> key=value …` runs a parameterised recipe; "
        "`/recipe <name> --help` shows its parameter list.\n"
        "- `/flow` — list Mermaid decision-tree flows from "
        "`.cantrip-flows/*.md` (repo) or `~/.config/cantrip/flows/*.md` "
        "(user).  `/flow <name>` (or `/flow:<name>`) walks the diagram; "
        "`/flow <name> --help` shows the node summary.\n"
        "- `/map` — print a compact summary of the top-ranked "
        "repository files (one line per file, primary symbol "
        "shown).  Use `/map full` for the per-file symbol "
        "breakdown the agent sees on every turn.\n"
        "- `/map-refresh` — discard the repo-map cache "
        "(`.cantrip-repomap.json`) and reparse from scratch.  "
        "Same compact-vs-full toggle as `/map`.\n"
        "- `/symbols <query>` — search the workspace symbol index "
        "(Phase 72b).  Layered match policy: exact qualified > "
        "exact > prefix > fuzzy.  Use this instead of grep when "
        "you know the symbol name.\n"
        "- `/definition <symbol>` — resolve a symbol to its "
        "defining file/line plus a bounded snippet.  Ambiguous "
        "queries return every candidate.\n"
        "- `/references <symbol>` — list every recorded callsite "
        "(call, attribute access, import) for a symbol, with file:line "
        "locations.  Honest about ambiguity and truncation.\n"
        "- `/search-charms <query>` — Phase 70.1 Librarian: search "
        "Charmhub and Launchpad in parallel for existing charms or "
        "projects matching *query*.  Quality flags surface stale or "
        "unmaintained hits; the agent can follow up with "
        "`charmhub_fetch` / `launchpad_fetch` to clone source.\n"
        "- `/icon <description>` — Phase 70.5 Painter: generate a "
        "Charmhub-style `icon.svg` for the active charm using an "
        "image-generation provider (default: Imagen).  Refuses to "
        "overwrite a non-placeholder existing icon; bounded by a "
        "per-session USD cap (`state.icon_max_session_cost_usd`).\n"
        "- `/quit`, `/exit` — leave cantrip cleanly."
    )
    custom = getattr(agent, "custom_commands", None) if agent is not None else None
    if not isinstance(custom, custom_commands.CustomCommandRegistry) or not custom.commands:
        return base
    extras = ["", "**User commands** (from `.cantrip/commands/*.md`)", ""]
    for command in custom.commands:
        suffix = ""
        if command.subtask or command.agent != custom_commands.DEFAULT_AGENT:
            suffix = f" _(routes to {command.agent} agent)_"
        extras.append(f"- `{command.verb}` — {command.description}{suffix}")
    return base + "\n" + "\n".join(extras)


def format_sandbox_status() -> str:
    """Render the current subprocess-sandbox configuration for ``/sandbox``.

    Reports the mechanism the host is actually using, the default
    policy ``RunCommandTool`` enforces, and a short note on how to
    strengthen isolation (install bubblewrap if unshare-only).
    """
    mechanism = sandbox.sandbox_available()

    lines = ["**Subprocess sandbox**", ""]

    if mechanism == "bwrap":
        lines.append(
            "- Mechanism: **bwrap** — full filesystem + PID + network + namespace isolation."
        )
    elif mechanism == "unshare":
        lines.append(
            "- Mechanism: **unshare** — PID + optional network isolation. "
            "No filesystem bind mounts (install `bubblewrap` for full "
            "isolation)."
        )
    elif mechanism == "sandbox-exec":
        lines.append(
            "- Mechanism: **sandbox-exec** — macOS SBPL profile enforces "
            "a read-only root with read-write access to the working tree."
        )
    else:
        lines.append(
            "- Mechanism: **none** — no sandbox available on this host. Commands run unsandboxed."
        )

    lines.append("")
    lines.append("**Per-tool overrides**")
    lines.append("")
    lines.append(
        "- `run_command`: network **off**, working tree bound read-write, "
        "system paths bound read-only."
    )

    sink_state = "on" if sandbox.get_event_sink() is not None else "off"
    lines.append("")
    lines.append(
        f"**Transcript logging:** {sink_state} — `sandbox_policy` events "
        "are recorded in the session store when a sink is registered."
    )
    return "\n".join(lines)


def format_hooks_status(agent: CantripAgent) -> str:
    """Render the configured-hook roster and running stats for ``/hooks``.

    Three sections:

    * **Configured hooks** — one line per hook with event, filter, and
      its ``continue_on_error`` / veto-capable flag.  Lists hooks that
      haven't run yet so users can tell "zero invocations" from "not
      loaded".
    * **Invocation stats** — per-hook counts (invocations, successes,
      vetoes, failures), average duration, and last-seen timestamp.
      Reads :class:`HookStats` which the agent populates via the
      ``HookRunner`` listener — so the numbers here and the
      ``hook_invocation`` transcript events always agree.
    * **Transcript logging** — one-line note on whether the session
      store is wired up so operators know where the audit trail lives.
    """
    runner = agent.hook_runner
    stats = agent.hook_stats

    lines = ["**Hooks**", ""]

    if runner.hook_count == 0:
        lines.append(
            "No hooks configured. Drop a `hooks.yaml` into "
            "`~/.config/cantrip/` or next to your charm as "
            "`cantrip.hooks.yaml`."
        )
        return "\n".join(lines)

    lines.append(f"Configured: **{runner.hook_count}** hook(s).")
    lines.append("")

    # Walk events in declaration order so pre_tool_call / post_tool_call
    # / pre_compact / ... line up with how operators reason about the
    # lifecycle.
    from cantrip.hooks import HookEvent

    for event in HookEvent:
        hooks = runner.hooks_for(event)
        if not hooks:
            continue
        lines.append(f"**{event.value}**")
        for hook in hooks:
            parts = [f"  - `{hook.name}`"]
            if hook.if_expr is not None:
                parts.append(f"if `{hook.if_expr.source}`")
            if not hook.continue_on_error:
                parts.append("**veto-capable**")
            lines.append("  ".join(parts))
            history = stats.for_hook(hook.name)
            if history is None or history.invocations == 0:
                lines.append("      not invoked yet")
                continue
            last_seen = (
                history.last_invoked_at.strftime("%H:%M:%S")
                if history.last_invoked_at is not None
                else "—"
            )
            veto_frag = f", {history.vetoes} vetoed" if history.vetoes else ""
            timeout_frag = f", {history.timeouts} timed out" if history.timeouts else ""
            lines.append(
                f"      {history.invocations} invocations "
                f"({history.successes} ok, {history.failures} failed"
                f"{veto_frag}{timeout_frag}) · "
                f"avg {history.avg_duration_seconds * 1000:.0f}ms · "
                f"last at {last_seen}"
            )
        lines.append("")

    transcript_state = "on" if agent._store is not None else "off"
    lines.append(
        f"**Transcript logging:** {transcript_state} — `hook_invocation` "
        "events carry per-call detail in the session store."
    )
    return "\n".join(lines)


def _handle_diagnostics(agent: CantripAgent, args: str) -> SlashResult:
    """``/diagnostics``: project-wide ruff/ty/charmlint snapshot.

    Result is cached for 30 s by the underlying aggregator so a quick
    re-run reads the cache; ``--refresh`` forces a re-lint when the
    user has just edited files outside the agent's tools and wants
    fresh output.  Returns Markdown so severity headers render
    distinctly in chat surfaces that style ``**bold**``.
    """
    # Lazy import: keeps slash_commands.py importable in environments
    # where the lint runners' optional binaries aren't on PATH and
    # the import-time cost is paid only when the command is invoked.
    from cantrip.agent.context import lint_context

    charm_path = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(
            text=(
                "**Cannot run /diagnostics:** no charm path for this session.  "
                "Open a charm with the CLI and try again."
            ),
            markdown=True,
        )

    force_refresh = args.strip().lower() in {"--refresh", "refresh", "-f"}

    async def _run() -> str:
        block = await lint_context.gather_project_diagnostics(
            pathlib.Path(charm_path),
            force_refresh=force_refresh,
        )
        return f"**Project diagnostics**\n\n{block.to_text()}"

    prelude = "Running ruff / ty / charmlint…"
    return SlashResult(text=prelude, followup=_run(), markdown=True)


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
