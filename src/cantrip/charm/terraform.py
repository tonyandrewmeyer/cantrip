"""Terraform module generator for Juju charms.

Generates a complete Terraform module (main.tf, variables.tf, outputs.tf,
versions.tf) from a charmcraft.yaml file.  Pure template expansion — no LLM
required.
"""

import pathlib
import re
import textwrap

import yaml

_COPYRIGHT = "# Copyright 2025 Canonical Ltd.\n# See LICENSE file for licensing details.\n"


def _resource_name(charm_name: str) -> str:
    """Derive a short Terraform resource name from a charm name.

    Strips ``-k8s``, ``-operator``, and ``-k8s-operator`` suffixes, then
    replaces hyphens with underscores so the result is a valid HCL identifier.
    """
    stripped = re.sub(r"(-k8s)?(-operator)?$", "", charm_name)
    return stripped.replace("-", "_")


def _generate_main_tf(
    charm_name: str,
    resource_name: str,
    has_resources: bool,
    has_storage: bool,
) -> str:
    """Build the ``main.tf`` content."""
    lines = [
        _COPYRIGHT,
        f'resource "juju_application" "{resource_name}" {{',
        "  name  = var.app_name",
        "  model = var.model",
        "",
        "  charm {",
        f'    name     = "{charm_name}"',
        "    channel  = var.channel",
        "    revision = var.revision",
        "    base     = var.base",
        "  }",
        "",
        "  config      = var.config",
        "  constraints = var.constraints",
        "  trust       = true",
        "  units       = var.units",
    ]
    if has_resources:
        lines.append("  resources = var.resources")
    if has_storage:
        lines.append("  storage_directives = var.storage_directives")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _generate_variables_tf(
    charm_name: str,
    has_resources: bool,
    has_storage: bool,
) -> str:
    """Build the ``variables.tf`` content."""
    blocks: list[str] = [_COPYRIGHT]

    blocks.append(
        textwrap.dedent(f"""\
        variable "app_name" {{
          description = "Name of the application in the Juju model."
          type        = string
          default     = "{charm_name}"
        }}
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "channel" {
          description = "Channel to deploy the charm from."
          type        = string
          default     = "latest/edge"
        }
    """)
    )

    blocks.append(
        textwrap.dedent(f"""\
        variable "config" {{
          description = "Charm configuration options. See https://charmhub.io/{charm_name}/configure for details."
          type        = map(string)
          default     = {{}}
        }}
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "constraints" {
          description = "Juju constraints for the application."
          type        = string
          default     = "arch=amd64"
        }
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "model" {
          description = "Name of the Juju model to deploy to."
          type        = string
        }
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "revision" {
          description = "Charm revision to deploy. Uses latest from channel if null."
          type        = number
          default     = null
        }
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "units" {
          description = "Number of units to deploy."
          type        = number
          default     = 1
        }
    """)
    )

    blocks.append(
        textwrap.dedent("""\
        variable "base" {
          description = "Base for the charm (e.g. ubuntu@22.04)."
          type        = string
          default     = "ubuntu@22.04"
        }
    """)
    )

    if has_resources:
        blocks.append(
            textwrap.dedent("""\
            variable "resources" {
              description = "Map of resource names to OCI image revisions."
              type        = map(string)
              default     = {}
            }
        """)
        )

    if has_storage:
        blocks.append(
            textwrap.dedent("""\
            variable "storage_directives" {
              description = "Map of storage names to directives (e.g. pool,size,count)."
              type        = map(string)
              default     = {}
            }
        """)
        )

    return "\n".join(blocks)


def _generate_outputs_tf(
    resource_name: str,
    provides: dict[str, dict[str, str]],
    requires: dict[str, dict[str, str]],
) -> str:
    """Build the ``outputs.tf`` content."""
    lines = [_COPYRIGHT]

    lines.append(
        textwrap.dedent(f"""\
        output "app_name" {{
          description = "Name of the deployed application."
          value       = juju_application.{resource_name}.name
        }}
    """)
    )

    if provides:
        lines.append('output "provides" {')
        lines.append('  description = "Map of provided relation endpoints."')
        lines.append("  value = {")
        for ep_name in sorted(provides):
            tf_key = ep_name.replace("-", "_")
            lines.append(f'    {tf_key} = "{ep_name}"')
        lines.append("  }")
        lines.append("}")
        lines.append("")

    if requires:
        lines.append('output "requires" {')
        lines.append('  description = "Map of required relation endpoints."')
        lines.append("  value = {")
        for ep_name in sorted(requires):
            tf_key = ep_name.replace("-", "_")
            lines.append(f'    {tf_key} = "{ep_name}"')
        lines.append("  }")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _generate_versions_tf() -> str:
    """Build the ``versions.tf`` content."""
    return (
        _COPYRIGHT
        + "\n"
        + textwrap.dedent("""\
        terraform {
          required_version = ">= 1.6"
          required_providers {
            juju = {
              source  = "juju/juju"
              version = "~> 1.0"
            }
          }
        }
    """)
    )


def generate_terraform_module(charmcraft_path: pathlib.Path) -> dict[str, str]:
    """Generate Terraform module files from a charmcraft.yaml.

    Reads the charmcraft.yaml at *charmcraft_path*, extracts charm metadata,
    and returns a dict mapping filenames to their content:
    ``{"main.tf": ..., "variables.tf": ..., "outputs.tf": ..., "versions.tf": ...}``
    """
    raw = yaml.safe_load(charmcraft_path.read_text())

    charm_name: str = raw["name"]
    res_name = _resource_name(charm_name)

    provides: dict[str, dict[str, str]] = raw.get("provides") or {}
    requires: dict[str, dict[str, str]] = raw.get("requires") or {}
    resources: dict[str, object] = raw.get("resources") or {}
    storage: dict[str, object] = raw.get("storage") or {}

    has_resources = bool(resources)
    has_storage = bool(storage)

    return {
        "main.tf": _generate_main_tf(charm_name, res_name, has_resources, has_storage),
        "variables.tf": _generate_variables_tf(charm_name, has_resources, has_storage),
        "outputs.tf": _generate_outputs_tf(res_name, provides, requires),
        "versions.tf": _generate_versions_tf(),
    }
