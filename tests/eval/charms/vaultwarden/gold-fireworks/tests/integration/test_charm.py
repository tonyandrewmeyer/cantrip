# Copyright 2026 Ubuntu
# See LICENSE file for licensing details.

"""Integration tests for the Vaultwarden charm."""

import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    resources = {
        "vaultwarden-image": METADATA["resources"]["vaultwarden-image"]["upstream-source"]
    }
    juju.deploy(charm.resolve(), app="vaultwarden-k8s", resources=resources)
    juju.wait(jubilant.all_active)


def test_workload_version_is_set(charm: pathlib.Path, juju: jubilant.Juju):  # noqa: ARG001
    """Check that the correct version of the workload is running."""
    juju.wait(jubilant.all_active)
    version = juju.status().apps["vaultwarden-k8s"].version
    assert version == "1.30.5"
