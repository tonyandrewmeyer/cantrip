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
import datetime
import logging
import pathlib
import shlex
import shutil
import tempfile
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cantrip import update as update_module
from cantrip.agent import custom_commands, mcp_commands, memory_commands, sandbox
from cantrip.agent.goal_budget import GoalBudget, format_summary, measure_usage
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.llm import pricing
from cantrip.llm.base import Message, ProviderError, Role
from cantrip.ui import events as ui_events

log = logging.getLogger(__name__)

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
    CommandInfo("/budget", "Show or raise the per-goal iteration / token budget"),
    CommandInfo("/arena", "Blind A/B compare two models"),
    CommandInfo("/model", "Show or switch the active model"),
    CommandInfo("/export", "Export the live session transcript"),
    CommandInfo("/share", "Upload the session as a secret GitHub gist"),
    CommandInfo("/update", "Check PyPI for a newer release"),
    CommandInfo("/sandbox", "Show subprocess sandbox status"),
    CommandInfo("/hooks", "List configured hooks and invocation stats"),
    CommandInfo("/undo", "Roll back the last user turn (files + messages)"),
    CommandInfo("/redo", "Re-apply the most recently undone turn"),
    CommandInfo("/plan", "Enter read-only plan mode (no file edits or shells)"),
    CommandInfo("/build", "Leave plan mode and resume executing changes"),
    CommandInfo("/yolo", "Toggle unattended mode — auto-approve every ask"),
    CommandInfo("/ralph", "Run a bounded iterate-until-green loop (Ralph)"),
    CommandInfo("/map", "Show the graph-ranked repository symbol map"),
    CommandInfo("/map-refresh", "Force a rebuild of the repository symbol map"),
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
        return SlashResult(text=format_cost(agent))
    if verb == "/budget":
        return SlashResult(text=_handle_budget(agent, args))
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
    if verb == "/plan":
        return SlashResult(text=handle_plan(agent))
    if verb == "/build":
        return SlashResult(text=handle_build(agent))
    if verb == "/yolo":
        return SlashResult(text=handle_yolo(agent, args))
    if verb == "/ralph":
        return SlashResult(text=handle_ralph(agent, args))
    if verb == "/map":
        return SlashResult(text=handle_map(agent))
    if verb == "/map-refresh":
        return SlashResult(text=handle_map_refresh(agent))
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


def _handle_budget(agent: CantripAgent, args: str) -> str:
    """Phase 55.3: show or raise the per-goal budget.

    ``/budget`` with no args prints current usage against the cap.
    ``/budget --max-iterations N`` sets or raises the iteration cap.
    ``/budget --max-prompt-tokens N`` / ``--max-completion-tokens N``
    set the equivalent token caps.  ``/budget --clear`` drops the
    budget entirely so the autonomous loop runs uncapped again.
    When a cap is raised, previously blocked tasks are moved back to
    pending so the executor picks them up on the next poll.
    """
    tokens = args.split()
    state = agent.state

    # Raise / clear path.
    if tokens:
        if tokens[0] == "--clear":
            state.goal_budget = None
            _unblock_budget_tasks(agent)
            return "Goal budget cleared.  Autonomous work is now uncapped."

        flag = tokens[0]
        if flag not in ("--max-iterations", "--max-prompt-tokens", "--max-completion-tokens"):
            return (
                "Usage: ``/budget`` (show) / "
                "``/budget --max-iterations N`` / "
                "``/budget --max-prompt-tokens N`` / "
                "``/budget --max-completion-tokens N`` / "
                "``/budget --clear``."
            )
        if len(tokens) != 2:
            return f"Usage: ``/budget {flag} N``"
        try:
            value = int(tokens[1])
        except ValueError:
            return f"Cap must be an integer: {tokens[1]!r}"
        if value < 0:
            return f"Cap must be >= 0: {value}"

        if state.goal_budget is None:
            state.goal_budget = GoalBudget()
        if flag == "--max-iterations":
            state.goal_budget.max_iterations = value
        elif flag == "--max-prompt-tokens":
            state.goal_budget.max_prompt_tokens = value
        else:
            state.goal_budget.max_completion_tokens = value

        _unblock_budget_tasks(agent)
        return f"Goal budget updated.  {_format_budget_summary(agent)}"

    return _format_budget_summary(agent)


def _format_budget_summary(agent: CantripAgent) -> str:
    """Return the one-line "used / cap" summary for the chat."""
    state = agent.state
    if state.goal_budget is None:
        return (
            "No goal budget set.  Set a cap with ``/budget --max-iterations N`` "
            "or ``/budget --max-tokens N`` to add a hard stop."
        )
    store = agent.store
    if store is None:
        return (
            f"Goal budget set (iterations={state.goal_budget.max_iterations}, "
            f"prompt={state.goal_budget.max_prompt_tokens}, "
            f"completion={state.goal_budget.max_completion_tokens}).  Usage "
            "unavailable until the store opens."
        )
    usage = measure_usage(store, state.goal_budget)
    return format_summary(state.goal_budget, usage)


