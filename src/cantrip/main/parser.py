"""Argument parsing for the ``cantrip`` CLI.

Builds the top-level :class:`argparse.ArgumentParser` plus every
subcommand parser.  ``parse_args`` is the only public entry point;
the ``_add_*_subparser`` and ``_add_run_*_options`` helpers are split
purely so the giant ``run`` subcommand stays comprehensible.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from cantrip import __version__

# Type alias for the value returned by ``ArgumentParser.add_subparsers``.
# Spelt out so the per-subcommand helpers below can be annotated; the
# runtime class is private but ``from __future__ import annotations``
# defers evaluation of annotations.
_SubParsers = argparse._SubParsersAction


_SUBCOMMANDS = frozenset(
    {
        "run",
        "export-transcript",
        "compare",
        "hooks",
        "skill",
        "checkpoints",
        "docs",
        "audit",
        "permissions",
    }
)


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
    _add_run_subparser(subparsers)
    _add_compare_subparser(subparsers)
    _add_export_transcript_subparser(subparsers)
    _add_hooks_subparser(subparsers)
    _add_skill_subparser(subparsers)
    _add_checkpoints_subparser(subparsers)
    _add_docs_subparser(subparsers)
    _add_audit_subparser(subparsers)
    _add_permissions_subparser(subparsers)

    return parser.parse_args(_normalise_argv(sys.argv[1:]))


def _normalise_argv(argv: list[str]) -> list[str]:
    """Treat a missing or non-subcommand first arg as ``cantrip run``.

    Lets ``cantrip /path/to/charm`` and ``cantrip --no-tui`` work without an
    explicit ``run`` subcommand, while still routing real subcommands to
    their parsers.
    """
    if (
        not argv
        or (argv[0] not in _SUBCOMMANDS and not argv[0].startswith("-"))
        or (argv[0].startswith("-") and argv[0] not in ("--version", "-h", "--help"))
    ):
        return ["run", *argv]
    return list(argv)


def _add_run_subparser(subparsers: _SubParsers) -> None:
    """Build the default ``run`` subcommand."""
    run_parser = subparsers.add_parser("run", help="Run cantrip agent")
    _add_run_model_options(run_parser)
    _add_run_session_options(run_parser)
    _add_run_budget_options(run_parser)
    _add_run_loop_options(run_parser)
    _add_run_print_options(run_parser)
    _add_run_appearance_options(run_parser)
    run_parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="Path to charm project (default: current directory)",
    )


def _add_run_model_options(parser: argparse.ArgumentParser) -> None:
    """Provider, model, and Phase 72.3 role-router selection."""
    parser.add_argument(
        "--provider",
        choices=[
            "gemini",
            "claude",
            "inference-snap",
            "fireworks",
            "openrouter",
            "opencode-zen",
            "openai-compatible",
        ],
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
        help=("Inference snap name when using --provider inference-snap (default: gemma3)"),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "API base URL override.  Required for --provider "
            "openai-compatible; optional for inference-snap (overrides "
            "snap discovery) and fireworks (proxies or compatible hosts)."
        ),
    )
    parser.add_argument(
        "--light-model",
        help=("Cheaper model for internal tasks like compaction (auto-detected if omitted)"),
    )
    parser.add_argument(
        "--light-snap",
        help="Lighter inference snap for internal tasks (e.g. nemotron-3-nano)",
    )
    parser.add_argument(
        "--light-provider",
        choices=[
            "gemini",
            "claude",
            "inference-snap",
            "fireworks",
            "openrouter",
            "opencode-zen",
        ],
        help="Use a different provider for light tasks (enables hybrid mode)",
    )
    parser.add_argument(
        "--embed-provider",
        choices=["voyage", "openai"],
        help=(
            "Phase 72.3: provider for the ``embed`` role (used by retrieval "
            "features such as ``@docs`` and memory recall).  Also settable "
            "via the ``CANTRIP_EMBED_PROVIDER`` env var."
        ),
    )
    parser.add_argument(
        "--embed-model",
        help=(
            "Phase 72.3: embed model identifier (e.g. ``voyage-3``, "
            "``text-embedding-3-small``).  Defaults vary per provider; "
            "also settable via ``CANTRIP_EMBED_MODEL``."
        ),
    )
    parser.add_argument(
        "--rerank-provider",
        choices=["voyage"],
        help=(
            "Phase 72.3: provider for the ``rerank`` role.  Voyage is the "
            "only first-class option today; OpenAI users pair its embeds "
            "with Voyage rerank.  Also settable via "
            "``CANTRIP_RERANK_PROVIDER``."
        ),
    )
    parser.add_argument(
        "--rerank-model",
        help=(
            "Phase 72.3: rerank model identifier (e.g. ``rerank-2``, "
            "``rerank-2-lite``).  Also settable via "
            "``CANTRIP_RERANK_MODEL``."
        ),
    )


def _add_run_session_options(parser: argparse.ArgumentParser) -> None:
    """How the session surfaces to the user — TUI, Web UI, or headless CLI."""
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run in CLI mode without TUI",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run with a browser-based Web UI instead of the TUI",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8471,
        help="Port for the Web UI (default: 8471)",
    )
    parser.add_argument(
        "--objective",
        type=str,
        default=None,
        metavar="TEXT",
        help=(
            "Free-text user-prose objective for the session, e.g. "
            '``--objective "build a Postgres charm with COS plus '
            'Pebble notices"``.  Stored on the session and used by '
            "Ralph re-feed and goal-aware status surfaces in place of "
            "the ``--charm-name`` + ``--charm-type`` paraphrase.  "
            "Update mid-session with ``/goal``."
        ),
    )


def _add_run_budget_options(parser: argparse.ArgumentParser) -> None:
    """Per-goal hard caps that block the work queue when exceeded."""
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Maximum concurrent subagent tasks (default: 3)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        dest="max_iterations",
        help=(
            "Per-goal budget: hard cap on LLM request count before the "
            "work queue blocks.  Also settable via "
            "``CANTRIP_MAX_ITERATIONS`` env var."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        dest="max_tokens",
        help=(
            "Per-goal budget: hard cap on total (prompt + completion) "
            "tokens before the work queue blocks.  Splits evenly across "
            "prompt and completion caps.  Also settable via "
            "``CANTRIP_MAX_TOKENS`` env var."
        ),
    )


def _add_run_loop_options(parser: argparse.ArgumentParser) -> None:
    """Toggles that change how the autonomous loop behaves each turn.

    Covers improve mode, snapshotting, per-edit linting, YOLO, the Ralph
    iterate-until-green loop, the architect/editor split, and per-turn
    auto-commit.
    """
    parser.add_argument(
        "--improve",
        type=pathlib.Path,
        default=None,
        metavar="CHARM_PATH",
        help="Improve an existing charm at the given path (audit, fix, redeploy)",
    )
    parser.add_argument(
        "--no-snapshots",
        action="store_true",
        dest="no_snapshots",
        help=(
            "Disable per-turn working-tree snapshots.  By default "
            "Cantrip commits the charm tree into a hidden git repo "
            "before every user turn so `/undo` and `/redo` can roll "
            "back agent edits.  Use this flag (or set "
            "`CANTRIP_SNAPSHOTS=false`) when working in a monorepo "
            "where snapshotting is too slow."
        ),
    )
    parser.add_argument(
        "--no-auto-lint",
        action="store_true",
        dest="no_auto_lint",
        help=(
            "Disable per-edit lint feedback.  By default Cantrip "
            "runs ``ruff`` and ``ty`` on every Python file the "
            "agent writes, and ``charmlint`` on charm YAML, then "
            "appends the diagnostics to the tool result so the "
            "agent reacts in the same turn.  Use this flag when "
            "the linters are unavailable or the feedback is "
            "noisy in your workflow."
        ),
    )
    parser.add_argument(
        "--yolo",
        "-y",
        action="store_true",
        dest="yolo",
        help=(
            "Unattended mode: auto-approve every `ask` permission "
            "for the session so CI scripts don't stall on prompts.  "
            "`deny` rules still block — review your `permissions.yaml` "
            "before a destructive run.  Toggle mid-session with "
            "`/yolo`."
        ),
    )
    parser.add_argument(
        "--ralph",
        type=int,
        default=0,
        dest="ralph_max_iterations",
        metavar="N",
        help=(
            "Bounded iterate-until-green Ralph Loop.  Re-seed the "
            "agent up to N times until it emits ``STOP`` on a line "
            "by itself or stall detection trips.  0 (default) "
            "disables the loop; -1 is unlimited (still bounded by "
            "stall detection and an internal safety ceiling).  Most "
            "useful in ``--print`` runs."
        ),
    )
    parser.add_argument(
        "--architect",
        action="store_true",
        dest="architect",
        help=(
            "Phase 71.2 architect/editor two-model split.  Each "
            "agent turn runs in two passes: an *architect* pass on "
            "the main model proposes the change in plain prose, "
            "then a cheaper *editor* pass turns the proposal into "
            "actual tool calls.  Both passes appear separately in "
            "``/cost``.  Toggle mid-session with ``/architect``; "
            "override the editor with "
            "``/architect on <provider>/<model>``."
        ),
    )
    parser.add_argument(
        "--editor-provider",
        dest="editor_provider",
        default=None,
        metavar="NAME",
        help=(
            "Override the editor provider for ``--architect``.  Useful "
            "for hybrid configurations like architect=Claude, "
            "editor=Gemini-Flash.  Ignored without ``--architect``."
        ),
    )
    parser.add_argument(
        "--editor-model",
        dest="editor_model",
        default=None,
        metavar="SLUG",
        help=(
            "Override the editor model slug for ``--architect``.  "
            "Defaults to the configured editor provider's default "
            "model.  Ignored without ``--architect``."
        ),
    )
    parser.add_argument(
        "--no-auto-commit",
        action="store_true",
        dest="no_auto_commit",
        help=(
            "Disable Phase 71.3 per-turn auto-commit.  By default "
            "every turn that mutates files lands as a discrete git "
            "commit in the charm repo with a Cantrip co-author "
            "trailer; pre-existing dirty work commits separately "
            "as ``chore(pre-cantrip)``.  Use this flag (or "
            "``/auto-commit off`` mid-session) when you prefer to "
            "batch agent edits into your own commits."
        ),
    )


def _add_run_print_options(parser: argparse.ArgumentParser) -> None:
    """Non-interactive print mode for scripted/CI invocations."""
    parser.add_argument(
        "--print",
        "-p",
        dest="print_goal",
        default=None,
        metavar="GOAL",
        help=(
            "Non-interactive print mode.  Run the autonomous loop to "
            "accomplish ``<GOAL>`` without a TUI; emit progress to "
            "stdout and exit when the work queue drains.  Combine with "
            "``--json`` for a script-friendly NDJSON event stream and "
            "``--yolo`` for unattended CI runs that auto-approve every "
            "ask permission."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit ``cantrip.ui.events`` payloads as newline-delimited "
            "JSON on stdout, one event per line.  Only honoured with "
            "``--print``.  See ``docs/docs/reference-cli.html`` for "
            "the documented event schema."
        ),
    )


def _add_run_appearance_options(parser: argparse.ArgumentParser) -> None:
    """TUI look & feel."""
    parser.add_argument(
        "--theme",
        type=str,
        default=None,
        help="TUI colour theme (cantrip, ubuntu, monokai, solarized-dark, light)",
    )


def _add_compare_subparser(subparsers: _SubParsers) -> None:
    """Phase 31.7 — diff two charm implementations side by side."""
    compare_parser = subparsers.add_parser(
        "compare",
        help="Diff two charm implementations (structure, config, relations, tests)",
    )
    compare_parser.add_argument(
        "left",
        type=pathlib.Path,
        help="First charm directory",
    )
    compare_parser.add_argument(
        "right",
        type=pathlib.Path,
        help="Second charm directory",
    )


def _add_export_transcript_subparser(subparsers: _SubParsers) -> None:
    """Render a session's `.cantrip` file as HTML / JSONL / Markdown."""
    export_parser = subparsers.add_parser(
        "export-transcript",
        help="Export a session transcript",
    )
    export_parser.add_argument(
        "path",
        type=pathlib.Path,
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
        type=pathlib.Path,
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
        "--branch",
        type=int,
        default=None,
        dest="filter_branch",
        help="Export the conversation path leading to a specific turn id "
        "(default: the currently active branch)",
    )
    export_parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        dest="page_size",
        help="Split HTML output into pages of N conversation messages each",
    )


