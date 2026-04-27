#!/bin/bash
# Optional: pre-cache the Qwen3-Coder-30B-A3B-Instruct GGUF weights
# in `cache/` so local snapcraft builds don't redownload.
#
# The snapcraft `model` part fetches the GGUF itself at build time
# (so `snapcraft remote-build` works without local weights), but
# prefers a copy at `cache/<file>` if present. Running this script
# before `snapcraft pack` saves a ~17GB redownload on every local
# rebuild. It also gives you the GGUF in a stable place for direct
# llama-server testing without going through the snap.
#
# `cache/` is gitignored.
#
# Customise: pick a quantisation that suits your RAM and latency
# budget. Q4_K_M (~17GB) is the sweet spot for CPU-only inference and
# matches what this snap is structured around. Q5_K_M (~21GB) buys a
# touch more quality at noticeable RAM and CPU cost; Q8_0 (~32GB) is
# overkill on CPU for a 30B-A3B MoE.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# CHANGE THESE: pick the GGUF host + filename you trust.
# Qwen's official repo (PyTorch + safetensors) is at
# https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct — Apache
# 2.0, no gating. Community GGUF conversions live on Hugging Face;
# `unsloth` and `lmstudio-community` are the trusted conversions for
# this model. Verify the lineage and checksum before publishing a
# snap built from these weights.
#
# Alternative: Unsloth also publishes UD ("Dynamic") quants — set
# GGUF_FILE=Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf for slightly
# better quality at ~10% more size, or Q5_K_M for the next quality
# tier up at ~21GB.
GGUF_REPO="${GGUF_REPO:-unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF}"
GGUF_FILE="${GGUF_FILE:-Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf}"

DEST_DIR="cache"
DEST="${DEST_DIR}/${GGUF_FILE}"

if [[ -f "$DEST" ]]; then
  echo "Model already present: $DEST"
  exit 0
fi

mkdir -p "$DEST_DIR"
URL="https://huggingface.co/${GGUF_REPO}/resolve/main/${GGUF_FILE}"
echo "Downloading $URL"
echo "(This is ~17GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
