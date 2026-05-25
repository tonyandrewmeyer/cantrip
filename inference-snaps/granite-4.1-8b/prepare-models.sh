#!/bin/bash
# Pre-cache the Granite 4.1-8B-Instruct GGUF weights in `cache/` so
# the smoke server (and a future Phase 105.3 snap build) doesn't
# have to redownload on every run.
#
# Customise: pick a quantisation that suits your VRAM and quality
# budget.  UD-Q4_K_XL (~5.49 GB) is the smoke-test default — it's
# Unsloth's dynamic 4-bit variant, recommended over plain Q4_K_M
# (~5.35 GB) for the same disk cost.  Granite 4.1 is a hybrid
# mamba-2 + transformer model, so KV cache scales much more
# favourably than a pure transformer at long context: even at 32 K
# the residual KV footprint leaves plenty of headroom on a 12 GB
# GPU.  Q5_K_M (~6.25 GB) buys a touch more quality if the budget
# allows; Q8_0 (~9.35 GB) is overkill for the 12 GB target.
#
# UD-Q4_K_XL ships Unsloth's chat-template fixes that the model
# card highlights for tool calling via `--jinja`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Unsloth's conversion is the default
# (https://huggingface.co/unsloth/granite-4.1-8b-GGUF) — it ships
# the dynamic UD-* quants plus chat-template fixes for `--jinja`
# tool calling.  Switch to `ibm-granite/granite-4.1-8b-instruct-GGUF`
# (if/when IBM publishes one) for the upstream conversion.
GGUF_REPO="${GGUF_REPO:-unsloth/granite-4.1-8b-GGUF}"
GGUF_FILE="${GGUF_FILE:-granite-4.1-8b-UD-Q4_K_XL.gguf}"

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
echo "(UD-Q4_K_XL is ~5.5 GB; expect a few minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
