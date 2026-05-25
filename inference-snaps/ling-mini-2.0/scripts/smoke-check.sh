#!/bin/bash
# Phase 112.3 smoke-check (Ling-mini-2.0 bailing_moe verification):
# hit the three OpenAI endpoints from inside the cantrip VM.  Run
# this once `smoke-server.sh` is up on the host and
# `setup-vm-inference-proxy.sh 8354` has the socat forwarder enabled.
#
# Phase 112.3 scope: resolve two unknowns about bailing_moe + b9050:
#   (1) Does llama-server load the model at all?  If it errors with
#       "unknown architecture: bailing_moe" or similar, the model
#       file never reaches the smoke and this script can't even
#       reach /v1/models.  That's the upstream-filing condition.
#   (2) If load works: does `--jinja` round-trip a synthetic tool
#       call?  Note: Ling-mini-2.0's model card *doesn't* claim
#       tool-calling training, so a substrate-clean-but-tool_calls-
#       null result is **expected**, not a regression.  Distinguish:
#
#       (a) tool_calls null AND content contains literal template
#           tokens (e.g. unfiltered <|...|> markers) → template
#           rendering broken on bailing_moe → llama.cpp issue.
#       (b) tool_calls null AND content is a generic prose reply →
#           model wasn't trained for tool calling → expected,
#           record and move on.

set -euo pipefail

HOST_URL="${HOST_URL:-http://10.42.160.1:8354}"

echo "=== /v1/models ==="
curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq .

MODEL_ID="$(curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq -r '.data[0].id')"
echo "Resolved model id: $MODEL_ID"
echo

echo "=== /v1/chat/completions (plain hello) ==="
plain_t0=$(date +%s.%N)
curl -sS --max-time 60 "${HOST_URL}/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg m "$MODEL_ID" '{model:$m, messages:[{role:"user", content:"Reply with exactly: OK"}], temperature:0.2, max_tokens:32}')" \
  | jq '{content: .choices[0].message.content, finish: .choices[0].finish_reason, usage}'
plain_t1=$(date +%s.%N)
plain_elapsed=$(echo "$plain_t1 - $plain_t0" | bc)
printf "plain-hello wall: %.2f s\n" "$plain_elapsed"
echo

echo "=== /v1/chat/completions (synthetic tool call) ==="
tc_t0=$(date +%s.%N)
curl -sS --max-time 60 "${HOST_URL}/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg m "$MODEL_ID" '{
    model:$m,
    temperature:0.2,
    max_tokens:128,
    messages:[
      {role:"system", content:"You are a helpful assistant. Use tools when relevant."},
      {role:"user", content:"What is the weather in Edinburgh today? Use the get_weather tool."}
    ],
    tools:[
      {
        type:"function",
        function:{
          name:"get_weather",
          description:"Get the current weather for a city.",
          parameters:{
            type:"object",
            properties:{
              city:{type:"string", description:"City name."}
            },
            required:["city"]
          }
        }
      }
    ],
    tool_choice:"auto"
  }')" \
  | jq '{content: .choices[0].message.content, tool_calls: .choices[0].message.tool_calls, finish: .choices[0].finish_reason, usage}'
tc_t1=$(date +%s.%N)
tc_elapsed=$(echo "$tc_t1 - $tc_t0" | bc)
printf "tool-call wall: %.2f s\n" "$tc_elapsed"
echo

cat <<EOF

Pass criteria (Phase 112.3 — Ling-mini-2.0):
  1. /v1/models returns one model id (something like
     "inclusionAI_Ling-mini-2.0-Q4_K_M.gguf").  PASS if non-empty.
     If even this fails, the upstream issue is more fundamental
     than a chat template — the model didn't load at all.
  2. Chat-completions plain hello returns content "OK" (or close)
     with finish_reason "stop".  FAIL if content is empty or
     contains stray template tokens like "<|...|>" in plain text
     (would indicate broken chat-template rendering for bailing_moe).
  3. Tool-call round-trip.  Three branches:
     (a) tool_calls non-null with name="get_weather", args contains
         city → **substrate green AND model trained for tools**.
         Surprising but welcome.
     (b) tool_calls null, content is generic prose ("I cannot access
         real-time weather") → substrate green, model not trained
         for tools.  **Expected**, not a regression — the model card
         doesn't claim function-calling support.
     (c) tool_calls null, content contains literal template tokens
         or raw JSON markers → broken substrate path for bailing_moe.
         File upstream at canonical/llama.cpp-builds and/or
         ggerganov/llama.cpp.

If branch (c) fires, optionally re-run with CHAT_TEMPLATE=chatml in
smoke-server.sh's env to see whether overriding the embedded template
helps — that's the roadmap's predicted fallback path.
EOF