def _unblock_budget_tasks(agent: CantripAgent) -> None:
    """Move every budget-blocked task back to pending.

    Called after a cap is raised or cleared — the executor's next
    poll will re-evaluate them against the new budget.  Tasks
    blocked for any other reason stay put.
    """
    queue = agent.work_queue
    for task in queue.all_tasks():
        reason = task.blocked_reason or ""
        if task.status.value == "blocked" and "Goal budget exceeded" in reason:
            queue.set_pending(task.id)


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
    {"gemini", "claude", "fireworks", "openrouter", "inference-snap"}
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
        "- `/plan` — enter read-only plan mode.  The agent can "
        "inspect files, git history, Juju state, and the web, but "
        "cannot edit or run shells.\n"
        "- `/build` — leave plan mode and resume executing changes."
        "  Re-feeds the last *Proposed changes* summary as context.\n"
        "- `/yolo [on|off]` — toggle unattended mode: every `ask` "
        "permission auto-approves for the rest of the session.  "
        "`deny` rules still block.  `--yolo` on the command line "
        "enables it at startup.\n"
        "- `/ralph [N|off]` — bounded iterate-until-green loop "
        "(Ralph).  Re-feeds the goal up to N times until the agent "
        "emits `STOP` or stall detection trips.  Engages inside "
        "`cantrip run --print --ralph N`.\n"
        "- `/map` — print the graph-ranked repository symbol map.  "
        "The same view the agent sees on every turn.\n"
        "- `/map-refresh` — force a full rebuild of the repo-map "
        "cache (`.cantrip/repomap.json`) and reprint it.\n"
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

    # Phase 52.6: tokens avoided via step-checkpoint replay.  These are
    # billed zero this session (the live provider never fired) but the
    # sum is worth showing so the user can see the cost-savings headroom
    # the durable-execution machinery bought them.
    savings = store.get_replay_savings()
    saved_total = savings["prompt_tokens"] + savings["completion_tokens"]
    if saved_total:
        lines.append(
            f"- Cached from checkpoint: {saved_total:,} tokens "
            f"({savings['prompt_tokens']:,} prompt, "
            f"{savings['completion_tokens']:,} completion, "
            f"{savings['request_count']} replayed turn(s))"
        )

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

    # Per-category breakdown (Phase 31.4) — aggregate across models so a
    # category row sums every subagent that ran under it.  Cache cost is
    # global (not category-attributed) so it stays out of this table.
    by_cat = store.get_usage_by_category()
    if by_cat:
        cat_totals: dict[str, tuple[int, float, int]] = {}
        for row in by_cat:
            cat = str(row.get("category", "conversation"))
            prompt_t = int(row.get("prompt_tokens", 0) or 0)
            completion_t = int(row.get("completion_tokens", 0) or 0)
            reqs = int(row.get("request_count", 0) or 0)
            cost = pricing.estimate_cost(
                str(row.get("model", "")),
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
            )
            tokens, running_cost, running_reqs = cat_totals.get(cat, (0, 0.0, 0))
            cat_totals[cat] = (
                tokens + prompt_t + completion_t,
                running_cost + cost,
                running_reqs + reqs,
            )
        lines.append("")
        lines.append("**By category**")
        for cat in sorted(cat_totals):
            tokens, cat_cost, reqs = cat_totals[cat]
            cost_str = pricing.format_cost(cat_cost) if cat_cost > 0 else "free"
            lines.append(f"- {cat}: {tokens:,} tokens, {reqs} requests, {cost_str}")

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
    executor = getattr(agent, "executor", None)
    if executor is not None:
        try:
            executor.set_yolo(target)
        except AttributeError:
            log.debug("executor has no set_yolo method", exc_info=True)

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


def _format_map_response(headline: str, rendered: str, file_count: int) -> str:
    """Build a chat-safe response for the /map family of slash commands.

    System messages render the body as Rich markup (``MessageWidget``
    in ``cantrip.tui.widgets.chat``).  Bracketed tokens like
    ``[relation]`` and Python type annotations like ``list[int]``
    look like Rich style tags, so without escaping they would either
    be silently stripped (best case) or trigger a ``MarkupError``
    that crashes the surface (worst case).  ``rich.markup.escape``
    rewrites ``[`` as ``\\[`` so every bracket renders verbatim.
    """
    from rich.markup import escape as rich_escape

    safe = rich_escape(rendered)
    return f"**{headline}** ({file_count} files)\n\n```\n{safe}\n```"


