"""Phase 67.3 — non-interactive print mode for ``cantrip run --print``.

Drives a single autonomous goal through the agent loop with no TUI:
*goal in*, *NDJSON or human-readable progress out*, exit when the work
queue drains.  Intended for CI scripts and shell pipelines — Pi's
``pi -p "query"`` is the closest analogue.

The event-stream format emitted under ``--json`` is the same set of
:class:`cantrip.ui.events.EventType` payloads the TUI / Web consume,
serialised one per line as ``{"type": "...", "data": {...},
"timestamp": ...}``.  Documented in
``docs/docs/reference-cli.html`` — once shipped, the schema is
treated as a stable public surface.

Pending CONFIRM tasks (Phase 64) block a print-mode run by default:
the runner refuses to proceed and exits non-zero with the list of
unresolved confirmations.  ``--yolo`` (Phase 69.2) is the explicit
opt-in that auto-approves every Phase 68.2 ``ask`` and so removes
the most common source of CONFIRM tasks.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys
from typing import TYPE_CHECKING

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import TaskCategory, TaskStatus
from cantrip.agent.workflows.ralph import RalphConfig, RalphOutcome, run_ralph
from cantrip.hooks import HookRunner
from cantrip.llm import create_provider, resolve_light_provider
from cantrip.llm.base import (
    ProviderConnectionError,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
)
from cantrip.ui import events as ui_events

if TYPE_CHECKING:
    from cantrip.agent.queue import AgentTask

log = logging.getLogger(__name__)

# How long to wait for the work queue to fully drain after the
# conversation loop returns before forcing shutdown.  Long enough for
# a typical build-deploy-test cycle, short enough that a stuck queue
# doesn't hang a CI job indefinitely.
_DRAIN_TIMEOUT_SECONDS = 30 * 60


def _emit_event(event: ui_events.Event) -> None:
    """Write one event to stdout as a single NDJSON line.

    ``Event.to_json`` already produces a compact JSON object; the only
    thing we add is a newline and a flush so that downstream consumers
    (``jq``, ``grep``, line-buffered pipes) see each event the moment
    the agent emits it rather than at process exit.
    """
    sys.stdout.write(event.to_json())
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_progress(event: ui_events.Event) -> None:
    """Render a subset of events as one short human-readable line.

    Mirrors the TUI's task-spinner cadence: task transitions, the
    final assistant message, permission decisions.  Events that don't
    carry actionable progress (cache metrics, watcher heartbeats) are
    deliberately skipped — print mode is for "tell me what the agent
    just did", not "show me everything".
    """
    et = event.type
    p = event.payload
    if et == ui_events.EventType.TASK_UPDATED:
        title = p.get("title", "?")
        status = p.get("status", "?")
        category = p.get("category", "?")
        sys.stdout.write(f"[task:{category}] {title} — {status}\n")
    elif et == ui_events.EventType.CHAT_MESSAGE:
        role = p.get("role", "?")
        content = p.get("content", "")
        sys.stdout.write(f"[{role}] {content}\n")
    elif et == ui_events.EventType.PERMISSION_DECIDED:
        outcome = p.get("outcome", "?")
        tool = p.get("tool_name", "?")
        sys.stdout.write(f"[permission] {tool} — {outcome}\n")
    elif et == ui_events.EventType.PERMISSION_AUTO_APPROVED:
        tool = p.get("tool_name", "?")
        sys.stdout.write(f"[permission] {tool} — auto-approved (yolo)\n")
    elif et == ui_events.EventType.GOAL_BUDGET_EXCEEDED:
        sys.stdout.write(f"[budget] {p.get('reason', 'budget exceeded')}\n")
    elif et == ui_events.EventType.POLICY_RATE_LIMITED:
        cap = p.get("cap", "?")
        sys.stdout.write(f"[rate-limit] policy cap reached ({cap})\n")
    elif et == ui_events.EventType.RALPH_ITERATION_STARTED:
        n = p.get("iteration", "?")
        m = p.get("max_iterations") or "∞"
        sys.stdout.write(f"[ralph] iteration {n}/{m}\n")
    elif et == ui_events.EventType.RALPH_CONVERGED:
        n = p.get("iteration", "?")
        sig = p.get("signal", "?")
        sys.stdout.write(f"[ralph] converged at iteration {n} (signal: {sig})\n")
    elif et == ui_events.EventType.RALPH_STALLED:
        n = p.get("iteration", "?")
        reason = p.get("reason", "no progress")
        sys.stdout.write(f"[ralph] stalled at iteration {n} — {reason}\n")
    elif et == ui_events.EventType.RALPH_EXHAUSTED:
        n = p.get("iteration", "?")
        sys.stdout.write(f"[ralph] exhausted after {n} iteration(s)\n")
    else:
        return
    sys.stdout.flush()


def _format_pending_confirmations(tasks: list[AgentTask]) -> str:
    """Return a human-readable summary of unresolved CONFIRM tasks."""
    lines = [
        "Refusing to run unattended: pending confirmations would block the queue.",
        "Re-run with --yolo to auto-approve both permission `ask` events and",
        "work-queue CONFIRM tasks, or resolve them interactively in the",
        "TUI/CLI mode first.",
        "",
        "Pending confirmations:",
    ]
    for task in tasks:
        lines.append(f"  - [{task.id}] {task.title}")
    return "\n".join(lines)


def _auto_approve_confirmations(agent: CantripAgent, tasks: list[AgentTask]) -> None:
    """Mark each pending CONFIRM task DONE under ``--yolo``.

    Phase 110.2: ``--yolo`` documents itself as covering unattended
    runs.  Until this change it auto-approved permission ``ask``
    events but not work-queue CONFIRMs, which left ``--print --yolo``
    runs exiting 1 whenever a local model emitted a post-success
    ``confirm-design-…`` task (see ``design/LOCAL_MODELS.md`` §5.2.2).

    The auto-approval just flips the task to ``DONE`` with a marker
    note; it does *not* invoke the per-CONFIRM handler (e.g.
    ``handle_design_confirmation``) because the handlers' job is to
    materialise follow-up work, and in the §5.2.2 failure mode the
    follow-up work is precisely what we're trying to suppress (the
    charm has already packed in this turn).  Operators who want a
    handler-driven response to a CONFIRM in unattended mode should
    not use ``--print --yolo`` — they should resolve interactively.
    """
    for task in tasks:
        agent.work_queue.set_done(task.id, "Auto-approved by --yolo")


def _pending_confirmations(agent: CantripAgent) -> list[AgentTask]:
    """Return every CONFIRM task that hasn't yet been resolved.

    Both PENDING and BLOCKED CONFIRM tasks count — they all need a
    user decision before the queue can move on, and a print-mode run
    has no way to provide one.
    """
    pending: list[AgentTask] = []
    for task in agent.work_queue.all_tasks():
        if task.category != TaskCategory.CONFIRM:
            continue
        if task.status in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            pending.append(task)
    return pending


async def _drain_queue(agent: CantripAgent) -> bool:
    """Wait for the work queue to fully drain.

    Returns ``True`` if every task settled into ``DONE`` or ``FAILED``
    (or there were no tasks to begin with), ``False`` if the timeout
    fired with work still in flight.

    A CONFIRM task in ``PENDING`` / ``BLOCKED`` short-circuits the
    drain: print mode has no way to resolve a confirmation, so
    waiting on one would hang the run forever.  The runner re-checks
    for confirmations after the drain returns and surfaces them as
    the refusal message.
    """
    queue = agent.work_queue
    if not queue.all_tasks():
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _DRAIN_TIMEOUT_SECONDS
    while loop.time() < deadline:
        tasks = queue.all_tasks()
        confirms = [
            t
            for t in tasks
            if t.category == TaskCategory.CONFIRM
            and t.status in (TaskStatus.PENDING, TaskStatus.BLOCKED)
        ]
        if confirms:
            # Defer to the post-drain confirmation check — there's no
            # progress to make until the user resolves these.
            return True
        in_flight = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.ACTIVE)]
        if not in_flight:
            return True
        await asyncio.sleep(0.5)
    return False


def _final_exit_code(agent: CantripAgent) -> int:
    """Return 0 when every task succeeded, 1 when any failed.

    Tasks left in ``BLOCKED`` count as failures for print-mode purposes
    — a CI run that finishes with a blocked task did not actually
    complete the goal.  Empty queues are still success: a goal that
    needed no follow-up work (a read-only question, say) shouldn't
    fail just because no tasks were created.
    """
    tasks = agent.work_queue.all_tasks()
    for task in tasks:
        if task.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
            return 1
    return 0


async def _run_async(
    agent: CantripAgent,
    goal: str,
    *,
    json_output: bool,
    ralph_config: RalphConfig | None = None,
) -> int:
    """Inner async runner — drives one goal through the agent and drains.

    When ``ralph_config`` is enabled the goal is wrapped in a
    bounded iterate-until-green outer loop (Phase 69.1) and the
    drain-and-confirm checks run *between* every iteration so a
    stuck CONFIRM doesn't burn the iteration cap.
    """
    agent.event_bus.bind_loop(asyncio.get_running_loop())

    if json_output:
        agent.event_bus.subscribe(None, _emit_event)
    else:
        agent.event_bus.subscribe(None, _emit_progress)

    agent.start_executor()
    try:
        # Slash commands are surface-handled in the CLI / TUI / Web —
        # mirror that here so ``cantrip run --print "/help"`` invokes
        # the dispatcher rather than sending the literal string to the
        # LLM (which produces a hallucinated answer).  When dispatch
        # returns ``None`` the message is not a slash command and falls
        # through to the normal goal path.
        slash_result = slash_commands.dispatch(agent, goal)
        if slash_result is not None:
            return await _emit_slash_result(slash_result, json_output=json_output)

        # JSON mode subscribers see the user's prompt as a chat_message
        # event so consumers reconstructing the conversation don't have
        # to re-derive it from argv.  The agent doesn't publish this
        # itself — the TUI streams the prompt straight into its chat
        # widget — so emit it here just before the turn starts.
        if json_output:
            _emit_event(ui_events.chat_message(role="user", content=goal))

        # Ralph mode wraps process_message in a bounded outer loop;
        # the same drain + confirmation gate runs after every
        # iteration so a stuck CONFIRM short-circuits the run.
        if ralph_config is not None and ralph_config.is_enabled():
            return await _run_ralph_loop(
                agent,
                goal,
                ralph_config,
                json_output=json_output,
            )

        try:
            response = await agent.process_message(goal)
        except (ProviderRateLimitError, ProviderOverloadedError, ProviderConnectionError) as exc:
            # Transient errors only land here when the retry loop has
            # already exhausted its budget — at that point further
            # retries inside print mode wouldn't help.  Surface a
            # specific message so CI logs distinguish "model down" from
            # "auth failed".
            print(f"Provider unavailable after retries: {exc}", file=sys.stderr)
            return 1
        except ProviderError as exc:
            print(f"Provider error: {exc}", file=sys.stderr)
            return 1

        # The conversation loop returns once the model stops issuing
        # tool calls; outstanding work in the queue still needs to run.
        drained = await _drain_queue(agent)

        # Re-check for confirmations queued *during* the run — a
        # subagent that hits a destructive tool gate can produce a
        # CONFIRM task even with --yolo if the rule is ``deny`` (yolo
        # only short-circuits ``ask``).  Phase 110.2: when ``--yolo``
        # is set, auto-approve any pending CONFIRMs and re-drain so
        # downstream work can settle before the exit-code check.
        pending = _pending_confirmations(agent)
        if pending and agent.state.yolo_mode:
            _auto_approve_confirmations(agent, pending)
            await _drain_queue(agent)
            pending = _pending_confirmations(agent)
        if pending:
            print(_format_pending_confirmations(pending), file=sys.stderr)
            return 1

        if not drained:
            print(
                f"Timed out after {_DRAIN_TIMEOUT_SECONDS}s with tasks still running.",
                file=sys.stderr,
            )
            return 1

        # Final assistant text goes to stdout in human mode; in JSON
        # mode it's emitted as a ``chat_message`` event so the consumer
        # has structured access to the reply alongside the rest of the
        # event stream.  ``process_message`` doesn't publish this event
        # itself — the TUI reads from the streaming yield path instead.
        if response:
            if json_output:
                _emit_event(ui_events.chat_message(role="assistant", content=response))
            else:
                sys.stdout.write(f"\n{response}\n")
                sys.stdout.flush()

        return _final_exit_code(agent)
    finally:
        await agent.stop_executor()


async def _emit_slash_result(
    result: slash_commands.SlashResult,
    *,
    json_output: bool,
) -> int:
    """Render a dispatched slash result for ``--print`` consumers.

    Mirrors the CLI's :func:`cli._print_slash_result` shape but writes
    a ``chat_message`` event instead of plain text under ``--json`` so
    NDJSON consumers see the slash output in the same channel as a
    normal assistant reply.  Async ``followup`` work is awaited inline
    so the run doesn't exit before the result arrives.
    """
    text = result.text
    if json_output:
        _emit_event(ui_events.chat_message(role="system", content=text))
    elif text:
        sys.stdout.write(f"{text}\n")
        sys.stdout.flush()

    if result.followup is not None:
        try:
            followup_text = await result.followup
        except Exception as exc:  # noqa: BLE001 — surface any handler error
            followup_text = f"Error: slash follow-up failed: {exc}"
        if json_output:
            _emit_event(ui_events.chat_message(role="system", content=followup_text))
        elif followup_text:
            sys.stdout.write(f"{followup_text}\n")
            sys.stdout.flush()

    return 0


async def _run_ralph_loop(
    agent: CantripAgent,
    goal: str,
    config: RalphConfig,
    *,
    json_output: bool,
) -> int:
    """Drive ``run_ralph`` with a print-mode-aware iteration callback.

    Between every iteration we drain the work queue and check for
    pending confirmations — same gates as the non-Ralph path,
    just applied per pass.  A confirmation showing up mid-run
    aborts the loop (``run_ralph`` doesn't see the abort; we raise
    ``_RalphAbortError`` from the callback to bail out of the
    refinement loop cleanly).
    """
    abort_message: dict[str, str] = {}

    async def _between_iterations(_iteration: int, _response: str) -> None:
        drained = await _drain_queue(agent)
        if not drained:
            abort_message["error"] = (
                f"Timed out after {_DRAIN_TIMEOUT_SECONDS}s with tasks still running."
            )
            raise _RalphAbortError()
        pending = _pending_confirmations(agent)
        # Phase 110.2: same auto-approval as the non-Ralph path.
        if pending and agent.state.yolo_mode:
            _auto_approve_confirmations(agent, pending)
            await _drain_queue(agent)
            pending = _pending_confirmations(agent)
        if pending:
            abort_message["error"] = _format_pending_confirmations(pending)
            raise _RalphAbortError()

    try:
        result = await run_ralph(
            process_message=agent.process_message,
            goal=goal,
            config=config,
            event_bus=agent.event_bus,
            charm_path=agent.state.charm_path,
            on_iteration=_between_iterations,
            # Phase 99.3: Ralph re-feed prefers the persisted user-prose
            # objective over the ``--print`` argument so a ``/goal``
            # issued mid-run (or an objective stamped at startup) drives
            # the iteration prompt without restarting the loop.
            objective_provider=lambda: agent.state.objective,
        )
    except _RalphAbortError:
        print(abort_message.get("error", "Ralph loop aborted."), file=sys.stderr)
        return 1
    except (ProviderRateLimitError, ProviderOverloadedError, ProviderConnectionError) as exc:
        print(f"Provider unavailable after retries: {exc}", file=sys.stderr)
        return 1
    except ProviderError as exc:
        print(f"Provider error: {exc}", file=sys.stderr)
        return 1

    if not json_output and result.final_response:
        sys.stdout.write(f"\n{result.final_response}\n")
        sys.stdout.flush()

    if result.outcome == RalphOutcome.STALLED:
        # A stall is a "could not make progress" outcome — surface
        # it as a non-zero exit so CI doesn't silently treat a
        # no-op iteration as success.
        return 1
    if result.outcome == RalphOutcome.EXHAUSTED:
        return 1
    return _final_exit_code(agent)


class _RalphAbortError(RuntimeError):
    """Sentinel raised from the iteration callback to abort the loop.

    Carrying state via an exception keeps the public ``run_ralph``
    signature clean (no return-channel kwargs) and means the
    callback's ``raise`` matches what asyncio will already do for
    cancellation.
    """


def run_print(args: argparse.Namespace) -> int:
    """Entry point for ``cantrip run --print "<goal>"`` (Phase 67.3).

    Builds a headless agent, refuses up-front if the resumed session
    has unresolved CONFIRM tasks (per the roadmap's "default to refuse
    and exit non-zero" rule), then drives the goal through one
    conversation turn plus a queue drain.  Returns the exit code the
    surrounding ``main()`` propagates back to the shell.
    """
    goal: str = args.print_goal
    if not goal or not goal.strip():
        print("Error: --print requires a non-empty goal string.", file=sys.stderr)
        return 2

    json_output = bool(getattr(args, "json_output", False))

    try:
        snap_name = getattr(args, "snap", "gemma3")
        light_snap_name = getattr(args, "light_snap", None)
        base_url = getattr(args, "base_url", None)
        provider = create_provider(
            args.provider, args.model, snap_name=snap_name, base_url=base_url
        )
    except (ValueError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    light_provider, _ = resolve_light_provider(
        provider,
        args.provider,
        light_provider_name=getattr(args, "light_provider", None),
        light_model_override=args.light_model,
        snap_name=snap_name,
        light_snap_name=light_snap_name,
    )

    charm_path: pathlib.Path = pathlib.Path(args.path)

    # Phase 72.3: build embed/rerank role router (env vars only — print
    # mode does not expose embed/rerank flags today).
    from cantrip.llm.roles import build_role_router

    role_router = build_role_router(
        embed_provider=getattr(args, "embed_provider", None),
        embed_model=getattr(args, "embed_model", None),
        rerank_provider=getattr(args, "rerank_provider", None),
        rerank_model=getattr(args, "rerank_model", None),
    )

    agent = CantripAgent(
        provider=provider,
        charm_path=charm_path,
        light_provider=light_provider,
        hook_runner=HookRunner.from_disk(repo_root=charm_path),
        role_router=role_router,
        short_session=getattr(args, "short_session", None),
    )

    # Per-goal budget (Phase 55.3) and snapshot opt-out (Phase 68.1)
    # behave the same in print mode as in the REPL.
    from cantrip.agent.runtime.goal_budget import from_cli_args
    from cantrip.agent.snapshots import snapshots_enabled

    agent.state.goal_budget = from_cli_args(
        max_iterations=getattr(args, "max_iterations", None),
        max_tokens=getattr(args, "max_tokens", None),
    )
    objective_arg = getattr(args, "objective", None)
    if objective_arg is not None and objective_arg.strip():
        agent.state.objective = objective_arg.strip()
    agent.state.snapshot_enabled = snapshots_enabled(
        no_snapshots_flag=bool(getattr(args, "no_snapshots", False)),
    )
    if bool(getattr(args, "yolo", False)):
        agent.state.yolo_mode = True

    # Phase 71.4: per-edit lint feedback opt-out.
    if bool(getattr(args, "no_auto_lint", False)):
        agent.state.auto_lint = False

    # Phase 71.2: architect/editor two-model split (CLI parity with REPL).
    if bool(getattr(args, "architect", False)):
        agent.state.architect_mode = True
        agent.state.editor_provider = getattr(args, "editor_provider", None) or None
        agent.state.editor_model = getattr(args, "editor_model", None) or None

    # Phase 71.3: auto-commit-per-turn opt-out.
    if bool(getattr(args, "no_auto_commit", False)):
        agent.state.git_auto_commit = False

    ralph_max = int(getattr(args, "ralph_max_iterations", 0) or 0)
    agent.state.ralph_max_iterations = ralph_max
    ralph_config = RalphConfig(max_iterations=ralph_max) if ralph_max != 0 else None

    # Resume any persisted session silently so a print-mode invocation
    # in a charm directory picks up where the last interactive run
    # left off.  This is also how pre-existing CONFIRM tasks become
    # visible to the up-front refusal check below.
    agent.load_state()

    pending = _pending_confirmations(agent)
    if pending:
        if agent.state.yolo_mode:
            # Phase 110.2: pre-existing CONFIRMs from a resumed session
            # don't block an unattended run any more — auto-approve them
            # so the executor can dispatch downstream work immediately
            # rather than parking on the up-front refusal check.
            _auto_approve_confirmations(agent, pending)
        else:
            print(_format_pending_confirmations(pending), file=sys.stderr)
            return 1

    try:
        return asyncio.run(
            _run_async(
                agent,
                goal,
                json_output=json_output,
                ralph_config=ralph_config,
            )
        )
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        return 130
