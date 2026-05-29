# DeepSeek-Coder-V2-Lite-Instruct inference snap (scaffold)

Status: **Phase 105.1.6 smoke-test scaffold.** Not yet a packaged
snap. The snapcraft.yaml + components layout will land in Phase
105.3 if the smoke confirms DeepSeek-Coder-V2-Lite as a
replacement (or co-default) alongside Qwen3-14B.

## Why DeepSeek-Coder-V2-Lite?

See [`design/LOCAL_MODELS.md`](../../design/research/LOCAL_MODELS.md) §5.7
for the full reasoning. Short version:

- **MoE shape**: 16 B total parameters, only ~2.4 B active per
  token. Decode rate should be closer to a 2.4 B dense model than
  a 16 B one.
- **Code-tuned**: DeepSeek's reported benchmarks have it
  competitive with GPT-4-Turbo on code-specific tasks.
- **128 K native context** vs Qwen3-14B's 32 K native (16 K
  runtime in our smoke).
- **Multi-head Latent Attention (MLA)**: KV cache is roughly 7 %
  the size of standard MHA at the same context, so 32 K + the
  10 GB weights still fits comfortably on the 12 GB GPU.

The big unknown vs Qwen3-14B is **tool-call reliability under
llama.cpp's `--jinja` flag**. The Qwen3 family's chat template is
well-tested; DeepSeek-V2's is less documented. Smoke-check 3
(synthetic tool call) is the gating test — if it fails, this
candidate is out and we fall back to Qwen3-14B as the sole
front-runner.

## VRAM budget

| Context | Approx KV cache (MLA) | Weights | Total |
|---|---|---|---|
| 16 K | ~0.3 GB | ~10 GB | ~10.3 GB |
| **32 K** | **~0.5 GB** | **~10 GB** | **~10.5 GB** *(default)* |
| 64 K | ~1 GB | ~10 GB | ~11 GB |
| 128 K | ~2 GB | ~10 GB | ~12 GB *(borderline)* |

`smoke-server.sh` defaults to **32 K** at fp16 KV — the MLA
compression makes that the sweet spot. Bump to 64 K or 128 K if
you want to test long-doc workflows. KV-cache quantisation
(`CACHE_TYPE_K=q8_0 CACHE_TYPE_V=q8_0`) is available but rarely
needed at this size.

## Smoke test (Phase 105.1.6) — host

Run these on the **host**, not inside the cantrip VM (the VM has
no GPU passthrough). The cantrip folder is shared with the host,
so the paths below resolve identically.

```bash
# 1. Free the GPU. Stop any other smoke server still running
# (qwen3-14b on :8340, qwen3-8b on :8338); also confirm the
# qwen3-coder snap is still stopped.
nvidia-smi    # confirm ~12 GiB free

# 2. Fetch the GGUF (~10 GB) into cache/.
bash inference-snaps/deepseek-coder-v2-lite/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8342 with
# full GPU offload, 32 K context, and --jinja for tool calling.
# The llama.cpp engine tarball is reused from any prior smoke
# (same b8589 build); only first run downloads it.
bash inference-snaps/deepseek-coder-v2-lite/scripts/smoke-server.sh
```

In a second host terminal, expose port 8342 to the cantrip VM:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8342
```

## Smoke checks (from the VM)

```bash
bash inference-snaps/deepseek-coder-v2-lite/scripts/smoke-check.sh
```

**Critical**: check 3 (synthetic tool call) is the gating test.
If `tool_calls` is null and the model emits `<tool_code>...` text
or the function name as plain content, bail out — improve runs
won't work without correct tool-call round-tripping.

## ntfy improve scenario (from the VM)

```bash
cd /home/ubuntu/cantrip-iter-runs/deepseek-coder-v2-lite-improve/ntfy
uv run --project /home/ubuntu/cantrip cantrip \
  --provider inference-snap --snap deepseek-coder-v2-lite \
  --base-url http://10.42.160.1:8342/v1 \
  --yolo
```

Pass criterion (per ROADMAP 105.1.6): produce ≥ 80 % of the
improve-02 feature target in ≤ 30 min. Compare wall clock,
tool-success rate, and final-charm completeness against
Qwen3-14B Run #3's baseline (5m 19s, autonomous pack, 1.19 MB
charm).

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarder:
sudo systemctl disable --now cantrip-inference-proxy@8342.service
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
