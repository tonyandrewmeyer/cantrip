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

import asyncio
import dataclasses
import logging
import pathlib
from collections.abc import Awaitable
from typing import TYPE_CHECKING

from cantrip import diagnostics
from cantrip import update as update_module
from cantrip.agent import sandbox
from cantrip.agent.commands import custom as custom_commands
from cantrip.agent.commands import mcp as mcp_commands
from cantrip.agent.commands.budget import handle_budget
from cantrip.agent.commands.cost import format_cost
from cantrip.agent.commands.goal import handle_goal
from cantrip.agent.commands.map import handle_map, handle_map_refresh
from cantrip.agent.commands.share import share_to_gist
from cantrip.agent.commands.transcript import export_transcript
from cantrip.agent.memory import commands as memory_commands
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.llm.base import Message, ProviderError, Role
from cantrip.ui import events as ui_events

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
    CommandInfo("/yolo", "Toggle unattended mode — auto-approve every ask"),
    CommandInfo("/pause", "Pause the autonomous loop (chat and CONFIRM tasks keep working)"),
    CommandInfo("/resume", "Resume a paused autonomous loop"),
    CommandInfo("/ralph", "Run a bounded iterate-until-green loop (Ralph)"),
    CommandInfo("/map", "Show top-ranked repository files (`/map full` for everything)"),
    CommandInfo("/map-refresh", "Rebuild the repository map and reprint"),
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
        return _handle_model(agent, args)
    if verb == "/export":
        return SlashResult(text=export_transcript(agent, args))
    if verb == "/share":
        return _handle_share(agent)
    if verb == "/copy":
        return _handle_copy(agent, args)
    if verb == "/update":
        return _handle_update(args)
    if verb == "/sandbox":
        return SlashResult(text=format_sandbox_status())
    if verb == "/hooks":
        return SlashResult(text=format_hooks_status(agent))
    if verb == "/undo":
        return SlashResult(text=handle_undo(agent))
    if verb == "/redo":
        return SlashResult(text=handle_redo(agent))
    if verb == "/branch":
        return SlashResult(text=handle_branch(agent, args))
    if verb == "/tree":
        return SlashResult(text=handle_tree(agent, args), markdown=True)
    if verb == "/plan":
        return SlashResult(text=handle_plan(agent))
    if verb == "/build":
        return SlashResult(text=handle_build(agent))
    if verb == "/architect":
        return SlashResult(text=handle_architect(agent, args))
    if verb == "/auto-commit":
        return SlashResult(text=handle_auto_commit(agent, args))
    if verb == "/yolo":
        return SlashResult(text=handle_yolo(agent, args))
    if verb == "/pause":
        return SlashResult(text=handle_pause(agent, args))
    if verb == "/resume":
        return SlashResult(text=handle_resume(agent, args))
    if verb == "/ralph":
        return SlashResult(text=handle_ralph(agent, args))
    if verb == "/map":
        return SlashResult(text=handle_map(agent, args), markdown=True)
    if verb == "/map-refresh":
        return SlashResult(text=handle_map_refresh(agent, args), markdown=True)
    if verb == "/diagnostics":
        return _handle_diagnostics(agent, args)
    if verb == "/review":
        return _handle_review(agent, args)
    if verb == "/search-charms":
        return _handle_search_charms(args)
    if verb == "/icon":
        return _handle_icon(agent, args)
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
        return await agent.process_message(prompt)

    return SlashResult(text=prelude, followup=_run())


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


def _handle_update(args: str) -> SlashResult:
    """Dispatch the ``/update`` slash command.

    ``/update`` forces a cache-bypassing PyPI check and renders the
    result in the chat.  ``--no-check`` / ``--check`` toggle the
    persistent opt-out in ``~/.config/cantrip/settings.json``.
    """
    tokens = args.split()
    if not tokens:
        return SlashResult(
            text="Checking PyPI for a newer Cantrip…",
            followup=_run_update_slash_check(),
        )

    flag = tokens[0].lower()
    if len(tokens) != 1 or flag not in {"--check", "--no-check"}:
        return SlashResult(
            text=(
                "Usage: `/update` (check PyPI now), "
                "`/update --no-check` (disable auto-check), "
                "or `/update --check` (re-enable)."
            )
        )
    try:
        path = update_module.set_update_check_disabled(flag == "--no-check")
    except OSError as exc:
        return SlashResult(text=f"_Failed to update {_SETTINGS_LABEL}: {exc}._")
    verb_label = "disabled" if flag == "--no-check" else "re-enabled"
    return SlashResult(text=f"Auto-update check {verb_label} — wrote `{path}`.")


_SETTINGS_LABEL = "~/.config/cantrip/settings.json"


# Providers that ``/model`` can construct with just a name (plus an
# optional model slug).  ``openai-compatible`` is deliberately absent —
# it needs a ``--base-url`` that doesn't fit the slash syntax.  Restart
# the session with ``cantrip --provider openai-compatible --base-url ...``
# when targeting a generic endpoint.
_MODEL_SWITCH_PROVIDERS: frozenset[str] = frozenset(
    {"gemini", "claude", "fireworks", "openrouter", "opencode-zen", "inference-snap"}
)


