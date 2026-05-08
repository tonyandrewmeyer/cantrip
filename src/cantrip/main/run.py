"""``cantrip run`` dispatcher and TUI/Web/CLI/print-mode handoff."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

# Markers that identify the Cantrip source tree when inspecting a
# ``pyproject.toml``.  Having *both* avoids confusing a third-party
# package called ``juju-cantrip`` with the real source checkout: a fork
# of our code is very likely to keep ``cantrip.main:main`` as its entry
# point, while a namespace collision would not.
_CANTRIP_PYPROJECT_NAME_MARKER = 'name = "juju-cantrip"'
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


def _is_cantrip_source_tree(path: pathlib.Path) -> bool:
    """Check whether path is the cantrip source tree itself."""
    pyproject = path / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text()
    except OSError:
        return False
    return _CANTRIP_PYPROJECT_NAME_MARKER in content and _CANTRIP_PYPROJECT_ENTRY_MARKER in content


def _run(args: argparse.Namespace) -> int:
    """Run the main cantrip agent."""
    # --improve overrides the positional path argument.
    improve_path: pathlib.Path | None = getattr(args, "improve", None)
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
    # directory cantrip was launched from.  ``mkdir`` raises if the path
    # already exists *as a regular file* (``FileExistsError``) or if a
    # parent is unwritable (``PermissionError``); turn either into a
    # friendly CLI error rather than a Python traceback.
    if charm_path.exists() and not charm_path.is_dir():
        print(f"Error: {charm_path} exists but is not a directory.", file=sys.stderr)
        return 1
    try:
        charm_path.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as exc:
        print(f"Error: cannot create charm directory {charm_path}: {exc}", file=sys.stderr)
        return 1
    os.chdir(charm_path)

    if args.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not set")
        print("Set it with: export GEMINI_API_KEY='your-key-here'")
        return 1
    elif args.provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
        return 1
    elif args.provider == "fireworks" and not os.environ.get("FIREWORKS_API_KEY"):
        print("Error: FIREWORKS_API_KEY environment variable not set")
        print("Get a key from: https://fireworks.ai/account/api-keys")
        print("Set it with: export FIREWORKS_API_KEY='your-key-here'")
        return 1
    elif args.provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        print("Error: OPENROUTER_API_KEY environment variable not set")
        print("Get a key from: https://openrouter.ai/settings/keys")
        print("Set it with: export OPENROUTER_API_KEY='your-key-here'")
        return 1
    elif args.provider == "opencode-zen" and not (
        os.environ.get("OPENCODE_ZEN_API_KEY") or os.environ.get("ZEN_API_KEY")
    ):
        print("Error: OPENCODE_ZEN_API_KEY environment variable not set")
        print("Get a key from: https://opencode.ai/zen")
        print("Set it with: export OPENCODE_ZEN_API_KEY='your-key-here'")
        return 1
    elif args.provider == "openai-compatible":
        if not getattr(args, "base_url", None):
            print("Error: --base-url is required with --provider openai-compatible")
            print("Example: cantrip --provider openai-compatible \\")
            print("           --base-url https://api.together.xyz/v1 \\")
            print("           --model meta-llama/Llama-3.3-70B-Instruct-Turbo")
            return 1
        if not args.model:
            print("Error: --model is required with --provider openai-compatible")
            return 1
        if not os.environ.get("OPENAI_COMPATIBLE_API_KEY"):
            print("Error: OPENAI_COMPATIBLE_API_KEY environment variable not set")
            print("Set it to your bearer token, or any non-empty string if")
            print("the endpoint does not require authentication.")
            return 1
    # inference-snap needs no API key (local model).

    _install_unraisable_hook()

    # Phase 67.3: non-interactive print mode pre-empts TUI/Web/CLI
    # entrypoints — it's its own dispatch path with no REPL.  Use
    # ``is not None`` so an explicit empty ``--print ""`` still selects
    # print mode (where ``run_print`` surfaces the empty-goal error)
    # rather than silently falling through to the interactive REPL.
    if getattr(args, "print_goal", None) is not None:
        if getattr(args, "web", False):
            print(
                "Error: --print and --web are mutually exclusive.",
                file=sys.stderr,
            )
            return 2
        from cantrip.print_mode import run_print

        return run_print(args)

    if getattr(args, "web", False):
        if improve_path is not None:
            print(
                "Error: --improve is not supported with --web. The improvement "
                "flow requires the interactive confirmation UI that only the "
                "TUI and CLI modes provide.",
                file=sys.stderr,
            )
            print(
                f"Run without --web:  cantrip run --improve {improve_path}",
                file=sys.stderr,
            )
            return 2
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
            base_url=getattr(args, "base_url", None),
            max_iterations=getattr(args, "max_iterations", None),
            max_tokens=getattr(args, "max_tokens", None),
            objective=getattr(args, "objective", None),
            no_snapshots=bool(getattr(args, "no_snapshots", False)),
            yolo=bool(getattr(args, "yolo", False)),
            no_auto_lint=bool(getattr(args, "no_auto_lint", False)),
            architect=bool(getattr(args, "architect", False)),
            editor_provider=getattr(args, "editor_provider", None),
            editor_model=getattr(args, "editor_model", None),
            no_auto_commit=bool(getattr(args, "no_auto_commit", False)),
            embed_provider=getattr(args, "embed_provider", None),
            embed_model=getattr(args, "embed_model", None),
            rerank_provider=getattr(args, "rerank_provider", None),
            rerank_model=getattr(args, "rerank_model", None),
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
        title = (
            f"juju-cantrip {info.current} has been yanked — upgrade to {info.latest} recommended"
        )
    else:
        title = f"A newer juju-cantrip is available: {info.latest} (you have {info.current})"

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
