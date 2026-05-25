#!/bin/bash
# Phase 112.3 smoke-test runner: drive a stock llama.cpp
# llama-server against the Ling-mini-2.0 Q4_K_M GGUF, with full
# GPU offload, 32 K context, and --jinja so tool-calling
# round-trips through the OpenAI-compatible endpoint.
#
# Run on the **host** (the cantrip multipass VM has no GPU
# passthrough). Foreground process; Ctrl-C kills it cleanly.
#
# Pairs with:
#   - inference-snaps/ling-mini-2.0/prepare-models.sh
#   - scripts/setup-vm-inference-proxy.sh 8354  (expose to VM)
#
# Once running, the cantrip-side checks live in
# `design/LOCAL_MODELS.md` §5.12 and the Phase 112.3 ROADMAP entry.
#
# Phase 112.3 scope: Ling-mini-2.0 is the only ``bailing_moe`` MoE
# in the 2026-05 candidate survey.  The pre-flight is here to
# resolve two unknowns: (1) does llama.cpp ``b9050`` even support
# the ``bailing_moe`` architecture (model loads at all)?  (2) if
# so, does ``--jinja`` round-trip tool calls — noting that the
# model card *doesn't* claim tool-calling training, so a
# substrate-clean-but-tool_calls-null outcome is expected, not a
# regression.
#
# If model load fails with an "unknown architecture" error, that's
# the upstream-filing condition the roadmap predicted.  Try
# ``CHAT_TEMPLATE=...`` or ``--chat-template-file <path>`` as a
# fallback before declaring blocked.
#
# Notes on the model:
#   - 16.26 B total / 1.43 B active params, 1/32 sparsity MoE.
#   - bailing_moe (architecture).
#   - Not a thinking/reasoning model — no --reasoning-format flag.
#   - Native context: not documented; we cap at 32 K to fit the 12 GB
#     budget at Q4_K_M.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SNAP_DIR"

# Configuration. All overridable via env var.
PORT="${PORT:-8354}"
HOST="${HOST:-127.0.0.1}"
CTX_SIZE="${CTX_SIZE:-32768}"
N_PARALLEL="${N_PARALLEL:-1}" # llama-server defaults to 4 parallel slots; we only use 1.
CACHE_TYPE_K="${CACHE_TYPE_K:-}" # e.g. "q8_0" to quantise K cache.
CACHE_TYPE_V="${CACHE_TYPE_V:-}" # e.g. "q8_0" to quantise V cache.
N_GPU_LAYERS="${N_GPU_LAYERS:-99}" # 99 == "all".
GGUF_FILE="${GGUF_FILE:-inclusionAI_Ling-mini-2.0-Q4_K_M.gguf}"
# Optional chat-template override.  Set CHAT_TEMPLATE to a known
# llama.cpp built-in (e.g. "chatml") or use --chat-template-file
# directly if the bailing_moe arch's embedded template doesn't
# render tool calls correctly.  Default empty: trust the embedded
# template via --jinja.
CHAT_TEMPLATE="${CHAT_TEMPLATE:-}"
MODEL_PATH="${MODEL_PATH:-cache/$GGUF_FILE}"

# Pinned llama.cpp build — matches the version the rest of the
# Phase 111.1 re-smoke matrix runs on, so tool-call behaviour is
# consistent across candidates.
LLAMA_BUILD_TAG="${LLAMA_BUILD_TAG:-b9050}"
LLAMA_BUILD_VARIANT="${LLAMA_BUILD_VARIANT:-cuda12}" # "cuda12" / "rocm" / "" for CPU.

# Engine cache layout matches what Phase 105.3's snap will reuse.
ENGINE_DIR="engines/llamacpp-${LLAMA_BUILD_VARIANT:-cpu}-${LLAMA_BUILD_TAG}"
# Locate an already-extracted binary before deciding to redownload.
# Canonical's tarballs nest under bin/ so a literal
# ``$ENGINE_DIR/llama-server`` never matches.  Resolve once via
# find(1) so a second run reuses the cached engine.
if [[ -z "${LLAMA_SERVER:-}" && -d "$ENGINE_DIR" ]]; then
  LLAMA_SERVER="$(find "$ENGINE_DIR" -name llama-server -type f -executable 2>/dev/null | head -n 1)"
fi
LLAMA_SERVER="${LLAMA_SERVER:-$ENGINE_DIR/llama-server}"

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "ERROR: GGUF not found at $MODEL_PATH" >&2
  echo "Run inference-snaps/ling-mini-2.0/prepare-models.sh first." >&2
  exit 1
