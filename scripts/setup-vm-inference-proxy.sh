#!/usr/bin/env bash
# Expose host inference snaps to the `cantrip` Multipass VM.
#
# Each inference snap listens on 127.0.0.1:<port> on the host and uses the
# host's GPU directly. A Multipass VM cannot reach the host's loopback, so we
# run a `socat` forwarder per port that listens on the Multipass bridge IP
# only, forwarding to host loopback. ufw is locked down so only traffic
# arriving on `mpqemubr0` from the VM subnet can reach the proxy.
#
# Default ports below cover qwen3-coder (8332) and gemma4 (8336). The full
# inference-snap port map lives in cantrip's
# `src/cantrip/llm/inference_snap.py::_SNAP_DEFAULTS`. Add extra ports to
# `PORTS` (or pass them as arguments) when you install more snaps.
#
# Usage:
#   sudo bash scripts/setup-vm-inference-proxy.sh                # defaults
#   sudo bash scripts/setup-vm-inference-proxy.sh 8328 8332 8336 # explicit
#
# See docs/src/howto-vm-inference-proxy.md (rendered:
# docs/docs/howto-vm-inference-proxy.html) for the companion docs.
set -euo pipefail

BRIDGE_IFACE="${BRIDGE_IFACE:-mpqemubr0}"
BRIDGE_IP="${BRIDGE_IP:-10.42.160.1}"
BRIDGE_NET="${BRIDGE_NET:-10.42.160.0/24}"

if [[ $# -gt 0 ]]; then
  PORTS=("$@")
else
  # qwen3-coder = 8332, gemma4 = 8336.
  PORTS=(8332 8336)
fi

if [[ $EUID -ne 0 ]]; then
  echo "This script must run as root (try: sudo bash $0)" >&2
  exit 1
fi

if ! ip -4 addr show dev "${BRIDGE_IFACE}" 2>/dev/null | grep -q "inet ${BRIDGE_IP}/"; then
  echo "Expected ${BRIDGE_IFACE} to have ${BRIDGE_IP}." >&2
  echo "Override with BRIDGE_IFACE=... BRIDGE_IP=... BRIDGE_NET=... if your" >&2
  echo "Multipass bridge differs (check with: ip -4 addr)." >&2
  exit 1
fi

if ! command -v socat >/dev/null; then
  apt-get update
  apt-get install -y socat
fi

cat > /etc/systemd/system/cantrip-inference-proxy@.service <<EOF
[Unit]
Description=Forward ${BRIDGE_IP}:%i to 127.0.0.1:%i for the cantrip Multipass VM
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/socat -d TCP-LISTEN:%i,bind=${BRIDGE_IP},reuseaddr,fork TCP:127.0.0.1:%i
Restart=on-failure
RestartSec=2
DynamicUser=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
for port in "${PORTS[@]}"; do
  systemctl enable --now "cantrip-inference-proxy@${port}.service"
done

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  for port in "${PORTS[@]}"; do
    ufw allow in on "${BRIDGE_IFACE}" from "${BRIDGE_NET}" to "${BRIDGE_IP}" \
      port "${port}" proto tcp \
      comment "cantrip VM -> host inference snap (${port})" || true
  done
fi

echo
echo "Active proxy listeners on ${BRIDGE_IP}:"
ss -tln | awk -v ip="${BRIDGE_IP}" '$0 ~ ip {print "  "$0}'
