# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Functions for interacting with the ntfy workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging

logger = logging.getLogger(__name__)

HEALTH_URL = "http://localhost:80/v1/health"
VERSION_URL = "http://localhost:80/v1/health"


def get_version(container) -> str | None:
    """Get the running version of the ntfy workload.

    Args:
        container: The Pebble container object used to execute commands.

    Returns:
        The version string if available, otherwise None.
    """
    try:
        proc = container.exec(["ntfy", "version"])
        stdout, _ = proc.wait_output()
        # ntfy version output is typically "ntfy version X.Y.Z"
        parts = stdout.strip().split()
        if len(parts) >= 3:
            return parts[2]
    except Exception:
        logger.debug("failed to get version from ntfy binary")
    return None


def check_health(container) -> bool:
    """Check whether the ntfy server health endpoint is responding.

    Args:
        container: The Pebble container object used to execute commands.

    Returns:
        True if the health endpoint returns HTTP 200, False otherwise.
    """
    try:
        proc = container.exec(
            ["curl", "-sf", "http://localhost:80/v1/health"],
            timeout=5,
        )
        proc.wait_output()
        return True
    except Exception:
        return False
