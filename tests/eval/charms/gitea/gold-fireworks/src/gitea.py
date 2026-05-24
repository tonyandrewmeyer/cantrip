# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Functions for interacting with the Gitea workload.

This module contains pure workload logic (no charming concerns) so it
could be reused outside the context of a Juju charm.
"""

from __future__ import annotations

import logging

import ops.pebble

logger = logging.getLogger(__name__)


def get_version(container: ops.Container) -> str | None:
    """Get the running version of Gitea.

    Args:
        container: The Pebble workload container.

    Returns:
        The version string, or None if the workload is not available.
    """
    try:
        proc = container.exec(["/usr/local/bin/gitea", "--version"])
        stdout, _ = proc.wait_output()
        # Output looks like: "Gitea version 1.21.5 built with ..."
        parts = stdout.strip().split()
        for i, part in enumerate(parts):
            if part.lower() == "version" and i + 1 < len(parts):
                return parts[i + 1]
        return None
    except (ops.pebble.ExecError, FileNotFoundError):
        logger.debug("Could not determine Gitea version")
        return None
