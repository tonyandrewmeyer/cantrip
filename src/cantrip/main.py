"""Cantrip entry point."""

import argparse
import os
import sys
from pathlib import Path

from cantrip import __version__

# Markers that identify the Cantrip source tree when inspecting a
# ``pyproject.toml``.  Having *both* avoids confusing a third-party
# package called ``cantrip`` with the real source checkout: a fork of
# our code is very likely to keep ``cantrip.main:main`` as its entry
# point, while a namespace collision would not.
_CANTRIP_PYPROJECT_NAME_MARKER = 'name = "cantrip"'
_CANTRIP_PYPROJECT_ENTRY_MARKER = "cantrip.main:main"


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

    subparsers = parser.add_subparsers(dest="command")

    # ── run (default) ────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="Run cantrip agent")
    run_parser.add_argument(
        "--provider",
        choices=["gemini", "claude", "inference-snap"],
        default="gemini",
        help="LLM provider to use (default: gemini)",
    )
    run_parser.add_argument(
        "--model",
        help="Specific model to use (provider-dependent)",
    )
    run_parser.add_argument(
        "--snap",
        default="gemma3",
        help=("Inference snap name when using --provider inference-snap (default: gemma3)"),
    )
    run_parser.add_argument(
        "--light-model",
        help=("Cheaper model for internal tasks like compaction (auto-detected if omitted)"),
    )
    run_parser.add_argument(
        "--light-snap",
        help="Lighter inference snap for internal tasks (e.g. nemotron-3-nano)",
    )
    run_parser.add_argument(
        "--light-provider",
        choices=["gemini", "claude", "inference-snap"],
        help="Use a different provider for light tasks (enables hybrid mode)",
    )
    run_parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in CLI mode without TUI",
    )
    run_parser.add_argument(
        "--web",
        action="store_true",
        help="Run with a browser-based Web UI instead of the TUI",
    )
    run_parser.add_argument(
        "--web-port",
        type=int,
        default=8471,
        help="Port for the Web UI (default: 8471)",
    )
    run_parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Maximum concurrent subagent tasks (default: 3)",
    )
    run_parser.add_argument(
        "--improve",
        type=Path,
        default=None,
        metavar="CHARM_PATH",
        help="Improve an existing charm at the given path (audit, fix, redeploy)",
    )
    run_parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="TUI colour theme (cantrip, ubuntu, monokai, solarized-dark, light)",
    )
    run_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to charm project (default: current directory)",
    )

    # ── compare (Phase 31.7) ─────────────────────────────────────────
    compare_parser = subparsers.add_parser(
        "compare",
        help="Diff two charm implementations (structure, config, relations, tests)",
    )
    compare_parser.add_argument(
        "left",
        type=Path,
        help="First charm directory",
    )
    compare_parser.add_argument(
        "right",
        type=Path,
        help="Second charm directory",
    )

    # ── export-transcript ────────────────────────────────────────────
    export_parser = subparsers.add_parser(
        "export-transcript",
        help="Export a session transcript",
    )
    export_parser.add_argument(
        "path",
        type=Path,
        help="Charm directory containing a .cantrip file",
    )
    export_parser.add_argument(
        "--format",
        choices=["html", "jsonl", "markdown"],
        default="html",
        dest="fmt",
        help="Output format (default: html)",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: transcript.<ext> in charm directory)",
    )
    export_parser.add_argument(
        "--task",
        default=None,
        dest="filter_task",
        help="Export only a specific task and its subagent conversation",
    )
    export_parser.add_argument(
        "--phase",
        choices=["research", "build", "deploy", "test"],
        default=None,
        dest="filter_phase",
        help="Export only tasks in a phase (research, build, deploy, test)",
    )
    export_parser.add_argument(
        "--since",
        default=None,
        dest="filter_since",
        help="Export only messages and events at or after an ISO timestamp",
    )
    export_parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        dest="page_size",
        help="Split HTML output into pages of N conversation messages each",
    )

    # When the first positional argument is not a known subcommand, treat
    # the entire argv as arguments to the "run" sub-parser.  This lets
    # ``cantrip /path/to/charm`` and ``cantrip --no-tui`` work without
    # requiring an explicit ``run`` subcommand.
    _subcommands = {"run", "export-transcript", "compare"}
    argv = sys.argv[1:]
    if (
        not argv
        or (argv[0] not in _subcommands and not argv[0].startswith("-"))
        or (argv[0].startswith("-") and argv[0] not in ("--version", "-h", "--help"))
    ):
        argv = ["run", *argv]

    args = parser.parse_args(argv)

    return args


def _is_cantrip_source_tree(path: Path) -> bool:
    """Check whether path is the cantrip source tree itself."""
    pyproject = path / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text()
    except OSError:
        return False
    return _CANTRIP_PYPROJECT_NAME_MARKER in content and _CANTRIP_PYPROJECT_ENTRY_MARKER in content


