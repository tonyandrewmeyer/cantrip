"""Operational readiness assessment tool.

Evaluates a charm against Canonical's Operational Readiness Metrics
standard, scoring it across five pillars: Best Practices, Documentation,
Reliability, Maintainability, and Security.  Produces a structured report
with pass/fail per check and categorised findings (must-fix, should-fix,
advisory).
"""

import contextlib
import pathlib
import re
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.estate_ops import (
    EstateOpportunity,
    assess_estate_opportunities,
    render_estate_section,
)

# ---------------------------------------------------------------------------
# Constants: pillar names, check definitions, action patterns
# ---------------------------------------------------------------------------

# Pillar names (keep ordering consistent).
PILLAR_BEST_PRACTICES = "Best Practices"
PILLAR_DOCUMENTATION = "Documentation"
PILLAR_RELIABILITY = "Reliability"
PILLAR_MAINTAINABILITY = "Maintainability"
PILLAR_SECURITY = "Security"

_PILLARS = [
    PILLAR_BEST_PRACTICES,
    PILLAR_DOCUMENTATION,
    PILLAR_RELIABILITY,
    PILLAR_MAINTAINABILITY,
    PILLAR_SECURITY,
]

# Status conditions the charm should report (via ops.StatusBase).
_EXPECTED_STATUS_CONDITIONS: list[tuple[str, str]] = [
    ("missing.*config", "Sets status for missing required configuration"),
    (
        "conflict.*config|invalid.*config|config.*invalid",
        "Sets status for conflicting/invalid config",
    ),
    (
        r"upstream|connect|unreachable|unavailable",
        "Sets status for inaccessible upstream services",
    ),
    (r"paus(?:e|ed|ing)", "Sets status for paused state"),
    (r"stop(?:ped)?|crash(?:ed)?", "Sets status for stopped/crashed services"),
    (r"missing.*relation|relation.*missing|no.*relation", "Sets status for missing relations"),
    (
        r"relation.*incomplete|incomplete.*relation|waiting.*relation",
        "Sets status for incomplete relations",
    ),
    (r"upgrad(?:e|ing)", "Sets status for upgrade in progress"),
]

# Common operational actions the charm should expose.
_EXPECTED_ACTIONS: dict[str, str] = {
    "get-health": "Health-check action (get-health, health-check, or check-health)",
    "pause": "Pause action to gracefully stop workload services",
    "resume": "Resume action to restart paused workload services",
}

# Alternative names for expected actions.
_ACTION_ALIASES: dict[str, list[str]] = {
    "get-health": ["health-check", "check-health", "get-status", "health"],
    "pause": ["stop", "disable"],
    "resume": ["start", "enable"],
}

# COS relation interfaces for full observability.
_COS_RELATIONS = {
    "tracing": "Tempo distributed tracing",
    "metrics-endpoint": "Prometheus metrics",
    "logging": "Loki log forwarding",
    "grafana-dashboard": "Grafana dashboard",
}

# Documentation files or sections expected.
_DOC_CHECKS: list[tuple[str, str, str]] = [
    ("installation", "Installation/setup guide", "must_fix"),
    ("configuration", "Configuration reference", "should_fix"),
    ("usage", "Usage instructions", "should_fix"),
    ("troubleshooting", "Troubleshooting guide", "should_fix"),
    ("management", "Management procedures", "should_fix"),
    ("upgrade", "Upgrade guide", "should_fix"),
    ("backup", "Backup and restore documentation", "should_fix"),
]


# ---------------------------------------------------------------------------
# Helper: YAML loading
# ---------------------------------------------------------------------------


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Check functions — each returns a list of (check_name, passed, detail) tuples
# ---------------------------------------------------------------------------


def _check_status_reporting(
    python_files: list[pathlib.Path],
) -> list[tuple[str, bool, str]]:
    """Check whether the charm sets status for expected conditions."""
    results: list[tuple[str, bool, str]] = []

    # Concatenate all Python source for pattern matching.
    all_source = ""
    for path in python_files:
        try:
            all_source += path.read_text(errors="replace") + "\n"
        except OSError:
            continue

    for pattern, description in _EXPECTED_STATUS_CONDITIONS:
        # Look for the pattern near a status-setting call.
        # We check if the condition keyword appears in source that also
        # sets status (BlockedStatus, WaitingStatus, MaintenanceStatus).
        has_condition = bool(re.search(pattern, all_source, re.IGNORECASE))
        has_status_call = bool(re.search(r"(?:Blocked|Waiting|Maintenance)Status", all_source))
        passed = has_condition and has_status_call
        results.append((f"status:{description}", passed, description))

    return results


