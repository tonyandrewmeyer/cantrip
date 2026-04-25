"""CLI mode for Cantrip (no TUI)."""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence

from cantrip import notifications, update
from cantrip.agent import slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.agent.queue import TaskStatus
from cantrip.hooks import HookRunner
from cantrip.llm import create_provider, pricing, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError
from cantrip.ui import events as ui_events

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Maximum time to wait for the background executor to finish before exiting.
_DRAIN_TIMEOUT_SECONDS = 60

_STATUS_ICONS = {
    CheckStatus.PENDING: "○",
    CheckStatus.RUNNING: "⟳",
    CheckStatus.PASSED: "✓",
    CheckStatus.FAILED: "✗",
    CheckStatus.SKIPPED: "–",
}

_TASK_STATUS_ICONS = {
    TaskStatus.PENDING: "○",
    TaskStatus.ACTIVE: "⟳",
    TaskStatus.DONE: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.BLOCKED: "◌",
}

_HELP_TEXT = """\
Available commands:
  /help, ?        Show this help message
  /tasks          Show current task status
  /status         Show Juju model status
  /cost           Show token usage summary
  /memory [scope] List memories (run `/memory help` for subcommands)
  /remember …     Write a memory (`<kind> [scope] -- <title> -- <body>`)
  /forget <title> Delete a memory by title
  /mcp            List configured MCP servers (run `/mcp help` for subcommands)
  /update         Check PyPI for a newer release (`--no-check` / `--check` toggle auto-check)
  exit, quit      Exit Cantrip
"""


# CLI-native verbs that live outside the shared dispatcher — ``/tasks`` and
# ``/status`` render Rich tables and so can't flow through ``slash_commands``.
_CLI_ONLY_VERBS: tuple[str, ...] = ("/tasks", "/status")


def _cli_slash_verbs() -> tuple[str, ...]:
    """Return every slash verb the CLI REPL accepts, sorted for display.

    Drives Tab-completion — verbs surface in the order Python's
    :mod:`readline` cycles through them.  Aliases (``?``) are excluded
    because readline treats them as independent tokens anyway.
    """
    shared = tuple(cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE)
    return tuple(sorted({*shared, *_CLI_ONLY_VERBS}, key=str.lower))


def _make_slash_completer(
    verbs: Sequence[str],
) -> Callable[[str, int], str | None]:
    """Return a :mod:`readline`-compatible completer for slash verbs.

    readline invokes the completer repeatedly — ``(text, 0)`` for the
    first completion, ``(text, 1)`` for the next, and so on until the
    callable returns ``None``.  We return the Nth catalogue verb whose
    prefix (case-insensitively) matches *text*, which is exactly what
    readline wants.  Non-slash tokens return ``None`` straight away so
    the default filename completion doesn't kick in on plain chat text.
    """
    frozen = tuple(verbs)

    def _completer(text: str, state: int) -> str | None:
        if not text.startswith("/"):
            return None
        prefix = text.lower()
        matches = [v for v in frozen if v.lower().startswith(prefix)]
        if state < 0 or state >= len(matches):
            return None
        return matches[state]

    return _completer


def _install_slash_completer(verbs: Sequence[str]) -> None:
    """Wire Tab-completion for slash verbs into Python's readline, if available.

    readline is POSIX-only and only works when ``input()`` is called on
    an interactive terminal — on non-TTY stdin the completer is still
    registered but never fires, which is the right no-op behaviour.
    A missing ``readline`` module (Windows, stripped containers) or an
    import failure makes this a silent no-op rather than an error; the
    CLI still works, just without Tab-completion.

    ``set_completer_delims`` is narrowed to whitespace so the ``/``
    character stays inside the token being completed — the default
    delimiters include ``/``, which would hand the completer ``"cost"``
    instead of ``"/cost"``.
    """
    try:
        import readline
    except ImportError:
        return

    readline.set_completer(_make_slash_completer(verbs))
    readline.set_completer_delims(" \t\n")
    # GNU readline and libedit spell the same binding differently.  Most
    # Linux systems (including Cantrip's snap) ship GNU readline, but
    # macOS's system Python defaults to libedit — support both.
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def _print_preflight_event(event: PreflightEvent) -> None:
    """Print a preflight event as a single status line."""
    icon = _STATUS_ICONS.get(event.status, "?")
    print(f"  {icon} {event.message}")


