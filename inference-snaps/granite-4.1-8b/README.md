# Granite 4.1-8B inference snap (scaffold)

Status: **Phase 112.1 smoke-test scaffold.** Not yet a packaged
snap. The snapcraft.yaml + components layout will land in Phase
105.3 once the smoke test confirms Granite 4.1-8B is a viable
qwen3-coder replacement.

This directory exists to:

1. Cache the Granite 4.1-8B-Instruct UD-Q4_K_XL GGUF in a place
   105.3 can reuse without re-downloading (`cache/`, gitignored).
2. Hold a host-side runner that drives a stock llama.cpp
   `llama-server` against the GGUF for the smoke test
   (`scripts/smoke-server.sh`).
3. Keep the directory layout aligned with the other
   `inference-snaps/*/` scaffolds so 105.3 becomes "add
   `snap/snapcraft.yaml` + `components/`" rather than "rename and
   rearrange".

## Why Granite 4.1-8B?

See [`design/LOCAL_MODELS.md`](../../design/LOCAL_MODELS.md) §5.8
for the smoke-test results and the
[`design/LOCAL_MODELS_SURVEY_2026-05.md`](../../design/LOCAL_MODELS_SURVEY_2026-05.md)
survey for the candidate-selection reasoning. Short version:

- **BFCL v3 = 68.27 as a post-training objective**, not a
  bolt-on — directly targets the failure modes that disqualified
  Mistral Nemo (post-pack planner spiral) and the Qwen2.5-Coder
  family (template-level `--jinja` bug).
- **Hybrid mamba-2 + transformer** — KV cache scales much more
  favourably than a pure transformer at long context.  Even at
  32 K the residual KV footprint leaves plenty of headroom on a
  12 GB GPU.
- **128 K native context** — second only to Mistral Nemo's
  128 K in the candidate matrix; we cap at 32 K for the smoke
  to match the rest of the matrix.
- **5.49 GB UD-Q4_K_XL on disk** — fits comfortably in 12 GiB
  VRAM with full GPU offload.
- **OpenAI-shaped tool calls via `<tool_call>` XML tags** —
  Unsloth's chat-template fixes (shipped in the GGUF) make
  `--jinja` round-trip them correctly.  Validated by the
  synthetic `get_weather` smoke check.
- **Not a thinking model** — no `<think>` preamble cost on
  every reply (cf. Qwen3-8B / Qwen3-14B).

## Smoke test (Phase 112.1) — host

Run these on the **host**, not inside the cantrip VM (the VM has
no GPU passthrough). The cantrip folder is shared with the host,
so the paths below resolve identically.

```bash
# 1. Free the VRAM. Stop other local models to get a clean run.
sudo snap stop qwen3-coder-tonyandrewmeyer   # or whatever name your install uses
nvidia-smi                                   # confirm ~10 GiB free

# 2. Fetch the GGUF (~5.5 GB) into cache/.
bash inference-snaps/granite-4.1-8b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8346 with
# full GPU offload, 32 K context, and --jinja for tool calling.
# Logs to stdout; Ctrl-C to stop. The first run also fetches a
# prebuilt llama.cpp+CUDA tarball (~150 MB) into engines/.
bash inference-snaps/granite-4.1-8b/scripts/smoke-server.sh
```

In a second host terminal, expose port 8346 to the cantrip VM
via the existing socat forwarder:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8346
```

## Smoke checks (from the VM)

Once the server and the proxy are up, run the pre-flight checks
from inside the cantrip VM:

```bash
bash inference-snaps/granite-4.1-8b/scripts/smoke-check.sh
```

That hits `/v1/models`, runs a plain hello, and round-trips a
synthetic `get_weather` tool call. The full pass criteria are
printed at the end of the script and pinned in
`design/LOCAL_MODELS.md` §5.8.

The full ntfy-improve scenario re-runs against
`--provider inference-snap --base-url http://10.42.160.1:8346/v1`.
Numbers (wall clock, decode rate, charm completeness, template
glitches) are appended to `design/LOCAL_MODELS.md` §5.8.

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarders are systemd-managed:
sudo systemctl disable --now cantrip-inference-proxy@8346.service
# Re-start qwen3-coder if you want it back:
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a snap.** No snapcraft.yaml, no components, no
  `snap install`. That's Phase 105.3.
- **Not a long-running service.** The smoke server runs in the
  foreground; it dies when you close the terminal. By design —
  this is throwaway scaffolding for a one-time evaluation.
- **Not VM-runnable.** llama-server in here uses CUDA. The cantrip
  multipass VM has no GPU passthrough; run this on the host.
