"""CLI mode for Cantrip (no TUI)."""

import argparse
import asyncio
import json
import sys

from cantrip.agent.core import CantripAgent
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.llm import create_provider, resolve_light_provider
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


def _print_preflight_event(event: PreflightEvent) -> None:
    """Print a preflight event as a single status line."""
    icon = _STATUS_ICONS.get(event.status, "?")
    print(f"  {icon} {event.message}")


def run_cli(args: argparse.Namespace) -> int:
    """Run Cantrip in CLI mode."""
    try:
        snap_name = getattr(args, "snap", "gemma3")
        light_snap_name = getattr(args, "light_snap", None)
        provider = create_provider(args.provider, args.model, snap_name=snap_name)
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
    )

    # Set improvement mode if --improve was passed.
    if improve_path is not None:
        from pathlib import Path

        agent.state.mode = "improve"
        agent.state.charm_path = Path(improve_path).resolve()

    display_path = improve_path if improve_path is not None else args.path
    banner = f"Cantrip CLI — provider: {args.provider}, path: {display_path}"
    if light_provider:
        banner += f", light model: {light_model_name}"
    print(banner)
    print("Type your message (Ctrl+C to quit).\n")

    try:
        asyncio.run(_repl(agent))
    except KeyboardInterrupt:
        print("\nGoodbye!")

    return 0


async def _spinner(label: str = "Thinking") -> None:
    """Show an animated spinner on the current line until cancelled."""
    i = 0
    try:
        while True:
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            print(f"\r{frame} {label}...", end="", flush=True)
            await asyncio.sleep(0.1)
            i += 1
    except asyncio.CancelledError:
        # Clear the spinner line.
        print("\r" + " " * (len(label) + 6) + "\r", end="", flush=True)


async def _repl(agent: CantripAgent) -> None:
    """Run the interactive read-eval-print loop."""
    # Load prior session state if it exists.
    if agent.load_state():
        summary = agent.build_resume_summary()
        if summary:
            print(f"[resume] {summary}\n")

    # Subscribe to task updates via the event bus.
    agent.event_bus.bind_loop(asyncio.get_running_loop())
    agent.event_bus.subscribe(ui_events.EventType.TASK_UPDATED, _on_bus_task_event)

    # Start the background executor so tasks are actually executed.
    agent.start_executor()

    # Eagerly prepare the full environment in the background.
    prepare_task = asyncio.create_task(_prepare_cli(agent))
    bootstrap_started = False

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

        spinner_task = asyncio.create_task(_spinner())
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
