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


def _hcl_variable(name: str, description: str, hcl_type: str, default: str | None) -> str:
    """Render a single HCL ``variable`` block."""
    lines = [
        f'variable "{name}" {{',
        f'  description = "{description}"',
        f"  type        = {hcl_type}",
    ]
    if default is not None:
        lines.append(f"  default     = {default}")
    lines.append("}")
    return "\n".join(lines)


def _generate_variables_tf(
    charm_name: str,
    has_resources: bool,
    has_storage: bool,
) -> str:
    """Build the ``variables.tf`` content.

    Variables are emitted in alphabetical order per CC008.
    """
    # Each entry: (name, description, hcl_type, default_or_None).
    specs: list[tuple[str, str, str, str | None]] = [
        ("app_name", "Name of the application in the Juju model.", "string", f'"{charm_name}"'),
        ("base", "Base for the charm (e.g. ubuntu@22.04).", "string", "null"),
        ("channel", "Channel to deploy the charm from.", "string", '"latest/edge"'),
        (
            "config",
            f"Charm configuration options. See https://charmhub.io/{charm_name}/configure for "
            "details.",
            "map(string)",
            "{}",
        ),
        ("constraints", "Juju constraints for the application.", "string", "null"),
        ("model_uuid", "UUID of the Juju model to deploy to.", "string", None),
        (
            "revision",
            "Charm revision to deploy. Uses latest from channel if null.",
            "number",
            "null",
        ),
        ("units", "Number of units to deploy.", "number", "1"),
    ]

    if has_resources:
        specs.append(
            ("resources", "Map of resource names to OCI image revisions.", "map(string)", "{}")
        )
    if has_storage:
        specs.append(
            (
                "storage_directives",
                "Map of storage names to directives (e.g. pool,size,count).",
                "map(string)",
                "{}",
            )
        )

    # Sort alphabetically by variable name.
    specs.sort(key=lambda s: s[0])

    blocks = [_COPYRIGHT]
    for name, description, hcl_type, default in specs:
        blocks.append(_hcl_variable(name, description, hcl_type, default))
        blocks.append("")

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

    output_blocks.append(
        (
            "application",
            textwrap.dedent(f"""\
        output "application" {{
          description = "The deployed application object."
          value       = juju_application.{resource_name}
        }}
    """),
        )
    )

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
    try:
        raw = yaml.safe_load(charmcraft_path.read_text(errors="replace"))
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f"Invalid YAML in {charmcraft_path}: {exc}") from exc
    if not raw or not isinstance(raw, dict):
        raise ValueError("charmcraft.yaml is empty or not a mapping")

    if "name" not in raw:
        raise KeyError("charmcraft.yaml missing required 'name' field")
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
