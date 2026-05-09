# Qwen3-14B inference snap (scaffold)

Status: **Phase 105.1.5 smoke-test scaffold.** Not yet a packaged
snap. The snapcraft.yaml + components layout will land in Phase
105.3 if the smoke test confirms Qwen3-14B as the replacement for
qwen3-coder.

This directory exists to:

1. Cache the Qwen3-14B Q4_K_M GGUF in a place 105.3 can reuse
   without re-downloading (`cache/`, gitignored).
2. Hold a host-side runner that drives a stock llama.cpp
   `llama-server` against the GGUF for the smoke test
   (`scripts/smoke-server.sh`).
3. Keep the directory layout aligned with `qwen3-8b/` and
   `qwen3-coder/` so 105.3 becomes "add `snap/snapcraft.yaml` +
   `components/`" rather than "rename and rearrange".

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
# if it's already on disk — same b8589 build.
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

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarder:
sudo systemctl disable --now cantrip-inference-proxy@8340.service
# Re-start qwen3-coder if you want it back:
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a snap.** No snapcraft.yaml, no components, no `snap install`.
  That's Phase 105.3.
- **Not a long-running service.** The smoke server runs in the
  foreground; it dies when you close the terminal. By design — this
  is throwaway scaffolding for a one-time evaluation.
- **Not VM-runnable.** llama-server in here uses CUDA. The cantrip
  multipass VM has no GPU passthrough; run this on the host.
