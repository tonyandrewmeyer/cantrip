"""Cantrip entry point."""

import argparse
import os
import sys
from pathlib import Path

from cantrip import __version__
from cantrip.cli import run_cli
from cantrip.tui.app import CantripApp


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="cantrip",
        description="A small spell for building Juju charms",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cantrip {__version__}",
    )
    parser.add_argument(
        "--provider",
        choices=["gemini", "claude"],
        default="gemini",
        help="LLM provider to use (default: gemini)",
    )
    parser.add_argument(
        "--model",
        help="Specific model to use (provider-dependent)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in CLI mode without TUI",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to charm project (default: current directory)",
    )
    return parser.parse_args()


def _is_cantrip_source_tree(path: Path) -> bool:
    """Check whether path is the cantrip source tree itself."""
    pyproject = path / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text()
        return 'name = "cantrip"' in content and "cantrip.main:main" in content
    except OSError:
        return False


def main() -> int:
    """Main entry point."""
    args = parse_args()

    charm_path = args.path.resolve()
    if _is_cantrip_source_tree(charm_path):
        print("Error: refusing to use the cantrip source tree as a charm project.")
        print("Run from your charm's directory, or pass a path:")
        print("  cantrip /path/to/my-charm")
        return 1

    if args.provider == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            print("Error: GEMINI_API_KEY environment variable not set")
            print("Set it with: export GEMINI_API_KEY='your-key-here'")
            return 1
    elif args.provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return 1

    if args.no_tui:
        return run_cli(args)
    else:
        app = CantripApp(
            provider=args.provider,
            model=args.model,
            charm_path=args.path,
        )
        app.run()
        return 0


if __name__ == "__main__":
    sys.exit(main())