def _print_slash_result(text: str, *, markdown: bool) -> None:
    """Print a slash-command result, rendering Markdown when requested.

    Routes through Rich's Markdown renderer when the handler set
    ``markdown=True`` so bold headers, fenced code blocks, and
    inline code spans display as formatting rather than literal
    asterisks and backticks.  Falls back to plain ``print`` when
    Rich isn't available — keeps the CLI useable in stripped-down
    environments.
    """
    if not markdown:
        print(f"\n{text}\n")
        return
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        Console().print()
        Console().print(Markdown(text))
        Console().print()
    except ImportError:
        print(f"\n{text}\n")


def run_cli(args: argparse.Namespace) -> int:
    """Run Cantrip in CLI mode."""
    try:
        snap_name = getattr(args, "snap", "gemma3")
        light_snap_name = getattr(args, "light_snap", None)
        base_url = getattr(args, "base_url", None)
        provider = create_provider(
            args.provider, args.model, snap_name=snap_name, base_url=base_url
        )
    except (ValueError, ProviderError) as e:
        print(f"Error: {e}")
        return 1

    # Resolve light provider for internal tasks (e.g. compaction).
    light_provider, light_model_name = resolve_light_provider(
        provider,
        args.provider,
        light_provider_name=getattr(args, "light_provider", None),
        light_model_override=args.light_model,
        snap_name=snap_name,
        light_snap_name=light_snap_name,
    )

    improve_path = getattr(args, "improve", None)

    agent = CantripAgent(
        provider=provider,
        charm_path=args.path,
        light_provider=light_provider,
        hook_runner=HookRunner.from_disk(repo_root=args.path),
    )

    # Phase 55.3: stamp the per-goal budget from CLI flags + env vars.
    from cantrip.agent.goal_budget import from_cli_args

    agent.state.goal_budget = from_cli_args(
        max_iterations=getattr(args, "max_iterations", None),
        max_tokens=getattr(args, "max_tokens", None),
    )

    # Phase 68.1: opt out of per-turn working-tree snapshots.
    from cantrip.agent.snapshots import snapshots_enabled

    agent.state.snapshot_enabled = snapshots_enabled(
        no_snapshots_flag=bool(getattr(args, "no_snapshots", False)),
    )

    # Phase 69.2: unattended ("yolo") mode.  When enabled at startup,
    # stamp the flag on state before any executor starts so the first
    # subagent sees ``ask`` decisions as auto-approvals.
    if bool(getattr(args, "yolo", False)):
        agent.state.yolo_mode = True

    # Phase 71.4: per-edit lint feedback.  Default on; ``--no-auto-lint``
    # opts out for users who find the inline diagnostics noisy.
    if bool(getattr(args, "no_auto_lint", False)):
        agent.state.auto_lint = False

    # Set improvement mode if --improve was passed.
    if improve_path is not None:
        from pathlib import Path

        agent.state.mode = "improve"
        agent.state.charm_path = Path(improve_path).resolve()

    display_path = improve_path if improve_path is not None else args.path
    banner = f"Cantrip CLI — provider: {args.provider}, path: {display_path}"
    if light_provider:
        banner += f", light model: {light_model_name}"
    if agent.state.github_repo:
        banner += f", github: {agent.state.github_repo}"
    print(banner)
    print("Type your message (Ctrl+C to quit). Type /help for commands.\n")

    try:
        asyncio.run(_repl(agent))
    except KeyboardInterrupt:
        print("\nGoodbye!")

    return 0


