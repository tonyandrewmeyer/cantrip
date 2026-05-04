#!/usr/bin/env bash
# Asciinema script: cantrip headless print mode.
set -e
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"
. demos/recordings/_play.sh

CHARM="$HOME/cli-demo"

# Reset session for a clean run.
rm -rf "$CHARM"/.cantrip*

clear

note "cantrip run --print: drive the autonomous loop without a TUI"
note "Drop into a CI script or a shell pipeline."
pause 0.6

run "uv run cantrip run --help 2>&1 | grep -A1 -E 'print|json|yolo' | head -16"
pause 1.6

note ""
note "A focused single-prompt run — Gemini 3 Pro, no TUI, no readline"
pause 0.4
run "cd $CHARM && uv run --project $REPO cantrip run . --provider gemini --print 'Summarise this charm in two sentences. Make no changes.'"
pause 2.0

note ""
note "Same task, --json: NDJSON event stream — one event per line"
note "Same payloads the TUI and Web UI consume."
pause 0.6
run "rm -rf $CHARM/.cantrip* && cd $CHARM && uv run --project $REPO cantrip run . --provider gemini --json --print 'List every dependency. Make no changes.' 2>/dev/null | head -10 | cut -c1-100"
pause 2.5
