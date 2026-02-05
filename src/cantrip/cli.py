"""CLI mode for Cantrip (no TUI)."""

import argparse
import asyncio
import sys

from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider


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

        try:
            response = await agent.process_message(user_input)
            print(f"\n{response}\n")
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as e:
            print(f"\nError: {e}\n", file=sys.stderr)
