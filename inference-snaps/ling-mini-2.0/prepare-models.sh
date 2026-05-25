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

mkdir -p "$DEST_DIR"
URL="https://huggingface.co/${GGUF_REPO}/resolve/main/${GGUF_FILE}"

# Determine the expected size from a HEAD request so we can resume a
# truncated download (the Q4_K_M file is ~9.94 GB; a single curl over
# a flaky link is liable to drop mid-stream and ``--fail`` exits 0 on
# a truncated transfer, leaving a corrupt GGUF on disk).  HF LFS
# supports Range requests, so ``curl -C -`` picks up where the
# previous attempt left off.
expected_size="$(curl -sIL "$URL" | awk -F': ' 'tolower($1)=="content-length" {gsub(/\r/,"",$2); size=$2} END {print size+0}')"

if [[ -f "$DEST" ]]; then
  actual_size="$(stat -c %s "$DEST")"
  if [[ "$expected_size" -gt 0 && "$actual_size" -eq "$expected_size" ]]; then
    echo "Model already present and complete: $DEST ($actual_size bytes)"
    exit 0
  elif [[ "$expected_size" -gt 0 && "$actual_size" -lt "$expected_size" ]]; then
    echo "Found truncated download: $DEST ($actual_size of $expected_size bytes)."
    echo "Resuming with curl --continue-at -."
  else
    echo "Found file of unexpected size: $DEST ($actual_size bytes; expected $expected_size)."
    echo "Re-fetching with curl --continue-at -; remove the file manually if this looks wrong."
  fi
fi

echo "Downloading $URL"
echo "(Q4_K_M is ~9.94 GB; resumes from the existing partial if any.)"
curl -L --fail --continue-at - --output "$DEST" "$URL"

# Verify final size — curl can complete cleanly on a server-side
# stream cut, leaving a truncated file with exit 0.
actual_size="$(stat -c %s "$DEST")"
if [[ "$expected_size" -gt 0 && "$actual_size" -ne "$expected_size" ]]; then
  echo "ERROR: post-download size mismatch ($actual_size bytes vs expected $expected_size)." >&2
  echo "Re-run this script to resume the rest." >&2
  exit 1
fi
echo "Wrote $DEST ($actual_size bytes)"
