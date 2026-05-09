#!/bin/bash
# Pre-cache the DeepSeek-Coder-V2-Lite-Instruct GGUF weights in
# `cache/` so the smoke server (and Phase 105.3's eventual snap
# build) doesn't have to redownload on every run.
#
# Customise: pick a quantisation that suits your VRAM and quality
# budget.
#
# **Q4_K_M (~10 GB) doesn't fit on 12 GB GPUs with the b8589
# llama.cpp build** — the per-layer compute buffers want ~4 GB
# contiguous on top of the weights and OOM at startup even with
# parallel=1 / ctx=16K / no MLA-cache savings.  Don't recommend.
#
# **Q3_K_S (~7.5 GB) is the practical default for 12 GB cards** —
# leaves ~4.5 GB headroom for compute buffers.  Slight quality
# reduction vs Q4_K_M but fits cleanly.
#
# Q3_K_M (~8.1 GB) is borderline; Q5_K_M (~12 GB) and larger
# quants do not fit at all.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Bartowski's repo
# (https://huggingface.co/bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF)
# has the full quant ladder including the smaller IQ3 variants
# we need to fit on a 12 GB GPU (lmstudio-community only ships
# Q3_K_L upward, which OOMs at startup with the b8589 build).
# IQ3_M is imatrix-calibrated 3-bit at "decent quality,
# comparable to Q3_K_M" per bartowski's notes — same fit profile
# as Q3_K_S but better calibration.
GGUF_REPO="${GGUF_REPO:-bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF}"
GGUF_FILE="${GGUF_FILE:-DeepSeek-Coder-V2-Lite-Instruct-IQ3_M.gguf}"

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
echo "(IQ3_M is ~7.5 GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
