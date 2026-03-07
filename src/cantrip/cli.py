"""CLI mode for Cantrip (no TUI)."""

import argparse
import asyncio
import sys

from cantrip.agent.core import CantripAgent
from cantrip.agent.preflight import DEFAULT_PRESET, CheckStatus, PreflightEvent
from cantrip.llm import create_provider, resolve_light_model
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

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
    light_provider = None
    light_model_name = None
    if light_snap_name and args.provider == "inference-snap":
        light_provider = create_provider("inference-snap", snap_name=light_snap_name)
        light_model_name = light_snap_name
    else:
        main_model = provider.model_name
        light_model_name = args.light_model or resolve_light_model(args.provider, main_model)
        if light_model_name != main_model:
            light_provider = create_provider(
                args.provider, light_model_name, snap_name=snap_name
            )
        else:
            light_model_name = None

    agent = CantripAgent(
        provider=provider,
        charm_path=args.path,
        light_provider=light_provider,
    )
    banner = f"Cantrip CLI — provider: {args.provider}, path: {args.path}"
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
    # Eagerly prepare the full environment in the background.
    prepare_task = asyncio.create_task(_prepare_cli(agent))
    bootstrap_started = False

    while True:
        try:
            user_input = input("> ")
        except EOFError:
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

            # Re-bootstrap if the user picked a different preset.
            if agent.state.charm_type and not bootstrap_started:
                bootstrap_started = True
                if agent.state.charm_type != DEFAULT_PRESET:
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
        except Exception as e:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\nUnexpected error: {e}\n", file=sys.stderr)

    prepare_task.cancel()
    await asyncio.gather(prepare_task, return_exceptions=True)


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
