# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Functions for interacting with the Meilisearch workload."""

import json
import logging

logger = logging.getLogger(__name__)


def _api_request(
    container,
    port: int,
    path: str,
    method: str = "GET",
    master_key: str | None = None,
    data: dict | None = None,
) -> dict | None:
    """Make an HTTP request to the Meilisearch API via Pebble exec."""
    url = f"http://127.0.0.1:{port}{path}"
    headers = {"Content-Type": "application/json"}
    if master_key:
        headers["Authorization"] = f"Bearer {master_key}"

    payload = json.dumps(data).encode("utf-8") if data else None

    cmd = ["curl", "-s", "-X", method]
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    if payload:
        cmd.extend(["-d", payload.decode("utf-8")])
    cmd.append(url)

    process = container.exec(cmd)
    try:
        stdout, _ = process.wait_output()
        if stdout:
            return json.loads(stdout)
        return None
    except Exception:
        logger.exception("API request to %s failed", path)
        return None


def get_version(container, port: int) -> str | None:
    """Get the running version of Meilisearch."""
    result = _api_request(container, port, "/version")
    if result:
        return result.get("pkgVersion")
    return None


def is_healthy(container, port: int) -> bool:
    """Check whether Meilisearch is healthy."""
    result = _api_request(container, port, "/health")
    if result:
        return result.get("status") == "available"
    return False


def create_snapshot(container, port: int, master_key: str) -> str:
    """Trigger a Meilisearch snapshot creation."""
    result = _api_request(container, port, "/snapshots", method="POST", master_key=master_key)
    if result and "taskUid" in result:
        return f"snapshot task queued with uid {result['taskUid']}"
    return "snapshot task queued"


def create_dump(container, port: int, master_key: str) -> str:
    """Trigger a Meilisearch dump creation."""
    result = _api_request(container, port, "/dumps", method="POST", master_key=master_key)
    if result and "taskUid" in result:
        return f"dump task queued with uid {result['taskUid']}"
    return "dump task queued"


def get_keys(container, port: int, master_key: str) -> list[dict]:
    """Retrieve the list of Meilisearch API keys."""
    result = _api_request(container, port, "/keys", master_key=master_key)
    if result and "results" in result:
        return result["results"]
    return []
