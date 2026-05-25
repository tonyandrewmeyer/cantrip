#!/bin/bash
# Phase 105.1.6 smoke-check: hit the three OpenAI endpoints we care
# about from inside the cantrip VM. Run this once `smoke-server.sh`
# is up on the host and `setup-vm-inference-proxy.sh` has the 8342
# socat forwarder enabled.
#
# Tool-call reliability is the *primary* unknown for this family —
# DeepSeek-V2's --jinja chat-template support isn't as well documented
# as the Qwen line.  If check 3 fails (tool_calls null, content
# contains the tool name as plain text), bail out and document in
# design/LOCAL_MODELS.md §5.7 — there's no point running the
# improve scenario without working tool calls.
#
# Three checks:
#   1. /v1/models          — confirms the server is reachable and
#                            advertises the model id.
#   2. /v1/chat/completions — plain hello, exercises chat-template
#                            tokenisation and decode.
#   3. Synthetic tool call  — confirms `--jinja` round-trips a
#                            tool_calls JSON payload (the failure
#                            mode that ruled out gemma4 + qwen2.5
#                            for tool use).

set -euo pipefail

HOST_URL="${HOST_URL:-http://10.42.160.1:8342}"

echo "=== /v1/models ==="
curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq .

MODEL_ID="$(curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq -r '.data[0].id')"
echo "Resolved model id: $MODEL_ID"
echo

echo "=== /v1/chat/completions (plain hello) ==="
curl -sS --max-time 60 "${HOST_URL}/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg m "$MODEL_ID" '{model:$m, messages:[{role:"user", content:"Reply with exactly: OK"}], temperature:0.2, max_tokens:512}')" \
  | jq '{content: .choices[0].message.content, finish: .choices[0].finish_reason, usage}'
echo

echo "=== /v1/chat/completions (synthetic tool call) ==="
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
  | jq '{content: .choices[0].message.content, tool_calls: .choices[0].message.tool_calls, finish: .choices[0].finish_reason}'
echo

cat <<EOF

Pass criteria (Phase 105.1.6 / 111.2):
  1. /v1/models returns one model id (something like
     "DeepSeek-Coder-V2-Lite-Instruct-IQ3_M.gguf"). PASS if id is
     non-empty — also confirms b9050's Gated Delta fix landed
     (the §5.7 b8589 blocker exited before this check ran).
  2. Chat-completions plain hello returns content "OK" (or close)
     with finish_reason "stop".  Not a thinking model — the
     default 32-token budget is fine.  FAIL if content is empty
     or contains stray template tokens.
  3. Tool-call round-trip returns a non-null tool_calls array with
     name="get_weather" and JSON arguments containing city.  FAIL
     if tool_calls is null and the content contains the literal
     "<｜tool▁calls▁begin｜>" / "<｜tool▁call▁begin｜>function"
     markers — that means llama.cpp's --jinja didn't parse
     DeepSeek-V2's outbound tool-call shape, and the model is
     disqualified from tool-using cantrip workflows until either
     a llama.cpp template fix lands upstream or a Phase 109-style
     inbound rewriter is written for the DeepSeek-V2 family.
EOF
