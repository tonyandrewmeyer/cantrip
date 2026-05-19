#!/usr/bin/env python3

"""Verifier for the ``build-a-stateful-charm`` cookbook recipe.

This is the counterpart to ``build-a-sprint-charm``: where the
sprint recipe verifies the *fast* path (no tests, ops-only deps),
this one verifies the **full** path Cantrip commits to for a
production charm — Scenario unit tests, ops-tracing, COS
integration, Jubilant integration tests.

Asserts that a charm directory produced by the full build matches
this shape:

- ``charmcraft.yaml`` exists, is a valid YAML mapping, and names
  the charm.
- ``src/charm.py`` exists.
- **ops-tracing is wired up**: ``ops-tracing`` (or ``ops[tracing]``)
  appears in ``pyproject.toml`` or ``requirements.txt``;
  ``src/charm.py`` references the ``ops_tracing`` module; and
  ``charmcraft.yaml`` declares a ``tracing`` relation.
- **COS integration beyond tracing** — at least one of: a metrics /
  logs / dashboard relation in ``charmcraft.yaml``, or a
  ``src/grafana_dashboards/`` / ``src/prometheus_alert_rules/`` /
  ``src/loki_alert_rules/`` directory with content.
- **Scenario unit tests** — ``tests/`` holds at least one ``.py``
  file, at least one uses a state-transition construct
  (``testing.Context`` / ``testing.State`` / ``ctx.run(...)``), and
  none uses the deprecated ``ops.testing.Harness``.
- **Jubilant integration tests** — a ``tests/integration/``
  directory with at least one ``.py`` file, or any test file that
  imports ``jubilant``.

It does not run the tests or ``charmcraft pack`` — those need a
real environment. The verifier is a shape contract; run
``charm_validate`` (or ``uv run pytest``) yourself for behaviour.

Exit codes:
- ``0`` — every assertion passed.
- ``1`` — at least one assertion failed; reason printed to stderr.
- ``2`` — the supplied path isn't a directory, argv is wrong, or a
  required parser dependency (PyYAML) is missing.

Usage:
    python verify.py /path/to/full/charm/dir
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

# Mirrors ``cantrip.agent.tools.harness_inventory`` — keep in sync if
# the upstream detector changes.
_HARNESS_RE = re.compile(r"\btesting\.Harness\b|\bops\.testing\.Harness\b|\bHarness\(")
_SCENARIO_RE = re.compile(
    r"\btesting\.Scenario\b|\bScenario\(|\btesting\.Context\b|\bops\.testing\.Context\b"
    r"|\btesting\.State\b|\bctx\.run\("
)

# Interfaces / endpoint names that signal COS metrics / logs / dashboard
# integration (as opposed to the tracing relation, checked separately).
_COS_INTERFACES = frozenset(
    {
        "prometheus_scrape",
        "loki_push_api",
        "grafana_dashboard",
        "grafana_datasource",
        "cos_agent",
    }
)
_COS_ENDPOINT_NAMES = frozenset(
    {"metrics-endpoint", "logging", "grafana-dashboard", "grafana-source", "cos-agent"}
)
# Directories whose presence (with content) also counts as COS wiring.
_COS_ASSET_DIRS = (
    "src/grafana_dashboards",
    "src/prometheus_alert_rules",
    "src/loki_alert_rules",
)

# Endpoint names / interfaces that count as the ops-tracing relation.
_TRACING_ENDPOINT_NAMES = frozenset({"tracing", "charm-tracing"})


class VerifyError(Exception):
    """Raised when a full-build invariant is violated."""


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


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(_read(path))
    except yaml.YAMLError as exc:
        raise VerifyError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise VerifyError(f"{path} must be a YAML mapping at the top level")
    return data


def _endpoints(charmcraft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten ``requires`` / ``provides`` / ``peers`` into ``name -> spec``."""
    out: dict[str, dict[str, Any]] = {}
    for section in ("requires", "provides", "peers"):
        block = charmcraft.get(section) or {}
        if not isinstance(block, dict):
            continue
        for name, spec in block.items():
            out[str(name)] = spec if isinstance(spec, dict) else {}
    return out


def _dep_text(charm_dir: pathlib.Path) -> str:
    """Return the concatenated text of every dependency manifest present."""
    chunks: list[str] = []
    for rel in ("pyproject.toml", "requirements.txt"):
        path = charm_dir / rel
        if path.exists():
            chunks.append(_read(path))
    return "\n".join(chunks)