async def _spinner(label: str | list[str] = "Thinking") -> None:
    """Show an animated spinner on the current line until cancelled.

    *label* can be a string or a single-element list for a mutable label
    that updates dynamically (e.g. from task event callbacks).
    """
    i = 0
    try:
        while True:
            current = label[0] if isinstance(label, list) else label
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            # Clear the line and redraw to handle label length changes.
            print(f"\r{frame} {current}...          ", end="", flush=True)
            await asyncio.sleep(0.1)
            i += 1
    except asyncio.CancelledError:
        # Clear the spinner line.
        print("\r" + " " * 40 + "\r", end="", flush=True)


_RESUME_PROMPT = "\n[R]esume / [F]resh / [T]ranscript (show last 20 messages)?\n> "


def _format_transcript_tail(agent: CantripAgent, limit: int = 20) -> str:
    """Return a plain-text render of the last ``limit`` persisted messages."""
    messages = agent.transcript_tail(limit=limit)
    if not messages:
        return "(no messages persisted)"
    lines: list[str] = []
    for msg in messages:
        content = msg.content.replace("\n", " ")
        if len(content) > 200:
            content = content[:197] + "..."
        lines.append(f"{msg.role.value.upper()}: {content}")
    return "\n".join(lines)


def _prompt_session_resume(agent: CantripAgent) -> None:
    """Ask the user whether to resume, start fresh, or review the transcript.

    When there's nothing to resume the function is silent — a brand-new
    charm directory shouldn't generate a prompt about a session that
    doesn't exist.  Non-interactive stdin (pipes, stripped containers)
    falls back to the previous silent-resume behaviour so scripts keep
    working.
    """
    preview = agent.preview_session()
    if not preview.exists:
        return

    # Scripts and piped input: stay out of their way.
    if not sys.stdin.isatty():
        if agent.load_state():
            summary = agent.build_resume_summary()
            if summary:
                print(f"[resume] {summary}\n")
        return

    print(f"\n{preview.summary()}")

    while True:
        try:
            choice = input(_RESUME_PROMPT).strip().lower()
        except EOFError:
            choice = "r"
        if choice in ("", "r", "resume"):
            if agent.load_state():
                summary = agent.build_resume_summary()
                if summary:
                    print(f"[resume] {summary}\n")
            return
        if choice in ("f", "fresh"):
            backup = agent.archive_session()
            if backup is not None:
                print(f"[fresh] Previous session archived to {backup.name}\n")
            return
        if choice in ("t", "transcript"):
            print("\n--- transcript tail ---")
            print(_format_transcript_tail(agent))
            print("--- end transcript ---\n")
            continue
        print(f"  Didn't understand {choice!r} — try R, F, or T.")


