#!/bin/bash
# Download the Qwen3-Coder-30B-A3B-Instruct GGUF weights into the
# model component.
#
# Run this before `snapcraft pack`. The downloaded *.gguf is gitignored
# and not committed.
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
# 2.0, no gating. Community GGUF conversions live on Hugging Face
# under repos like the one below; verify the conversion lineage and
# checksum before you publish a snap built from it.
GGUF_REPO="${GGUF_REPO:-bartowski/Qwen_Qwen3-Coder-30B-A3B-Instruct-GGUF}"
GGUF_FILE="${GGUF_FILE:-Qwen_Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf}"

DEST_DIR="components/model-30b-a3b-q4-k-m-gguf"
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
