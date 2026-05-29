# Ling-mini-2.0 inference snap (scaffold)

Status: **Phase 112.3 smoke-test scaffold.** Not a packaged snap
and not on track to become one — this directory exists to hold
the bailing_moe architecture-support check on llama.cpp `b9050`.

## Why Ling-mini-2.0?

See [`design/LOCAL_MODELS.md`](../../design/research/LOCAL_MODELS.md) §5.12
for the smoke-test results and
[`design/LOCAL_MODELS_SURVEY_2026-05.md`](../../design/research/LOCAL_MODELS_SURVEY_2026-05.md)
for the candidate-selection reasoning.  Short version:

- **Only `bailing_moe` MoE in the survey shortlist.**  16.26 B
  total / 1.43 B active per token (1/32 sparsity).  Architecture
  support on llama.cpp's b9050 is the first thing to verify; the
  roadmap's predicted failure mode is the bailing_moe template
  gap or arch-load failure.
- **Tool-calling NOT claimed by the model card.**  Unlike Granite
  4.1 or Llama 3.1, Ling-mini-2.0's published documentation
  doesn't claim function-calling training.  So a substrate-
  clean-but-tool_calls-null outcome on `--jinja` is *expected*,
  not a regression — it'd just mean "the model wasn't trained
  for tools".
- **9.94 GB Q4_K_M on disk.**  Tight fit on 12 GiB VRAM at 32 K
  context; Q3_K_M (~7.54 GB) opens up more headroom if needed.

## Smoke test (Phase 112.3) — host

```bash
# 1. Free the VRAM. Ling-mini-2.0 needs nearly all of 12 GB.
sudo snap stop qwen3-coder-tonyandrewmeyer
nvidia-smi                                   # confirm ~11 GiB free

# 2. Fetch the GGUF (~9.94 GB).  Largest single download in the
# candidate matrix; expect 2-3 minutes on a fast link.
bash inference-snaps/ling-mini-2.0/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8354.
# **If this exits immediately with "unknown architecture:
# bailing_moe" or similar**, that's the upstream-filing condition.
bash inference-snaps/ling-mini-2.0/scripts/smoke-server.sh
```

In a second host terminal:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8354
```

## Smoke checks (from the VM)

```bash
bash inference-snaps/ling-mini-2.0/scripts/smoke-check.sh
```

The script's pass-criteria block enumerates three distinct tool-
call outcome branches: (a) substrate works + model emits tool
calls (surprising, welcome); (b) substrate works + model emits
prose (expected — model wasn't trained for tools); (c) substrate
breaks (broken template rendering — file upstream).

If branch (c) fires, the roadmap suggests re-running with
`CHAT_TEMPLATE=chatml` in `smoke-server.sh`'s env to see whether
overriding the embedded template helps.  The smoke-server script
already wires the `--chat-template` argv conditionally, so this
is just `CHAT_TEMPLATE=chatml bash scripts/smoke-server.sh`.

Pass criteria are pinned in `design/LOCAL_MODELS.md` §5.12.

## Charm-build scenario

Per Phase 112.3, "only run the full charm-build scenario if the
synthetic tool call passes."  Since the model card doesn't claim
function-calling training, branch (b) above is the most likely
outcome and charm-build is then skipped.

## Tear-down

```bash
sudo systemctl disable --now cantrip-inference-proxy@8354.service
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a packaged snap.**  No snapcraft.yaml, no components.
- **Not an adoption candidate.**  Phase 112.3 is an architecture-
  support verification.
- **Not VM-runnable.**  llama-server uses CUDA; run this on the host.