async def _repl(agent: CantripAgent) -> None:
    """Run the interactive read-eval-print loop."""
    # Tab-completes slash verbs against the shared catalogue plus the
    # CLI-native ``/tasks`` and ``/status``.  No-op if readline isn't
    # available (non-POSIX, stripped containers) or stdin isn't a TTY.
    _install_slash_completer(_cli_slash_verbs())

    # Kick off the PyPI update check in the background so the result
    # is ready by the time the REPL exits.  The cache on
    # ``~/.cache/cantrip/update.json`` keeps subsequent launches
    # instant; the post-exit notice is printed just before this
    # coroutine returns.
    update_task: asyncio.Task[update.UpdateInfo | None] = asyncio.create_task(
        update.check_for_update()
    )

    # Offer an explicit Resume / Fresh / Transcript choice on launch
    # rather than silently loading whatever's on disk.
    _prompt_session_resume(agent)

    # Subscribe to task updates via the event bus.
    agent.event_bus.bind_loop(asyncio.get_running_loop())
    agent.event_bus.subscribe(ui_events.EventType.TASK_UPDATED, _on_bus_task_event)
    notifications.install(agent.event_bus)

    # Start the background executor so tasks are actually executed.
    agent.start_executor()

    # Eagerly prepare the full environment in the background.
    prepare_task = asyncio.create_task(_prepare_cli(agent))
    bootstrap_started = False

    # Mutable label for the spinner — updated by task events.
    spinner_label = ["Thinking"]

    def _update_spinner_label(event: ui_events.Event) -> None:
        """Update spinner label based on task activity."""
        status = event.payload.get("status", "")
        category = event.payload.get("category", "")
        if status == "active":
            labels = {
                "research": "Researching",
                "build": "Writing code",
                "deploy": "Deploying",
                "test": "Testing",
                "debug": "Debugging",
                "infra": "Setting up",
            }
            spinner_label[0] = labels.get(category, "Working")

    agent.event_bus.subscribe(ui_events.EventType.TASK_UPDATED, _update_spinner_label)

    while True:
        try:
            # Run input() in a thread so the asyncio event loop stays free
            # for the background executor and other concurrent tasks.
            user_input = await asyncio.to_thread(input, "> ")
        except EOFError:
            # Wait for any in-flight or pending tasks before exiting.
            await _drain_executor(agent)
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            break

        # Handle REPL commands.
        if user_input.lower() in ("/help", "?", "help"):
            print(_HELP_TEXT)
            continue
        if user_input.lower() == "/tasks":
            _print_tasks(agent)
            continue
        if user_input.lower() == "/status":
            await _print_juju_status(agent)
            continue
        if user_input.lower() == "/cost":
            _print_cost(agent)
            continue

        # Blind A/B arena picks (A/B/tie/skip) resolve the pending
        # session before the slash dispatcher runs — a one-letter reply
        # is not a command.
        if agent.active_arena is not None:
            reveal = agent.handle_arena_pick(user_input)
            if reveal is not None:
                print(f"\n{reveal}\n")
                continue

        # Shared slash commands (memory, mcp) that render the same text
        # in every surface.  The CLI prints the text directly and, if
        # there's an async follow-up (e.g. `/mcp marketplace`), awaits
        # it inline so the user sees the result before the next prompt.
        # When the handler set ``markdown=True``, route through Rich so
        # the bold headers and fenced code blocks render as formatting.
        shared_result = slash_commands.dispatch(agent, user_input)
        if shared_result is not None:
            _print_slash_result(shared_result.text, markdown=shared_result.markdown)
            if shared_result.clipboard_text is not None:
                from cantrip import clipboard as clipboard_mod

                if not clipboard_mod.write_to_terminal(shared_result.clipboard_text):
                    # The tty rejected OSC 52 (e.g. piped stdout, or a
                    # terminal with set-clipboard off in tmux).  Print
                    # the body so the user can still copy it manually.
                    print(f"\n{shared_result.clipboard_text}\n")
            if shared_result.followup is not None:
                try:
                    followup_text = await shared_result.followup
                except Exception as exc:  # noqa: BLE001 — surface any loader error
                    followup_text = f"_Error: marketplace lookup failed: {exc}_"
                print(f"{followup_text}\n")
            if shared_result.quit:
                await _drain_executor(agent)
                break
            continue

        spinner_label[0] = "Thinking"
        spinner_task = asyncio.create_task(_spinner(spinner_label))
        try:
            response = await agent.process_message(user_input)
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\n{response}\n")

            # Persist session state after each turn.
            agent.save_state()

            # Re-bootstrap if the user picked a different preset — but
            # skip if the Juju controller is already healthy (avoids a
            # slow COS deploy when everything is already working).
            if agent.state.charm_type and not bootstrap_started:
                bootstrap_started = True
                from cantrip.agent.tools.environment import _juju_controller_healthy

                if agent.state.charm_type != DEFAULT_PRESET and not _juju_controller_healthy():
                    asyncio.create_task(_bootstrap_cli(agent))

        except KeyboardInterrupt:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print("\n[interrupted]")
            # Drain the executor cleanly instead of abandoning it.
            await _drain_executor(agent)
        except (ProviderRateLimitError, ProviderOverloadedError):
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print("\nProvider temporarily unavailable — please wait a moment and try again.\n")
        except ProviderError as e:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\nProvider error: {e}\n", file=sys.stderr)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as e:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\nUnexpected error: {e}\n", file=sys.stderr)

    prepare_task.cancel()
    await asyncio.gather(prepare_task, return_exceptions=True)
    await agent.stop_executor()

    await _print_update_notice(update_task)


