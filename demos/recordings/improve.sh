#!/usr/bin/env bash
# Asciinema script: cantrip --improve audit on a deliberately-broken charm.
# Renders both the deterministic charmlint pass (to set up the gap visually)
# and a cantrip --improve --print run that produces the LLM-driven audit.
set -e
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"
. demos/recordings/_play.sh

CHARM="$HOME/broken-charm"

clear

note "A deliberately incomplete charm: no tests, no tracing, no COS, no docs"
pause 0.6
run "ls $CHARM && cat $CHARM/charmcraft.yaml | head -25"
pause 2.4

note ""
note "charmlint surfaces the deterministic gaps in milliseconds"
pause 0.4
run "uv run charmlint --no-color $CHARM 2>&1 | head -22"
pause 2.6

note ""
note "Now hand it to cantrip with --improve and ask for an audit"
note "(real run, real LLM — Gemini 3 Pro)"
pause 0.6
run "cd $CHARM && uv run --project $REPO cantrip run . --improve . --provider gemini --max-iterations 1 --print 'audit this charm and produce a concise prioritised report of the issues you found — do not start work or queue research tasks'"
pause 2.0

note ""
note "From here cantrip would queue fix tasks, branch, and apply them"
note "in disposable subagents. Gate every step with /tasks confirm."
pause 1.5
