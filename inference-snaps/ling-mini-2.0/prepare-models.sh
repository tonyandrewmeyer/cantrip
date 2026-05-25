#!/bin/bash
# Pre-cache the Ling-mini-2.0 GGUF weights in `cache/` so the
# smoke server doesn't have to redownload on every run.
#
# Phase 112.3 scope: Ling-mini-2.0 is the only ``bailing_moe``
# architecture candidate in the 2026-05 survey.  Two distinct
# unknowns the pre-flight is here to resolve:
#
#   (1) Does llama.cpp ``b9050`` support the ``bailing_moe``
#       architecture?  If ``llama-server`` fails to load the GGUF
#       at all (unknown architecture), that's the upstream-filing
#       condition the roadmap predicted (the "bailingmoe2 template
#       gap" turned out to also be an arch-support gap).
#   (2) If it loads: does ``--jinja`` round-trip tool calls?
#       Note that the Ling-mini-2.0 *model card* doesn't claim
#       tool-calling training, so a substrate-clean-but-tool_calls-
#       null outcome is *expected*, not a regression.
#
# Quant choice: Q4_K_M (~9.94 GB) is the smoke-test default.  A
# 16.26 B / 1.43 B-active MoE at 4-bit is the closest practical fit
# to 12 GiB VRAM; Q3_K_M (~7.54 GB) opens up more headroom if KV
# cache pressure shows up; Q5_K_M (~11.6 GB) is the upper bound
# before OOM at 32 K context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source repo + filename.  Bartowski's conversion is the default
# (https://huggingface.co/bartowski/inclusionAI_Ling-mini-2.0-GGUF).
GGUF_REPO="${GGUF_REPO:-bartowski/inclusionAI_Ling-mini-2.0-GGUF}"
GGUF_FILE="${GGUF_FILE:-inclusionAI_Ling-mini-2.0-Q4_K_M.gguf}"

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
echo "(Q4_K_M is ~9.94 GB; expect 2-3 minutes on a fast link.)"
curl -L --fail --output "$DEST" "$URL"
echo "Wrote $DEST"
