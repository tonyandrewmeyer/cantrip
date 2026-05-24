# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the Alertmanager workload."""

import json
import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ALERTMANAGER_SNAP = "alertmanager"
ALERTMANAGER_SERVICE = "snap.alertmanager.alertmanager"
CONFIG_DIR = Path("/etc/alertmanager")
CONFIG_FILE = CONFIG_DIR / "alertmanager.yml"
DATA_DIR = Path("/var/snap/alertmanager/current")
API_PORT = 9093
API_URL = f"http://localhost:{API_PORT}"


def install() -> None:
    """Install Alertmanager from the Snap Store."""
    logger.info("Installing alertmanager snap")
    subprocess.run(
        ["snap", "install", ALERTMANAGER_SNAP, "--classic"],
        check=True,
        capture_output=True,
        text=True,
    )
    # Ensure config directory exists
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # The snap creates /var/snap/alertmanager/current for data
    logger.info("Alertmanager snap installed")


def ensure_service_stopped() -> None:
    """Stop the Alertmanager systemd service if running."""
    logger.info("Stopping %s", ALERTMANAGER_SERVICE)
    subprocess.run(
        ["systemctl", "stop", ALERTMANAGER_SERVICE],
        check=False,
        capture_output=True,
    )


def start_service() -> None:
    """Start and enable the Alertmanager systemd service."""
    logger.info("Starting %s", ALERTMANAGER_SERVICE)
    subprocess.run(
        ["systemctl", "enable", "--now", ALERTMANAGER_SERVICE],
        check=True,
        capture_output=True,
        text=True,
    )


def restart_service() -> None:
    """Restart the Alertmanager systemd service."""
    logger.info("Restarting %s", ALERTMANAGER_SERVICE)
    subprocess.run(
        ["systemctl", "restart", ALERTMANAGER_SERVICE],
        check=True,
        capture_output=True,
        text=True,
    )


def is_service_active() -> bool:
    """Check whether the Alertmanager systemd service is active."""
    result = subprocess.run(
        ["systemctl", "is-active", ALERTMANAGER_SERVICE],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def get_version() -> str | None:
    """Return the installed Alertmanager version, or None if unavailable."""
    try:
        result = subprocess.run(
            ["snap", "list", ALERTMANAGER_SNAP],
            capture_output=True,
            text=True,
            check=True,
        )
        # Output format: Name  Version  Rev  Tracking  Publisher  Notes
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 2:
                return parts[1]
    except subprocess.CalledProcessError:
        pass
    return None


def _write_config(config: dict[str, Any]) -> None:
    """Write the Alertmanager YAML configuration to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CONFIG_FILE.with_suffix(".tmp")
    with temp_path.open("w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    shutil.move(str(temp_path), str(CONFIG_FILE))
    logger.info("Wrote %s", CONFIG_FILE)


def build_config(
    resolve_timeout: str,
    log_level: str,  # noqa: ARG001 - Fireworks declared but never used; kept for caller compat.
    smtp_smarthost: str = "",
    smtp_from: str = "",
    peer_addresses: list[str] | None = None,
) -> dict[str, Any]:
    """Build an Alertmanager configuration dictionary."""
    config: dict[str, Any] = {
        "global": {
            "resolve_timeout": resolve_timeout,
        },
        "route": {
            "group_by": ["alertname", "juju_model", "juju_application"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": "12h",
            "receiver": "default",
        },
        "receivers": [
            {
                "name": "default",
            },
        ],
    }

    if smtp_smarthost:
        config["global"]["smtp_smarthost"] = smtp_smarthost
        if smtp_from:
            config["global"]["smtp_from"] = smtp_from
        # Add an email receiver named 'email'
        config["receivers"].append(
            {
                "name": "email",
                "email_configs": [
                    {
                        "to": "admin@localhost",
                    },
                ],
            }
        )
        # Route everything to email if smtp is configured
        config["route"]["receiver"] = "email"

    if peer_addresses:
        config["cluster"] = {
            "peers": peer_addresses,
        }

    return config


def write_and_reload(
    resolve_timeout: str,
    log_level: str,
    smtp_smarthost: str = "",
    smtp_from: str = "",
    peer_addresses: list[str] | None = None,
) -> None:
    """Write configuration and reload Alertmanager."""
    config = build_config(
        resolve_timeout=resolve_timeout,
        log_level=log_level,
        smtp_smarthost=smtp_smarthost,
        smtp_from=smtp_from,
        peer_addresses=peer_addresses,
    )
    _write_config(config)
    if is_service_active():
        # Signal reload via SIGHUP or restart
        subprocess.run(
            ["systemctl", "kill", "-s", "HUP", ALERTMANAGER_SERVICE],
            check=False,
            capture_output=True,
        )
    else:
        start_service()


def send_test_alert() -> None:
    """Send a synthetic test alert to the local Alertmanager API."""
    test_alert = [
        {
            "labels": {
                "alertname": "TestAlert",
                "severity": "warning",
                "instance": socket.gethostname(),
            },
            "annotations": {
                "summary": "This is a test alert from the Alertmanager charm",
                "description": ("If you receive this, the notification pipeline is working."),
            },
            "startsAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "generatorURL": f"http://{socket.getfqdn()}:9093/test",
        }
    ]
    import urllib.request

    req = urllib.request.Request(
        f"{API_URL}/api/v2/alerts",
        data=json.dumps(test_alert).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 202):
            raise RuntimeError(f"Unexpected status {resp.status}")