def _check_common_actions(
    actions: dict[str, Any],
) -> list[tuple[str, bool, str]]:
    """Check whether common operational actions are defined."""
    results: list[tuple[str, bool, str]] = []
    action_names = set(actions.keys())

    for canonical_name, description in _EXPECTED_ACTIONS.items():
        aliases = [canonical_name, *_ACTION_ALIASES.get(canonical_name, [])]
        found = any(alias in action_names for alias in aliases)
        results.append((f"action:{canonical_name}", found, description))

    return results


def _check_action_quality(
    actions: dict[str, Any],
) -> list[tuple[str, bool, str]]:
    """Check action metadata quality (descriptions, parameters)."""
    results: list[tuple[str, bool, str]] = []

    for action_name, action_def in actions.items():
        if not isinstance(action_def, dict):
            continue
        has_description = bool(action_def.get("description"))
        results.append(
            (
                f"action-quality:{action_name}",
                has_description,
                f"Action '{action_name}' has a description",
            )
        )

        # Check parameters have descriptions.
        params = action_def.get("params", action_def.get("parameters", {}))
        if isinstance(params, dict):
            properties = params.get("properties", params)
            for param_name, param_def in properties.items():
                if isinstance(param_def, dict):
                    has_param_desc = bool(param_def.get("description"))
                    results.append(
                        (
                            f"action-quality:{action_name}:{param_name}",
                            has_param_desc,
                            f"Action '{action_name}' parameter '{param_name}' has a description",
                        )
                    )

    return results


def _check_config_quality(
    config: dict[str, Any],
) -> list[tuple[str, bool, str]]:
    """Check configuration option quality (types, defaults, descriptions)."""
    results: list[tuple[str, bool, str]] = []
    options = config.get("options", config)

    for opt_name, opt_def in options.items():
        if not isinstance(opt_def, dict):
            continue
        has_type = bool(opt_def.get("type"))
        has_default = "default" in opt_def
        has_description = bool(opt_def.get("description"))

        results.append(
            (
                f"config:{opt_name}:type",
                has_type,
                f"Config '{opt_name}' has a defined type",
            )
        )
        results.append(
            (
                f"config:{opt_name}:default",
                has_default,
                f"Config '{opt_name}' has a default value",
            )
        )
        results.append(
            (
                f"config:{opt_name}:description",
                has_description,
                f"Config '{opt_name}' has a description",
            )
        )

    return results


def _check_documentation(
    charm_dir: pathlib.Path,
    readme_content: str,
) -> list[tuple[str, bool, str]]:
    """Check documentation presence and completeness."""
    results: list[tuple[str, bool, str]] = []
    docs_dir = charm_dir / "docs"

    for keyword, description, _severity in _DOC_CHECKS:
        # Check for docs/ files mentioning the topic, or README sections.
        found_in_docs = False
        if docs_dir.is_dir():
            for doc_file in docs_dir.rglob("*.md"):
                try:
                    content = doc_file.read_text(errors="replace").lower()
                    if keyword in content:
                        found_in_docs = True
                        break
                except OSError:
                    continue

        found_in_readme = keyword in readme_content.lower()
        results.append(
            (
                f"docs:{keyword}",
                found_in_docs or found_in_readme,
                description,
            )
        )

    return results


def _check_reliability(
    actions: dict[str, Any],
    python_files: list[pathlib.Path],
) -> list[tuple[str, bool, str]]:
    """Check reliability-related features."""
    results: list[tuple[str, bool, str]] = []
    action_names = set(actions.keys())

    # Health check mechanism.
    health_aliases = {"get-health", "health-check", "check-health", "health", "get-status"}
    has_health = bool(action_names & health_aliases)
    results.append(("reliability:health-check", has_health, "Health validation mechanism exists"))

    # Backup/restore actions.
    backup_aliases = {"create-backup", "backup", "make-backup"}
    restore_aliases = {"restore-backup", "restore", "restore-from-backup"}
    has_backup = bool(action_names & backup_aliases)
    has_restore = bool(action_names & restore_aliases)
    results.append(("reliability:backup", has_backup, "Backup action exists"))
    results.append(("reliability:restore", has_restore, "Restore action exists"))

    # Graceful shutdown handling (check for stop/remove event handlers).
    all_source = ""
    for path in python_files:
        try:
            all_source += path.read_text(errors="replace") + "\n"
        except OSError:
            continue

    has_stop_handler = bool(re.search(r"(?:stop|remove)_event|on\.stop|on\.remove", all_source))
    results.append(
        (
            "reliability:graceful-shutdown",
            has_stop_handler,
            "Handles graceful shutdown (stop/remove event)",
        )
    )

    return results


