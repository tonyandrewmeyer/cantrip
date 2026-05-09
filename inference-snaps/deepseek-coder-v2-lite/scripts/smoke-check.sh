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

Pass criteria (Phase 105.1.6):
  1. /v1/models returns one model id (something like
     "Qwen_Qwen3-14B-Q4_K_M.gguf" or "qwen3-14b"). PASS if id is
     non-empty.
  2. Chat-completions plain hello returns content "OK" (or close)
     with finish_reason "stop".  Qwen3-14B is also a thinking model,
     so the visible content may follow ~100 tokens of separated
     reasoning_content; budget 512+ max_tokens to give it room. FAIL
     if content is empty or contains stray template tokens like
     <function=...> or <tool_code>.
  3. Tool-call round-trip returns a non-null tool_calls array with
     name="get_weather" and JSON arguments containing city. FAIL if
     tool_calls is null and the content contains the tool name as
     plain text — that's the gemma4 / qwen2.5-coder failure shape
     we explicitly want to confirm Qwen3-14B doesn't share.
EOF
