#!/usr/bin/env bash
# Asciinema script: charmlint walkthrough.
# Run via: asciinema rec --command demos/recordings/charmlint.sh demos/recordings/charmlint.cast
set -e
cd "$(git rev-parse --show-toplevel)"
. demos/recordings/_play.sh

clear

note "charmlint — standalone Juju charm linter, ships with cantrip"
pause 0.8

run "uv run charmlint --help | head -15"
pause 1.6

note ""
note "Lint a real charm — the gold-standard ntfy reference"
pause 0.6
run "uv run charmlint tests/eval/charms/ntfy/gold-claude"
pause 2.0

note ""
note "Filter to a single category — observability rules only"
pause 0.6
run "uv run charmlint --select COS tests/eval/charms/ntfy/gold-claude"
pause 1.6

note ""
note "Machine-readable JSON for tools and CI"
pause 0.6
run "uv run charmlint --format=json --select META tests/eval/charms/ntfy/gold-claude | head -20"
pause 1.8

note ""
note "Strict mode turns warnings into a non-zero exit — gate it in CI"
pause 0.6
run "uv run charmlint --strict --select COS tests/eval/charms/ntfy/gold-claude; echo exit=\$?"
pause 1.8
