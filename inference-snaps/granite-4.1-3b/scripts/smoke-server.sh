#!/bin/bash
# Phase 112.4 smoke-test runner: drive a stock llama.cpp
# llama-server against the Granite 4.1-3B-Instruct UD-Q4_K_XL GGUF,
# with full GPU offload, 32 K context, and --jinja so tool-calling
# round-trips through the OpenAI-compatible endpoint.
#
# Run on the **host** (the cantrip multipass VM has no GPU
# passthrough). Foreground process; Ctrl-C kills it cleanly.
#
# Pairs with:
#   - inference-snaps/granite-4.1-3b/prepare-models.sh
#   - scripts/setup-vm-inference-proxy.sh 8348  (expose to VM)
#
# Once running, the cantrip-side checks live in
# `design/LOCAL_MODELS.md` §5.9 and the Phase 112.4 ROADMAP entry.
#
# Phase 112.4 scope: this snap is being smoked as a *planner /
# router* candidate, not as a charm-build candidate.  The 4.1-8B
# sibling (§5.9.1) already produced the disqualifying code-payload
# accuracy datapoint for the family.  The load-bearing question here
# is decode rate — does 3 B beat 8 B's improve-run decode by ≥3× so
# it makes sense as the "planner" half of a future split-provider
# setup (Phase 104 short-session mode + ``--planner-provider`` /
# ``--executor-provider``)?
#
# Notes on the model:
#   - Granite 4.1-3B is a hybrid mamba-2 + transformer, *not* a
#     thinking/reasoning model.  Same family substrate as the 8 B
#     (no --reasoning-format flag).
#   - Tool calls round-trip cleanly through ``--jinja`` because of
#     Unsloth's chat-template fixes — the 8 B sibling validated
#     this in Phase 112.1, the 3 B inherits the same fix.
#   - Native context is 128 K; we cap at 32 K to keep this aligned
#     with the rest of the candidate matrix.  The 3 B's hybrid KV
#     footprint is trivially small on a 12 GB GPU.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SNAP_DIR"

# Configuration. All overridable via env var.
PORT="${PORT:-8348}"
HOST="${HOST:-127.0.0.1}"
CTX_SIZE="${CTX_SIZE:-32768}"
N_PARALLEL="${N_PARALLEL:-1}" # llama-server defaults to 4 parallel slots; we only use 1.
CACHE_TYPE_K="${CACHE_TYPE_K:-}" # e.g. "q8_0" to quantise K cache.
CACHE_TYPE_V="${CACHE_TYPE_V:-}" # e.g. "q8_0" to quantise V cache.
N_GPU_LAYERS="${N_GPU_LAYERS:-99}" # 99 == "all".
GGUF_FILE="${GGUF_FILE:-granite-4.1-3b-UD-Q4_K_XL.gguf}"
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
  echo "Run inference-snaps/granite-4.1-3b/prepare-models.sh first." >&2
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
Starting Granite 4.1-3B smoke server.

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