async def _print_update_notice(update_task: asyncio.Task[update.UpdateInfo | None]) -> None:
    """Print the PyPI update notice if one is available.

    Waits up to a second for the background check to finish — the
    cache makes normal runs effectively instant; a first-run machine
    on a slow network just doesn't see the notice on this launch,
    but the next launch will because the cache will be populated.
    Cancels the task if it hasn't settled so asyncio doesn't warn
    about a pending task being garbage-collected at shutdown.
    """
    try:
        info = await asyncio.wait_for(asyncio.shield(update_task), timeout=1.0)
    except TimeoutError:
        update_task.cancel()
        return
    except asyncio.CancelledError:
        return
    except (OSError, RuntimeError, ValueError):
        return
    if info is None:
        return
    print()
    print(update.format_cli_notice(info))


def _on_bus_task_event(event: ui_events.Event) -> None:
    """Print a brief status line when a task changes state."""
    title = event.payload.get("title", "?")
    status = event.payload.get("status", "?")
    print(f"\r  [task] {title} — {status}                    ")


async def _drain_executor(agent: CantripAgent) -> None:
    """Wait for the background executor to finish all pending and active tasks.

    Times out after 60 seconds to avoid hanging on blocked tasks that
    require user confirmation.
    """
    queue = agent.work_queue
    if not queue.all_tasks():
        return
    print("[executor] Waiting for tasks to complete...")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _DRAIN_TIMEOUT_SECONDS
    while loop.time() < deadline:
        tasks = queue.all_tasks()
        still_running = [t for t in tasks if t.status.value in ("pending", "active")]
        if not still_running:
            break
        await asyncio.sleep(1)
    print("[executor] All tasks finished.")


async def _prepare_cli(agent: CantripAgent) -> None:
    """Eagerly prepare the full environment in the background."""
    print("[preflight] Preparing environment...")
    await agent.prepare(preset=DEFAULT_PRESET, callback=_print_preflight_event)
    if agent.state.environment_ready:
        print("[preflight] Environment ready.\n")
    else:
        print("[preflight] Preparation complete (some checks had errors).\n")


async def _bootstrap_cli(agent: CantripAgent) -> None:
    """Re-bootstrap if the user chose a different preset."""
    preset = agent.state.charm_type
    if not preset:
        return
    print(f"\n[preflight] Re-bootstrapping environment ({preset})...")
    await agent.bootstrap_environment(preset=preset, callback=_print_preflight_event)
    if agent.state.environment_ready:
        print("[preflight] Environment ready.\n")
    else:
        print("[preflight] Environment setup had errors.\n")


def _print_tasks(agent: CantripAgent) -> None:
    """Print current task status."""
    tasks = agent.work_queue.all_tasks()
    if not tasks:
        print("No tasks.\n")
        return

    print()
    for task in tasks:
        icon = _TASK_STATUS_ICONS.get(task.status, "?")
        print(f"  {icon} [{task.category.value}] {task.title}")
        if task.blocked_reason:
            print(f"    Blocked: {task.blocked_reason}")

    # Summary line.
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.status.value] = counts.get(t.status.value, 0) + 1
    summary_parts = [f"{v} {k}" for k, v in sorted(counts.items())]
    print(f"\n  Total: {len(tasks)} ({', '.join(summary_parts)})\n")


