# Qwen3-14B inference snap

Status: **Phase 105.3 packaged snap recipe.** The
snapcraft.yaml + components layout is in place and
buildable.  Pack with `snapcraft pack` from this directory;
the smoke-test scaffold (`scripts/smoke-server.sh`) stays
alongside for ad-hoc evaluation against a host
`llama-server` without snap installation.

This directory carries both surfaces:

1. **Packaged snap** (Phase 105.3): `snap/snapcraft.yaml`
   plus `components/{llamacpp,llamacpp-cuda,llamacpp-rocm,
   model-14b-q4-k-m-gguf}/` define the
   `qwen3-14b-tonyandrewmeyer` snap.  Build with
   `snapcraft pack`; install with `snap install --dangerous
   *.snap` and the `*+*.comp` components produced alongside.
   The install hook sets port 8340 (matching
   `_SNAP_DEFAULTS["qwen3-14b"]` in cantrip) so
   `cantrip --snap qwen3-14b` works without `--base-url`.
2. **Smoke scaffold** (Phase 105.1.5):
   `scripts/smoke-server.sh` drives a host `llama-server`
   directly against the same GGUF, no snap install needed.
   Useful for quick re-tests when iterating on llama.cpp
   tags or chat-template work without re-packing.
3. **GGUF cache** (`cache/`, gitignored): shared between
   the snap build (`prepare-models.sh` pre-warms it; the
   `model` part in `snap/snapcraft.yaml` copies from
   `cache/<file>` before falling back to Hugging Face) and
   the smoke scaffold.  Saves ~9 GB of redownload on
   repeat local packs.

## Why Qwen3-14B?

See [`design/LOCAL_MODELS.md`](../../design/LOCAL_MODELS.md) §5.6
for the full reasoning and ROADMAP Phase 105.1.5 for the work
breakdown. Short version: same Qwen3 family as the failed
[`qwen3-8b/`](../qwen3-8b/) smoke (so we know the `--jinja`
tool-call substrate works), but materially larger. The 105.1.2
chained-p result identified `edit_file` `old_string` accuracy as
the binding constraint, so size + code-tuning matter more than the
8 B's decode-speed advantage. ~9 GB Q4_K_M weights plus a 16 K KV
cache fits in the 12 GB GPU with full offload.

## VRAM budget — read this first

Qwen3-14B has 40 transformer layers and uses GQA with 8 KV heads
of 128 head_dim each. KV cache cost is ~170 KB per token at fp16:

| Context | KV cache | Weights | Activations | Total |
|---|---|---|---|---|
| 8 K | ~1.4 GB | ~9 GB | ~0.4 GB | ~10.8 GB |
| 16 K | ~2.7 GB | ~9 GB | ~0.4 GB | ~12.1 GB *(borderline — current default)* |
| 32 K (fp16 KV) | ~5.4 GB | ~9 GB | ~0.4 GB | ~14.8 GB *(does not fit)* |
| 32 K (q8 KV) | ~2.7 GB | ~9 GB | ~0.4 GB | ~12.1 GB *(borderline — opt in via `CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0`)* |

`smoke-server.sh` defaults to **16 K** at fp16 KV. If allocation
fails at startup, drop to 8 K (`CTX_SIZE=8192`) or quantise the KV
cache (`CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0`) to reach 32 K.

## Smoke test (Phase 105.1.5) — host

Run these on the **host**, not inside the cantrip VM (the VM has
no GPU passthrough). The cantrip folder is shared with the host,
so the paths below resolve identically.

```bash
# 1. Free the VRAM. Stop the qwen3-8b smoke server if it's still
# running (Ctrl-C in its terminal), and confirm gemma4 + qwen3-coder
# are also stopped.
nvidia-smi    # confirm ~12 GiB free

# 2. Fetch the GGUF (~9 GB) into cache/.
bash inference-snaps/qwen3-14b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8340 with full
# GPU offload, 16 K context, and --jinja for tool calling. The
# llama.cpp engine tarball is reused from inference-snaps/qwen3-8b/
# if it's already on disk — same b9050 build.
bash inference-snaps/qwen3-14b/scripts/smoke-server.sh
```

