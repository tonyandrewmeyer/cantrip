#!/usr/bin/env bash
# Asciinema script: cantrip export-transcript walkthrough.
set -e
cd "$(git rev-parse --show-toplevel)"
. demos/recordings/_play.sh

# The sample session lives in $HOME/sample-charm (outside the 9p mount so
# SQLite WAL mode works during recording). Set up at scaffold time —
# see demos/recordings/README.md.
SESSION="$HOME/sample-charm"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

clear

note "Every cantrip session writes a SQLite transcript to <charm>/.cantrip"
pause 0.6
run "ls -lh $SESSION/.cantrip"
pause 1.4

note ""
note "The export-transcript subcommand turns it into a portable artefact"
run "uv run cantrip export-transcript --help | head -18"
pause 1.8

note ""
note "Markdown export — copy into a bug report or PR description"
pause 0.4
run "uv run cantrip export-transcript $SESSION --format markdown --output $WORK/transcript.md"
pause 0.4
run "wc -l $WORK/transcript.md && head -10 $WORK/transcript.md"
pause 2.2

note ""
note "Filter to a single phase — only research-loop activity"
pause 0.4
run "uv run cantrip export-transcript $SESSION --format markdown --phase research --output $WORK/research.md && wc -l $WORK/research.md"
pause 1.6

note ""
note "JSONL — drop into an eval pipeline or another tool"
pause 0.4
run "uv run cantrip export-transcript $SESSION --format jsonl --output $WORK/transcript.jsonl"
pause 0.4
run "head -3 $WORK/transcript.jsonl | python3 -c 'import json,sys; [print(json.dumps(json.loads(l), indent=2)[:200]+\"...\") for l in sys.stdin]'"
pause 2.2

note ""
note "HTML — paginated, styled, readable in a browser"
pause 0.4
run "uv run cantrip export-transcript $SESSION --format html --page-size 30 --output $WORK/transcript.html"
pause 0.4
run "ls -1 $WORK/*.html | head -3"
pause 1.6

note ""
note "Nothing leaves your machine — transcripts stay local until you share them"
pause 1.5
