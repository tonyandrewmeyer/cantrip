#!/usr/bin/env python3

"""Verifier for the ``build-a-sprint-charm`` cookbook recipe.

Asserts that a charm directory produced by sprint mode matches the
shape the recipe teaches:

- ``charmcraft.yaml`` exists and pins ``base: ubuntu@24.04``.
- At least one part uses the ``charm`` plugin.
- No part declares ``build-snaps:`` (sprint mode removes them).
- ``requirements.txt`` exists and contains exactly one ``ops>=3,<4``
  pin with no extras (``ops-tracing`` / ``ops-scenario`` and
  third-party deps are forbidden in sprint mode).
- ``src/charm.py`` exists.

Exit codes:
- ``0`` — every assertion passed.
- ``1`` — at least one assertion failed; reason printed to stderr.
- ``2`` — the supplied path isn't a charm directory at all.

Usage:
    python verify.py /path/to/sprint/charm/dir
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("verify.py requires PyYAML (pip install pyyaml / uv sync).\n")
    sys.exit(2)


class VerifyError(Exception):
    """Raised when a sprint-mode invariant is violated."""


def _require(charm_dir: pathlib.Path, rel: str) -> pathlib.Path:
    """Return ``charm_dir / rel`` or raise :class:`VerifyError` if missing."""
    path = charm_dir / rel
    if not path.exists():
        raise VerifyError(f"missing {rel!r} in {charm_dir}")
    return path


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise VerifyError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise VerifyError(f"{path} must be a YAML mapping at the top level")
    return data


def check_charmcraft_yaml(charm_dir: pathlib.Path) -> None:
    """Assert sprint-mode invariants on ``charmcraft.yaml``."""
    path = _require(charm_dir, "charmcraft.yaml")
    data = _load_yaml(path)

    base = data.get("base")
    if base != "ubuntu@24.04":
        raise VerifyError(
            f"charmcraft.yaml base is {base!r}, expected 'ubuntu@24.04' "
            "(sprint mode pins this base so packing stays fast)"
        )

    parts = data.get("parts") or {}
    if not isinstance(parts, dict) or not parts:
        raise VerifyError(
            "charmcraft.yaml has no parts — sprint mode needs at least one charm-plugin part"
        )

    has_charm_plugin = any(
        isinstance(part, dict) and part.get("plugin") == "charm" for part in parts.values()
    )
    if not has_charm_plugin:
        plugins = {
            name: part.get("plugin") if isinstance(part, dict) else None
            for name, part in parts.items()
        }
        raise VerifyError(
            "charmcraft.yaml has no part using plugin: charm "
            f"(parts: {plugins!r}). Sprint mode uses the charm plugin; uv "
            "plugin triggers a slower source build."
        )

    for name, part in parts.items():
        if isinstance(part, dict) and "build-snaps" in part:
            raise VerifyError(
                f"charmcraft.yaml part {name!r} declares build-snaps — "
                "sprint mode removes build-snaps to keep packing fast"
            )


_OPS_PIN = re.compile(r"^\s*ops\s*([<>=!~].+)?$")
_OPS_PIN_RANGE = re.compile(r"^ops\s*>=\s*3(?:[.,]|$|\s)")


def check_requirements(charm_dir: pathlib.Path) -> None:
    """Assert sprint-mode invariants on ``requirements.txt``."""
    path = _require(charm_dir, "requirements.txt")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise VerifyError("requirements.txt is empty — sprint mode needs exactly one ops pin")

    forbidden = {"ops-tracing", "ops-scenario"}
    for line in lines:
        base_name = re.split(r"[<>=!~\s]", line, maxsplit=1)[0].strip().lower()
        if base_name in forbidden:
            raise VerifyError(
                f"requirements.txt contains {line!r} — sprint mode forbids "
                f"{sorted(forbidden)} so source builds stay small"
            )

    if len(lines) != 1:
        raise VerifyError(
            f"requirements.txt has {len(lines)} non-blank lines "
            f"({lines!r}); sprint mode pins only a single ops>=3,<4 line"
        )

    only = lines[0]
    if not _OPS_PIN.match(only):
        raise VerifyError(
            f"requirements.txt line {only!r} is not an ops pin; sprint mode expects ops>=3,<4"
        )
    # Loose check for the version range: ops>=3 (with optional ,<4).
    normalised = only.replace(" ", "")
    if not normalised.startswith("ops>=3"):
        raise VerifyError(
            f"requirements.txt line {only!r} does not pin ops>=3 — sprint "
            "mode requires the ops>=3,<4 range"
        )


def check_src_charm(charm_dir: pathlib.Path) -> None:
    """Assert that ``src/charm.py`` exists."""
    _require(charm_dir, "src/charm.py")


def verify(charm_dir: pathlib.Path) -> None:
    """Run every sprint-mode check against *charm_dir*."""
    if not charm_dir.is_dir():
        raise VerifyError(f"{charm_dir} is not a directory")
    check_charmcraft_yaml(charm_dir)
    check_requirements(charm_dir)
    check_src_charm(charm_dir)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(
            "Usage: verify.py <charm-dir>\n  <charm-dir>: path to the directory Cantrip built\n"
        )
        return 2
    charm_dir = pathlib.Path(argv[0]).resolve()
    try:
        verify(charm_dir)
    except VerifyError as exc:
        sys.stderr.write(f"FAIL: {exc}\n")
        return 1
    print("OK — sprint-mode shape verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
