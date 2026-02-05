"""CLI mode for Cantrip (no TUI)."""

import argparse
import asyncio
import sys

from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider
from cantrip.llm.base import ProviderError, ProviderRateLimitError

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def run_cli(args: argparse.Namespace) -> int:
    """Run Cantrip in CLI mode."""
    try:
        provider = create_provider(args.provider, args.model)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    agent = CantripAgent(provider=provider, charm_path=args.path)
    print(f"Cantrip CLI — provider: {args.provider}, path: {args.path}")
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
        except KeyboardInterrupt:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print("\n[interrupted]")
        except ProviderRateLimitError:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print("\nRate limited — please wait a moment and try again.\n")
        except ProviderError as e:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\nProvider error: {e}\n", file=sys.stderr)
        except Exception as e:
            spinner_task.cancel()
            await asyncio.gather(spinner_task, return_exceptions=True)
            print(f"\nUnexpected error: {e}\n", file=sys.stderr)
