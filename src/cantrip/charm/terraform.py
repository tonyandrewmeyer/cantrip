"""Terraform module generator for Juju charms.

Generates a complete Terraform module (main.tf, variables.tf, outputs.tf,
terraform.tf) from a charmcraft.yaml file, following the CC008 Terraform
standard specification.  Pure template expansion — no LLM required.
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
        "  model = var.model_uuid",
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
    """Build the ``variables.tf`` content.

    Variables are emitted in alphabetical order per CC008.
    """
    # Collect all variable blocks, then sort alphabetically by variable name.
    variables: list[tuple[str, str]] = []

    variables.append((
        "app_name",
        textwrap.dedent(f"""\
        variable "app_name" {{
          description = "Name of the application in the Juju model."
          type        = string
          default     = "{charm_name}"
        }}
    """),
    ))

    variables.append((
        "base",
        textwrap.dedent("""\
        variable "base" {
          description = "Base for the charm (e.g. ubuntu@22.04)."
          type        = string
          default     = null
        }
    """),
    ))

    variables.append((
        "channel",
        textwrap.dedent("""\
        variable "channel" {
          description = "Channel to deploy the charm from."
          type        = string
          default     = "latest/edge"
        }
    """),
    ))

    variables.append((
        "config",
        textwrap.dedent(f"""\
        variable "config" {{
          description = "Charm configuration options. See https://charmhub.io/{charm_name}/configure for details."
          type        = map(string)
          default     = {{}}
        }}
    """),
    ))

    variables.append((
        "constraints",
        textwrap.dedent("""\
        variable "constraints" {
          description = "Juju constraints for the application."
          type        = string
          default     = null
        }
    """),
    ))

    variables.append((
        "model_uuid",
        textwrap.dedent("""\
        variable "model_uuid" {
          description = "UUID of the Juju model to deploy to."
          type        = string
        }
    """),
    ))

    if has_resources:
        variables.append((
            "resources",
            textwrap.dedent("""\
            variable "resources" {
              description = "Map of resource names to OCI image revisions."
              type        = map(string)
              default     = {}
            }
        """),
        ))

    variables.append((
        "revision",
        textwrap.dedent("""\
        variable "revision" {
          description = "Charm revision to deploy. Uses latest from channel if null."
          type        = number
          default     = null
        }
    """),
    ))

    if has_storage:
        variables.append((
            "storage_directives",
            textwrap.dedent("""\
            variable "storage_directives" {
              description = "Map of storage names to directives (e.g. pool,size,count)."
              type        = map(string)
              default     = {}
            }
        """),
        ))

    variables.append((
        "units",
        textwrap.dedent("""\
        variable "units" {
          description = "Number of units to deploy."
          type        = number
          default     = 1
        }
    """),
    ))

    # Sort alphabetically by variable name.
    variables.sort(key=lambda pair: pair[0])

    blocks: list[str] = [_COPYRIGHT]
    for _name, block in variables:
        blocks.append(block)

    return "\n".join(blocks)


def _generate_outputs_tf(
    resource_name: str,
    provides: dict[str, dict[str, str]],
    requires: dict[str, dict[str, str]],
) -> str:
    """Build the ``outputs.tf`` content.

    Outputs are emitted in alphabetical order per CC008.
    """
    output_blocks: list[tuple[str, str]] = []

    output_blocks.append((
        "application",
        textwrap.dedent(f"""\
        output "application" {{
          description = "The deployed application object."
          value       = juju_application.{resource_name}
        }}
    """),
    ))

    if provides:
        provide_lines = ['output "provides" {']
        provide_lines.append('  description = "Map of provided relation endpoints."')
        provide_lines.append("  value = {")
        for ep_name in sorted(provides):
            tf_key = ep_name.replace("-", "_")
            provide_lines.append(f'    {tf_key} = "{ep_name}"')
        provide_lines.append("  }")
        provide_lines.append("}")
        provide_lines.append("")
        output_blocks.append(("provides", "\n".join(provide_lines)))

    if requires:
        require_lines = ['output "requires" {']
        require_lines.append('  description = "Map of required relation endpoints."')
        require_lines.append("  value = {")
        for ep_name in sorted(requires):
            tf_key = ep_name.replace("-", "_")
            require_lines.append(f'    {tf_key} = "{ep_name}"')
        require_lines.append("  }")
        require_lines.append("}")
        require_lines.append("")
        output_blocks.append(("requires", "\n".join(require_lines)))

    # Sort alphabetically by output name.
    output_blocks.sort(key=lambda pair: pair[0])

    lines = [_COPYRIGHT]
    for _name, block in output_blocks:
        lines.append(block)

    return "\n".join(lines)


def _generate_terraform_tf() -> str:
    """Build the ``terraform.tf`` content."""
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
    ``{"main.tf": ..., "variables.tf": ..., "outputs.tf": ..., "terraform.tf": ...}``
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
        "terraform.tf": _generate_terraform_tf(),
    }
