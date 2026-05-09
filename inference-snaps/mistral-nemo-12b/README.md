# Mistral Nemo 12B Instruct inference snap (scaffold)

Status: **Phase 105.1.7 smoke-test scaffold.** Not yet a packaged
snap. The snapcraft.yaml + components layout will land in Phase
105.3 if the smoke confirms Mistral Nemo as a viable alternative
or co-default alongside Qwen3-14B.

## Why Mistral Nemo 12B?

See [`design/LOCAL_MODELS.md`](../../design/LOCAL_MODELS.md) §5.2
for the full reasoning. Short version:

- **Native function calling** — Mistral's tool-call format is a
  first-class part of the chat template; well-tested with
  llama.cpp `--jinja`.
- **128 K native context** — best-in-class long-context option in
  the candidate set (vs Qwen3-14B's 32 K native / 16 K runtime in
  our smoke).
- **Standard Mistral architecture** — no MLA, no Gated Delta Net,
  no special attention shapes. The b8589 llama.cpp build supports
  it cleanly without the Flash-Attention fallback path that bit
  DeepSeek-V2-Lite (see §5.7).
- **Comfortable VRAM fit** — Q4_K_M is ~7.5 GB, leaving ~4.5 GB
  for KV cache and compute on a 12 GB GPU.

## VRAM budget

Mistral Nemo's KV cache is ~160 KB/token at fp16 (40 layers ×
8 KV heads × 128 head_dim × 2 (K+V) × 2 bytes):

| Context | KV cache (fp16) | Weights | Total |
|---|---|---|---|
| 16 K | ~2.6 GB | ~7.5 GB | ~10.1 GB |
| **24 K** | **~3.8 GB** | **~7.5 GB** | **~11.3 GB** *(default)* |
| 32 K | ~5.2 GB | ~7.5 GB | ~12.7 GB *(needs `CACHE_TYPE_K=q8_0`)* |
| 64 K | ~10 GB | ~7.5 GB | does not fit at fp16 |

`smoke-server.sh` defaults to **24 K** at fp16 KV — comfortable
in 12 GB with ~700 MB headroom for compute. Drop to 16 K via
`CTX_SIZE=16384` if allocation tightens; quantise the cache via
`CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0` to reach 64 K.

## Smoke test (Phase 105.1.7) — host

Run these on the **host**, not inside the cantrip VM (the VM has
no GPU passthrough). The cantrip folder is shared with the host,
so the paths below resolve identically.

```bash
# 1. Free the GPU. Stop any other smoke server still running
# (qwen3-14b on :8340, deepseek on :8342); confirm qwen3-coder
# snap is also stopped.
nvidia-smi    # confirm ~12 GiB free

# 2. Fetch the GGUF (~7.5 GB) into cache/.
bash inference-snaps/mistral-nemo-12b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8344 with
# full GPU offload, 24 K context, and --jinja for tool calling.
# The llama.cpp engine tarball is reused from any prior smoke
# (same b8589 build); only first run downloads it.
bash inference-snaps/mistral-nemo-12b/scripts/smoke-server.sh
```

In a second host terminal, expose port 8344 to the cantrip VM:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8344
```

## Smoke checks (from the VM)

```bash
bash inference-snaps/mistral-nemo-12b/scripts/smoke-check.sh
```

Mistral Nemo's tool-call format is well-trodden in llama.cpp; we
expect check 3 (synthetic tool call) to pass cleanly without the
DeepSeek-V2 architecture cliff-edge.

## ntfy improve scenario (from the VM)

```bash
cd /home/ubuntu/cantrip-iter-runs/mistral-nemo-12b-improve/ntfy
uv run --project /home/ubuntu/cantrip cantrip \
  --provider inference-snap --snap mistral-nemo-12b \
  --base-url http://10.42.160.1:8344/v1 \
  --yolo
```

Pass criterion: produce ≥ 80 % of the improve-02 feature target
in ≤ 30 min. Compare wall clock + tool-success rate against
Qwen3-14B Run #3's baseline (5m 19s, autonomous pack, 1.19 MB
charm).

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarder:
sudo systemctl disable --now cantrip-inference-proxy@8344.service
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
