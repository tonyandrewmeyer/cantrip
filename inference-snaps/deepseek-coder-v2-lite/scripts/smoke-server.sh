#!/bin/bash
# Phase 105.1.6 smoke-test runner: drive a stock llama.cpp
# llama-server against the DeepSeek-Coder-V2-Lite-Instruct Q4_K_M
# GGUF, with full GPU offload, 32 K context (DeepSeek-V2's MLA
# attention compresses the KV cache enough that 32 K + the 10 GB
# weights still fits comfortably on a 12 GB GPU), and --jinja so
# tool-calling round-trips through the OpenAI-compatible endpoint.
#
# Run on the **host** (the cantrip multipass VM has no GPU
# passthrough). Foreground process; Ctrl-C kills it cleanly.
#
# Pairs with:
#   - inference-snaps/deepseek-coder-v2-lite/prepare-models.sh
#   - scripts/setup-vm-inference-proxy.sh 8342  (expose to VM)
#
# Once running, the cantrip-side checks live in
# `design/LOCAL_MODELS.md` §5.7 and the Phase 105.1.6 ROADMAP entry.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SNAP_DIR"

# Configuration. All overridable via env var.
PORT="${PORT:-8342}"
HOST="${HOST:-127.0.0.1}"
# Context size: DeepSeek-V2-Lite's per-token KV footprint is unusually
# large (n_embd_head_k=192, n_embd_head_v=128, 27 layers — ~140 KB/token
# at fp16).  Without Flash Attention (auto-disabled on b9050 — see
# CACHE_TYPE_K below), the fp16 KV cache is ~1.1 GB at 8 K and
# ~2.3 GB at 16 K.  Combined with the 7.5 GB IQ3_M weights plus
# ~0.6 GB compute / scratch buffers, 8 K leaves ~3 GB of 12 GiB free,
# while 16 K is on the edge.  Bump if your GPU has more headroom.
CTX_SIZE="${CTX_SIZE:-8192}"
N_PARALLEL="${N_PARALLEL:-1}" # llama-server defaults to 4 parallel slots; we only use 1.
# KV-cache quantisation defaults to *off* on b9050.
#
# Background: Flash Attention auto-disables for DeepSeek-V2-Lite's
# attention geometry on b9050 (the FA tensor lands on CPU due to
# missing GPU support for this shape), and quantised V cache
# *requires* Flash Attention — the b9050 ``llama_init_from_model``
# refuses to create a context with "quantized V cache was requested,
# but this requires Flash Attention" otherwise.  The b8589 era
# defaulted to ``q8_0`` to fit Q4_K_M weights at 16 K in 12 GiB, but
# the b8589 init crashed on the fused Gated Delta path before this
# constraint mattered; b9050 fixes Gated Delta and surfaces the FA
# requirement as the new blocker.  fp16 KV at 8 K context fits.
#
# Opt back into quant if a future llama.cpp build re-enables FA for
# DeepSeek-V2-Lite — set CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0.
CACHE_TYPE_K="${CACHE_TYPE_K:-}"
CACHE_TYPE_V="${CACHE_TYPE_V:-}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}" # 99 == "all"; DeepSeek-Coder-V2-Lite has 27 layers.
GGUF_FILE="${GGUF_FILE:-DeepSeek-Coder-V2-Lite-Instruct-IQ3_M.gguf}"
MODEL_PATH="${MODEL_PATH:-cache/$GGUF_FILE}"

# Pinned llama.cpp build — matches the version the qwen3-coder snap
# uses, so tool-call behaviour is consistent between the two.
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
  echo "Run inference-snaps/deepseek-coder-v2-lite/prepare-models.sh first." >&2
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
Starting DeepSeek-Coder-V2-Lite smoke server.

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

exec "$LLAMA_SERVER" "${args[@]}"
