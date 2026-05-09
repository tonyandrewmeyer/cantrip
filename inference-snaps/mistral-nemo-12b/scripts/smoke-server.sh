#!/bin/bash
# Phase 105.1.7 smoke-test runner: drive a stock llama.cpp
# llama-server against the Mistral Nemo 12B Instruct Q4_K_M GGUF,
# with full GPU offload, 24 K context, and --jinja so tool-calling
# round-trips through the OpenAI-compatible endpoint.
#
# Run on the **host** (the cantrip multipass VM has no GPU
# passthrough). Foreground process; Ctrl-C kills it cleanly.
#
# Pairs with:
#   - inference-snaps/mistral-nemo-12b/prepare-models.sh
#   - scripts/setup-vm-inference-proxy.sh 8344  (expose to VM)
#
# Once running, the cantrip-side checks live in
# `design/LOCAL_MODELS.md` §5.2 and the Phase 105.1.7 ROADMAP entry.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SNAP_DIR"

# Configuration. All overridable via env var.
PORT="${PORT:-8344}"
HOST="${HOST:-127.0.0.1}"
# Mistral Nemo's KV cache is ~160 KB/token at fp16 (40 layers ×
# 8 KV heads × 128 head_dim × 2 (K+V) × 2 bytes).  At 24 K context
# that's ~3.8 GB; combined with the 7.5 GB Q4_K_M weights this
# leaves ~700 MB headroom on a 12 GB GPU for compute.  Drop to
# 16384 if allocation fails, or quantise the cache via
# CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0 to halve KV and reach 64 K.
# Mistral Nemo trains to 128 K natively but llama.cpp can't fit
# that on 12 GB without aggressive KV quantisation.
CTX_SIZE="${CTX_SIZE:-24576}"
N_PARALLEL="${N_PARALLEL:-1}" # llama-server defaults to 4 parallel slots; we only use 1.
CACHE_TYPE_K="${CACHE_TYPE_K:-}" # e.g. "q8_0" to quantise K cache.
CACHE_TYPE_V="${CACHE_TYPE_V:-}" # e.g. "q8_0" to quantise V cache.
# Chat-template override.  Mistral Nemo's embedded Tekken template
# rejects cantrip's "tool" role messages with a strict
# alternation check; CHAT_TEMPLATE=chatml swaps to a permissive
# template that handles tool messages cleanly.  Empty default keeps
# the GGUF's embedded template.
CHAT_TEMPLATE="${CHAT_TEMPLATE:-}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}" # 99 == "all"; Mistral Nemo has 40 layers.
GGUF_FILE="${GGUF_FILE:-Mistral-Nemo-Instruct-2407-Q4_K_M.gguf}"
MODEL_PATH="${MODEL_PATH:-cache/$GGUF_FILE}"

# Pinned llama.cpp build — matches the version the qwen3-coder snap
# uses, so tool-call behaviour is consistent between the two.
LLAMA_BUILD_TAG="${LLAMA_BUILD_TAG:-b8589}"
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
  echo "Run inference-snaps/mistral-nemo-12b/prepare-models.sh first." >&2
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
Starting Mistral Nemo 12B smoke server.

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
