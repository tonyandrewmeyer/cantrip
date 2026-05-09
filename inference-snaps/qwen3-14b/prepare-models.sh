#!/bin/bash
# Pre-cache the Qwen3-14B GGUF weights in `cache/` so the smoke
# server (and Phase 105.3's eventual snap build) doesn't have to
# redownload on every run.
#
# Customise: pick a quantisation that suits your VRAM and quality
# budget. Q4_K_M (~9.0 GB) is the smoke-test default — at 12 GB
# usable on the host GPU it leaves about 3 GB for KV cache and
# activations, enough for a 16 K context. Q5_K_M (~10.4 GB) barely
# fits even with no cache. Q3_K_M (~7.4 GB) frees enough headroom
# for a 32 K cache if you'd rather trade quality for context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename. Bartowski's conversion is the default
# (https://huggingface.co/bartowski/Qwen_Qwen3-14B-GGUF) — well-
# tested with llama.cpp's --jinja tool calling and matches what
# `design/LOCAL_MODELS.md` §5.6 cites. Override to
# `unsloth/Qwen3-14B-GGUF` with filename `Qwen3-14B-Q4_K_M.gguf`
# if bartowski's mirror is slow.
GGUF_REPO="${GGUF_REPO:-bartowski/Qwen_Qwen3-14B-GGUF}"
GGUF_FILE="${GGUF_FILE:-Qwen_Qwen3-14B-Q4_K_M.gguf}"

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
echo "(This is ~9 GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