def _check_maintainability(
    metadata: dict[str, Any],
    actions: dict[str, Any],
    python_files: list[pathlib.Path],
) -> list[tuple[str, bool, str]]:
    """Check maintainability-related features."""
    results: list[tuple[str, bool, str]] = []

    # Full COS observability.
    all_relations: dict[str, Any] = {}
    for section in ("requires", "provides", "peers"):
        all_relations.update(metadata.get(section, {}))

    for interface, description in _COS_RELATIONS.items():
        present = any(
            rel.get("interface") == interface
            for rel in all_relations.values()
            if isinstance(rel, dict)
        )
        results.append(
            (
                f"maintainability:cos:{interface}",
                present,
                f"COS integration: {description}",
            )
        )

    # Diagnostics/SOS action.
    action_names = set(actions.keys())
    diag_aliases = {"collect-diagnostics", "diagnostics", "sos", "collect-sos", "get-diagnostics"}
    has_diagnostics = bool(action_names & diag_aliases)
    results.append(
        (
            "maintainability:diagnostics",
            has_diagnostics,
            "Diagnostics/SOS action to collect sanitised data",
        )
    )

    # Upgrade pre-flight.
    upgrade_aliases = {"pre-upgrade-check", "pre-upgrade", "upgrade-check"}
    has_pre_upgrade = bool(action_names & upgrade_aliases)

    # Also check for upgrade event handling in source.
    all_source = ""
    for path in python_files:
        try:
            all_source += path.read_text(errors="replace") + "\n"
        except OSError:
            continue

    has_upgrade_handler = bool(re.search(r"upgrade|pre.upgrade", all_source, re.IGNORECASE))
    results.append(
        (
            "maintainability:upgrade-preflight",
            has_pre_upgrade or has_upgrade_handler,
            "Upgrade pre-flight checks exist",
        )
    )

    return results


def _check_security(
    metadata: dict[str, Any],
    python_files: list[pathlib.Path],
    actions: dict[str, Any],
) -> list[tuple[str, bool, str]]:
    """Check security-related features."""
    results: list[tuple[str, bool, str]] = []

    # TLS — check for tls-certificates relation or TLS-related code.
    all_relations: dict[str, Any] = {}
    for section in ("requires", "provides", "peers"):
        all_relations.update(metadata.get(section, {}))

    has_tls_relation = any(
        rel.get("interface") in ("tls-certificates", "certificates")
        for rel in all_relations.values()
        if isinstance(rel, dict)
    )

    all_source = ""
    for path in python_files:
        try:
            all_source += path.read_text(errors="replace") + "\n"
        except OSError:
            continue

    has_tls_code = bool(re.search(r"tls|certificate|ssl", all_source, re.IGNORECASE))
    results.append(
        (
            "security:encryption-transit",
            has_tls_relation or has_tls_code,
            "Data encryption in transit (TLS)",
        )
    )

    # Juju secrets usage (vs plain-text config).
    has_juju_secrets = bool(re.search(r"juju.*secret|Secret(?:Changed|Rotate)", all_source))
    # Check for config options that look like secrets.
    config = _load_config_from_metadata_or_file(metadata)
    secret_config_names = {"password", "secret", "token", "api-key", "api_key", "credential"}
    has_secret_config = any(
        any(s in opt_name.lower() for s in secret_config_names) for opt_name in config
    )
    # Pass if using secrets API or if no secret-like config exists.
    results.append(
        (
            "security:secrets-management",
            has_juju_secrets or not has_secret_config,
            "Secrets stored via Juju secrets, not plain-text config",
        )
    )

    # Certificate management actions.
    cert_aliases = {"get-certificate", "view-certificate", "regenerate-certificate", "rotate-tls"}
    action_names = set(actions.keys())
    has_cert_actions = bool(action_names & cert_aliases)
    # Only relevant if TLS is in use.
    if has_tls_relation or has_tls_code:
        results.append(
            (
                "security:cert-management",
                has_cert_actions,
                "Certificate management actions (view/regenerate)",
            )
        )

    return results


