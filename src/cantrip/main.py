"""Cantrip entry point."""

import argparse
import os
import sys
from pathlib import Path

from cantrip import __version__


def _install_unraisable_hook() -> None:
    """Suppress 'Event loop is closed' errors from asyncio transport cleanup.

    When the TUI exits, asyncio subprocess transports may be garbage-collected
    after the event loop is already closed, producing noisy but harmless
    RuntimeError tracebacks on stderr.
    """
    _original = sys.unraisablehook

    def _hook(unraisable: object) -> None:
        if isinstance(unraisable.exc_value, RuntimeError) and "Event loop is closed" in str(
            unraisable.exc_value
        ):
            return
        _original(unraisable)

    sys.unraisablehook = _hook


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
        choices=["gemini", "claude", "inference-snap"],
        default="gemini",
        help="LLM provider to use (default: gemini)",
    )
    parser.add_argument(
        "--model",
        help="Specific model to use (provider-dependent)",
    )
    parser.add_argument(
        "--snap",
        default="gemma3",
        help="Inference snap name when using --provider inference-snap (default: gemma3)",
    )
    parser.add_argument(
        "--light-model",
        help="Cheaper model for internal tasks like compaction (auto-detected if omitted)",
    )
    parser.add_argument(
        "--light-snap",
        help="Lighter inference snap for internal tasks (e.g. nemotron-3-nano)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in CLI mode without TUI",
    )
    parser.add_argument(
        "--watcher",
        action="store_true",
        help="Start the event watcher on launch (monitors dev model for changes)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Maximum concurrent subagent tasks (default: 3)",
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

    # Ensure the charm directory exists and switch to it so that all tool
    # defaults (path=".") resolve relative to the charm project, not the
    # directory cantrip was launched from.
    charm_path.mkdir(parents=True, exist_ok=True)
    os.chdir(charm_path)

    if args.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set")
        print("Set it with: export GEMINI_API_KEY='your-key-here'")
        return 1
    elif args.provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return 1
    # inference-snap needs no API key (local model).

    _install_unraisable_hook()

    if args.no_tui:
        from cantrip.cli import run_cli

        return run_cli(args)
    else:
        from cantrip.tui.app import CantripApp

        app = CantripApp(
            provider=args.provider,
            model=args.model,
            charm_path=args.path,
            light_model=args.light_model,
            watcher=args.watcher,
            max_concurrency=args.concurrency,
            snap_name=args.snap,
            light_snap_name=args.light_snap,
        )
        app.run()
        return 0


if __name__ == "__main__":
    sys.exit(main())
