"""Command-line interface for charmlint."""

import argparse
import json
import sys
from pathlib import Path

from charmlint.config import load_config
from charmlint.linter import lint
from charmlint.models import Severity


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="charmlint",
        description="Lint a Juju charm for best practices, observability, testing, and more.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the charm directory (default: current directory)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--select",
        help="Comma-separated list of rule categories to enable (e.g. COS,META)",
    )
    parser.add_argument(
        "--ignore",
        help="Comma-separated list of rule IDs or categories to skip",
    )
    parser.add_argument(
        "--severity",
        choices=["error", "warning", "info"],
        help="Minimum severity to report",
    )
    parser.add_argument(
        "--config",
        help="Path to .charmlint.yaml config file",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 if warnings are found (default: only errors cause non-zero exit)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the charmlint CLI. Returns the exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    charm_dir = Path(args.path).resolve()
    if not charm_dir.is_dir():
        print(f"Error: {args.path} is not a directory", file=sys.stderr)
        return 1

    # Load config from file, then overlay CLI flags.
    config_path = Path(args.config) if args.config else None
    config = load_config(charm_dir, config_path)

    if args.select:
        config.select = [s.strip() for s in args.select.split(",")]
    if args.ignore:
        config.ignore.extend(s.strip() for s in args.ignore.split(","))
    if args.severity:
        config.min_severity = Severity(args.severity)

    report = lint(charm_dir, config)

    if args.output_format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for diagnostic in report.diagnostics:
            print(diagnostic.format_text(charm_dir))
        if report.diagnostics:
            print()
        print(report.summary_line())

    # Exit codes.
    if report.error_count > 0:
        return 1
    if args.strict and report.warning_count > 0:
        return 2
    return 0


def cli_entry() -> None:
    """Entry point for the ``charmlint`` console script."""
    sys.exit(main())