In a second host terminal, expose port 8340 to the cantrip VM via
the existing socat forwarder:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8340
```

## Smoke checks (from the VM)

Once the server and the proxy are up:

```bash
bash inference-snaps/qwen3-14b/scripts/smoke-check.sh
```

Three pass criteria — see the script header. The plain-hello
budget is 512 tokens because Qwen3-14B is a thinking model and
reasoning content lands in the `reasoning_content` field (not
`content`), separated by llama.cpp's default `--reasoning-format
deepseek`.

## ntfy improve scenario (from the VM)

```bash
cd /home/ubuntu/cantrip-iter-runs/qwen3-14b-improve/ntfy
uv run --project /home/ubuntu/cantrip cantrip \
  --provider inference-snap --snap qwen3-14b \
  --base-url http://10.42.160.1:8340/v1 \
  --yolo
```

Pass criterion (per ROADMAP 105.1.5): produce ≥ 80 % of the
improve-02 feature target in ≤ 30 min, OR exit with a clear
Phase 102 / 103 / 106 failure mode.

## Packaged snap (Phase 105.3) — pack and install

The recipe ships under the personal namespace
`qwen3-14b-tonyandrewmeyer`; the unsuffixed `qwen3-14b` name
is reserved for a future Canonical-published edition.  Same
build pattern as `qwen3-coder/` — three engines (CPU /
NVIDIA CUDA / AMD ROCm), a model component for the Q4_K_M
GGUF, and three llama.cpp engine components pinned to b9050.

```bash
# 1. (Optional) pre-warm the GGUF cache so the snap build
#    doesn't refetch ~9 GB from Hugging Face.
bash inference-snaps/qwen3-14b/prepare-models.sh

# 2. Pack the snap (LXD-isolated build; expect 10-15 minutes
#    on a fast link).  Produces .snap + three .comp components.
cd inference-snaps/qwen3-14b
snapcraft pack

# 3. Install the snap and all four components in dangerous
#    (locally-signed) mode.
sudo snap install --dangerous qwen3-14b-tonyandrewmeyer_v0_amd64.snap
sudo snap install --dangerous \
  --component llamacpp=qwen3-14b-tonyandrewmeyer+llamacpp_b9050.comp \
  --component llamacpp-cuda=qwen3-14b-tonyandrewmeyer+llamacpp-cuda_b9050.comp \
  --component model-14b-q4-k-m-gguf=qwen3-14b-tonyandrewmeyer+model-14b-q4-k-m-gguf_q4-k-m.comp \
  qwen3-14b-tonyandrewmeyer

# 4. The install hook sets port 8340 + auto-selects an engine
#    based on hardware.  The server runs as a snap daemon —
#    no manual start needed.
snap services qwen3-14b-tonyandrewmeyer
curl -sS http://localhost:8340/v1/models | jq .

# 5. From cantrip (in the VM), open the proxy and talk to it:
sudo bash scripts/setup-vm-inference-proxy.sh 8340
cantrip run . --provider inference-snap --snap qwen3-14b
```

The ROCm component is amd64-only; on arm64 the snap falls
back to CPU or CUDA per the engine compatibility matrix
(`engines/*/engine.yaml`).  The `+llamacpp-rocm_b9050.comp`
artefact only exists when packing on amd64.

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarder:
sudo systemctl disable --now cantrip-inference-proxy@8340.service
# Re-start qwen3-coder if you want it back:
sudo snap start qwen3-coder-tonyandrewmeyer
# Remove the packaged snap (if installed):
sudo snap remove --purge qwen3-14b-tonyandrewmeyer
```

## What this is *not*

- **Not in the Snap Store.**  The recipe builds the snap
  locally; `snap install --dangerous` is the install path.
  Upstreaming to Canonical's inference-snap catalogue under
  the unsuffixed `qwen3-14b` name stays on the long-term
  list, not the immediate ship.  See `design/LOCAL_MODELS.md`
  §6 for the (a)-vs-(b) decision.
- **Not VM-runnable.** Both the smoke server and the
  packaged snap need GPU access. The cantrip multipass VM
  has no GPU passthrough; run them on the host and reach
  them from the VM via `scripts/setup-vm-inference-proxy.sh`.
