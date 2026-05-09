#!/bin/bash
# Pre-cache the Mistral Nemo 12B Instruct GGUF weights in `cache/`
# so the smoke server (and Phase 105.3's eventual snap build)
# doesn't have to redownload on every run.
#
# Customise: pick a quantisation that suits your VRAM and quality
# budget.  Q4_K_M (~7.5 GB) is the smoke-test default — at 12 GB
# usable on the host GPU it leaves about 4.5 GB for KV cache and
# compute buffers, enough for ~24 K context (Mistral Nemo's KV
# cache is ~160 KB/token at fp16).  Q5_K_M (~8.7 GB) is comfortable
# at 16 K; Q6_K (~10.0 GB) needs KV-cache quantisation to fit at
# 16 K.  Q3_K_M (~6.0 GB) opens up ~32 K context for long-doc work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Bartowski's conversion is the default
# (https://huggingface.co/bartowski/Mistral-Nemo-Instruct-2407-GGUF)
# — well-tested with llama.cpp's --jinja tool calling and matches
# what `design/LOCAL_MODELS.md` §5.2 cites.  The Mistral
# architecture has clean llama.cpp support (no MLA / no special
# attention shapes), so b8589 handles it directly without the
# Flash-Attention fallback path that bit DeepSeek-V2-Lite.
GGUF_REPO="${GGUF_REPO:-bartowski/Mistral-Nemo-Instruct-2407-GGUF}"
GGUF_FILE="${GGUF_FILE:-Mistral-Nemo-Instruct-2407-Q4_K_M.gguf}"

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
echo "(Q4_K_M is ~7.5 GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
