"""Cantrip entry point.

The argument parser, the ``run`` dispatcher, and one handler per
subcommand each live in a focused submodule under this package.  This
``__init__`` wires :func:`main` and re-exports the public + monkey-
patchable surface tests rely on so existing ``from cantrip.main import
…`` lines keep working unchanged.
"""

from __future__ import annotations

import sys

# Re-exports.  The redundant ``as`` aliases mark these as intentional
# re-exports for ruff (private symbols are kept available to tests and
# for ``cantrip.main.<name>`` patches that would otherwise break after
# the package extraction).
from cantrip.main.audit import _audit as _audit
from cantrip.main.checkpoints import _checkpoints as _checkpoints
from cantrip.main.checkpoints import _checkpoints_delete as _checkpoints_delete
from cantrip.main.checkpoints import _checkpoints_list as _checkpoints_list
from cantrip.main.checkpoints import _checkpoints_show as _checkpoints_show
from cantrip.main.compare import _compare_charms as _compare_charms
from cantrip.main.hooks_cmd import _hooks_test as _hooks_test
from cantrip.main.parser import _SUBCOMMANDS as _SUBCOMMANDS
from cantrip.main.parser import _add_audit_subparser as _add_audit_subparser
from cantrip.main.parser import _add_checkpoints_subparser as _add_checkpoints_subparser
from cantrip.main.parser import _add_compare_subparser as _add_compare_subparser
from cantrip.main.parser import _add_docs_subparser as _add_docs_subparser
from cantrip.main.parser import (
    _add_export_transcript_subparser as _add_export_transcript_subparser,
)
from cantrip.main.parser import _add_hooks_subparser as _add_hooks_subparser
from cantrip.main.parser import _add_permissions_subparser as _add_permissions_subparser
from cantrip.main.parser import _add_run_appearance_options as _add_run_appearance_options
from cantrip.main.parser import _add_run_budget_options as _add_run_budget_options
from cantrip.main.parser import _add_run_loop_options as _add_run_loop_options
from cantrip.main.parser import _add_run_model_options as _add_run_model_options
from cantrip.main.parser import _add_run_print_options as _add_run_print_options
from cantrip.main.parser import _add_run_session_options as _add_run_session_options
from cantrip.main.parser import _add_run_subparser as _add_run_subparser
from cantrip.main.parser import _add_skill_subparser as _add_skill_subparser
from cantrip.main.parser import _normalise_argv as _normalise_argv
from cantrip.main.parser import parse_args as parse_args
from cantrip.main.permissions import _load_permissions_for_cli as _load_permissions_for_cli
from cantrip.main.permissions import _permissions_list as _permissions_list
from cantrip.main.permissions import _permissions_test as _permissions_test
from cantrip.main.permissions import _print_ruleset as _print_ruleset
from cantrip.main.run import _CANTRIP_PYPROJECT_ENTRY_MARKER as _CANTRIP_PYPROJECT_ENTRY_MARKER
from cantrip.main.run import _CANTRIP_PYPROJECT_NAME_MARKER as _CANTRIP_PYPROJECT_NAME_MARKER
from cantrip.main.run import _install_unraisable_hook as _install_unraisable_hook
from cantrip.main.run import _is_cantrip_source_tree as _is_cantrip_source_tree
from cantrip.main.run import _print_update_panel as _print_update_panel
from cantrip.main.run import _run as _run
from cantrip.main.run import _truncate_notes as _truncate_notes
from cantrip.main.skill_cmd import _skill_export as _skill_export
from cantrip.main.transcript import _export_transcript as _export_transcript

__all__ = [
    "main",
    "parse_args",
]


def main() -> int:
    """Return main entry point."""
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
    if args.command == "permissions":
        if args.permissions_command == "test":
            return _permissions_test(args)
        if args.permissions_command == "list":
            return _permissions_list(args)
        print(
            f"Unknown permissions subcommand: {args.permissions_command}",
            file=sys.stderr,
        )
        return 2
    if args.command == "docs":
        from cantrip.docs_index import cli as docs_cli

        return docs_cli.dispatch(args)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
