"""Shared helpers and constants for the acceptance testing tools.

Holds the patchable ``juju_subprocess`` reference plus the charm-metadata
loader, relation-data verifier, unit-address lookup, and the action/config
test-value generators that the individual acceptance tools build on.
"""

import json
import pathlib
import re
import subprocess
from typing import Any

import yaml

from cantrip.agent.tools import juju_subprocess

# Wait timeout after changes (seconds).
_SETTLE_TIMEOUT = 300

# Patterns indicating destructive actions that should be skipped by default.
_DESTRUCTIVE_PATTERNS = re.compile(
    r"^(delete|destroy|reset|purge|wipe|remove|drop|erase|nuke)-",
    re.IGNORECASE,
)

# Well-known interface → partner charm mapping for relation smoke tests.
#
# Identity-platform interfaces (oauth, oauth-cli, oidc-info,
# hydra-token-introspect, kratos-external-idp) are smoke-tested against
# the standalone hydra / kratos charms rather than the
# canonical-identity-platform bundle: the smoke harness deploys one
# partner per interface, and a single charm gives a tighter blast radius
# than a multi-app bundle.  The bundle topology is the *deployment*
# default (see the identity-platform skill); the smoke topology is just
# scoped narrower.
_INTERFACE_PARTNERS: dict[str, str] = {
    "mysql_client": "mysql-k8s",
    "mysql": "mysql-k8s",
    "pgsql": "postgresql-k8s",
    "postgresql_client": "postgresql-k8s",
    "ingress": "traefik-k8s",
    "ingress-per-unit": "traefik-k8s",
    "cos-agent": "grafana-agent-k8s",
    "grafana-dashboard": "grafana-k8s",
    "metrics-endpoint": "prometheus-k8s",
    "logging": "loki-k8s",
    "tracing": "tempo-k8s",
    "mongodb_client": "mongodb-k8s",
    "redis": "redis-k8s",
    "s3": "s3-integrator",
    "certificates": "self-signed-certificates",
    "oauth": "hydra",
    "oauth-cli": "hydra",
    "oidc-info": "hydra",
    "hydra-token-introspect": "hydra",
    "kratos-external-idp": "kratos",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_charm_metadata(charm_dir: pathlib.Path) -> dict[str, Any] | None:
    """Load charm metadata, merging the legacy split-yaml shape into one dict.

    Modern charms keep everything in ``charmcraft.yaml``, but legacy
    charms still split into ``metadata.yaml`` (``requires``/``provides``/
    ``peers``), ``config.yaml`` (``options:``), and ``actions.yaml``
    (top-level action map).  When a split file exists *and* the
    charmcraft.yaml block is missing, the legacy file is folded into
    the same shape the acceptance tools expect from charmcraft.yaml —
    so a smoke run against a split-shape charm doesn't silently report
    "nothing to test".

    ``charmcraft.yaml`` always wins on conflict, mirroring how
    ``charmcraft`` itself merges the two formats.  Returns ``None``
    only when no metadata is found at all.
    """

    def _safe_load(path: pathlib.Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = yaml.safe_load(path.read_text(errors="replace"))
        except (yaml.YAMLError, RecursionError):
            return {}
        return data if isinstance(data, dict) else {}

    charmcraft = _safe_load(charm_dir / "charmcraft.yaml")
    metadata = _safe_load(charm_dir / "metadata.yaml")
    config_yaml = _safe_load(charm_dir / "config.yaml")
    actions_yaml = _safe_load(charm_dir / "actions.yaml")

    if not (charmcraft or metadata or config_yaml or actions_yaml):
        return None

    # Start from metadata.yaml (top-level requires/provides/peers/name shape
    # already matches charmcraft.yaml), then layer charmcraft.yaml on top.
    merged: dict[str, Any] = dict(metadata)
    merged.update(charmcraft)

    # actions.yaml: top-level keys are action names; promote into ``actions:``
    # only when charmcraft.yaml didn't already set the block.
    if actions_yaml and not merged.get("actions"):
        merged["actions"] = actions_yaml

    # config.yaml: top-level ``options:``; promote into ``config: options:``.
    if config_yaml and not merged.get("config"):
        options = config_yaml.get("options")
        if isinstance(options, dict):
            merged["config"] = {"options": options}

    return merged


def _verify_relation_data(
    unit: str,
    endpoint: str,
    model: str | None,
) -> tuple[bool, str]:
    """Check whether a relation databag has non-trivial data.

    Returns (has_data, notes) where has_data is True if the related unit
    published at least one key beyond standard address fields.
    """
    cmd = ["juju", "show-unit", unit, "--format", "json"]
    if model:
        cmd.extend(["--model", model])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=juju_subprocess.JUJU_SUBPROCESS_TIMEOUT
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, "Could not read relation data"

    if result.returncode != 0:
        return False, "juju show-unit failed"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "Invalid JSON from show-unit"

    unit_data = data.get(unit, {})
    # Standard address-only keys that don't indicate real data flow.
    _ADDRESS_KEYS = {"ingress-address", "private-address", "egress-subnets"}

    for rel in unit_data.get("relation-info", []):
        if rel.get("endpoint") != endpoint:
            continue
        # Check application-level data.
        app_data = rel.get("application-data", {})
        meaningful_app = set(app_data.keys()) - _ADDRESS_KEYS
        if meaningful_app:
            return True, f"App data keys: {', '.join(sorted(meaningful_app))}"
        # Check related unit data.
        for _runit, rdata in rel.get("related-units", {}).items():
            meaningful_unit = set(rdata.get("data", {}).keys()) - _ADDRESS_KEYS
            if meaningful_unit:
                return True, f"Unit data keys: {', '.join(sorted(meaningful_unit))}"
        return False, "Relation established but databag is empty (address-only)"

    return False, "Endpoint not found in relation-info"


def _get_unit_address(app: str, model: str | None) -> str | None:
    """Get the address of the first unit via juju status --format json."""
    result = juju_subprocess.run_juju(["status", "--format", "json", app], model)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        units = data.get("applications", {}).get(app, {}).get("units", {})
        for _unit_name, unit_data in sorted(units.items()):
            addr = unit_data.get("address")
            if addr:
                return addr
    except (ValueError, KeyError):
        pass
    return None


def _generate_action_params(action_spec: dict[str, Any]) -> dict[str, str]:
    """Generate plausible parameter values from an action's parameter schema.

    Uses types, defaults, and descriptions to produce reasonable test values.
    """
    params: dict[str, str] = {}
    properties = action_spec.get("params", action_spec.get("parameters", {}))
    if not isinstance(properties, dict):
        return params

    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue

        # Use default if available.
        if "default" in spec:
            params[name] = str(spec["default"])
            continue

        # Generate from type.
        param_type = spec.get("type", "string")
        if param_type == "boolean":
            params[name] = "true"
        elif param_type in ("integer", "number"):
            minimum = spec.get("minimum", 1)
            params[name] = str(minimum)
        elif param_type == "string":
            # Use first enum value if available, otherwise a placeholder.
            enum_vals = spec.get("enum", [])
            if enum_vals:
                params[name] = str(enum_vals[0])
            else:
                params[name] = "test"
        elif param_type == "array":
            params[name] = "[]"

    return params


def _generate_test_value(
    opt_type: str,
    default: Any,
) -> str | None:
    """Generate a non-default config test value for a given type.

    Returns ``None`` if no sensible alternative can be produced.
    """
    if opt_type == "boolean":
        # Toggle from default.
        if default is True:
            return "false"
        return "true"
    if opt_type in ("int", "integer"):
        base = int(default) if default is not None else 0
        return str(base + 1)
    if opt_type == "float":
        base = float(default) if default is not None else 0.0
        return str(base + 0.5)
    if opt_type == "string":
        if default:
            return f"{default}-test"
        return "test-value"
    return None