def handle_map(agent: CantripAgent) -> str:
    """``/map``: print the graph-ranked symbol map.

    Shows the same view the agent receives on every turn (sized at
    the full configured budget — context-pressure shrinking only
    applies to the in-prompt copy).  Failures are reported in-line
    so the slash command can never crash the surface.
    """
    rm = agent.repo_map
    if rm is None:
        return (
            "No repository map: this session has no active charm path.  "
            "Open a charm and try again, or set the path with the CLI."
        )
    try:
        rm.build()
        rendered = rm.render_full()
    except Exception as exc:  # noqa: BLE001 — surface, don't crash.
        log.warning("/map build failed: %s", exc, exc_info=True)
        return f"Repository map build failed: {type(exc).__name__}: {exc}"
    if not rendered:
        return (
            "Repository map is empty — no parseable Python or charm "
            "metadata found under the active charm path."
        )
    return _format_map_response("Repository map", rendered, len(rm.rankings))


def handle_map_refresh(agent: CantripAgent) -> str:
    """``/map-refresh``: discard cache and reparse everything."""
    rm = agent.repo_map
    if rm is None:
        return "No repository map: this session has no active charm path."
    try:
        rendered = agent.refresh_repo_map()
    except Exception as exc:  # noqa: BLE001 — surface, don't crash.
        log.warning("/map-refresh failed: %s", exc, exc_info=True)
        return f"Repository map rebuild failed: {type(exc).__name__}: {exc}"
    if not rendered:
        return "Repository map rebuilt — no parseable files found under the active charm path."
    return _format_map_response("Repository map rebuilt", rendered, len(rm.rankings))


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
        followup=_run_share_to_gist(db_path, charm_path),
    )


async def _run_share_to_gist(db_path: pathlib.Path, charm_path: pathlib.Path) -> str:
    """Export to HTML and upload via ``gh gist create``.

    On ``gh`` absence or auth failure, write the HTML locally and
    return a message containing the path + the exact ``gh`` command
    the user can run manually.  The session is never blocked — every
    error path returns a human-readable string.
    """
    # Import lazily so the slash module stays importable even when the
    # renderer's optional deps are unusual.
    from cantrip.transcript import export as transcript_export
    from cantrip.transcript.html import render_html

    try:
        data = transcript_export.load_transcript(db_path)
        content = render_html(data)
    except (OSError, ValueError, RuntimeError) as exc:
        return f"_Failed to render transcript: {exc}._"

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    charm_name = charm_path.name or "cantrip"
    description = f"Cantrip session — {charm_name} — {timestamp}"

    # Write into a tempfile the subprocess call can read.  Use the
    # charm name as a prefix so the gist's default filename is
    # discoverable rather than being a random hex string.
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"cantrip-session-{charm_name}-",
            suffix=".html",
            delete=False,
        ) as tmp:
            tmp.write(content.encode("utf-8"))
            tmp_path = pathlib.Path(tmp.name)
    except OSError as exc:
        return f"_Failed to write temp transcript: {exc}._"

    if not shutil.which("gh"):
        return (
            f"`gh` is not installed — transcript written to `{tmp_path}`.\n\n"
            f"Install GitHub CLI and run:\n\n"
            f"```\ngh gist create --desc {shlex.quote(description)} {shlex.quote(str(tmp_path))}\n```"
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "gist",
            "create",
            "--desc",
            description,
            str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
    except (OSError, FileNotFoundError) as exc:
        return (
            f"_Failed to launch `gh`: {exc}._ Transcript written to "
            f"`{tmp_path}` — upload manually with the `gh gist create` "
            f"command."
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        # gh auth status failure is the common case — the stderr
        # carries the hint, so surface it verbatim.
        hint = stderr or f"`gh` exited with code {proc.returncode}"
        return (
            f"_Failed to upload gist: {hint}._ Transcript written to "
            f"`{tmp_path}` — run `gh auth login` and retry with:\n\n"
            f"```\ngh gist create --desc {shlex.quote(description)} {shlex.quote(str(tmp_path))}\n```"
        )

    # ``gh gist create`` prints the URL on the last non-empty stdout
    # line; older versions include a progress preamble.
    url = next(
        (line for line in reversed(stdout.splitlines()) if line.strip().startswith("http")),
        "",
    )
    if not url:
        return (
            f"Uploaded, but could not parse a URL from `gh` output. "
            f"Raw output:\n\n```\n{stdout}\n```"
        )

    # Clean up the local tempfile now that the gist is live — leaving
    # it behind would gradually fill /tmp and the user has the URL.
    try:
        tmp_path.unlink()
    except OSError:
        log.debug("Failed to unlink temp transcript %s", tmp_path, exc_info=True)

    return f"Shared session as a secret gist: {url}"


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
    "handle_redo",
    "handle_undo",
    "help_text",
]
