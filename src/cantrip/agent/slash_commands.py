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
from cantrip.agent import mcp_commands, memory_commands, sandbox
from cantrip.llm import pricing
from cantrip.llm.base import ProviderError

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
    CommandInfo("/arena", "Blind A/B compare two models"),
    CommandInfo("/model", "Show or switch the active model"),
    CommandInfo("/export", "Export the live session transcript"),
    CommandInfo("/share", "Upload the session as a secret GitHub gist"),
    CommandInfo("/update", "Check PyPI for a newer release"),
    CommandInfo("/sandbox", "Show subprocess sandbox status"),
    CommandInfo("/hooks", "List configured hooks and invocation stats"),
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
    if verb in {"/quit", "/exit"}:
        return SlashResult(text="Goodbye!", quit=True)
    return None


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
        "- `/quit`, `/exit` — leave cantrip cleanly."
    )


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
    "help_text",
]
