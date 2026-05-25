#!/bin/bash
# Pre-cache the Phi-4-mini-instruct GGUF weights in `cache/` so the
# smoke server doesn't have to redownload on every run.
#
# Phase 112.5 scope: this is a *function-calling baseline*, not an
# adoption candidate.  Phi-4-mini is one of the reference models
# whose model card documents tool calling end-to-end; a clean
# synthetic ``get_weather`` round-trip on b9050 is what we want to
# confirm.  A regression here on b9050 would be a llama.cpp issue
# worth filing upstream, independent of any cantrip decision.
#
# Quant choice: Q4_K_M (~2.49 GB) is the smoke-test default.  No
# UD-* quants on this Unsloth repo, so plain Q4_K_M is what we
# pick.  Q5_K_M (~2.85 GB) buys a touch more quality; Q8_0
# (~4.08 GB) is overkill for a baseline check.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Unsloth's conversion is the default
# (https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF).
# Switch to Microsoft's upstream conversion if/when they publish
# one.
GGUF_REPO="${GGUF_REPO:-unsloth/Phi-4-mini-instruct-GGUF}"
GGUF_FILE="${GGUF_FILE:-Phi-4-mini-instruct-Q4_K_M.gguf}"

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
echo "(Q4_K_M is ~2.49 GB; expect under a minute on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
