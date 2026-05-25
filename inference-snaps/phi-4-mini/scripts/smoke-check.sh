#!/bin/bash
# Phase 112.5 smoke-check (Phi-4-mini baseline): hit the three
# OpenAI endpoints from inside the cantrip VM. Run this once
# `smoke-server.sh` is up on the host and
# `setup-vm-inference-proxy.sh 8350` has the socat forwarder enabled.
#
# Phase 112.5's load-bearing check is #3 — the synthetic
# `get_weather` tool call.  Phi-4-mini is a function-calling
# baseline; if `--jinja` doesn't round-trip a tool_calls payload
# here, that's a llama.cpp regression on b9050 worth filing
# upstream, not a cantrip-side adoption decision.

set -euo pipefail

HOST_URL="${HOST_URL:-http://10.42.160.1:8350}"

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

Pass criteria (Phase 112.5 — Phi-4-mini baseline):
  1. /v1/models returns one model id ("Phi-4-mini-instruct-Q4_K_M.gguf"
     or similar). PASS if non-empty.
  2. Chat-completions plain hello returns content "OK" (or close)
     with finish_reason "stop". FAIL if content is empty or
     contains stray template tokens.
  3. Tool-call round-trip returns a non-null tool_calls array with
     name="get_weather" and JSON arguments containing city.
     **This is the load-bearing check.**  Phi-4-mini's model card
     documents tool calling; a failure here means \`--jinja\` on
     b9050 has regressed something for this template shape and is
     worth filing upstream at canonical/llama.cpp-builds /
     ggerganov/llama.cpp.
EOF
