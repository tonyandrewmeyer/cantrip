#!/usr/bin/env -S uvx --with pexpect python
"""Drive the cantrip TUI through scripted keypresses for an asciinema capture.

Usage (recommended — outer asciinema captures the proxied output):
    asciinema rec --command demos/recordings/_tui_driver.py out.cast

The driver spawns ``cantrip run`` against a pre-built sample charm, waits
for Textual to finish its initial paint, then walks a fixed sequence of
function-key toggles and slash commands. Output is mirrored to
``sys.stdout`` so asciinema records every frame Textual draws.

All steps are deterministic (sleep-driven) so the timing of the resulting
cast is consistent across re-runs.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

import pexpect

CHARM = pathlib.Path.home() / "tui-demo"
COLS = 110
ROWS = 32


def _repo_root() -> pathlib.Path:
    """Walk up from this file to find the cantrip checkout."""
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    # Fall back to ``git rev-parse`` against CWD — handles loose checkouts
    # of demos/ that sit outside a real cantrip clone.
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return pathlib.Path(out.stdout.strip())


REPO = _repo_root()


def _send(p: pexpect.spawn, keys: str, hold: float = 1.6) -> None:
    """Send *keys* to the TUI then sleep so the new frame is recorded."""
    p.send(keys)
    time.sleep(hold)


def main() -> int:
    if not CHARM.exists():
        sys.stderr.write(f"missing scaffold: {CHARM}\n")
        return 2

    env = os.environ | {
        "TERM": "xterm-256color",
        "COLUMNS": str(COLS),
        "LINES": str(ROWS),
        "CANTRIP_DISABLE_UPDATE_CHECK": "1",
    }

    cmd = [
        "uv",
        "run",
        "--project",
        str(REPO),
        "cantrip",
        "run",
        str(CHARM),
        "--provider",
        "gemini",
        "--theme",
        "cantrip",
    ]
    p = pexpect.spawn(
        cmd[0],
        cmd[1:],
        env=env,
        encoding="utf-8",
        dimensions=(ROWS, COLS),
        timeout=120,
    )
    p.logfile_read = sys.stdout

    # Generous initial wait — preflight checks can take several seconds.
    time.sleep(8.0)

    # 1) Show the help overlay (F1).
    _send(p, "\x1bOP", 2.5)  # F1
    _send(p, "\x1b", 1.2)  # close

    # 2) Toggle the model-info pane on / off (F7).
    _send(p, "\x1b[18~", 2.0)  # F7
    _send(p, "\x1b[18~", 1.2)  # F7 again to close

    # 3) Toggle the watcher pane (F5).
    _send(p, "\x1b[15~", 2.0)
    _send(p, "\x1b[15~", 1.2)

    # 4) Toggle the transcript pane (F9).
    _send(p, "\x1b[20~", 2.0)
    _send(p, "\x1b[20~", 1.2)

    # 5) Slash command: /memory list (read-only memory listing).
    for ch in "/memory list":
        _send(p, ch, 0.05)
    _send(p, "\r", 2.5)

    # 6) Slash command: /cost — token usage table.
    for ch in "/cost":
        _send(p, ch, 0.05)
    _send(p, "\r", 2.8)

    # 7) Slash command: /map — repository map.
    for ch in "/map":
        _send(p, ch, 0.05)
    _send(p, "\r", 3.0)

    # 8) Quit cleanly with q (or Ctrl+C, then 'y').
    _send(p, "q", 1.5)

    p.expect(pexpect.EOF, timeout=10)
    return p.exitstatus or 0


if __name__ == "__main__":
    sys.exit(main())
