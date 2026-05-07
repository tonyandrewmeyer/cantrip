---
title: "How to run Cantrip in a Multipass VM with host GPU inference — Cantrip"
description: "Sandbox Cantrip in a Multipass VM while still using host inference snaps that need the GPU."
h1: "Run Cantrip in a VM with host GPU inference"
subtitle: "Sandbox Cantrip in a Multipass VM and let it reach inference snaps running on the host's GPU, without GPU passthrough."
section: howto
breadcrumb_label: "VM with host GPU inference"
see_also:
  - label: "Choose an LLM provider"
    href: "howto-provider.html"
  - label: "CLI reference"
    href: "reference-cli.html"
---

Cantrip works well sandboxed in a Multipass VM, but inference snaps such as
`qwen3-coder` and `gemma4` are happiest using the host's GPU directly.
Multipass on Linux does not support PCI passthrough, and full VFIO
passthrough on a hybrid-graphics laptop typically means the host loses its
GPU while the VM runs. The pragmatic answer is to **keep inference on the
host where the GPU lives, and let the VM reach those snaps over the
Multipass bridge.**

This guide walks through the setup. A helper script
(`scripts/setup-vm-inference-proxy.sh`) automates the host side.

## How it works

Each inference snap binds `127.0.0.1:<port>` on the host. The Multipass VM
sees the host as `10.42.160.1` (the `mpqemubr0` bridge gateway) and cannot
reach the host's loopback. A small `socat` forwarder per port listens on
the bridge IP only, forwarding to host loopback:

```
cantrip VM (10.42.160.198)
   │  http://10.42.160.1:8332/v1/...
   ▼
mpqemubr0 (10.42.160.1)  ← socat listener
   │
   ▼
127.0.0.1:8332 (qwen3-coder snap, GPU)
```

The forwarder never binds on `0.0.0.0`, and `ufw` is locked down so only
traffic arriving on `mpqemubr0` from the VM subnet can reach it. The
inference snaps have no auth, so this matters.

## Prerequisites

- A Multipass VM (named `cantrip` in the examples) on the `mpqemubr0`
  bridge.
- Inference snaps installed and running on the host. Confirm they're
  listening:

  ```bash
  snap services
  ss -tln | grep -E ':(8324|8326|8328|8330|8332|8336) '
  ```

  Cantrip's default port map (defined in
  `src/cantrip/llm/inference_snap.py`):

  | Snap              | Port |
  |-------------------|------|
  | `deepseek-r1`     | 8324 |
  | `qwen-vl`         | 8326 |
  | `gemma3`          | 8328 |
  | `nemotron-3-nano` | 8330 |
  | `qwen3-coder`     | 8332 |
  | `gemma4`          | 8336 |

## Set up the host

Run the helper script. The defaults expose `qwen3-coder` (8332) and
`gemma4` (8336):

```bash
sudo bash scripts/setup-vm-inference-proxy.sh
```

Or pass an explicit port list:

```bash
sudo bash scripts/setup-vm-inference-proxy.sh 8328 8332 8336
```

The script:

1. Installs `socat` if missing.
2. Drops a templated systemd unit
   `cantrip-inference-proxy@.service` and enables one instance per port.
3. If `ufw` is active, adds rules allowing only the VM subnet
   (`10.42.160.0/24`, ingress on `mpqemubr0`) to reach those ports.

If your Multipass install uses a different bridge, override with environment
variables (check with `ip -4 addr show dev mpqemubr0`):

```bash
sudo BRIDGE_IFACE=mpqemubr0 BRIDGE_IP=10.42.160.1 BRIDGE_NET=10.42.160.0/24 \
    bash scripts/setup-vm-inference-proxy.sh
```

Verify from the VM:

```bash
multipass exec cantrip -- curl -s http://10.42.160.1:8332/v1/models
multipass exec cantrip -- curl -s http://10.42.160.1:8336/v1/models
```

## Point Cantrip at the host snaps

Inside the VM, Cantrip's `inference-snap` provider auto-discovery runs
`<snap-name> status`, which won't work because the snap isn't installed in
the VM. Use `--base-url` to bypass discovery:

```bash
# Inside the cantrip VM
cantrip --provider inference-snap \
        --snap-name qwen3-coder \
        --base-url http://10.42.160.1:8332/v1
```

Or use the generic provider:

```bash
cantrip --provider openai-compatible \
        --base-url http://10.42.160.1:8332/v1 \
        --model Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
```

For `gemma4` swap the port to `8336` and the snap name accordingly.

## Security notes

- The forwarder listens on the bridge IP only, never on `0.0.0.0` or your
  LAN interface. The inference snaps have no auth, so the bind address is
  load-bearing.
- If `ufw` is inactive, anything able to route to `10.42.160.1` can reach
  the proxy. Enable `ufw` (`sudo ufw enable`) or add an equivalent
  `nftables` rule before relying on isolation.
- The VM still has full NAT egress to the internet by default. Cantrip
  inside the VM is sandboxed from your host filesystem (apart from the
  explicit Multipass mounts), but not from the rest of the world.

## Remove the proxy

```bash
for port in 8332 8336; do
  sudo systemctl disable --now "cantrip-inference-proxy@${port}.service"
done
sudo rm /etc/systemd/system/cantrip-inference-proxy@.service
sudo systemctl daemon-reload

# Optional: revoke ufw rules
sudo ufw status numbered
sudo ufw delete <number>  # for each rule mentioning cantrip
```

## Why not other approaches

- **Multipass GPU passthrough** — not implemented upstream.
- **LXD/Incus VM with a `gpu` device** — works but requires IOMMU and
  binding the host's discrete GPU to `vfio-pci`, which on a hybrid-graphics
  laptop means the host loses CUDA while the VM runs.
- **Install the inference snap inside the VM** — the VM has no GPU, so the
  snap falls back to CPU and is unusably slow for 30B-class models.
- **LXD container with a `gpu` device** — lighter and works, but containers
  share the host kernel so isolation is weaker than a VM. If you'd accept
  that trade-off, run Cantrip *and* the inference snap together inside one
  LXD container with a `gpu` device attached, and skip this proxy entirely.