def check_charm_skeleton(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Assert this is a charm: ``charmcraft.yaml`` (named) plus ``src/charm.py``."""
    charmcraft = _load_yaml(_require(charm_dir, "charmcraft.yaml"))
    if not charmcraft.get("name"):
        raise VerifyError("charmcraft.yaml has no 'name' — not a buildable charm")
    _require(charm_dir, "src/charm.py")
    return charmcraft


def check_ops_tracing(charm_dir: pathlib.Path, charmcraft: dict[str, Any]) -> None:
    """Assert ops-tracing is declared, imported, and related."""
    deps = _dep_text(charm_dir).replace(" ", "").lower()
    if "ops-tracing" not in deps and "ops[tracing]" not in deps:
        raise VerifyError(
            "no ops-tracing dependency in pyproject.toml / requirements.txt — "
            "the full path always instruments charm code with ops-tracing"
        )

    charm_src = _read(charm_dir / "src" / "charm.py")
    if "ops_tracing" not in charm_src:
        raise VerifyError(
            "src/charm.py does not reference the ops_tracing module — expected "
            '`import ops_tracing` and `ops_tracing.Tracing(self, "tracing")`'
        )

    endpoints = _endpoints(charmcraft)
    has_tracing_rel = any(
        name in _TRACING_ENDPOINT_NAMES or spec.get("interface") == "tracing"
        for name, spec in endpoints.items()
    )
    if not has_tracing_rel:
        raise VerifyError(
            "charmcraft.yaml has no tracing relation (a 'tracing'/'charm-tracing' "
            "endpoint, or one with interface: tracing) — ops_tracing.Tracing needs "
            "a matching relation to send spans to Tempo"
        )


def check_cos_integration(charm_dir: pathlib.Path, charmcraft: dict[str, Any]) -> None:
    """Assert at least one COS metrics / logs / dashboard signal is present."""
    endpoints = _endpoints(charmcraft)
    for name, spec in endpoints.items():
        if name in _COS_ENDPOINT_NAMES or spec.get("interface") in _COS_INTERFACES:
            return
    for rel in _COS_ASSET_DIRS:
        path = charm_dir / rel
        if path.is_dir() and any(path.iterdir()):
            return
    raise VerifyError(
        "no COS integration beyond tracing — expected a metrics-endpoint / "
        "logging / grafana-dashboard relation in charmcraft.yaml, or a "
        f"populated {' / '.join(_COS_ASSET_DIRS)} directory"
    )


def _test_files(charm_dir: pathlib.Path) -> list[pathlib.Path]:
    tests_root = charm_dir / "tests"
    if not tests_root.is_dir():
        raise VerifyError(
            f"no tests/ directory in {charm_dir} — the full path always ships "
            "Scenario unit tests and Jubilant integration tests"
        )
    return sorted(tests_root.rglob("*.py"))


def check_unit_tests(charm_dir: pathlib.Path, test_files: list[pathlib.Path]) -> None:
    """Assert Scenario unit tests exist and no Harness usage remains."""
    if not test_files:
        raise VerifyError(f"tests/ under {charm_dir} contains no .py files")
    offenders = [str(p.relative_to(charm_dir)) for p in test_files if _HARNESS_RE.search(_read(p))]
    if offenders:
        raise VerifyError(
            f"these test files use the deprecated ops.testing.Harness: {offenders!r} "
            "— the full path uses state-transition (Scenario) unit tests"
        )
    if not any(_SCENARIO_RE.search(_read(p)) for p in test_files):
        raise VerifyError(
            "no test file uses a state-transition construct (testing.Context / "
            "testing.State / ctx.run(...)) — unit tests must be Scenario tests"
        )


def check_integration_tests(charm_dir: pathlib.Path, test_files: list[pathlib.Path]) -> None:
    """Assert Jubilant integration tests are present."""
    integ_dir = charm_dir / "tests" / "integration"
    if integ_dir.is_dir() and any(integ_dir.rglob("*.py")):
        return
    if any("jubilant" in _read(p) for p in test_files):
        return
    raise VerifyError(
        "no Jubilant integration tests — expected a tests/integration/ directory "
        "with .py files, or a test file that imports jubilant"
    )


def verify(charm_dir: pathlib.Path) -> None:
    """Run every full-build check against *charm_dir*."""
    if not charm_dir.is_dir():
        raise VerifyError(f"{charm_dir} is not a directory")
    charmcraft = check_charm_skeleton(charm_dir)
    check_ops_tracing(charm_dir, charmcraft)
    check_cos_integration(charm_dir, charmcraft)
    test_files = _test_files(charm_dir)
    check_unit_tests(charm_dir, test_files)
    check_integration_tests(charm_dir, test_files)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(
            "Usage: verify.py <charm-dir>\n  <charm-dir>: path to the charm Cantrip built\n"
        )
        return 2
    charm_dir = pathlib.Path(argv[0]).resolve()
    try:
        verify(charm_dir)
    except VerifyError as exc:
        sys.stderr.write(f"FAIL: {exc}\n")
        return 1
    print("OK — full-build shape verified (tests + tracing + COS).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
