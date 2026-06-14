#!/usr/bin/env python3
"""Speed up an asciicast file by scaling its event timestamps.

Asciinema v2 cast files are JSONL: the first line is a metadata
dict; every subsequent line is ``[t_seconds, "o", "data"]``.  Scaling
``t_seconds`` by ``1/factor`` makes the playback ``factor``× faster
without re-encoding the terminal output.

Usage:
    _speedup.py <input.cast> <output.cast> --factor 6.0
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("input", type=pathlib.Path, help="source asciicast")
    p.add_argument("output", type=pathlib.Path, help="destination asciicast")
    p.add_argument(
        "--factor",
        type=float,
        default=6.0,
        help="speedup multiplier (default 6.0 — turns 30 min into 5)",
    )
    p.add_argument(
        "--idle-cap",
        type=float,
        default=2.0,
        help=(
            "Cap any single event's gap from the previous event at this "
            "many seconds (post-scale) so long quiet periods don't drag "
            "the playback.  Default 2.0; pass 0 to disable."
        ),
    )
    args = p.parse_args()

    if args.factor <= 0:
        sys.stderr.write("--factor must be > 0\n")
        return 2

    with args.input.open() as src, args.output.open("w") as dst:
        header_line = src.readline()
        if not header_line:
            sys.stderr.write(f"empty cast: {args.input}\n")
            return 2
        header = json.loads(header_line)
        if header.get("version") != 2:
            sys.stderr.write(f"only asciicast v2 supported (got v{header.get('version')})\n")
            return 2
        # Preserve idle_time_limit if present so the player still knows.
        dst.write(json.dumps(header) + "\n")

        prev_scaled = 0.0
        prev_raw = 0.0
        for line in src:
            if not line.strip():
                continue
            ev = json.loads(line)
            raw_t = float(ev[0])
            scaled = raw_t / args.factor
            if args.idle_cap > 0:
                # Cap the inter-event gap (post-scale) so we don't sit
                # on dead air longer than necessary.
                gap = scaled - prev_scaled
                if gap > args.idle_cap:
                    scaled = prev_scaled + args.idle_cap
            ev[0] = round(scaled, 6)
            dst.write(json.dumps(ev) + "\n")
            prev_scaled = scaled
            prev_raw = raw_t

    sys.stdout.write(
        f"scaled {args.input.name}: {prev_raw:.1f}s -> "
        f"{prev_scaled:.1f}s (factor {args.factor}, idle-cap {args.idle_cap}s)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
