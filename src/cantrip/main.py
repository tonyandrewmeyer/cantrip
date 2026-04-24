"""Cantrip entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cantrip import __version__

if TYPE_CHECKING:
    from cantrip.agent import durability as durability_mod
    from cantrip.agent import store as store_mod

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
        choices=[
            "gemini",
            "claude",
            "inference-snap",
            "fireworks",
            "openrouter",
            "openai-compatible",
        ],
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
        "--base-url",
        default=None,
        help=(
            "API base URL override.  Required for --provider "
            "openai-compatible; optional for inference-snap (overrides "
            "snap discovery) and fireworks (proxies or compatible hosts)."
        ),
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
        choices=["gemini", "claude", "inference-snap", "fireworks", "openrouter"],
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
        "--max-iterations",
        type=int,
        default=None,
        dest="max_iterations",
        help=(
            "Phase 55.3 per-goal budget: hard cap on LLM request count "
            "before the work queue blocks.  Also settable via "
            "``CANTRIP_MAX_ITERATIONS`` env var."
        ),
    )
    run_parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        dest="max_tokens",
        help=(
            "Phase 55.3 per-goal budget: hard cap on total (prompt + "
            "completion) tokens before the work queue blocks.  Splits "
            "evenly across prompt and completion caps.  Also settable "
            "via ``CANTRIP_MAX_TOKENS`` env var."
        ),
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

    # ── hooks (Phase 46.5) ────────────────────────────────────────────
    hooks_parser = subparsers.add_parser(
        "hooks",
        help="Manage user-defined hooks (test them, see which are loaded)",
    )
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command", required=True)
    hooks_test = hooks_sub.add_parser(
        "test",
        help="Fire a synthetic event against loaded hooks and print the results",
    )
    hooks_test.add_argument(
        "event",
        help="Event name to fire (e.g. pre_tool_call, pre_compact, pre_subagent)",
    )
    hooks_test.add_argument(
        "--payload",
        default=None,
        help="Optional JSON payload to merge into the synthetic event (default: minimal)",
    )
    hooks_test.add_argument(
        "--path",
        type=Path,
        default=None,
        dest="charm_path",
        help="Repo root for cantrip.hooks.yaml discovery (default: CWD)",
    )

    # ── skill (Phase 50.2) ────────────────────────────────────────────
    skill_parser = subparsers.add_parser(
        "skill",
        help="Manage Cantrip skills (export them in the standard SKILL.md format)",
    )
    skill_sub = skill_parser.add_subparsers(dest="skill_command", required=True)
    skill_export = skill_sub.add_parser(
        "export",
        help="Write a discovered skill to a file in standard SKILL.md format",
    )
    skill_export.add_argument(
        "name",
        help="Name of the skill to export (as shown in `index.list_skills()`)",
    )
    skill_export.add_argument(
        "path",
        type=Path,
        help=(
            "Output path. A '.md' path is written verbatim; any other path is "
            "treated as a directory and the file is written as <path>/<name>/SKILL.md."
        ),
    )
    skill_export.add_argument(
        "--charm-path",
        type=Path,
        default=None,
        dest="charm_path",
        help=(
            "Path whose occurrences are scrubbed to <CHARM_PATH> in the exported body "
            "(default: no charm-path scrubbing; secret scrubbing still runs)"
        ),
    )
    skill_export.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target file if it already exists",
    )

    # ── checkpoints (Phase 52.5) ──────────────────────────────────────
    checkpoints_parser = subparsers.add_parser(
        "checkpoints",
        help=(
            "Inspect and surgically remove step-level durable-execution "
            "checkpoints stored under a session's .cantrip file"
        ),
    )
    checkpoints_parser.add_argument(
        "--db",
        type=Path,
        default=Path(".cantrip"),
        help="Path to the .cantrip session file (default: ./.cantrip)",
    )
    checkpoints_sub = checkpoints_parser.add_subparsers(dest="checkpoints_command", required=True)
    cps_list = checkpoints_sub.add_parser(
        "list",
        help="List checkpoint rows for a task (or all tasks).",
    )
    cps_list.add_argument(
        "--task-id",
        default=None,
        help="Filter to a single task id (default: list every task with checkpoints)",
    )
    cps_show = checkpoints_sub.add_parser(
        "show",
        help="Pretty-print one stored checkpoint blob as JSON.",
    )
    cps_show.add_argument("task_id", help="Task id the checkpoint belongs to")
    cps_show.add_argument("step_name", help="Step name, e.g. llm_turn or tool:read_file")
    cps_show.add_argument("ordinal", type=int, help="1-based ordinal within the step")
    cps_delete = checkpoints_sub.add_parser(
        "delete",
        help="Delete every checkpoint for a task.",
    )
    cps_delete.add_argument(
        "--task-id",
        required=True,
        help="Task id whose checkpoints should be purged",
    )
    cps_delete.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )

    # ── audit (Phase 80.4) ────────────────────────────────────────────
    audit_parser = subparsers.add_parser(
        "audit",
        help="Inspect the JSONL policy-decision audit trail written by the subagent",
    )
    audit_parser.add_argument(
        "--path",
        type=Path,
        default=None,
        dest="audit_path",
        help=(
            "Path to the audit file (default: ``<cwd>/.cantrip-audit.jsonl``). "
            "Matches the file the subagent writes under ``context.charm_path``."
        ),
    )
    audit_sub = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_list = audit_sub.add_parser(
        "list",
        help="Print audit lines filtered by task, action, or tool.",
    )
    audit_list.add_argument("--task-id", default=None, help="Filter to a single task id.")
    audit_list.add_argument(
        "--action",
        default=None,
        choices=("allowed", "denied", "review-requested", "rate-limited"),
        help="Filter to one action kind.",
    )
    audit_list.add_argument(
        "--tool",
        default=None,
        help="Filter to a single tool name (exact match).",
    )
    audit_export = audit_sub.add_parser(
        "export",
        help="Re-emit the audit trail in a different format (jsonl passthrough or csv).",
    )
    audit_export.add_argument(
        "--format",
        default="jsonl",
        choices=("jsonl", "csv"),
        help="Output format (default: jsonl, which passes through unchanged).",
    )

    # When the first positional argument is not a known subcommand, treat
    # the entire argv as arguments to the "run" sub-parser.  This lets
    # ``cantrip /path/to/charm`` and ``cantrip --no-tui`` work without
    # requiring an explicit ``run`` subcommand.
    _subcommands = {
        "run",
        "export-transcript",
        "compare",
        "hooks",
        "skill",
        "checkpoints",
        "audit",
    }
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


def _hooks_test(args: argparse.Namespace) -> int:
    """Fire a synthetic event against the user's configured hooks.

    Useful when authoring a hook config: ``cantrip hooks test
    pre_tool_call --payload '{"tool": "git_push"}'`` tells you at a
    glance whether the ``if:`` filter would match, whether the hook
    exits cleanly, and how long it takes — no need to stand up a live
    agent session.
    """
    import asyncio
    import json

    from cantrip.hooks import HookEvent, HookRunner

    try:
        event = HookEvent(args.event)
    except ValueError:
        valid = ", ".join(sorted(e.value for e in HookEvent))
        print(f"Unknown event {args.event!r}. Valid events: {valid}", file=sys.stderr)
        return 2

    # Validate --payload up front — it's a CLI-argument error that's
    # independent of config state, and we don't want it hidden behind
    # the "no hooks configured" early return.
    payload: dict[str, object] = {}
    if args.payload:
        try:
            parsed = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            print(f"--payload must be valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("--payload must parse to a JSON object", file=sys.stderr)
            return 2
        payload.update(parsed)

    repo_root = args.charm_path or Path.cwd()
    runner = HookRunner.from_disk(repo_root=repo_root)

    if runner.hook_count == 0:
        print("No hooks are configured.")
        print("  - user config: ~/.config/cantrip/hooks.yaml (or $CANTRIP_HOOKS_USER_CONFIG)")
        print(f"  - repo config: {repo_root / 'cantrip.hooks.yaml'}")
        return 0

    matching = runner.hooks_for(event)
    print(f"Firing `{event.value}` against {len(matching)} matching hook(s).")
    if not matching:
        print("No hooks registered for that event — nothing to do.")
        return 0

    results = asyncio.run(runner.fire(event, payload))

    if not results:
        print("Every matching hook was filtered out by its `if:` expression.")
        return 0

    for result in results:
        mark = "✓" if result.succeeded else ("∅" if result.vetoed else "✗")
        print(
            f"  {mark} {result.name} — exit {result.exit_code} "
            f"in {result.duration_seconds * 1000:.0f}ms"
            + (" (timed out)" if result.timed_out else "")
            + (" (VETO)" if result.vetoed else "")
        )
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                print(f"      stdout: {line}")
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                print(f"      stderr: {line}")
    return 0


def _skill_export(args: argparse.Namespace) -> int:
    """Export a discovered skill to a SKILL.md file (Phase 50.2).

    Uses the default :class:`SkillsIndex` — bundled + external dirs — so a
    user can round-trip their own ``~/.config/cantrip/skills/<foo>/SKILL.md``
    skill through the export step to, say, paste a sanitised copy into a
    gist or PR.
    """
    from cantrip.agent import skill_export
    from cantrip.agent.skills import SkillsIndex

    index = SkillsIndex()
    index.discover()

    try:
        result = skill_export.export_skill(
            args.name,
            args.path,
            index=index,
            charm_path=args.charm_path,
            force=args.force,
        )
    except skill_export.SkillExportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Exported {result.name!r} to {result.output_path}")
    if result.redactions:
        print(f"Redacted {result.redactions} secret-pattern match(es).")
    return 0


def _checkpoints(args: argparse.Namespace) -> int:
    """Dispatch ``cantrip checkpoints {list,show,delete}`` (Phase 52.5)."""
    from cantrip.agent import durability as durability_mod
    from cantrip.agent import store as store_mod

    db_path: Path = args.db
    if not db_path.exists():
        print(f"Error: {db_path} does not exist.", file=sys.stderr)
        return 2

    session_store = store_mod.SessionStore(db_path)
    session_store.open()
    cps = durability_mod.CheckpointStore(session_store)
    try:
        if args.checkpoints_command == "list":
            return _checkpoints_list(session_store, cps, args.task_id)
        if args.checkpoints_command == "show":
            return _checkpoints_show(cps, args.task_id, args.step_name, args.ordinal)
        if args.checkpoints_command == "delete":
            return _checkpoints_delete(cps, args.task_id, args.yes)
        print(f"Unknown checkpoints subcommand: {args.checkpoints_command}", file=sys.stderr)
        return 2
    finally:
        session_store.close()


def _checkpoints_list(
    session_store: store_mod.SessionStore,
    cps: durability_mod.CheckpointStore,
    task_id: str | None,
) -> int:
    """Print a compact table of checkpoint rows for one or every task."""
    if task_id is None:
        tasks = session_store.load_tasks()
        task_ids = [t.id for t in tasks if cps.count_for_task(t.id) > 0]
        titles = {t.id: t.title for t in tasks}
    else:
        task_ids = [task_id]
        titles = {task_id: ""}

    if not task_ids:
        print("No tasks with checkpoints.")
        return 0

    for tid in task_ids:
        records = cps.list_for_task(tid)
        if not records:
            if task_id is not None:
                print(f"No checkpoints for task {tid!r}.")
            continue
        header = f"{titles.get(tid, '')}  ({tid}, {len(records)} step(s))".strip()
        print(header)
        print("-" * len(header))
        for r in records:
            hash_prefix = (r.input_hash or "(none)")[:12]
            print(f"  {r.step_name}#{r.ordinal}  {r.kind:<13} {hash_prefix:<12} {r.created_at}")
        print()
    return 0


def _checkpoints_show(
    cps: durability_mod.CheckpointStore,
    task_id: str,
    step_name: str,
    ordinal: int,
) -> int:
    """Pretty-print one stored blob as JSON (or base64 for KIND_BYTES)."""
    import base64
    import json

    from cantrip.agent.durability import KIND_BYTES

    record = cps.get(task_id, step_name, ordinal)
    if record is None:
        print(
            f"Error: no checkpoint for ({task_id!r}, {step_name!r}, {ordinal}).",
            file=sys.stderr,
        )
        return 1

    print(
        f"Task:       {record.task_id}\n"
        f"Step:       {record.step_name}#{record.ordinal}\n"
        f"Kind:       {record.kind}\n"
        f"Input hash: {record.input_hash or '(none)'}\n"
        f"Created:    {record.created_at}"
    )
    print("-" * 40)
    if record.kind == KIND_BYTES:
        print(f"(bytes, {len(record.blob)} bytes; base64):")
        print(base64.b64encode(record.blob).decode("ascii"))
        return 0
    try:
        decoded = record.decode()
    except json.JSONDecodeError as exc:
        print(f"Error: stored blob is not valid JSON: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(decoded, indent=2, sort_keys=True, default=str))
    return 0


def _checkpoints_delete(
    cps: durability_mod.CheckpointStore,
    task_id: str,
    yes: bool,
) -> int:
    """Purge every checkpoint row for *task_id* after confirmation."""
    count = cps.count_for_task(task_id)
    if count == 0:
        print(f"No checkpoints to delete for task {task_id!r}.")
        return 0
    if not yes:
        reply = input(f"Delete {count} checkpoint(s) for task {task_id!r}? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1
    removed = cps.purge_task(task_id)
    print(f"Removed {removed} checkpoint(s) for task {task_id!r}.")
    return 0


def _audit(args: argparse.Namespace) -> int:
    """Phase 80.4: read and filter the JSONL audit trail.

    The writer in ``cantrip.agent.subagent`` appends one line per
    policy decision to ``<charm>/.cantrip-audit.jsonl``.  This
    subcommand reads that file (from ``--path`` or the default
    ``<cwd>/.cantrip-audit.jsonl``), applies the user's filter
    chain, and prints the result — either as the raw JSONL (so the
    output composes with ``grep`` / ``jq``) or as CSV for
    spreadsheet import.
    """
    import csv

    from cantrip.agent.audit import AUDIT_FILENAME, filter_entries, read_entries

    path: Path = args.audit_path or Path.cwd() / AUDIT_FILENAME
    if not path.is_file():
        print(f"Audit file not found: {path}", file=sys.stderr)
        return 1

    entries = list(read_entries(path))
    if args.audit_command == "list":
        filtered = filter_entries(
            entries,
            task_id=args.task_id,
            action=args.action,
            tool=args.tool,
        )
        for entry in filtered:
            print(entry.to_json())
        return 0

    if args.audit_command == "export":
        if args.format == "jsonl":
            for entry in entries:
                print(entry.to_json())
            return 0
        # CSV: one row per entry, arguments JSON-encoded into the
        # last column so the row stays rectangular even when
        # different tools carry different argument shapes.
        writer = csv.writer(sys.stdout)
        writer.writerow(
            ["timestamp", "task_id", "tool", "action", "policy_name", "reason", "arguments"]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.timestamp,
                    entry.task_id or "",
                    entry.tool,
                    entry.action.value,
                    entry.policy_name,
                    entry.reason,
                    json.dumps(entry.arguments, sort_keys=True, ensure_ascii=False),
                ]
            )
        return 0

    print(f"Unknown audit subcommand: {args.audit_command}", file=sys.stderr)
    return 2


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.command == "export-transcript":
        return _export_transcript(args)
    if args.command == "compare":
        return _compare_charms(args)
    if args.command == "hooks":
        if args.hooks_command == "test":
            return _hooks_test(args)
        print(f"Unknown hooks subcommand: {args.hooks_command}", file=sys.stderr)
        return 2
    if args.command == "skill":
        if args.skill_command == "export":
            return _skill_export(args)
        print(f"Unknown skill subcommand: {args.skill_command}", file=sys.stderr)
        return 2
    if args.command == "checkpoints":
        return _checkpoints(args)
    if args.command == "audit":
        return _audit(args)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