def _load_config_from_metadata_or_file(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Extract config options from metadata or config.yaml."""
    config = metadata.get("config", {})
    if isinstance(config, dict) and config.get("options"):
        return config["options"]
    if isinstance(config, dict) and config:
        return config
    return {}


# ---------------------------------------------------------------------------
# Scoring and report formatting
# ---------------------------------------------------------------------------


def _categorise_checks(
    checks: list[tuple[str, bool, str]],
) -> dict[str, list[tuple[str, bool, str]]]:
    """Group checks by pillar based on their name prefix."""
    pillar_map = {
        "status:": PILLAR_BEST_PRACTICES,
        "action:": PILLAR_BEST_PRACTICES,
        "action-quality:": PILLAR_BEST_PRACTICES,
        "config:": PILLAR_BEST_PRACTICES,
        "docs:": PILLAR_DOCUMENTATION,
        "reliability:": PILLAR_RELIABILITY,
        "maintainability:": PILLAR_MAINTAINABILITY,
        "security:": PILLAR_SECURITY,
    }

    by_pillar: dict[str, list[tuple[str, bool, str]]] = {p: [] for p in _PILLARS}
    for check_name, passed, detail in checks:
        pillar = PILLAR_BEST_PRACTICES  # default
        for prefix, p in pillar_map.items():
            if check_name.startswith(prefix):
                pillar = p
                break
        by_pillar[pillar].append((check_name, passed, detail))

    return by_pillar


def _score_pillar(checks: list[tuple[str, bool, str]]) -> tuple[int, int, int]:
    """Return (passed, total, percentage) for a list of checks."""
    if not checks:
        return (0, 0, 100)
    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    pct = round(100 * passed / total) if total > 0 else 100
    return (passed, total, pct)


# Severity mapping for failed checks.
_MUST_FIX_PREFIXES = frozenset(
    {
        "reliability:health-check",
        "docs:installation",
        "security:encryption-transit",
        "security:secrets-management",
    }
)


def _format_readiness_report(
    charm_name: str,
    by_pillar: dict[str, list[tuple[str, bool, str]]],
    estate_opportunities: list[EstateOpportunity] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Format OPERATIONAL_READINESS.md and a structured data dict.

    ``estate_opportunities`` carries the Phase 98 Pro / Landscape
    advisory items.  When present and non-empty they render as a
    dedicated ``## Estate Operations`` section below the pillar
    breakdown so the operator sees estate-level recommendations
    alongside the code-level must-fix list, without conflating them.
    """
    estate_opportunities = estate_opportunities or []
    must_fix: list[str] = []
    should_fix: list[str] = []
    advisory: list[str] = []

    pillar_scores: dict[str, dict[str, int]] = {}
    all_checks: list[dict[str, Any]] = []

    lines = [f"# Operational Readiness: {charm_name}", ""]
    lines.append("## Summary")
    lines.append("")

    # Score each pillar.
    for pillar in _PILLARS:
        checks = by_pillar.get(pillar, [])
        passed, total, pct = _score_pillar(checks)
        pillar_scores[pillar] = {"passed": passed, "total": total, "percentage": pct}
        lines.append(f"- **{pillar}**: {passed}/{total} ({pct}%)")

    # Overall score.
    total_passed = sum(s["passed"] for s in pillar_scores.values())
    total_checks = sum(s["total"] for s in pillar_scores.values())
    overall_pct = round(100 * total_passed / total_checks) if total_checks > 0 else 100
    lines.append("")
    lines.append(f"**Overall: {total_passed}/{total_checks} ({overall_pct}%)**")
    lines.append("")

    # Detailed results per pillar.
    for pillar in _PILLARS:
        checks = by_pillar.get(pillar, [])
        if not checks:
            continue
        lines.append(f"## {pillar}")
        lines.append("")
        for check_name, passed, detail in checks:
            mark = "PASS" if passed else "FAIL"
            lines.append(f"- [{mark}] {detail}")

            all_checks.append(
                {
                    "name": check_name,
                    "pillar": pillar,
                    "passed": passed,
                    "detail": detail,
                }
            )

            # Categorise failures.
            if not passed:
                if check_name in _MUST_FIX_PREFIXES:
                    must_fix.append(f"[{pillar}] {detail}")
                else:
                    should_fix.append(f"[{pillar}] {detail}")

        lines.append("")

    # Advisory items (organisational, not code-fixable).
    advisory_items = [
        "Platform compatibility matrix — document supported substrates and versions",
        "Reference architecture — provide recommended deployment topologies",
        "Escalation methods — define how operators reach support",
        "Long-term stability testing — run extended soak tests",
        "SSDLC compliance — ensure secure development lifecycle adherence",
    ]
    lines.append("## Advisory")
    lines.append("")
    lines.append("These items require organisational action, not code changes:")
    lines.append("")
    for item in advisory_items:
        lines.append(f"- {item}")
        advisory.append(item)
    lines.append("")

    estate_lines = render_estate_section(estate_opportunities)
    lines.extend(estate_lines)

    findings = {
        "must_fix": must_fix,
        "should_fix": should_fix,
        "advisory": advisory,
        "estate_opportunities": [opp.to_dict() for opp in estate_opportunities],
    }

    data = {
        "charm_name": charm_name,
        "overall_score": overall_pct,
        "total_passed": total_passed,
        "total_checks": total_checks,
        "pillar_scores": pillar_scores,
        "checks": all_checks,
        "findings": findings,
    }

    return "\n".join(lines), data


# ---------------------------------------------------------------------------
# Collect Python files
# ---------------------------------------------------------------------------


def _collect_python_files(charm_dir: pathlib.Path) -> list[pathlib.Path]:
    """Collect all Python files in src/ and lib/ directories."""
    files: list[pathlib.Path] = []
    for subdir in ("src", "lib"):
        d = charm_dir / subdir
        if d.is_dir():
            files.extend(d.rglob("*.py"))
    return files


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------


class OperationalReadinessTool(Tool):
    """Assess a charm's operational readiness against Canonical's metrics."""

    @property
    def name(self) -> str:
        return "operational_readiness"

    @property
    def description(self) -> str:
        return (
            "Evaluate a charm against Canonical's Operational Readiness Metrics. "
            "Scores the charm across five pillars: Best Practices, Documentation, "
            "Reliability, Maintainability, and Security. Returns a structured "
            "report (OPERATIONAL_READINESS.md) with per-pillar scores and "
            "categorised findings (must-fix, should-fix, advisory)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run operational readiness checks on a charm directory."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        # Load metadata.
        metadata = _load_yaml(charm_dir / "charmcraft.yaml")
        if not metadata:
            metadata = _load_yaml(charm_dir / "metadata.yaml")
        if not metadata:
            return ToolResult(
                success=False,
                output="",
                error="No charmcraft.yaml or metadata.yaml found — is this a charm directory?",
            )

        charm_name = metadata.get("name", charm_dir.name)

        # Load actions (charmcraft.yaml or actions.yaml).
        actions: dict[str, Any] = metadata.get("actions", {})
        if not actions:
            actions_data = _load_yaml(charm_dir / "actions.yaml")
            actions = actions_data if isinstance(actions_data, dict) else {}

        # Load config (charmcraft.yaml or config.yaml).
        config_section = metadata.get("config", {})
        if isinstance(config_section, dict) and config_section.get("options"):
            config_options = config_section["options"]
        elif isinstance(config_section, dict) and config_section:
            config_options = config_section
        else:
            config_data = _load_yaml(charm_dir / "config.yaml")
            config_options = config_data.get("options", config_data) if config_data else {}

        # Collect source files.
        python_files = _collect_python_files(charm_dir)

        # Load README.
        readme_content = ""
        readme_path = charm_dir / "README.md"
        if readme_path.exists():
            with contextlib.suppress(OSError):
                readme_content = readme_path.read_text(errors="replace")

        # Run all checks.
        all_checks: list[tuple[str, bool, str]] = []
        all_checks.extend(_check_status_reporting(python_files))
        all_checks.extend(_check_common_actions(actions))
        all_checks.extend(_check_action_quality(actions))
        all_checks.extend(_check_config_quality(config_options))
        all_checks.extend(_check_documentation(charm_dir, readme_content))
        all_checks.extend(_check_reliability(actions, python_files))
        all_checks.extend(_check_maintainability(metadata, actions, python_files))
        all_checks.extend(_check_security(metadata, python_files, actions))

        # Categorise and format.
        by_pillar = _categorise_checks(all_checks)
        estate_opportunities = assess_estate_opportunities(charm_dir, metadata)
        report, data = _format_readiness_report(charm_name, by_pillar, estate_opportunities)

        # Write report file.
        report_path = charm_dir / "OPERATIONAL_READINESS.md"
        try:
            report_path.write_text(report)
            data["report_path"] = str(report_path)
        except OSError:
            pass

        score = data.get("overall_score", 0)
        passed = data.get("total_passed", 0)
        total = data.get("total_checks", 0)
        return ToolResult(
            success=True,
            output=report,
            data=data,
            caption=f"readiness: {passed}/{total} ({score}%)",
        )
