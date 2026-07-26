#!/usr/bin/env python3

"""Verifier for the ``add-observability`` cookbook recipe.

Asserts that an existing charm has been wired into the Canonical
Observability Stack the way Cantrip's ``observability`` skill
teaches:

- It's still a charm — ``charmcraft.yaml`` (valid, named) plus
  ``src/charm.py``.
- **ops-tracing is wired up**: ``ops-tracing`` (or ``ops[tracing]``)
  is a dependency; ``src/charm.py`` references the ``ops_tracing``
  module; and ``charmcraft.yaml`` declares a ``tracing`` relation.
- **The metrics, logs, and dashboards relations are all present**
  in ``charmcraft.yaml`` — either as separate endpoints
  (``metrics-endpoint`` / ``logging`` / ``grafana-dashboard``, by
  name or interface) or via a single ``cos-agent`` relation, which
  carries all three for machine charms.
- **At least one Grafana dashboard ships** — a populated
  ``src/grafana_dashboards/`` directory (where
  ``GrafanaDashboardProvider`` / ``COSAgentProvider`` look for
  dashboard JSON).
- **The COS provider libraries are actually wired** — ``src/charm.py``
  references at least one of ``MetricsEndpointProvider``,
  ``GrafanaDashboardProvider``, ``LokiPushApiConsumer``,
  ``LogProxyConsumer``, ``LogForwarder``, ``COSAgentProvider`` — so
  the relations aren't decoration.

It does not run the tests or ``charmcraft pack`` — those need a real
environment. The verifier is a shape contract; run ``charm_validate``
(or ``uv run pytest``) yourself for behaviour.

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
import sys
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("verify.py requires PyYAML (pip install pyyaml / uv sync).\n")
    sys.exit(2)

# Endpoint names / interfaces that count as the ops-tracing relation.
_TRACING_ENDPOINT_NAMES = frozenset({"tracing", "charm-tracing"})

# The all-in-one COS relation (machine charms): one of these and you
# have metrics + logs + dashboards in a single endpoint.
_COS_AGENT_NAMES = frozenset({"cos-agent", "cos-agent-receiver"})
_COS_AGENT_INTERFACES = frozenset({"cos_agent"})

# Per-pillar signals when the charm wires the three COS relations
# separately (typical for K8s charms).
_METRICS_NAMES = frozenset({"metrics-endpoint", "self-metrics-endpoint"})
_METRICS_INTERFACES = frozenset({"prometheus_scrape"})
_LOGS_NAMES = frozenset({"logging", "log-proxy", "logging-consumer"})
_LOGS_INTERFACES = frozenset({"loki_push_api"})
_DASHBOARD_NAMES = frozenset({"grafana-dashboard"})
_DASHBOARD_INTERFACES = frozenset({"grafana_dashboard"})

# Provider/consumer classes that mean the relations are actually wired.
_COS_PROVIDER_CLASSES = (
    "MetricsEndpointProvider",
    "GrafanaDashboardProvider",
    "LokiPushApiConsumer",
    "LogProxyConsumer",
    "LogForwarder",
    "COSAgentProvider",
)

_DASHBOARD_DIR = "src/grafana_dashboards"


class VerifyError(Exception):
    """Raised when a COS-integration invariant is violated."""


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


def _matches(
    endpoints: dict[str, dict[str, Any]], names: frozenset, interfaces: frozenset
) -> bool:
    return any(
        name in names or spec.get("interface") in interfaces for name, spec in endpoints.items()
    )


def _dep_text(charm_dir: pathlib.Path) -> str:
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
            "no ops-tracing dependency in pyproject.toml / requirements.txt — COS "
            "integration starts with ops-tracing for charm-code spans"
        )
    if "ops_tracing" not in _read(charm_dir / "src" / "charm.py"):
        raise VerifyError(
            "src/charm.py does not reference the ops_tracing module — expected "
            '`import ops_tracing` and `ops_tracing.Tracing(self, "tracing")`'
        )
    endpoints = _endpoints(charmcraft)
    if not any(
        name in _TRACING_ENDPOINT_NAMES or spec.get("interface") == "tracing"
        for name, spec in endpoints.items()
    ):
        raise VerifyError(
            "charmcraft.yaml has no tracing relation (a 'tracing'/'charm-tracing' "
            "endpoint, or one with interface: tracing) — ops_tracing.Tracing needs "
            "a matching relation to send spans to Tempo"
        )


def check_cos_relations(charmcraft: dict[str, Any]) -> None:
    """Assert metrics, logs, and dashboard relations are all present."""
    endpoints = _endpoints(charmcraft)
    has_cos_agent = _matches(endpoints, _COS_AGENT_NAMES, _COS_AGENT_INTERFACES)
    pillars = {
        "metrics": has_cos_agent or _matches(endpoints, _METRICS_NAMES, _METRICS_INTERFACES),
        "logs": has_cos_agent or _matches(endpoints, _LOGS_NAMES, _LOGS_INTERFACES),
        "dashboards": has_cos_agent
        or _matches(endpoints, _DASHBOARD_NAMES, _DASHBOARD_INTERFACES),
    }
    missing = sorted(p for p, present in pillars.items() if not present)
    if missing:
        raise VerifyError(
            f"charmcraft.yaml is missing COS relation(s) for: {missing} — wire "
            "metrics-endpoint / logging / grafana-dashboard (or a single cos-agent "
            "relation, which covers all three for machine charms)"
        )


def check_dashboard_assets(charm_dir: pathlib.Path) -> None:
    """Assert at least one Grafana dashboard ships under ``src/grafana_dashboards/``."""
    path = charm_dir / _DASHBOARD_DIR
    if not path.is_dir() or not any(path.iterdir()):
        raise VerifyError(
            f"no dashboards under {_DASHBOARD_DIR}/ — GrafanaDashboardProvider / "
            "COSAgentProvider forward dashboard JSON from there; ship at least one"
        )


def check_providers_wired(charm_dir: pathlib.Path) -> None:
    """Assert ``src/charm.py`` actually instantiates a COS provider/consumer."""
    charm_src = _read(charm_dir / "src" / "charm.py")
    if not any(cls in charm_src for cls in _COS_PROVIDER_CLASSES):
        raise VerifyError(
            "src/charm.py references none of "
            f"{list(_COS_PROVIDER_CLASSES)} — the COS relations are declared but not "
            "wired; instantiate the matching provider/consumer in the charm"
        )


def verify(charm_dir: pathlib.Path) -> None:
    """Run every COS-integration check against *charm_dir*."""
    if not charm_dir.is_dir():
        raise VerifyError(f"{charm_dir} is not a directory")
    charmcraft = check_charm_skeleton(charm_dir)
    check_ops_tracing(charm_dir, charmcraft)
    check_cos_relations(charmcraft)
    check_dashboard_assets(charm_dir)
    check_providers_wired(charm_dir)


def main(argv: list[str]) -> int:
    """Verify the cookbook recipe's output and report the result."""
    if len(argv) != 1:
        sys.stderr.write(
            "Usage: verify.py <charm-dir>\n  <charm-dir>: path to the charm Cantrip instrumented\n"
        )
        return 2
    charm_dir = pathlib.Path(argv[0]).resolve()
    try:
        verify(charm_dir)
    except VerifyError as exc:
        sys.stderr.write(f"FAIL: {exc}\n")
        return 1
    print("OK — COS integration shape verified (tracing + metrics + logs + dashboards).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
