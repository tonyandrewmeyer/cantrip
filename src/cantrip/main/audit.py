"""``cantrip audit {list,export}`` handler (Phase 80.4)."""

from __future__ import annotations

import json
import pathlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


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

    path: pathlib.Path = args.audit_path or pathlib.Path.cwd() / AUDIT_FILENAME
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
