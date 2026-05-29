# Qwen3-8B inference snap (scaffold)

Status: **Phase 105.1 smoke-test scaffold.** Not yet a packaged snap.
The snapcraft.yaml + components layout will land in Phase 105.3 once
the smoke test confirms Qwen3-8B is the right pick.

This directory exists to:

1. Cache the Qwen3-8B-Instruct Q4_K_M GGUF in a place 105.3 can
   reuse without re-downloading (`cache/`, gitignored).
2. Hold a host-side runner that drives a stock llama.cpp `llama-server`
   against the GGUF for the smoke test (`scripts/smoke-server.sh`).
3. Keep the directory layout aligned with `qwen3-coder/` so 105.3
   becomes "add `snap/snapcraft.yaml` + `components/`" rather than
   "rename and rearrange".

## Why Qwen3-8B?

See [`design/LOCAL_MODELS.md`](../../design/research/LOCAL_MODELS.md) for the
full comparison and ROADMAP Phase 105 for the work breakdown. Short
version: 5 GB Q4_K_M weights + 2.5 GB KV cache at 32 K context fits
in ~7.5 GB of VRAM with full GPU offload, which clears the ~10–11
GiB headroom on the host once gemma4 is stopped. Native tool calling
via llama.cpp's `--jinja` flag.

## Smoke test (Phase 105.1) — host

Run these on the **host**, not inside the cantrip VM (the VM has no
GPU passthrough). The cantrip folder is shared with the host, so
the paths below resolve identically.

```bash
# 1. Free the VRAM. gemma4 should already be stopped; also stop
# qwen3-coder for a clean comparison (the 30B-MoE partial offload
# we're trying to replace eats ~6 GB even at "idle").
sudo snap stop qwen3-coder-tonyandrewmeyer  # or whatever name your install uses
nvidia-smi                                  # confirm ~10 GiB free

# 2. Fetch the GGUF (~5 GB) into cache/.
bash inference-snaps/qwen3-8b/prepare-models.sh

# 3. Run llama-server in the foreground on 127.0.0.1:8338 with full
# GPU offload, 32 K context, and --jinja for tool calling. Logs to
# stdout; Ctrl-C to stop. The first run also fetches a prebuilt
# llama.cpp+CUDA tarball (~150 MB) into engines/.
bash inference-snaps/qwen3-8b/scripts/smoke-server.sh
```

In a second host terminal, expose port 8338 to the cantrip VM via
the existing socat forwarder:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8332 8338
```

(`8332` keeps the qwen3-coder forwarder if you want both reachable;
the script is idempotent.)

## Smoke checks (from the VM)

Once the server and the proxy are up, the cantrip-side checks live
in the Phase 105 tracking issue / your terminal session — the basic
shape is:

```bash
curl -sS http://10.42.160.1:8338/v1/models | jq .
curl -sS http://10.42.160.1:8338/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}]}'
# Then a synthetic tool-call request — see design/LOCAL_MODELS.md §5.1.
```

The full ntfy-improve scenario re-runs against
`--provider inference-snap --base-url http://10.42.160.1:8338/v1`.
Numbers (wall clock, decode rate, reconnect count, charm
completeness) are appended to `design/LOCAL_MODELS.md` §5.1.

## Tear-down

```bash
# Smoke server: Ctrl-C in its terminal.
# Proxy forwarders are systemd-managed:
sudo systemctl disable --now cantrip-inference-proxy@8338.service
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
