#!/bin/bash
# Phase 112.1 smoke-check: hit the three OpenAI endpoints we care
# about from inside the cantrip VM. Run this once `smoke-server.sh`
# is up on the host and `setup-vm-inference-proxy.sh 8346` has the
# socat forwarder enabled.
#
# Three checks:
#   1. /v1/models           — confirms the server is reachable and
#                             advertises the model id.
#   2. /v1/chat/completions — plain hello, exercises chat-template
#                             tokenisation and decode.  Granite is
#                             *not* a thinking model so the budget
#                             is the same 32 tokens the rest of the
#                             matrix uses; no <think> preamble.
#   3. Synthetic tool call  — confirms `--jinja` round-trips a
#                             tool_calls JSON payload through
#                             Granite's <|start_of_role|> +
#                             <tool_call>…</tool_call> template.

set -euo pipefail

HOST_URL="${HOST_URL:-http://10.42.160.1:8346}"

echo "=== /v1/models ==="
curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq .

MODEL_ID="$(curl -sS --max-time 5 "${HOST_URL}/v1/models" | jq -r '.data[0].id')"
echo "Resolved model id: $MODEL_ID"
echo

echo "=== /v1/chat/completions (plain hello) ==="
curl -sS --max-time 60 "${HOST_URL}/v1/chat/completions" \
  -H 'content-type: application/json' \
  -d "$(jq -nc --arg m "$MODEL_ID" '{model:$m, messages:[{role:"user", content:"Reply with exactly: OK"}], temperature:0.2, max_tokens:32}')" \
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

Pass criteria (Phase 112.1):
  1. /v1/models returns one model id (something like
     "granite-4.1-8b" or "granite-4.1-8b-UD-Q4_K_XL.gguf"). PASS
     if id is non-empty.
  2. Chat-completions plain hello returns content "OK" (or close)
     with finish_reason "stop". FAIL if content is empty or
     contains stray template tokens like <|start_of_role|> or
     <tool_call> in plain text.
  3. Tool-call round-trip returns a non-null tool_calls array with
     name="get_weather" and JSON arguments containing city. FAIL
     if tool_calls is null and the content contains the literal
     <tool_call>…</tool_call> XML — that means \`--jinja\` didn't
     parse Granite's outbound tool-call shape and we'd need to
     either contribute a llama.cpp template fix or land a Phase
     109-style inbound rewriter for the Granite family.
EOF
