#!/usr/bin/env bash
# Drive the cantrip Web UI through Playwright and produce demos/recordings/web.gif.
#
# Pre-staged: $HOME/web-demo (a small charm directory).  Re-run by:
#   demos/recordings/web.sh
set -euo pipefail
REPO=$(git rev-parse --show-toplevel)
cd "$REPO"

CHARM="$HOME/web-demo"
PORT=8473
LOG=/tmp/cantrip-web.log
TMP=/tmp/cantrip-web-rec

# Clean any prior session for a deterministic capture.
rm -rf "$CHARM"/.cantrip* "$TMP"
mkdir -p "$TMP"

# Stop any stray cantrip web server on this port.
pkill -f "cantrip.*--web-port $PORT" 2>/dev/null || true
sleep 1

# Start cantrip --web in the background.
cd "$CHARM"
setsid uv run --project "$REPO" cantrip run . \
    --provider gemini --web --web-port "$PORT" \
    > "$LOG" 2>&1 < /dev/null &
WEB_PID=$!
disown
cd - >/dev/null

# Wait for the server to start.
for _ in $(seq 1 20); do
    if curl -sf "http://localhost:$PORT/" > /dev/null; then
        break
    fi
    sleep 1
done

# Drive the UI; the driver prints the recorded webm path to stdout.
WEBM=$(demos/recordings/_web_driver.py)

# Tear down the server now that we have the recording.
kill "$WEB_PID" 2>/dev/null || true
wait "$WEB_PID" 2>/dev/null || true

# Convert webm -> gif.  ffmpeg's default palette gives a pleasant
# size/quality trade-off here.
ffmpeg -y -i "$WEBM" -loglevel error demos/recordings/web.gif
echo "wrote demos/recordings/web.gif ($(stat -c %s demos/recordings/web.gif) bytes)"
