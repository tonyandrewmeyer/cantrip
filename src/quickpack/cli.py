"""Command-line interface for quick pack."""

import argparse
import pathlib
import sys
import time

from quickpack import pack as _pack


def main() -> None:
    """Entry point for the ``quickpack`` command."""
    parser = argparse.ArgumentParser(
        prog="quickpack",
        description="Fast local charm packing for development workflows.",
    )
    parser.add_argument(
        "charm_dir",
        nargs="?",
        default=".",
        help="Path to the charm project directory (default: current directory).",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Directory to write the .charm file to (default: charm directory).",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output.",
    )

    args = parser.parse_args()

    charm_dir = pathlib.Path(args.charm_dir).resolve()
    if not charm_dir.is_dir():
        print(f"Error: {charm_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    charmcraft_yaml = charm_dir / "charmcraft.yaml"
    if not charmcraft_yaml.exists():
        print(f"Error: charmcraft.yaml not found in {charm_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir = pathlib.Path(args.output_dir) if args.output_dir else None

    if not args.quiet:
        print(f"Packing charm in {charm_dir} ...")

    start = time.monotonic()
    try:
        charm_path = _pack.quick_pack(charm_dir, output_dir=output_dir)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.monotonic() - start

    if not args.quiet:
        print(f"Created {charm_path.name} in {elapsed:.1f}s")
