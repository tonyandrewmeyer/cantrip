"""CLI mode for Cantrip (no TUI)."""

import argparse


def run_cli(args: argparse.Namespace) -> int:
    """Run Cantrip in CLI mode."""
    print("Cantrip CLI mode")
    print(f"Provider: {args.provider}")
    print(f"Path: {args.path}")
    print()
    print("CLI mode not yet implemented. Use TUI mode (remove --no-tui flag).")
    return 1