def _export_transcript(args: argparse.Namespace) -> int:
    """Export a session transcript."""
    charm_path = args.path.resolve()
    db_path = charm_path / ".cantrip"
    if not db_path.exists():
        print(f"Error: no .cantrip file found in {charm_path}")
        return 1

    from cantrip.transcript.export import load_transcript

    data = load_transcript(
        db_path,
        task_id=getattr(args, "filter_task", None),
        phase=getattr(args, "filter_phase", None),
        since=getattr(args, "filter_since", None),
    )

    fmt = args.fmt
    page_size: int | None = getattr(args, "page_size", None)

    if fmt == "html" and page_size is not None and page_size > 0:
        from cantrip.transcript.html import render_html_paginated

        output_dir = (args.output or charm_path).resolve()
        if output_dir.suffix:
            # User gave a file path — use its parent as the output directory
            # and its stem as the filename prefix.
            stem = output_dir.stem
            output_dir = output_dir.parent
        else:
            stem = "transcript"
        pages = render_html_paginated(data, page_size, stem=stem)
        for filename, html in pages:
            filepath = output_dir / filename
            filepath.write_text(html)
        print(f"Transcript exported to {output_dir}/ ({len(pages)} pages)")
        return 0

    if fmt == "html":
        from cantrip.transcript.html import render_html

        content = render_html(data)
        suffix = ".html"
    elif fmt == "jsonl":
        from cantrip.transcript.jsonl import render_jsonl

        content = render_jsonl(data)
        suffix = ".jsonl"
    elif fmt == "markdown":
        from cantrip.transcript.markdown import render_markdown

        content = render_markdown(data)
        suffix = ".md"
    else:
        print(f"Error: unknown format {fmt}")
        return 1

    output = args.output or (charm_path / f"transcript{suffix}")
    Path(output).write_text(content)
    print(f"Transcript exported to {output}")
    return 0


def _compare_charms(args: argparse.Namespace) -> int:
    """Diff two charm implementations and print the report to stdout (Phase 31.7)."""
    from cantrip import compare

    left = args.left.resolve()
    right = args.right.resolve()
    for label, path in (("left", left), ("right", right)):
        if not path.is_dir():
            print(f"Error: {label} charm path is not a directory: {path}")
            return 1

    report = compare.compare_charms(left, right)
    print(compare.format_report(report))
    return 0


def _run(args: argparse.Namespace) -> int:
    """Run the main cantrip agent."""
    # --improve overrides the positional path argument.
    improve_path: Path | None = getattr(args, "improve", None)
    if improve_path is not None:
        improve_path = improve_path.resolve()
        if not improve_path.is_dir():
            print(f"Error: {improve_path} is not a directory")
            return 1
        charm_path = improve_path
    else:
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

    if getattr(args, "web", False):
        from cantrip.web.server import run_web

        return run_web(args)

    if args.no_tui:
        from cantrip.cli import run_cli

        return run_cli(args)
    else:
        from cantrip.tui.app import CantripApp

        app = CantripApp(
            provider=args.provider,
            model=args.model,
            charm_path=charm_path,
            light_model=args.light_model,
            max_concurrency=args.concurrency,
            snap_name=args.snap,
            light_snap_name=args.light_snap,
            light_provider_name=args.light_provider,
            improve_path=improve_path,
            theme_name=args.theme,
        )
        app.run()
        _print_update_panel(app.pending_update_info)
        return 0


def _print_update_panel(info: object) -> None:
    """Render the PyPI update notice in a Rich panel after TUI shutdown.

    Called only once the Textual screen has torn down so the prompt
    doesn't clash with live widgets.  Matches ``toad``'s exit-time
    prompt pattern.  Safe to call with ``None`` — a user already on
    the latest release sees no extra output.
    """
    from cantrip import update

    if info is None:
        return
    if not isinstance(info, update.UpdateInfo):
        return

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    command = update.upgrade_command()
    if info.installed_yanked:
        title = f"Cantrip {info.current} has been yanked — upgrade to {info.latest} recommended"
    else:
        title = f"A newer Cantrip is available: {info.latest} (you have {info.current})"

    body_parts: list[str] = [f"PyPI: {info.pypi_url}"]
    if command is not None:
        body_parts.append(f"Upgrade: `{command}`")
    else:
        body_parts.append("Upgrade via your usual installer.")
    if info.release_notes_markdown:
        body_parts.append("")
        body_parts.append(_truncate_notes(info.release_notes_markdown))

    body = "\n\n".join(body_parts)
    console = Console()
    console.print()
    console.print(Panel(Markdown(body), title=title, border_style="cyan"))


def _truncate_notes(markdown: str, *, line_cap: int = 30) -> str:
    """Trim the release-notes markdown to *line_cap* visible lines.

    Four releases of backlog shouldn't swamp the terminal when the
    TUI quits — keep the panel short and point at the PyPI URL for
    the rest.
    """
    lines = markdown.splitlines()
    if len(lines) <= line_cap:
        return markdown
    return "\n".join(lines[:line_cap]) + "\n\n_… see the PyPI URL for full notes._"


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.command == "export-transcript":
        return _export_transcript(args)
    if args.command == "compare":
        return _compare_charms(args)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