fi

# Fetch a pre-built llama.cpp tarball if we don't already have a
# server binary. The Canonical-published builds at
# canonical/llama.cpp-builds are the same ones the qwen3-coder snap
# bundles; reusing them keeps tool-call template behaviour aligned.
if [[ ! -x "$LLAMA_SERVER" ]]; then
  arch="$(uname -m)"
  case "$arch" in
    x86_64) arch_tag="amd64" ;;
    aarch64) arch_tag="arm64" ;;
    *) echo "ERROR: unsupported arch $arch" >&2; exit 1 ;;
  esac

  if [[ -n "$LLAMA_BUILD_VARIANT" ]]; then
    suffix="+${LLAMA_BUILD_VARIANT}"
  else
    suffix=""
  fi

  url="https://github.com/canonical/llama.cpp-builds/releases/download/${LLAMA_BUILD_TAG}/llamacpp-${arch_tag}${suffix}.tar.gz"
  echo "Fetching llama.cpp engine: $url"
  mkdir -p "$ENGINE_DIR"
  tmp_tar="$(mktemp --suffix=.tar.gz)"
  trap 'rm -f "$tmp_tar"' EXIT
  curl -L --fail -o "$tmp_tar" "$url"
  tar -xzf "$tmp_tar" -C "$ENGINE_DIR"
  trap - EXIT
  rm -f "$tmp_tar"

  if [[ ! -x "$LLAMA_SERVER" ]]; then
    # Some tarballs put binaries at the top level; some nest under
    # bin/. Re-resolve.
    candidate="$(find "$ENGINE_DIR" -name llama-server -type f -executable | head -n 1)"
    if [[ -n "$candidate" ]]; then
      LLAMA_SERVER="$candidate"
    else
      echo "ERROR: no llama-server binary found under $ENGINE_DIR" >&2
      echo "Inspect the tarball layout and set LLAMA_SERVER explicitly." >&2
      exit 1
    fi
  fi
  echo "Engine ready: $LLAMA_SERVER"
fi

# Make sure the server's bundled libraries (CUDA runtime, ggml,
# libmtmd, libllama) are discoverable when we exec it from outside
# its directory. The Canonical-published tarballs split shared libs
# across `bin/` (per-arch libggml-cpu variants and the binary) and
# `lib/` (libmtmd, libggml.so.0, libllama.so, …). Add both, and any
# other sibling that exists.
bin_dir="$(dirname "$LLAMA_SERVER")"
engine_root="$(cd "${bin_dir}/.." 2>/dev/null && pwd || echo "$bin_dir")"
ld_extra="$bin_dir"
for sib in lib lib64; do
  [[ -d "${engine_root}/${sib}" ]] && ld_extra="${engine_root}/${sib}:${ld_extra}"
done
export LD_LIBRARY_PATH="${ld_extra}:${LD_LIBRARY_PATH:-}"

cat <<EOF
Starting Ling-mini-2.0 smoke server.

  Engine:    $LLAMA_SERVER
  Model:     $MODEL_PATH
  Listen:    ${HOST}:${PORT}
  Ctx size:  ${CTX_SIZE}
  GPU lyr:   ${N_GPU_LAYERS}
  KV cache:  K=${CACHE_TYPE_K:-fp16} V=${CACHE_TYPE_V:-fp16}
  Jinja:     on (tool-call template handling)

Expose to the cantrip VM in a second terminal:

  sudo bash scripts/setup-vm-inference-proxy.sh ${PORT}

Then from the VM:

  curl -sS http://10.42.160.1:${PORT}/v1/models | jq .

Ctrl-C here to stop.
EOF

# Build the argv conditionally so we only pass --cache-type-* when
# the operator opted into KV-cache quantisation.  llama-server
# defaults to fp16 K/V when those flags are absent.
args=(
  --model "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX_SIZE"
  --parallel "$N_PARALLEL"
  --n-gpu-layers "$N_GPU_LAYERS"
  --jinja
  --metrics
  --log-prefix
  --threads "$(nproc)"
)
[[ -n "$CACHE_TYPE_K" ]] && args+=(--cache-type-k "$CACHE_TYPE_K")
[[ -n "$CACHE_TYPE_V" ]] && args+=(--cache-type-v "$CACHE_TYPE_V")
[[ -n "$CHAT_TEMPLATE" ]] && args+=(--chat-template "$CHAT_TEMPLATE")

exec "$LLAMA_SERVER" "${args[@]}"