def _add_hooks_subparser(subparsers: _SubParsers) -> None:
    """Phase 46.5 — manage user-defined hooks (the ``cantrip hooks`` group)."""
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
        type=pathlib.Path,
        default=None,
        dest="charm_path",
        help="Repo root for cantrip.hooks.yaml discovery (default: CWD)",
    )


def _add_skill_subparser(subparsers: _SubParsers) -> None:
    """Phase 50.2 — export discovered skills in the standard SKILL.md format."""
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
        type=pathlib.Path,
        help=(
            "Output path. A '.md' path is written verbatim; any other path is "
            "treated as a directory and the file is written as <path>/<name>/SKILL.md."
        ),
    )
    skill_export.add_argument(
        "--charm-path",
        type=pathlib.Path,
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


def _add_checkpoints_subparser(subparsers: _SubParsers) -> None:
    """Phase 52.5 — inspect and surgically remove durable-execution checkpoints."""
    checkpoints_parser = subparsers.add_parser(
        "checkpoints",
        help=(
            "Inspect and surgically remove step-level durable-execution "
            "checkpoints stored under a session's .cantrip file"
        ),
    )
    checkpoints_parser.add_argument(
        "--db",
        type=pathlib.Path,
        default=pathlib.Path(".cantrip"),
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


def _add_docs_subparser(subparsers: _SubParsers) -> None:
    """Phase 72.1 — index Canonical doc sites for retrieval."""
    docs_parser = subparsers.add_parser(
        "docs",
        help=(
            "Index Canonical documentation sites for retrieval via "
            "@docs and the docs_search tool (Phase 72.1)"
        ),
    )
    docs_sub = docs_parser.add_subparsers(dest="docs_command", required=True)
    docs_index_p = docs_sub.add_parser("index", help="Crawl and index a doc site")
    docs_index_p.add_argument(
        "--site",
        help="Site name (juju, ops, charmcraft, rockcraft, jubilant, charmhub)",
    )
    docs_index_p.add_argument(
        "--all",
        action="store_true",
        dest="all_sites",
        help="Index every registered site (mutually exclusive with --site)",
    )
    docs_index_p.add_argument(
        "--embed-provider",
        choices=["voyage", "openai"],
        help="Override embed provider for this index run (defaults to env vars)",
    )
    docs_index_p.add_argument(
        "--embed-model",
        help="Override embed model for this index run (defaults to env vars)",
    )
    docs_list_p = docs_sub.add_parser("list", help="List indexed and available sites")
    docs_list_p.add_argument(
        "--root",
        type=pathlib.Path,
        default=None,
        help="Override the cache root (default: ~/.cache/cantrip/docs-index/)",
    )
    docs_search_p = docs_sub.add_parser(
        "search", help="Run a similarity search against an indexed site"
    )
    docs_search_p.add_argument("site", help="Site to search (e.g. ops, juju)")
    docs_search_p.add_argument("query", help="Free-text query string")
    docs_search_p.add_argument(
        "--top-k",
        type=int,
        default=5,
        dest="top_k",
        help="Number of hits to return (default: 5)",
    )


def _add_audit_subparser(subparsers: _SubParsers) -> None:
    """Phase 80.4 — read the JSONL policy-decision audit trail."""
    audit_parser = subparsers.add_parser(
        "audit",
        help="Inspect the JSONL policy-decision audit trail written by the subagent",
    )
    audit_parser.add_argument(
        "--path",
        type=pathlib.Path,
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


def _add_permissions_subparser(subparsers: _SubParsers) -> None:
    """Inspect and test the discovered permission ruleset."""
    permissions_parser = subparsers.add_parser(
        "permissions",
        help="Inspect the permission ruleset (test a hypothetical call, list rules)",
    )
    permissions_sub = permissions_parser.add_subparsers(dest="permissions_command", required=True)
    perms_test = permissions_sub.add_parser(
        "test",
        help="Evaluate a hypothetical tool call against the discovered ruleset",
    )
    perms_test.add_argument(
        "tool",
        help="Tool name to test (e.g. run_command, read_file, juju_status)",
    )
    perms_test.add_argument(
        "--command",
        default=None,
        dest="bash_command",
        help="Bash command string for the `bash` section (only used with run_command-class tools)",
    )
    perms_test.add_argument(
        "--path",
        default=None,
        dest="path_arg",
        help="Path argument for the `paths` section (matched as the tool's path/file_path/filename)",
    )
    perms_test.add_argument(
        "--agent",
        default=None,
        dest="agent_name",
        help="Agent overlay to apply (e.g. RESEARCH, BUILD); matches SubagentContext.task.category.value",
    )
    perms_test.add_argument(
        "--charm-path",
        type=pathlib.Path,
        default=None,
        dest="charm_path",
        help="Repo root for .cantrip/permissions.yaml discovery (default: CWD)",
    )
    perms_test.add_argument(
        "--user-config",
        type=pathlib.Path,
        default=None,
        dest="user_config_dir",
        help="User config directory for permissions.yaml (default: ~/.config/cantrip)",
    )
    perms_test.add_argument(
        "--no-builtin",
        action="store_true",
        help="Skip the built-in safe defaults so only file-loaded rules are evaluated",
    )
    perms_test.add_argument(
        "--show-rules",
        action="store_true",
        help="Also print every loaded rule grouped by section after the verdict",
    )
    perms_list = permissions_sub.add_parser(
        "list",
        help="List every loaded permission rule grouped by section and source",
    )
    perms_list.add_argument(
        "--charm-path",
        type=pathlib.Path,
        default=None,
        dest="charm_path",
        help="Repo root for .cantrip/permissions.yaml discovery (default: CWD)",
    )
    perms_list.add_argument(
        "--user-config",
        type=pathlib.Path,
        default=None,
        dest="user_config_dir",
        help="User config directory for permissions.yaml (default: ~/.config/cantrip)",
    )
    perms_list.add_argument(
        "--no-builtin",
        action="store_true",
        help="Skip the built-in safe defaults so only file-loaded rules are listed",
    )
