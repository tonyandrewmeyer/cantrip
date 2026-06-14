#!/usr/bin/env python3

"""Verifier for the ``generate-a-terraform-module`` cookbook recipe.

Asserts that a charm directory carries a Terraform module of the
standard shape Cantrip's ``terraform`` skill teaches:

- A ``terraform/`` directory at the charm root holding exactly the
  four standard files: ``main.tf``, ``variables.tf``, ``outputs.tf``,
  ``terraform.tf``.
- ``main.tf`` declares a ``resource "juju_application" "..." {}``
  block with a nested ``charm { ... }`` block that names *this*
  charm (the ``name`` from ``charmcraft.yaml``), not a placeholder.
- ``variables.tf`` declares at least one ``variable "..." {}`` block.
- ``outputs.tf`` declares at least one ``output "..." {}`` block.
- ``terraform.tf`` has a ``terraform { ... }`` block with a
  ``required_providers`` entry pinning the ``juju/juju`` provider
  source.

It does not run ``terraform init`` / ``validate`` — that needs the
Terraform CLI and a provider download. The verifier is a shape
contract; run ``terraform validate`` in ``terraform/`` yourself for
the parse check.

Exit codes:
- ``0`` — every assertion passed.
- ``1`` — at least one assertion failed; reason printed to stderr.
- ``2`` — the supplied path isn't a directory, argv is wrong, or a
  required parser dependency (PyYAML) is missing.

Usage:
    python verify.py /path/to/charm/dir
"""

from __future__ import annotations

import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write("verify.py requires PyYAML (pip install pyyaml / uv sync).\n")
    sys.exit(2)

_MODULE_DIR = "terraform"
_REQUIRED_FILES = ("main.tf", "variables.tf", "outputs.tf", "terraform.tf")

_JUJU_APPLICATION_RE = re.compile(r'resource\s+"juju_application"\s+"[^"]+"\s*\{')
_VARIABLE_BLOCK_RE = re.compile(r'variable\s+"[^"]+"\s*\{')
_OUTPUT_BLOCK_RE = re.compile(r'output\s+"[^"]+"\s*\{')
_TERRAFORM_BLOCK_RE = re.compile(r"terraform\s*\{")


class VerifyError(Exception):
    """Raised when a Terraform-module invariant is violated."""


def _require(charm_dir: pathlib.Path, rel: str) -> pathlib.Path:
    """Return ``charm_dir / rel`` or raise :class:`VerifyError` if missing."""
    path = charm_dir / rel
    if not path.exists():
        raise VerifyError(f"missing {rel!r} in {charm_dir}")
    return path


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc


def _charm_name(charm_dir: pathlib.Path) -> str:
    """Return the charm's ``name`` from ``charmcraft.yaml``, or raise."""
    path = _require(charm_dir, "charmcraft.yaml")
    try:
        data = yaml.safe_load(_read(path))
    except yaml.YAMLError as exc:
        raise VerifyError(f"charmcraft.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or not data.get("name"):
        raise VerifyError("charmcraft.yaml has no 'name' — can't tie the module to a charm")
    return str(data["name"])


def check_module_files(charm_dir: pathlib.Path) -> dict[str, str]:
    """Assert ``terraform/`` exists with the four standard files; return their text."""
    tf_dir = charm_dir / _MODULE_DIR
    if not tf_dir.is_dir():
        raise VerifyError(
            f"no {_MODULE_DIR}/ directory in {charm_dir} — a charm Terraform module "
            f"lives in {_MODULE_DIR}/ at the charm root"
        )
    texts: dict[str, str] = {}
    missing: list[str] = []
    for name in _REQUIRED_FILES:
        path = tf_dir / name
        if path.is_file():
            texts[name] = _read(path)
        else:
            missing.append(name)
    if missing:
        raise VerifyError(
            f"{_MODULE_DIR}/ is missing required file(s): {missing!r} — the standard "
            f"module has {', '.join(_REQUIRED_FILES)}"
        )
    return texts


def check_main_tf(texts: dict[str, str], charm_name: str) -> None:
    """Assert ``main.tf`` deploys *this* charm via a ``juju_application`` resource."""
    main = texts["main.tf"]
    if not _JUJU_APPLICATION_RE.search(main):
        raise VerifyError(
            'terraform/main.tf has no `resource "juju_application" "..." {}` block — '
            "that resource is the heart of the module"
        )
    if "charm" not in main:
        raise VerifyError(
            "terraform/main.tf's juju_application has no `charm { ... }` block — it "
            "needs one naming the Charmhub charm and channel"
        )
    if f'"{charm_name}"' not in main:
        raise VerifyError(
            f'terraform/main.tf does not reference the charm name "{charm_name}" (from '
            "charmcraft.yaml) — the module should deploy this charm, not a placeholder"
        )


def check_variables_tf(texts: dict[str, str]) -> None:
    """Assert ``variables.tf`` declares at least one input variable."""
    if not _VARIABLE_BLOCK_RE.search(texts["variables.tf"]):
        raise VerifyError(
            'terraform/variables.tf declares no `variable "..." {}` blocks — callers '
            "need at least model / channel inputs to override"
        )


def check_outputs_tf(texts: dict[str, str]) -> None:
    """Assert ``outputs.tf`` exports at least one value."""
    if not _OUTPUT_BLOCK_RE.search(texts["outputs.tf"]):
        raise VerifyError(
            'terraform/outputs.tf declares no `output "..." {}` blocks — downstream '
            "modules need at least the application name exported"
        )


def check_terraform_tf(texts: dict[str, str]) -> None:
    """Assert ``terraform.tf`` pins the Juju Terraform provider."""
    body = texts["terraform.tf"]
    if not _TERRAFORM_BLOCK_RE.search(body):
        raise VerifyError("terraform/terraform.tf has no `terraform { ... }` block")
    if "required_providers" not in body:
        raise VerifyError(
            "terraform/terraform.tf has no `required_providers` block — pin the Juju "
            "Terraform provider so the module resolves reproducibly"
        )
    if "juju/juju" not in body:
        raise VerifyError(
            "terraform/terraform.tf does not pin the `juju/juju` provider source — the "
            "module needs the Juju Terraform provider"
        )


def verify(charm_dir: pathlib.Path) -> None:
    """Run every Terraform-module check against *charm_dir*."""
    if not charm_dir.is_dir():
        raise VerifyError(f"{charm_dir} is not a directory")
    charm_name = _charm_name(charm_dir)
    texts = check_module_files(charm_dir)
    check_main_tf(texts, charm_name)
    check_variables_tf(texts)
    check_outputs_tf(texts)
    check_terraform_tf(texts)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(
            "Usage: verify.py <charm-dir>\n  <charm-dir>: path to the charm carrying the module\n"
        )
        return 2
    charm_dir = pathlib.Path(argv[0]).resolve()
    try:
        verify(charm_dir)
    except VerifyError as exc:
        sys.stderr.write(f"FAIL: {exc}\n")
        return 1
    print("OK — Terraform module shape verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
