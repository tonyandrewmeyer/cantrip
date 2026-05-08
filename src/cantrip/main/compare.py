"""``cantrip compare`` handler."""

from __future__ import annotations

import argparse


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
