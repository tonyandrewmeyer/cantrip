#!/bin/bash
# Pre-cache the Meta-Llama-3.1-8B-Instruct GGUF weights in `cache/`
# so the smoke server doesn't have to redownload on every run.
#
# Phase 112.5 scope: this is a *function-calling baseline*, not an
# adoption candidate.  Llama 3.1 introduced native function calling
# in the Llama family; the model card documents it via the OpenAI
# tool_calls shape (with llama.cpp's --jinja flag) as well as
# Meta's own <|python_tag|> raw format.  A clean synthetic
# ``get_weather`` round-trip on b9050 is what we want to confirm.
# A regression here would be a llama.cpp issue worth filing
# upstream at canonical/llama.cpp-builds / ggerganov/llama.cpp.
#
# Quant choice: Q4_K_M (~4.92 GB) is the smoke-test default.
# Bartowski's conversion is the standard pick; Llama 3.1 weights
# are licensed via Meta's terms and Unsloth's mirror is auth-
# gated, so bartowski/Meta-Llama-3.1-8B-Instruct-GGUF is the
# canonical public conversion.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Bartowski's conversion is the default
# (https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF).
GGUF_REPO="${GGUF_REPO:-bartowski/Meta-Llama-3.1-8B-Instruct-GGUF}"
GGUF_FILE="${GGUF_FILE:-Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}"

DEST_DIR="cache"
DEST="${DEST_DIR}/${GGUF_FILE}"

if [[ -f "$DEST" ]]; then
  echo "Model already present: $DEST"
  echo "(set GGUF_REPO / GGUF_FILE to fetch a different quant.)"
  exit 0
fi

mkdir -p "$DEST_DIR"
URL="https://huggingface.co/${GGUF_REPO}/resolve/main/${GGUF_FILE}"
echo "Downloading $URL"
echo "(Q4_K_M is ~4.92 GB; expect 1-2 minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