async def _print_juju_status(agent: CantripAgent) -> None:
    """Print Juju model status."""
    if not agent.state.dev_model:
        print("No development model is set.\n")
        return

    try:
        import jubilant

        juju = jubilant.Juju(model=agent.state.dev_model)
        status = await asyncio.to_thread(juju.status)

        print(f"\nModel: {agent.state.dev_model}")
        for app_name, app in status.apps.items():
            unit_count = len(app.units) if app.units else 0
            app_status = app.status.current if app.status else "unknown"
            print(f"  {app_name}: {app_status} ({unit_count} units)")
            if app.units:
                for unit_name, unit in app.units.items():
                    unit_status = (
                        unit.workload_status.current if unit.workload_status else "unknown"
                    )
                    agent_status = unit.agent_status.current if unit.agent_status else "unknown"
                    print(f"    {unit_name}: {unit_status} ({agent_status})")
        print()
    except (ImportError, TimeoutError, OSError, ValueError) as e:
        print(f"Failed to get Juju status: {e}\n")


def _print_cost(agent: CantripAgent) -> None:
    """Print token usage and estimated USD cost."""
    store = agent.store
    if not store:
        print("No usage data available.\n")
        return

    total = store.get_total_usage()
    prompt = total.get("prompt_tokens", 0)
    completion = total.get("completion_tokens", 0)
    total_tokens = prompt + completion

    if total_tokens == 0:
        print("No tokens used yet.\n")
        return

    print("\nToken usage:")
    print(f"  Prompt:     {prompt:>10,}")
    print(f"  Completion: {completion:>10,}")
    print(f"  Total:      {total_tokens:>10,}")

    # Cache stats if available (Claude).
    if agent.cache_creation_tokens or agent.cache_read_tokens:
        cache_total = agent.cache_creation_tokens + agent.cache_read_tokens
        hit_pct = agent.cache_read_tokens / cache_total * 100 if cache_total else 0
        print(f"  Cache hit:  {hit_pct:>9.0f}%")

    # Phase 52.6: tokens avoided via step-checkpoint replay.  These are
    # billed *zero* this session (the live provider call never fired),
    # but the sum is worth showing so the user can see the cost-savings
    # headroom the durable-execution machinery bought them.
    savings = store.get_replay_savings()
    saved_total = savings["prompt_tokens"] + savings["completion_tokens"]
    if saved_total:
        print(
            f"  Cached from checkpoint: {saved_total:,} tokens "
            f"({savings['prompt_tokens']:,} prompt, "
            f"{savings['completion_tokens']:,} completion, "
            f"{savings['request_count']} replayed turn(s))"
        )

    # Per-model breakdown with cost.
    by_model = store.get_usage_by_model()
    total_cost = 0.0
    if by_model:
        print("\n  By model:")
        for row in by_model:
            model = row.get("model", "unknown")
            reqs = row.get("request_count", 0)
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
            print(f"    {model}: {tokens:,} tokens, {reqs} requests, {cost_str}")

    # Add Claude cache cost (read at 10% of input rate, write at 125%).
    if agent.cache_read_tokens or agent.cache_creation_tokens:
        cache_cost = pricing.estimate_cost(
            agent.provider.model_name,
            cache_read_tokens=agent.cache_read_tokens,
            cache_write_tokens=agent.cache_creation_tokens,
        )
        total_cost += cache_cost

    # Per-category breakdown (Phase 31.4) — aggregate across models so
    # a category row sums every subagent that ran under it.  Cache cost
    # is global (not category-attributed) so it stays out of this
    # breakdown to avoid double-counting.
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
        print("\n  By category:")
        for cat in sorted(cat_totals):
            tokens, cat_cost, reqs = cat_totals[cat]
            cost_str = pricing.format_cost(cat_cost) if cat_cost > 0 else "free"
            print(f"    {cat}: {tokens:,} tokens, {reqs} requests, {cost_str}")

    if total_cost > 0:
        print(f"\n  Estimated total: {pricing.format_cost(total_cost)}")
        print("  (approximate; published list prices, may drift)")
    print()
