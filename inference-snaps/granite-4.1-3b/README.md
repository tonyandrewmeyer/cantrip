# Granite 4.1-3B inference snap (scaffold)

Status: **Phase 112.4 smoke-test scaffold.** Not yet a packaged
snap. The 4.1-8B sibling (`inference-snaps/granite-4.1-8b/`) is
the disqualified-but-still-allowlisted charm-build candidate
(see `design/LOCAL_MODELS.md` §5.9.1).  The 3B variant is here
to answer one question: does its decode rate beat 4.1-8B's by
≥3×, making it a planner-role candidate for a future split-
provider setup (Phase 104 short-session mode +
`--planner-provider` / `--executor-provider`)?

This directory exists to:

1. Cache the Granite 4.1-3B-Instruct UD-Q4_K_XL GGUF in a place
   105.3 can reuse without re-downloading (`cache/`, gitignored).
2. Hold a host-side runner that drives a stock llama.cpp
   `llama-server` against the GGUF for the smoke test
   (`scripts/smoke-server.sh`).
3. Keep the directory layout aligned with the other
   `inference-snaps/*/` scaffolds so a future packaging step
   becomes "add `snap/snapcraft.yaml` + `components/`" rather
   than "rename and rearrange".

## Why Granite 4.1-3B?

See [`design/LOCAL_MODELS.md`](../../design/research/LOCAL_MODELS.md) §5.9.2
for the smoke-test results and the
[`design/LOCAL_MODELS_SURVEY_2026-05.md`](../../design/research/LOCAL_MODELS_SURVEY_2026-05.md)
survey for the candidate-selection reasoning. Short version:

- **Not a charm-build candidate.**  3 B coding accuracy is
  unknown and the survey doesn't claim it.  The 4.1-8B sibling
  already produced the disqualifying code-payload accuracy
  datapoint for the family (§5.9.1).
- **Planner-role candidate.**  Small, fast models are useful for
  cheap planning passes that don't need long-form code accuracy:
  task decomposition, dependency analysis, tool selection.  The
  question is whether 4.1-3B is *fast enough* to make a split-
  provider setup worth the wiring cost.
- **Same family substrate as 4.1-8B** — hybrid mamba-2 +
  transformer, OpenAI-shaped tool calls via `<tool_call>` XML
  tags, Unsloth chat-template fixes, no `<think>` preamble, no
  Phase 109-style rewriter needed.  Substrate is proven by
  §5.9.1; the only open question is decode rate.
- **2.15 GB UD-Q4_K_XL on disk** — trivially fits any 12 GB GPU.
  Could run alongside another local model if VRAM allows.
- **128 K native context** — same as the 4.1-8B; we cap at 32 K
  for the smoke to match the rest of the candidate matrix.

## Smoke test (Phase 112.4) — host

Run these on the **host**, not inside the cantrip VM (the VM has
no GPU passthrough). The cantrip folder is shared with the host,
so the paths below resolve identically.

```bash
# 1. Free the VRAM. The 4.1-8B smoke server (port 8346) and any
# other local models can stay if they fit; the 3 B fits in ~3 GB.
sudo snap stop qwen3-coder-tonyandrewmeyer   # or whatever name your install uses
nvidia-smi                                   # confirm enough free

# 2. Fetch the GGUF (~2.15 GB) into cache/.
bash inference-snaps/granite-4.1-3b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8348 with
# full GPU offload, 32 K context, and --jinja for tool calling.
# Logs to stdout; Ctrl-C to stop. The first run also fetches a
# prebuilt llama.cpp+CUDA tarball (~150 MB) into engines/, or
# reuses the 4.1-8B sibling's if you copy the engines/ dir.
bash inference-snaps/granite-4.1-3b/scripts/smoke-server.sh
```

In a second host terminal, expose port 8348 to the cantrip VM
via the existing socat forwarder:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8348
```

## Smoke checks (from the VM)

Once the server and the proxy are up, run the pre-flight checks
from inside the cantrip VM:

```bash
bash inference-snaps/granite-4.1-3b/scripts/smoke-check.sh
```

That hits `/v1/models`, runs a plain hello, and round-trips a
synthetic `get_weather` tool call.  The script also prints the
wall-clock for plain-hello and tool-call so the §5.9.2 write-up
can compare them to 4.1-8B's baseline directly.  Full pass
criteria are printed at the end of the script and pinned in
`design/LOCAL_MODELS.md` §5.9.2.

**Planner-role gate:** if the pre-flight passes AND the plain-
hello wall-clock is ≥3× faster than 4.1-8B's §5.9.1 baseline
(2 completion tokens), flag 4.1-3B as a candidate for the
short-session-mode planner path (Phase 104).  If not, record
the negative result and move on.

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarders are systemd-managed:
sudo systemctl disable --now cantrip-inference-proxy@8348.service
# Re-start qwen3-coder if you want it back:
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a snap.** No snapcraft.yaml, no components, no
  `snap install`.
- **Not a charm-build candidate.**  The 4.1-8B sibling's §5.9.1
  result rules that out for the family on this prompt shape;
  3 B with less capacity is not going to do better.
- **Not a long-running service.** The smoke server runs in the
  foreground; it dies when you close the terminal. By design —
  this is throwaway scaffolding for a one-time evaluation.
- **Not VM-runnable.** llama-server in here uses CUDA. The cantrip
  multipass VM has no GPU passthrough; run this on the host.
