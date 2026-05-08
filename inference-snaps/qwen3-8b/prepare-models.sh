#!/bin/bash
# Pre-cache the Qwen3-8B-Instruct GGUF weights in `cache/` so the
# smoke server (and Phase 105.3's eventual snap build) doesn't have
# to redownload on every run.
#
# Customise: pick a quantisation that suits your VRAM and quality
# budget. Q4_K_M (~5.0 GB) is the smoke-test default — it's the
# pick `design/LOCAL_MODELS.md` is built around. Q5_K_M (~5.7 GB)
# buys a touch more quality at modest VRAM cost; Q8_0 (~8.7 GB)
# leaves no room for a 32K KV cache on a 12 GB GPU.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename. The official Qwen-published GGUF
# (https://huggingface.co/Qwen/Qwen3-8B-GGUF) is the default. Switch
# to `unsloth/Qwen3-8B-GGUF` or `bartowski/Qwen_Qwen3-8B-GGUF` for
# community conversions if Qwen's mirror is slow or geofenced.
GGUF_REPO="${GGUF_REPO:-Qwen/Qwen3-8B-GGUF}"
GGUF_FILE="${GGUF_FILE:-Qwen3-8B-Q4_K_M.gguf}"

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
echo "(This is ~5GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