def _handle_model(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch the ``/model`` slash command.

    No argument: print the active provider + model.  Argument parses
    as ``provider`` (switch to that provider's default model) or
    ``provider/model`` (switch to a specific model).  Model slugs can
    contain ``/`` themselves — only the first ``/`` is treated as the
    separator.
    """
    spec = args.strip()
    if not spec:
        light = ""
        if agent._light_provider is not None:
            light = f" (light: {agent._light_provider.name}/{agent._light_provider.model_name})"
        return SlashResult(
            text=(
                f"**Active model:** {agent.provider.name}/"
                f"{agent.provider.model_name}{light}\n\n"
                "Usage: `/model <provider>[/model]` — switch to another "
                "provider.  Known providers: "
                f"`{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`.  "
                "Model slug is optional (uses the provider's default "
                "when omitted).  Example: `/model claude/claude-sonnet-4-6`."
            )
        )

    provider_name, _, model_slug = spec.partition("/")
    provider_name = provider_name.strip()
    model_slug = model_slug.strip() or None

    if provider_name not in _MODEL_SWITCH_PROVIDERS:
        return SlashResult(
            text=(
                f"Unknown provider `{provider_name}`.  Known providers: "
                f"`{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`.  "
                "For `openai-compatible` endpoints, restart Cantrip with "
                "`--provider openai-compatible --base-url ...`."
            )
        )

    try:
        agent.switch_model(provider_name, model_slug)
    except (ProviderError, ValueError) as exc:
        return SlashResult(text=f"_Failed to switch model: {exc}_")

    return SlashResult(
        text=(
            f"Switched to **{agent.provider.name}/{agent.provider.model_name}** "
            f"(context window: {agent.provider.context_window_tokens:,} tokens)."
        )
    )


async def _run_update_slash_check() -> str:
    """Hit PyPI, bypassing the cache, and format the result for chat.

    Follows the same failure-model as the startup check — any error
    gets translated into a clear user-facing message rather than a
    traceback.  The cache bypass exists precisely for a user who just
    ran their installer's upgrade command and wants to see the new
    version reflected immediately.
    """
    if update_module.update_check_disabled():
        return (
            "_Auto-update check is disabled (env var or settings file). "
            "Re-enable with `/update --check`._"
        )
    try:
        info = await update_module.check_for_update(use_cache=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return f"_Could not reach PyPI: {exc}._"
    if info is None:
        return "You're on the latest Cantrip release."
    return update_module.format_slash_notice(info)


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
        "permission auto-approves for the rest of the session.  "
        "`deny` rules still block.  `--yolo` on the command line "
        "enables it at startup.\n"
        "- `/pause` — stop the autonomous loop picking new tasks.  "
        "Chat and CONFIRM tasks keep working; in-flight tasks run "
        "to completion.  Run `/resume` to restart.\n"
        "- `/resume` — resume a paused autonomous loop.\n"
        "- `/ralph [N|off]` — bounded iterate-until-green loop "
        "(Ralph).  Re-feeds the goal up to N times until the agent "
        "emits `STOP` or stall detection trips.  Engages inside "
        "`cantrip run --print --ralph N`.\n"
        "- `/map` — print a compact summary of the top-ranked "
        "repository files (one line per file, primary symbol "
        "shown).  Use `/map full` for the per-file symbol "
        "breakdown the agent sees on every turn.\n"
        "- `/map-refresh` — discard the repo-map cache "
        "(`.cantrip-repomap.json`) and reparse from scratch.  "
        "Same compact-vs-full toggle as `/map`.\n"
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


def handle_undo(agent: CantripAgent) -> str:
    """Phase 68.1 ``/undo``: roll back the last user turn.

    Restores the working tree to the snapshot taken just before the
    most recent user message landed, truncates that message and every
    follow-up assistant / tool message from both ``state.messages``
    and the SQLite ``messages`` table, and pushes the discarded
    state onto the snapshot manager's redo stack so ``/redo`` can
    re-apply it.

    Returns a single-paragraph status string suitable for chat.  Each
    failure mode (snapshots disabled, no user turns yet, no snapshot
    recorded for this turn, git restore failed) returns a clear
    one-liner rather than raising.
    """
    mgr = agent.snapshot_manager
    if mgr is None:
        return (
            "_Snapshots are disabled — relaunch without `--no-snapshots` "
            "or set `CANTRIP_SNAPSHOTS=true` to enable `/undo` and `/redo`._"
        )

    state = agent.state
    user_idx: int | None = None
    for i in range(len(state.messages) - 1, -1, -1):
        if state.messages[i].role == Role.USER:
            user_idx = i
            break
    if user_idx is None:
        return "_Nothing to undo — no user turns yet._"

    user_msg = state.messages[user_idx]
    target_sha = user_msg.metadata.get("snapshot_sha") if user_msg.metadata else None
    if not target_sha:
        return (
            "_Cannot undo this turn — no snapshot was recorded for it. "
            "Snapshots may have been disabled or git unavailable when "
            "this turn started._"
        )

    # Snapshot the *current* working tree before resetting so any
    # mid-turn agent edits the user might want back can be redone.
    redo_sha = mgr.snapshot_turn(f"pre-undo-{user_idx}")

    paths_changed = mgr.restore(str(target_sha), direction="undo")
    if paths_changed is None:
        return f"_Failed to restore snapshot `{str(target_sha)[:8]}` — check the logs._"

    removed = list(state.messages[user_idx:])
    del state.messages[user_idx:]
    if redo_sha is not None:
        mgr.push_undone(redo_sha, removed)

    deleted = 0
    db_message_id = user_msg.metadata.get("db_message_id") if user_msg.metadata else None
    store = agent.store
    if db_message_id is not None and store is not None:
        try:
            deleted = store.delete_messages_from(int(db_message_id))
        except (ValueError, TypeError):
            log.warning("Skipping store truncate: bad db_message_id %r", db_message_id)

    parts = [
        f"Undid the last turn — restored **{paths_changed}** file(s), "
        f"removed **{len(removed)}** message(s) from history",
    ]
    if deleted:
        parts.append(f"({deleted} from the session store)")
    redo_note = " · `/redo` re-applies." if redo_sha is not None else ""
    return " ".join(parts) + "." + redo_note


def handle_redo(agent: CantripAgent) -> str:
    """Phase 68.1 ``/redo``: re-apply the most recently undone turn.

    Pops the top of the snapshot manager's redo stack, restores the
    working tree to the SHA captured at ``/undo`` time, re-appends
    the messages that were stripped, and re-records them in the
    session store (with fresh row IDs).

    Returns a single-paragraph status string.  An empty redo stack
    or a failed restore returns a clear one-liner; the redo entry
    is preserved on restore failure so the user can try again.
    """
    mgr = agent.snapshot_manager
    if mgr is None:
        return "_Snapshots are disabled — nothing to redo._"

    entry = mgr.pop_undone()
    if entry is None:
        return (
            "_Nothing to redo — the redo stack is empty.  It clears "
            "whenever a new user turn arrives._"
        )

    paths_changed = mgr.restore(entry.redo_sha, direction="redo")
    if paths_changed is None:
        # Put the entry back so a retry stays available.
        mgr.push_undone(entry.redo_sha, entry.removed_messages)
        return f"_Failed to restore snapshot `{entry.redo_sha[:8]}` — check the logs._"

    agent.state.messages.extend(entry.removed_messages)
    for msg in entry.removed_messages:
        # New IDs land in metadata so a subsequent /undo on this turn
        # finds the right rows to delete.
        agent._record_message(msg)

    return (
        f"Redid the last undo — restored **{paths_changed}** file(s), "
        f"re-added **{len(entry.removed_messages)}** message(s)."
    )


def handle_branch(agent: CantripAgent, args: str) -> str:
    """Phase 67.1 ``/branch``: rewind to a prior turn and start a new branch.

    With a turn id (``/branch 17``), moves the active head to that
    message and rebuilds ``state.messages`` so the next prompt forks
    off it.  Without an argument, picks the turn before the most
    recent user message — handy after a bad steering message: the
    user issues ``/branch`` and types a corrected instruction.

    Off-branch messages stay in the SQLite store; ``/tree`` lists
    them and re-activating any node restores that branch.  Unlike
    ``/undo`` this command never deletes rows and never touches the
    working tree.
    """
    store = agent.store
    if store is None:
        return "_No session store available — `/branch` needs a saved session._"

    target: int | None = None
    args_stripped = args.strip()
    if args_stripped:
        try:
            target = int(args_stripped)
        except ValueError:
            return f"_`/branch` expected an integer turn id, got `{args_stripped}`._"
        # Validate the target exists in this session before moving.
        all_messages = {m["id"]: m for m in store.load_messages()}
        if target not in all_messages:
            return (
                f"_Turn `{target}` not found in this session.  "
                "Run `/tree` to see the turns you can fork from._"
            )
    else:
        # Find the message before the most recent user turn.  Walk
        # the active branch from the leaf back to skip the user
        # message itself, then take its parent.
        branch = store.load_active_branch()
        last_user_idx: int | None = None
        for i in range(len(branch) - 1, -1, -1):
            if branch[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx is None:
            return "_Nothing to fork from — no user turns yet._"
        # When the first message is the user turn, forking before it
        # means an empty conversation; clearing the head matches that.
        target = None if last_user_idx == 0 else int(branch[last_user_idx - 1]["id"])

    previous_head = store.get_active_head()
    store.set_active_head(target)
    rebuilt = agent._rebuild_messages_from_active_branch()

    if target is None:
        return (
            "Forked from before the first user turn — the conversation is now empty.  "
            f"The previous branch (head `{previous_head}`) stays in the store."
        )
    return (
        f"Forked at turn `{target}` — rebuilt **{rebuilt}** message(s) on the active branch.  "
        f"The prior branch (head `{previous_head}`) is still reachable via `/tree`."
    )


@dataclasses.dataclass(frozen=True)
class TreeNode:
    """A turn rendered for the ``/tree`` view.

    ``depth`` is the indent level (root is 0); ``id`` is the message
    db row id used by ``/branch``; ``label`` is the one-line
    description shown on the row; ``on_active_branch`` lets the
    renderer mark live nodes versus historical forks.
    """

    depth: int
    id: int
    role: str
    label: str
    timestamp: str
    on_active_branch: bool


def build_tree_nodes(
    messages: list[dict[str, object]],
    active_branch_ids: set[int],
) -> list[TreeNode]:
    """Render a flat message list as a depth-first tree traversal.

    Pure function so the TUI modal can reuse the rendering rule the
    text ``/tree`` produces.  *messages* is the full row dump from
    ``SessionStore.load_messages``; *active_branch_ids* is the set
    of ids currently on the live branch (so the renderer can mark
    them).  Children are visited in id order, which matches the
    chronological order rows were recorded — newer forks appear
    later under their shared parent.
    """
    by_id: dict[int, dict[str, object]] = {}
    children: dict[int | None, list[int]] = {}
    for msg in messages:
        msg_id = msg.get("id")
        if not isinstance(msg_id, int):
            continue
        by_id[msg_id] = msg
        parent = msg.get("parent_turn_id")
        parent_key = parent if isinstance(parent, int) else None
        children.setdefault(parent_key, []).append(msg_id)
    for kids in children.values():
        kids.sort()

    nodes: list[TreeNode] = []

    def visit(node_id: int, depth: int) -> None:
        msg = by_id[node_id]
        content = str(msg.get("content") or "").splitlines()
        first_line = content[0].strip() if content else ""
        if len(first_line) > 80:
            first_line = first_line[:77] + "…"
        nodes.append(
            TreeNode(
                depth=depth,
                id=node_id,
                role=str(msg.get("role") or ""),
                label=first_line or "(empty)",
                timestamp=str(msg.get("timestamp") or ""),
                on_active_branch=node_id in active_branch_ids,
            )
        )
        for child_id in children.get(node_id, []):
            visit(child_id, depth + 1)

    for root_id in children.get(None, []):
        visit(root_id, 0)

    return nodes


def handle_tree(agent: CantripAgent, _args: str) -> str:
    """Phase 67.1 ``/tree``: render the session as a tree of turns.

    Lists every persisted turn, grouped under its parent in id order.
    Each row shows the turn id, role, a marker (``*``) for nodes on
    the active branch, the first line of the message, and the
    timestamp.  Pair with ``/branch <id>`` to fork from any node.
    The TUI surface replaces this with an interactive picker; CLI
    and Web see the text form.
    """
    store = agent.store
    if store is None:
        return "_No session store available — `/tree` needs a saved session._"

    messages = store.load_messages()
    if not messages:
        return "_No turns yet — `/tree` will populate after the first message._"

    active_ids = {m["id"] for m in store.load_active_branch()}
    nodes = build_tree_nodes(messages, active_ids)

    lines = [
        "**Session tree** — `*` marks the active branch, `/branch <id>` forks from any turn.",
        "",
    ]
    for node in nodes:
        prefix = "  " * node.depth
        marker = "*" if node.on_active_branch else " "
        timestamp = node.timestamp[:19] if node.timestamp else ""
        lines.append(
            f"{prefix}{marker} `{node.id}` **{node.role}** — {node.label}"
            + (f"  _({timestamp})_" if timestamp else "")
        )
    return "\n".join(lines)


def handle_plan(agent: CantripAgent) -> str:
    """Phase 68.4 ``/plan``: enter the read-only plan-mode gate.

    Flips ``state.plan_mode`` and publishes a ``STATUS_BAR_CHANGED``
    event so every surface (TUI, Web, CLI) can re-tint the mode
    indicator.  Returns a concise one-liner noting the allow-listed
    tools.  Already-in-plan-mode is a no-op; the status line stays
    a single, truthful sentence.
    """
    if agent.state.plan_mode:
        return "Already in plan mode.  Use `/build` to resume executing changes."
    agent.state.plan_mode = True
    # Clear any stale summary from a prior plan cycle.  ``/build``
    # will capture a new one the next time the agent produces a
    # "Proposed changes" section.
    agent.state.plan_summary = None
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="plan"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /plan")
    return (
        "**Plan mode on.**  I will read the code, Juju state, git history, "
        "and web, and produce a *Proposed changes* summary — but I won't "
        "edit files, run shells, or deploy.  Flip back with `/build`."
    )


def handle_build(agent: CantripAgent) -> str:
    """Phase 68.4 ``/build``: leave plan mode and resume executing changes.

    Flips ``state.plan_mode`` off and, when a ``plan_summary`` was
    captured while planning, re-sends it as an assistant-role prelude
    so the agent picks the next turn up with the *Proposed changes*
    section already in scope.  Without a captured summary we just
    note the mode switch.
    """
    if not agent.state.plan_mode:
        return "Already in build mode — every tool is available."
    agent.state.plan_mode = False
    resume_note = ""
    if agent.state.plan_summary:
        # Drop the summary into ``state.messages`` so the next user
        # message sees it in the LLM's context.  We tag the role as
        # ASSISTANT so the LLM treats it as its own prior output and
        # builds on it rather than re-planning from scratch.
        agent.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=f"## Proposed changes (from plan mode)\n\n{agent.state.plan_summary}",
            )
        )
        resume_note = (
            "  Resumed the plan's *Proposed changes* section as context — "
            "the next turn will execute against it."
        )
        agent.state.plan_summary = None
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="build"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /build")
    return f"**Build mode on.**  Every tool is available again.{resume_note}"


def handle_architect(agent: CantripAgent, args: str) -> str:
    """Phase 71.2 ``/architect``: toggle architect/editor two-model split.

    Bare ``/architect`` flips the flag; ``/architect on`` and
    ``/architect off`` are explicit forms.  An optional second token
    sets the editor provider/model in the same syntax as ``/model``
    (``provider`` or ``provider/model``).  When toggled on without
    an explicit editor, ``resolve_light_provider`` picks a same-
    family cheaper variant.  When no lighter variant exists the
    editor falls back to the main provider (no cost saving but the
    dual-pass shape stays).

    Examples::

        /architect              # toggle on/off
        /architect on           # enable
        /architect on claude/claude-haiku-4-5-20251001
        /architect off
    """
    tokens = args.strip().split(maxsplit=1)
    if not tokens:
        target = not agent.state.architect_mode
        editor_spec = ""
    else:
        first = tokens[0].lower()
        if first in {"on", "enable", "true", "1"}:
            target = True
        elif first in {"off", "disable", "false", "0"}:
            target = False
        else:
            return (
                "Usage: `/architect` toggles, `/architect on` enables, "
                "`/architect off` disables.  An optional second token "
                "(`provider` or `provider/model`) overrides the editor."
            )
        editor_spec = tokens[1].strip() if len(tokens) > 1 else ""

    if editor_spec and not target:
        return "_Editor override only makes sense with `/architect on`._"

    if editor_spec:
        provider_name, _, model_slug = editor_spec.partition("/")
        provider_name = provider_name.strip()
        model_slug = model_slug.strip() or None
        if provider_name not in _MODEL_SWITCH_PROVIDERS:
            return (
                f"Unknown editor provider `{provider_name}`.  Known "
                f"providers: `{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`."
            )
        agent.state.editor_provider = provider_name
        agent.state.editor_model = model_slug

    if target == agent.state.architect_mode and not editor_spec:
        return (
            f"Architect mode is already {'on' if target else 'off'}.  Bare `/architect` toggles."
        )

    agent.state.architect_mode = target
    agent.state.architect_consecutive_failures = 0
    if not target:
        # Drop any explicit editor override on disable so the next
        # enable starts from the same-family default.
        agent.state.editor_provider = None
        agent.state.editor_model = None

    try:
        agent.event_bus.publish(
            ui_events.status_bar_changed(mode="architect" if target else "build")
        )
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /architect")

    if not target:
        return "**Architect mode off.**  Single-model conversation resumed."

    editor_label = _describe_editor(agent)
    return (
        f"**Architect mode on.**  Architect: "
        f"`{agent.provider.name}/{agent.provider.model_name}` — "
        f"Editor: `{editor_label}`.  Each turn now runs as "
        "*propose → edit*; both passes appear separately in `/cost`."
    )


def _describe_editor(agent: CantripAgent) -> str:
    """One-line label for the current editor provider/model.

    Reads ``state.editor_provider`` / ``editor_model`` first; falls
    back to the resolved light provider when no explicit override is
    set; falls back to the main provider when no lighter variant
    exists either (the no-saving case).
    """
    if agent.state.editor_provider:
        slug = agent.state.editor_model or "<default>"
        return f"{agent.state.editor_provider}/{slug}"
    light = getattr(agent, "_light_provider", None)
    if light is not None:
        return f"{light.name}/{light.model_name}"
    return f"{agent.provider.name}/{agent.provider.model_name}"


def handle_auto_commit(agent: CantripAgent, args: str) -> str:
    """Phase 71.3 ``/auto-commit``: toggle per-turn auto-commit.

    Bare ``/auto-commit`` flips the flag; ``/auto-commit on`` and
    ``/auto-commit off`` are explicit.  When on, every turn that
    mutates files lands as a discrete git commit with a Cantrip
    co-author trailer; pre-existing dirty work commits separately
    as ``chore(pre-cantrip): save in-progress work``.

    The toggle is sticky for the session and not persisted; restart
    Cantrip with ``--no-auto-commit`` to start fresh sessions with
    auto-commit disabled.
    """
    token = args.strip().lower()
    if token in {"on", "enable", "true", "1"}:
        target = True
    elif token in {"off", "disable", "false", "0"}:
        target = False
    elif token == "":
        target = not agent.state.git_auto_commit
    else:
        return (
            "Usage: `/auto-commit` toggles, `/auto-commit on` enables, "
            "`/auto-commit off` disables."
        )

    if target == agent.state.git_auto_commit:
        return f"Auto-commit is already {'on' if target else 'off'}."

    agent.state.git_auto_commit = target
    if target:
        return (
            "**Auto-commit on.**  Every turn that touches files will "
            "land as a discrete git commit with a Cantrip co-author "
            "trailer; pre-existing dirty work commits first."
        )
    return (
        "**Auto-commit off.**  Agent edits stay in the working tree and you choose when to commit."
    )


def handle_yolo(agent: CantripAgent, args: str) -> str:
    """Phase 69.2 ``/yolo``: toggle unattended auto-approve mode.

    Bare ``/yolo`` flips the flag.  ``/yolo on`` and ``/yolo off``
    are explicit forms used by scripts and by operators who want to
    be sure which state they are heading into.  Any other argument
    is rejected with a usage line to prevent typos like
    ``/yolo yes`` from being silently interpreted.

    Syncs the flag onto the executor's ``PermissionManager`` when
    one is running so existing pending asks either resolve (on) or
    stop auto-approving (off).  Publishes a
    ``STATUS_BAR_CHANGED`` event with ``mode=yolo|build`` so every
    surface repaints its banner in lockstep.
    """
    token = args.strip().lower()
    if token in {"on", "enable", "true", "1"}:
        target = True
    elif token in {"off", "disable", "false", "0"}:
        target = False
    elif token == "":
        target = not agent.state.yolo_mode
    else:
        return "Usage: `/yolo` toggles, `/yolo on` enables, `/yolo off` disables."

    if target == agent.state.yolo_mode:
        state_text = "on" if target else "off"
        return f"Already in yolo mode {state_text}."

    agent.state.yolo_mode = target
    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is not None:
        try:
            executor_ctl.set_yolo(target)
        except AttributeError:
            log.debug("executor_ctl has no set_yolo method", exc_info=True)

    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="yolo" if target else "build"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /yolo")

    if target:
        return (
            "**Yolo mode on.**  Every `ask` permission auto-approves "
            "for the rest of this session.  `deny` rules still block — "
            "review your `permissions.yaml` before a destructive run.  "
            "Flip back with `/yolo off`."
        )
    return "**Yolo mode off.**  `ask` rules prompt again as usual."


def handle_pause(agent: CantripAgent, args: str) -> str:
    """Phase 99.1 ``/pause``: stop the autonomous loop picking new tasks.

    The flag is sticky: chat keeps working and any CONFIRM task already
    in flight continues to completion, but no new background tasks are
    dispatched until the user runs ``/resume``.  Bare ``/pause`` is the
    only accepted form — ``on``/``off`` arguments would just duplicate
    the ``/resume`` verb.
    """
    if args.strip():
        return "Usage: `/pause` takes no arguments — use `/resume` to restart the loop."

    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is None or not hasattr(executor_ctl, "user_pause"):
        return "Background executor is not available — nothing to pause."

    changed = executor_ctl.user_pause()
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(loop_state="paused"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /pause")

    if not changed:
        return "Already paused.  Use `/resume` to restart the autonomous loop."
    return (
        "**Autonomous loop paused.**  Chat and CONFIRM tasks keep working; "
        "no new background tasks will start until you run `/resume`."
    )


def handle_resume(agent: CantripAgent, args: str) -> str:
    """Phase 99.1 ``/resume``: restart a paused autonomous loop."""
    if args.strip():
        return "Usage: `/resume` takes no arguments — use `/pause` to stop the loop."

    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is None or not hasattr(executor_ctl, "user_resume"):
        return "Background executor is not available — nothing to resume."

    changed = executor_ctl.user_resume()
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(loop_state="running"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /resume")

    if not changed:
        return "Already running.  Use `/pause` to stop the autonomous loop."
    return "**Autonomous loop resumed.**  Background tasks pick up where they left off."


def handle_ralph(agent: CantripAgent, args: str) -> str:
    """Phase 69.1 ``/ralph N``: enable the bounded iterate-until-green loop.

    Stamps ``state.ralph_max_iterations`` on the agent so the next
    print-mode invocation (or future TUI integration) picks it up.
    Bare ``/ralph`` reports the current setting.  ``/ralph off``
    or ``/ralph 0`` disables.  Any positive integer is the new cap;
    ``-1`` is unlimited.

    Mid-session in the TUI the flag is informational — the actual
    refinement loop only fires inside ``cantrip run --print``
    (where there's no human to drive iteration manually).  We still
    accept the slash command in the TUI so a session can record
    its intended Ralph cap for later or to flip the audit-trail
    flag explicitly.
    """
    token = args.strip().lower()
    current = agent.state.ralph_max_iterations
    if token == "":
        if current == 0:
            return (
                "Ralph loop is **off**.  Run `/ralph N` to set a cap, or "
                "`cantrip run --ralph N --print '<goal>'` for unattended "
                "refinement."
            )
        if current < 0:
            return "Ralph loop is **on** with no iteration cap (`-1` = unlimited)."
        return f"Ralph loop is **on** with a cap of {current} iteration(s)."

    if token in {"off", "disable", "false", "0"}:
        new_value = 0
    else:
        try:
            new_value = int(token)
        except ValueError:
            return (
                "Usage: `/ralph` shows the cap, `/ralph N` sets it, "
                "`/ralph off` or `/ralph 0` disables, `/ralph -1` is "
                "unlimited."
            )

    agent.state.ralph_max_iterations = new_value

    if new_value == 0:
        return "**Ralph loop off.**  Single-shot runs only."
    if new_value < 0:
        return (
            "**Ralph loop on (unlimited).**  Loop until the agent emits "
            "`STOP` or stall detection trips.  Bounded internally by a "
            "safety ceiling so a stuck agent can't run forever."
        )
    return (
        f"**Ralph loop on, cap = {new_value}.**  Re-feeds the goal up to "
        f"{new_value} time(s) until the agent emits `STOP` on its own "
        "line."
    )


def _handle_review(agent: CantripAgent, args: str) -> SlashResult:
    """``/review``: run all loaded prompt-based checks against the charm.

    Each check is one structured LLM call (Phase 70.4); results are
    aggregated into a single Markdown report.  When the active charm
    also has linter diagnostics (Phase 72.4 ruff/ty/charmlint), they
    appear underneath as a deterministic-checks section so the user
    sees one combined view.

    ``args`` is reserved for future filters (severity, name pattern);
    today an unknown arg returns a usage hint rather than silently
    ignoring it so the user doesn't think their filter ran.
    """
    from cantrip.agent import checks, lint_context

    if args.strip():
        return SlashResult(
            text=(
                "**Usage:** ``/review`` — runs every loaded check.  "
                "Per-check filters are not implemented yet."
            ),
            markdown=True,
        )

    charm_path = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(
            text=(
                "**Cannot run /review:** no charm path for this session.  "
                "Open a charm with the CLI and try again."
            ),
            markdown=True,
        )

    provider = getattr(agent, "provider", None)
    if provider is None:
        return SlashResult(
            text="**Cannot run /review:** no LLM provider attached to this agent.",
            markdown=True,
        )

    charm_root = pathlib.Path(charm_path)

    async def _run() -> str:
        index = checks.CheckIndex(project_root=charm_root)
        discovered = index.discover()
        if not discovered and not index.shadows:
            return (
                "_No checks configured._  Drop a markdown file under "
                "``.cantrip/checks/`` (repo) or "
                "``~/.config/cantrip/checks/`` (user) to add one — "
                "see ``design/CHECKS.md`` for the schema."
            )
        report = await checks.run_all_checks(
            discovered,
            provider=provider,
            charm_root=charm_root,
            shadows=index.shadows,
        )
        sections = [report.to_text()]
        diag = await lint_context.gather_project_diagnostics(charm_root)
        if not diag.is_empty():
            sections.append("---")
            sections.append(diag.to_text(header="Deterministic checks"))
        return "\n\n".join(sections)

    prelude = "Running review checks…"
    return SlashResult(text=prelude, followup=_run(), markdown=True)


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
    from cantrip.agent import lint_context

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


def _handle_copy(agent: CantripAgent, args: str) -> SlashResult:
    """Copy a single chat message to the system clipboard (Phase 76).

    With no argument, picks the most recent assistant message.
    With ``last`` (any role), picks the most recent message regardless
    of role.  With a positive integer ``N``, picks the N-th message in
    1-based session order (useful when the user can see the index in
    an export but not in the live chat -- ``/export markdown`` to
    cross-reference).

    Returns a :class:`SlashResult` whose ``text`` is a one-line
    confirmation and whose ``clipboard_text`` carries the rendered
    Markdown for the surface to put on the user's clipboard.  Falls
    back to embedding the body in ``text`` when copy is not viable
    (no charm path, no messages) so the user still sees an
    actionable response.
    """
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot copy: no charm path for this session._")
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return SlashResult(text=f"_Cannot copy: no `.cantrip` file at {charm_path}._")

    # Lazy import: keeps the slash module importable even when the
    # transcript renderers' optional deps are unusual.
    from cantrip.transcript import export as transcript_export
    from cantrip.transcript.markdown import render_message

    data = transcript_export.load_transcript(db_path)
    messages = data.messages
    if not messages:
        return SlashResult(text="_Nothing to copy: this session has no messages yet._")

    selector = args.strip().lower()
    target: dict | None = None
    label: str
    if selector in ("", "assistant"):
        target = next(
            (m for m in reversed(messages) if (m.get("role") or "").lower() == "assistant"),
            None,
        )
        if target is None:
            # Fall back to the most recent message of any role rather
            # than refusing — when the agent's first turn errors out
            # before producing an assistant message, the user still
            # sees content on screen and reasonably expects /copy to
            # capture *something*.  The label makes the role explicit
            # so it's clear what landed on the clipboard.
            if selector == "assistant":
                return SlashResult(
                    text="_Nothing to copy: no assistant messages in this session yet._"
                )
            target = messages[-1]
            role = (target.get("role") or "message").lower()
            label = f"last {role} message (no assistant messages yet)"
        else:
            label = "last assistant message"
    elif selector == "last":
        target = messages[-1]
        role = (target.get("role") or "message").lower()
        label = f"last {role} message"
    else:
        try:
            index = int(selector)
        except ValueError:
            return SlashResult(
                text=(
                    "_Usage: `/copy` (last assistant message), `/copy last` "
                    "(last message of any role), or `/copy <N>` (1-based "
                    "message index)._"
                )
            )
        if index < 1 or index > len(messages):
            return SlashResult(
                text=f"_Cannot copy: message index {index} out of range (1..{len(messages)})._"
            )
        target = messages[index - 1]
        label = f"message #{index} ({(target.get('role') or 'unknown').lower()})"

    body = render_message(target, include_header=False).strip()
    if not body:
        return SlashResult(text=f"_Nothing to copy: the {label} has no body._")

    return SlashResult(
        text=f"Copied {label} to clipboard ({len(body)} chars).",
        clipboard_text=body,
    )


def _handle_share(agent: CantripAgent) -> SlashResult:
    """Dispatch the ``/share`` slash command.

    Returns an immediate "Uploading..." prelude plus a followup that
    exports the HTML transcript, uploads it as a secret gist via
    ``gh gist create``, and resolves to the gist URL.  When ``gh`` is
    unavailable we still want the user to have *something* useful —
    the followup writes the export locally and returns a
    copy-pasteable ``gh gist create`` command.
    """
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot share: no charm path for this session._")
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        return SlashResult(text=f"_Cannot share: no `.cantrip` file at {charm_path}._")

    return SlashResult(
        text="Uploading session as a secret gist…",
        followup=share_to_gist(db_path, charm_path),
    )


# ---------------------------------------------------------------------------
# Phase 70.1 — /search-charms slash command
# ---------------------------------------------------------------------------


def _handle_search_charms(args: str) -> SlashResult:
    """Dispatch the ``/search-charms`` slash command.

    Returns an immediate "searching…" prelude plus a followup that
    queries Charmhub and Launchpad in parallel and renders both
    result blocks together as Markdown.  Cheap — no source fetch is
    triggered from the slash; the agent invokes ``charmhub_fetch``
    / ``launchpad_fetch`` if it needs to read source.
    """
    query = args.strip()
    if not query:
        return SlashResult(
            text=(
                "Usage: ``/search-charms <query>`` — searches Charmhub and "
                "Launchpad for existing charms or projects matching *query*."
            )
        )
    return SlashResult(
        text=f"Searching Charmhub and Launchpad for `{query}`…",
        followup=_run_search_charms(query),
        markdown=True,
    )


async def _run_search_charms(query: str) -> str:
    """Query Charmhub + Launchpad concurrently; render combined Markdown."""
    # Late imports keep the slash module's cold-start cheap when the
    # user never reaches for the Librarian.
    from cantrip.agent.tools.charmhub import CharmhubSearchTool
    from cantrip.agent.tools.launchpad import LaunchpadSearchTool

    charmhub_tool = CharmhubSearchTool()
    launchpad_tool = LaunchpadSearchTool()

    charmhub_result, launchpad_result = await asyncio.gather(
        charmhub_tool.execute(query=query),
        launchpad_tool.execute(query=query),
        return_exceptions=False,
    )

    sections: list[str] = [f"# Charm-library search: `{query}`", ""]

    sections.append("## Charmhub")
    if charmhub_result.success:
        sections.append(charmhub_result.output or "_No results._")
    else:
        sections.append(f"_Charmhub search failed: {charmhub_result.error}_")
    sections.append("")

    sections.append("## Launchpad")
    if launchpad_result.success:
        sections.append(launchpad_result.output or "_No results._")
    else:
        sections.append(f"_Launchpad search failed: {launchpad_result.error}_")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Phase 70.5 — /icon slash command (Painter)
# ---------------------------------------------------------------------------


def _handle_icon(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch the ``/icon`` slash command.

    Returns an immediate "painting…" prelude plus a followup that
    invokes :class:`CharmIconGenerateTool` against the active charm
    path and renders the per-call cost summary.  Cheap edge cases
    (missing charm path, empty description) short-circuit before
    spawning any image-provider call.
    """
    description = args.strip()
    if not description:
        return SlashResult(
            text=(
                "Usage: ``/icon <one-line workload description>`` — "
                "generates a Charmhub-style icon.svg for the active "
                "charm using the configured image provider (default: "
                "Imagen).  Example: ``/icon a Postgres database "
                "operator``."
            )
        )
    charm_path: pathlib.Path | None = getattr(agent.state, "charm_path", None)
    if charm_path is None:
        return SlashResult(text="_Cannot paint icon: no charm path for this session._")
    if not pathlib.Path(charm_path).is_dir():
        return SlashResult(text=f"_Charm path does not exist: {charm_path}._")
    return SlashResult(
        text=f"Painting icon.svg for `{description}`…",
        followup=_run_icon(agent, description, str(charm_path)),
        markdown=True,
    )


async def _run_icon(agent: CantripAgent, description: str, charm_path: str) -> str:
    """Invoke the Painter tool and render the result as Markdown."""
    # Late import keeps the dispatcher cheap when the user never
    # reaches for the Painter.
    from cantrip.agent.tools.icon import CharmIconGenerateTool

    tool = CharmIconGenerateTool(
        state=agent.state,
        store_getter=lambda: getattr(agent, "_store", None),
    )
    result = await tool.execute(description=description, path=charm_path)
    if not result.success:
        return f"_Painter failed: {result.error}_"
    return result.output


__all__ = [
    "COMMAND_CATALOGUE",
    "CommandInfo",
    "SHARED_VERBS",
    "SlashResult",
    "dispatch",
    "export_transcript",
    "format_cost",
    "TreeNode",
    "build_tree_nodes",
    "handle_branch",
    "handle_redo",
    "handle_tree",
    "handle_undo",
    "help_text",
]
