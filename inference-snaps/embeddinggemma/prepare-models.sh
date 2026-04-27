#!/bin/bash
# Download the EmbeddingGemma GGUF weights into the model component.
#
# Run this before `snapcraft pack`. The downloaded *.gguf is gitignored
# and not committed.
#
# Customise: pick a quantisation that suits your latency budget.
# Q8_0 is near-fp16 quality at ~330MB; Q4_K_M is ~200MB with a small
# quality drop. Both are widely available on Hugging Face.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# CHANGE THESE: pick the GGUF host + filename you trust.
# Google's official EmbeddingGemma repo (PyTorch + safetensors) is at
# https://huggingface.co/google/embeddinggemma-300m — gated; accept
# the Gemma terms while logged in. Community GGUF conversions live on
# Hugging Face under repos like the one below.
GGUF_REPO="${GGUF_REPO:-mradermacher/embeddinggemma-300m-GGUF}"
GGUF_FILE="${GGUF_FILE:-embeddinggemma-300m.Q8_0.gguf}"

DEST_DIR="components/model-300m-q8-0-gguf"
DEST="${DEST_DIR}/${GGUF_FILE}"

if [[ -f "$DEST" ]]; then
  echo "Model already present: $DEST"
  exit 0
fi

mkdir -p "$DEST_DIR"
URL="https://huggingface.co/${GGUF_REPO}/resolve/main/${GGUF_FILE}"
echo "Downloading $URL"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
