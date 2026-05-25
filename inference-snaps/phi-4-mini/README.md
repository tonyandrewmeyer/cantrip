# Phi-4-mini inference snap (scaffold)

Status: **Phase 112.5 smoke-test scaffold.** Not a packaged snap
and not on track to become one — this directory exists to hold
the function-calling baseline check.  Phi-4-mini's model card
documents tool calling end-to-end; if it doesn't round-trip a
tool call via llama.cpp's `--jinja` on b9050, that's a llama.cpp
template-handling regression worth filing upstream, independent
of any cantrip adoption decision.

## Why Phi-4-mini?

See [`design/LOCAL_MODELS.md`](../../design/LOCAL_MODELS.md) §5.10
for the smoke-test results. Short version:

- **Function-calling reference model.**  Microsoft's docs treat
  tool calling as a first-class Phi-4-mini feature.  A clean
  pre-flight on b9050 is what we want — *not* an adoption
  signal.
- **~3.84 B params**, dense transformer, Q4_K_M ~2.49 GB on disk.
  Trivially fits any 12 GB GPU; charm-build performance is
  unknown (the survey doesn't claim it).
- **Standard chat template**, not the hybrid mamba-2 of Granite
  or the Tekken-style folded-tool-calls of Mistral.  Tool calls
  should round-trip cleanly through `--jinja` without per-family
  shenanigans.

## Smoke test (Phase 112.5) — host

```bash
# 1. Free the VRAM.
sudo snap stop qwen3-coder-tonyandrewmeyer   # or your install's name
nvidia-smi                                   # confirm ~10 GiB free

# 2. Fetch the GGUF (~2.49 GB).
bash inference-snaps/phi-4-mini/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8350.
bash inference-snaps/phi-4-mini/scripts/smoke-server.sh
```

In a second host terminal:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8350
```

## Smoke checks (from the VM)

```bash
bash inference-snaps/phi-4-mini/scripts/smoke-check.sh
```

**The load-bearing check is #3** (synthetic `get_weather`).
Phi-4-mini's model card documents tool calling — a failure here
on b9050 means upstream llama.cpp has broken something for this
template shape, not that Phi-4-mini is unsuitable.

Pass criteria are printed at the end of the script and pinned in
`design/LOCAL_MODELS.md` §5.10.

## Charm-build scenario

Per Phase 112.5, "charm-build scenario only if there's spare
time — these are baselines, not adoption candidates."  Skip
unless you specifically want to compare Phi-4-mini's
code-payload accuracy against the §5.6 / §5.9 candidates.

## Tear-down

```bash
sudo systemctl disable --now cantrip-inference-proxy@8350.service
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a packaged snap.**  No snapcraft.yaml, no components.
- **Not an adoption candidate.**  Phase 112.5 is a baseline check.
- **Not VM-runnable.**  llama-server uses CUDA; run this on the host.
