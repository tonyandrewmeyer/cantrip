#!/usr/bin/env bash
# Long-running asciinema capture: cantrip building the ntfy charm from scratch.
#
# Uses --no-tui interactive mode (richer output than --print — preflight
# ticks, the spinner animation, the full chat replies all render to the
# terminal) with the goal piped through stdin via a heredoc.  Cantrip
# exits cleanly when stdin closes — at the moment of EOF this lands at
# the design-confirm step, since the CLI doesn't yet auto-approve
# design confirmations.  The cast therefore captures research →
# synthesis → design proposal; the build/deploy/test continuation is
# best driven from the TUI.  See demos/07-build-ntfy-from-scratch.md.
#
# Run it with:
#   demos/recordings/hero-ntfy.sh
#
# Wall-clock duration: ~5–8 minutes.  Kick off in the background.
set -euo pipefail
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"

CHARM="$HOME/ntfy-charm"
CAST="demos/recordings/hero-ntfy.cast"
PROMPT_FILE="$HOME/.ntfy-hero-prompt.txt"

# Reset target directory for a clean from-scratch run.
rm -rf "$CHARM"
mkdir -p "$CHARM"

# The prompt is staged to a file so the asciinema --command stays
# readable.  Workflow guidance is load-bearing: without it Cantrip's
# planner sees `charm_name="ntfy"` + an inferred `charm_type="k8s"`
# and routes through sprint mode (no tests, no observability).
cat > "$PROMPT_FILE" <<'EOF'
Please research ntfy — the self-hosted push notification server at
https://github.com/binwiederhier/ntfy version 2.19.2 — and produce a
design proposal for a production-grade Juju charm.

Run the full research path: read the upstream source, sweep the
operator documentation, survey Charmhub for prior art, then
synthesise the findings into a design.  When you call plan_tasks,
omit the charm_type argument so the planner schedules the research
subagents rather than skipping ahead.

The design proposal you produce should cover ops-tracing, full COS
observability (Prometheus scrape, Loki logs, Grafana dashboards,
Tempo traces), persistent storage for the message cache and
attachments, ingress with behind-proxy support, and a test plan
(Scenario unit tests, Jubilant integration tests).  Charm name:
ntfy.
EOF

# Record into a temp path first, then promote on a sanity check.  This
# guards against a botched re-record (e.g. cantrip spawn-failure)
# stomping a previously-good cast — which exact accident motivated
# this guard.
TMP_CAST=$(mktemp --suffix=.cast)
trap 'rm -f "$TMP_CAST"' EXIT

TERM=xterm-256color uvx asciinema rec --overwrite \
    --cols 110 --rows 32 --idle-time-limit 3 \
    --command "cd $CHARM && cat $PROMPT_FILE | uv run --project $REPO cantrip run . --provider gemini --yolo --no-tui" \
    "$TMP_CAST"

# Refuse to promote a tiny cast — a real research+design run is at
# least ~50 KB and several lines of events.  A fast spawn failure
# leaves a ~600-byte file with one or two events.  Keep the prior
# good cast in that case.
if [ "$(stat -c %s "$TMP_CAST")" -lt 20000 ]; then
    echo "Recording suspiciously small ($(stat -c %s "$TMP_CAST") bytes)" >&2
    echo "— probably a spawn or rate-limit failure.  Preserving prior" >&2
    echo "$CAST and dumping the failed capture for inspection at:" >&2
    echo "    $TMP_CAST" >&2
    trap - EXIT
    exit 1
fi

mv "$TMP_CAST" "$CAST"
trap - EXIT
echo "wrote $CAST ($(stat -c %s "$CAST") bytes)"
