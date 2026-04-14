"""Charm audit tool — delegates to charmlint for deterministic checks."""

import contextlib
import re
from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult
from charmlint import LintConfig, lint
from charmlint.models import Severity

# COS relation descriptions for the report.
_COS_RELATIONS = {
    "tracing": "ops-tracing / Tempo integration",
    "metrics-endpoint": "Prometheus metrics",
    "logging": "Loki log forwarding",
    "grafana-dashboard": "Grafana dashboard",
}

# Listing fields for the report.
_LISTING_FIELDS = {
    "display-name": "Human-readable charm name",
    "summary": "One-line summary",
    "description": "Detailed description",
    "docs": "Documentation URL",
    "issues": "Issue tracker URL",
    "source": "Source code URL",
    "tags": "Charmhub tags",
}


# Patterns indicating modern Ops framework usage.
_MODERN_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"def\s+_(?:reconcile|update_status|set_status)\b",
        "holistic_status",
        "Holistic status handling — single reconciliation method for unit status",
    ),
    (
        r"config.changed|config_changed|_on_config_changed",
        "config_reconciliation",
        "Config-changed event handler",
    ),
    (
        r"relation.changed|relation_changed|_on_.*_relation_changed",
        "relation_handling",
        "Relation-changed event handler",
    ),
    (
        r"PebbleReadyEvent|pebble.ready|pebble_ready|can_connect\(\)",
        "pebble_readiness",
        "Pebble readiness checks",
    ),
]


def _check_modern_patterns(charm_dir: Path) -> dict[str, bool]:
    """Check whether the charm uses modern Ops framework patterns."""
    results: dict[str, bool] = {name: False for _, name, _ in _MODERN_PATTERNS}

    all_source = ""
    for subdir in ("src",):
        d = charm_dir / subdir
        if d.is_dir():
            for path in d.rglob("*.py"):
                with contextlib.suppress(OSError):
                    all_source += path.read_text(errors="replace") + "\n"

    for pattern, name, _desc in _MODERN_PATTERNS:
        if re.search(pattern, all_source):
            results[name] = True

    return results


def _charmlint_to_audit_report(
    charm_dir: Path,
    charm_name: str,
) -> tuple[str, dict[str, list[str]], dict[str, Any]]:
    """Run charmlint and convert results to the legacy audit report format.

    Returns (report_text, findings_dict, data_dict).
    """
    report = lint(charm_dir, LintConfig())

    must_fix: list[str] = []
    should_fix: list[str] = []
    nice_to_have: list[str] = []

    for d in report.diagnostics:
        if d.rule_id == "FATAL":
            continue
        msg = d.message
        if d.fix_hint:
            msg += f" — {d.fix_hint}"
        if d.severity == Severity.ERROR:
            must_fix.append(msg)
        elif d.severity == Severity.WARNING:
            should_fix.append(msg)
        else:
            nice_to_have.append(msg)

    # Modern patterns are not in charmlint yet — check directly.
    modern_patterns = _check_modern_patterns(charm_dir)
    for _pattern, name, desc in _MODERN_PATTERNS:
        if not modern_patterns.get(name):
            nice_to_have.append(f"Missing modern pattern: {desc}")

    # Build the Markdown report.
    lines = [f"# Audit Report: {charm_name}", ""]
    if must_fix:
        lines.append("## Must Fix")
        lines.append("")
        for item in must_fix:
            lines.append(f"- {item}")
        lines.append("")
    if should_fix:
        lines.append("## Should Fix")
        lines.append("")
        for item in should_fix:
            lines.append(f"- {item}")
        lines.append("")
    if nice_to_have:
        lines.append("## Nice to Have")
        lines.append("")
        for item in nice_to_have:
            lines.append(f"- {item}")
        lines.append("")
    if not must_fix and not should_fix and not nice_to_have:
        lines.append("No issues found — the charm looks good!")
        lines.append("")

    findings = {
        "must_fix": must_fix,
        "should_fix": should_fix,
        "nice_to_have": nice_to_have,
    }

    # Build the gaps dict from charmlint diagnostics.
    rule_ids = {d.rule_id for d in report.diagnostics}
    gaps = {
        "cos_tracing": "COS001" in rule_ids,
        "cos_metrics": "COS002" in rule_ids,
        "cos_logging": "COS003" in rule_ids,
        "cos_dashboards": "COS004" in rule_ids,
        "ops_tracing": "COS005" in rule_ids,
        "unit_tests": "TEST001" in rule_ids,
        "integration_tests": "TEST002" in rule_ids,
        "readme": "DOC001" in rule_ids,
        "licence": "STR001" in rule_ids,
        "icon": "STR002" in rule_ids,
        "type_annotations": "STR003" in rule_ids,
        "modern_patterns": any(not v for v in modern_patterns.values()),
    }

    # Build deprecated_apis list from DEP diagnostics.
    deprecated_apis = [
        {"api": d.rule_id, "file": d.path or "", "advice": d.message}
        for d in report.diagnostics
        if d.rule_id.startswith("DEP")
    ]

    # Build fetch_libs list from LIB diagnostics.
    fetch_libs = [
        {"lib_prefix": d.message.split(" ")[0] if d.message else "", "advice": d.message}
        for d in report.diagnostics
        if d.rule_id.startswith("LIB")
    ]

    # Build listing_fields from META diagnostics.
    listing_present = dict.fromkeys(_LISTING_FIELDS, True)
    _META_TO_FIELD = {
        "META002": "display-name",
        "META003": "summary",
        "META004": "description",
        "META005": "docs",
        "META006": "issues",
        "META007": "source",
    }
    for rid, field in _META_TO_FIELD.items():
        if rid in rule_ids:
            listing_present[field] = False

    data = {
        "charm_name": charm_name,
        "total_issues": sum(len(v) for v in findings.values()),
        "findings": findings,
        "gaps": gaps,
        "modern_patterns": modern_patterns,
        "deprecated_apis": deprecated_apis,
        "fetch_libs": fetch_libs,
        "listing_fields": listing_present,
    }

    return "\n".join(lines), findings, data


class CharmAuditTool(Tool):
    """Tool to audit an existing charm against best practices.

    Delegates to charmlint for deterministic checks.
    """

    @property
    def name(self) -> str:
        return "charm_audit"

    @property
    def description(self) -> str:
        return (
            "Audit an existing charm directory against best practices. "
            "Checks COS integration, test coverage, deprecated APIs, "
            "metadata completeness, and listing readiness. Returns a "
            "structured AUDIT.md report with categorised findings "
            "(must-fix, should-fix, nice-to-have). Powered by charmlint."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the existing charm directory",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run deterministic audit checks on a charm directory."""
        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        # Check for metadata file.
        has_metadata = (charm_dir / "charmcraft.yaml").exists() or (
            charm_dir / "metadata.yaml"
        ).exists()
        if not has_metadata:
            return ToolResult(
                success=False,
                output="",
                error="No charmcraft.yaml or metadata.yaml found — is this a charm directory?",
            )

        # Load charm name from metadata.
        for meta_file in ("charmcraft.yaml", "metadata.yaml"):
            meta_path = charm_dir / meta_file
            if meta_path.exists():
                try:
                    with meta_path.open() as f:
                        metadata = yaml.safe_load(f)
                    if isinstance(metadata, dict):
                        charm_name = metadata.get("name", charm_dir.name)
                        break
                except (yaml.YAMLError, OSError):
                    pass
        else:
            charm_name = charm_dir.name

        report_text, findings, data = _charmlint_to_audit_report(charm_dir, charm_name)

        return ToolResult(
            success=True,
            output=report_text,
            data=data,
        )
