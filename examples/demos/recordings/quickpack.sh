#!/usr/bin/env bash
# Asciinema script: quickpack walkthrough.
set -e
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"
. demos/recordings/_play.sh

CHARM=demos/recordings/_assets/qp-demo

# Locate the Rust quickpack binary — checked-in artefacts live under
# stage/ (snap build); a developer build lands under src/quickpack-rs/.
RS=
for cand in stage/src/quickpack-rs/target/release/quickpack src/quickpack-rs/target/release/quickpack; do
    if [ -x "$cand" ]; then
        RS="$cand"
        break
    fi
done
if [ -z "$RS" ]; then
    echo "Rust quickpack binary not found. Build it with:" >&2
    echo "    (cd src/quickpack-rs && cargo build --release)" >&2
    exit 1
fi

# Clean any previous artefacts so the cast is reproducible.
rm -f "$CHARM"/*.charm

clear

note "quickpack — drop-in charmcraft pack replacement for the inner dev loop"
pause 0.8

run "uv run quickpack --help"
pause 1.6

note ""
note "Real charm — a tiny ops charm with ops-tracing"
run "ls $CHARM"
pause 1.0
run "cat $CHARM/charmcraft.yaml"
pause 1.5

note ""
note "Pack it. Python backend first."
pause 0.4
run "uv run quickpack $CHARM"
pause 1.6

note ""
note "Same charm, Rust backend — 50–200 ms cold for tighter red/green loops"
pause 0.4
run "rm -f $CHARM/*.charm && time $RS $CHARM"
pause 1.8

note ""
note "Resulting .charm is what charmcraft would have produced — minus the wait"
run "ls -la $CHARM/*.charm && unzip -l $CHARM/*.charm | head -10"
pause 2.0

# Cleanup
rm -f "$CHARM"/*.charm
