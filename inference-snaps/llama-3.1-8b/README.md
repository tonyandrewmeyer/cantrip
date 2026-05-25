# Llama 3.1-8B-Instruct inference snap (scaffold)

Status: **Phase 112.5 smoke-test scaffold.** Not a packaged snap
and not on track to become one — this directory exists to hold
the function-calling baseline check.  Llama 3.1 introduced
native function calling in the Llama family; the model card
documents both the OpenAI `tool_calls` shape (via llama.cpp's
`--jinja`) and Meta's own `<|python_tag|>` raw format.  A clean
pre-flight on b9050 confirms `--jinja` is producing the OpenAI
shape, not the raw `<|python_tag|>` payload that cantrip would
have to parse manually.

## Why Llama 3.1-8B?

See [`design/LOCAL_MODELS.md`](../../design/LOCAL_MODELS.md) §5.11
for the smoke-test results. Short version:

- **Function-calling reference model.**  Meta's docs treat tool
  calling as a Llama 3.1 first-class feature.  A clean pre-flight
  on b9050 is what we want — *not* an adoption signal.
- **8 B params**, dense transformer, Q4_K_M ~4.92 GB on disk.
  Fits in 12 GB VRAM with full GPU offload.
- **Llama 3 chat template** — `<|begin_of_text|>`,
  `<|start_header_id|>`/`<|end_header_id|>`, `<|eot_id|>`.  Tool
  calls via `--jinja` should produce OpenAI `tool_calls`; the
  model can also emit `<|python_tag|>{"name":…}<|eom_id|>` as a
  raw format we'd have to parse manually.  Pre-flight confirms
  which we get.

## Smoke test (Phase 112.5) — host

```bash
# 1. Free the VRAM.
sudo snap stop qwen3-coder-tonyandrewmeyer
nvidia-smi                                   # confirm ~10 GiB free

# 2. Fetch the GGUF (~4.92 GB).
bash inference-snaps/llama-3.1-8b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8352.
bash inference-snaps/llama-3.1-8b/scripts/smoke-server.sh
```

In a second host terminal:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8352
```

## Smoke checks (from the VM)

```bash
bash inference-snaps/llama-3.1-8b/scripts/smoke-check.sh
```

**The load-bearing check is #3** (synthetic `get_weather`).
Two distinct failure modes the script's pass-criteria block
calls out:

- `tool_calls` null AND content contains a literal `<|python_tag|>`
  payload → llama.cpp `--jinja` regression worth filing upstream.
- `tool_calls` null AND content is generic prose → model decided
  not to call the tool.  Recorded as a model-behaviour data point,
  not a llama.cpp issue.

Pass criteria are printed at the end of the script and pinned in
`design/LOCAL_MODELS.md` §5.11.

## Charm-build scenario

Per Phase 112.5, "charm-build scenario only if there's spare
time — these are baselines, not adoption candidates."  Skip
unless you specifically want to compare Llama 3.1-8B's
code-payload accuracy against the §5.6 / §5.9 candidates.

## Tear-down

```bash
sudo systemctl disable --now cantrip-inference-proxy@8352.service
sudo snap start qwen3-coder-tonyandrewmeyer
```

## What this is *not*

- **Not a packaged snap.**  No snapcraft.yaml, no components.
- **Not an adoption candidate.**  Phase 112.5 is a baseline check.
- **Not VM-runnable.**  llama-server uses CUDA; run this on the host.
