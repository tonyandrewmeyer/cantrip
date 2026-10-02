"""Charm audit tool — charmlint plus cantrip's own improvement checks.

Most findings come from charmlint.  The checks that feed the
improvement planner's gaps (COS relations, ops-tracing, integration
tests, type annotations, deprecated APIs) are not in charmlint, so
they run here, directly against the charm's files.
"""

import contextlib
import pathlib
import re
from typing import Any

import yaml

from cantrip.agent.tools import charmlint_tool
from cantrip.agent.tools.base import Tool, ToolResult

# COS relations every charm should declare: (gap key, interface, message).
_COS_INTERFACES: list[tuple[str, str, str]] = [
    ("cos_tracing", "tracing", "Missing tracing relation (interface: tracing)"),
    (
        "cos_metrics",
        "prometheus_scrape",
        "Missing metrics-endpoint relation (interface: prometheus_scrape)",
    ),
    ("cos_logging", "loki_push_api", "Missing logging relation (interface: loki_push_api)"),
    (
        "cos_dashboards",
        "grafana_dashboard",
        "Missing grafana-dashboard relation (interface: grafana_dashboard)",
    ),
]

# Deprecated APIs in charm source: (api, pattern, message, fix hint).
_DEPRECATED_APIS: list[tuple[str, str, str, str]] = [
    (
        "stored-state",
        r"\bStoredState\b",
        "Uses deprecated StoredState",
        "Use instance attributes or Juju secrets instead",
    ),
    (
        "harness",
        r"\bfrom\s+ops\.testing\s+import\s+Harness\b",
        "Imports deprecated Harness from ops.testing",
        "Use Scenario (ops.testing.Context, State) instead",
    ),
    (
        "framework-breakpoint",
        r"\bself\.framework\.breakpoint\b",
        "Uses removed framework.breakpoint()",
        "Use standard Python breakpoint() or debugger",
    ),
    (
        "reactive-framework",
        r"from\s+charms\.reactive\b|@(?:when|when_not|when_any|when_all|hook)\(",
        "Uses legacy reactive framework (charms.reactive / @when / @hook decorators)",
        "Rewrite as an ops.CharmBase subclass with framework.observe() event handlers",
    ),
]

# Listing fields for the report, named as the unified charmcraft.yaml
# spells them so the agent is not told to add a legacy key.
_LISTING_FIELDS = {
    "title": "Human-readable charm name (legacy: display-name)",
    "summary": "One-line summary",
    "description": "Detailed description",
    "links.documentation": "Documentation URL (legacy: docs)",
    "links.issues": "Issue tracker URL (legacy: issues)",
    "links.source": "Source code URL (legacy: source)",
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


def _check_modern_patterns(charm_dir: pathlib.Path) -> dict[str, bool]:
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


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Load a YAML mapping, or return an empty dict if it is absent or unreadable."""
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _relation_interfaces(charm_dir: pathlib.Path) -> set[str]:
    """Collect every relation interface the charm declares, in any metadata file."""
    interfaces: set[str] = set()
    for name in ("charmcraft.yaml", "metadata.yaml"):
        metadata = _load_yaml(charm_dir / name)
        for section in ("requires", "provides", "peers"):
            relations = metadata.get(section)
            if not isinstance(relations, dict):
                continue
            for relation in relations.values():
                if isinstance(relation, dict) and relation.get("interface"):
                    interfaces.add(str(relation["interface"]))
    return interfaces


def _src_sources(charm_dir: pathlib.Path) -> dict[pathlib.Path, str]:
    """Read every Python file under the charm's ``src/``."""
    sources: dict[pathlib.Path, str] = {}
    src_dir = charm_dir / "src"
    if src_dir.is_dir():
        for path in sorted(src_dir.rglob("*.py")):
            with contextlib.suppress(OSError):
                sources[path] = path.read_text(errors="replace")
    return sources


def _has_ops_tracing(charm_dir: pathlib.Path, sources: dict[pathlib.Path, str]) -> bool:
    """Return whether ops-tracing is a dependency or set up in source."""
    for name in ("requirements.txt", "pyproject.toml"):
        with contextlib.suppress(OSError):
            if "ops-tracing" in (charm_dir / name).read_text(errors="replace"):
                return True
    return any(re.search(r"ops_tracing|setup_tracing", text) for text in sources.values())


def _cantrip_checks(charm_dir: pathlib.Path) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    """Run the audit checks that charmlint does not cover.

    Returns diagnostics in charmlint's JSON shape, so the report treats
    them the same way, and the gaps they reveal.
    """
    diagnostics: list[dict[str, Any]] = []
    gaps: dict[str, bool] = {}

    interfaces = _relation_interfaces(charm_dir)
    for gap, interface, message in _COS_INTERFACES:
        gaps[gap] = interface not in interfaces
        if gaps[gap]:
            diagnostics.append(
                {
                    "rule_id": gap,
                    "severity": "warning",
                    "message": message,
                    "path": "charmcraft.yaml",
                }
            )

    sources = _src_sources(charm_dir)
    gaps["ops_tracing"] = not _has_ops_tracing(charm_dir, sources)
    if gaps["ops_tracing"]:
        diagnostics.append(
            {
                "rule_id": "ops_tracing",
                "severity": "warning",
                "message": "ops-tracing not detected — add for distributed tracing",
                "fix_hint": "Add 'ops-tracing' to requirements.txt or pyproject.toml",
            }
        )

    integration_dir = charm_dir / "tests" / "integration"
    gaps["integration_tests"] = not (
        integration_dir.is_dir() and any(integration_dir.glob("test_*.py"))
    )
    if gaps["integration_tests"]:
        diagnostics.append(
            {
                "rule_id": "integration_tests",
                "severity": "warning",
                "message": "No integration tests found in tests/integration/",
                "path": "tests/",
            }
        )

    gaps["type_annotations"] = not any(
        re.search(r"def\s+\w+\([^)]*\)\s*->", text) for text in sources.values()
    )
    if gaps["type_annotations"]:
        diagnostics.append(
            {
                "rule_id": "type_annotations",
                "severity": "info",
                "message": "No type annotations found — add return-type hints to functions",
                "fix_hint": "Add -> ReturnType annotations to function definitions",
            }
        )

    for api, pattern, message, fix_hint in _DEPRECATED_APIS:
        match = _first_match(re.compile(pattern), sources)
        if match is None:
            continue
        path, line = match
        diagnostics.append(
            {
                "rule_id": f"deprecated:{api}",
                "severity": "error",
                "message": message,
                "path": str(path.relative_to(charm_dir)),
                "line": line,
                "fix_hint": fix_hint,
            }
        )
    gaps["reactive_framework"] = any(
        d["rule_id"] == "deprecated:reactive-framework" for d in diagnostics
    )
    return diagnostics, gaps


def _first_match(
    pattern: re.Pattern[str], sources: dict[pathlib.Path, str]
) -> tuple[pathlib.Path, int] | None:
    """Return the first file and line in *sources* matching *pattern*."""
    for path, text in sources.items():
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                return path, number
    return None


def _lib_module(charm_dir: pathlib.Path, path: str) -> str:
    """Return the dotted module for a vendored library path, e.g. ``charms.foo.v0.bar``."""
    lib_path = pathlib.Path(path)
    with contextlib.suppress(ValueError):
        lib_path = lib_path.relative_to(charm_dir)
    with contextlib.suppress(ValueError):
        lib_path = lib_path.relative_to("lib")
    return ".".join(lib_path.with_suffix("").parts)


def _audit_report(
    charm_dir: pathlib.Path,
    charm_name: str,
) -> tuple[str, dict[str, list[str]], dict[str, Any]]:
    """Run charmlint and cantrip's own checks, and build the audit report.

    Returns (report_text, findings_dict, data_dict).  Raises
    :class:`~cantrip.agent.tools.charmlint_tool.CharmlintError` if
    charmlint cannot be run.
    """
    lint_report = charmlint_tool.run_charmlint(charm_dir)
    extra_diagnostics, gaps = _cantrip_checks(charm_dir)
    diagnostics = [d for d in lint_report.get("diagnostics", []) if d.get("rule_id") != "FATAL"]
    diagnostics.extend(extra_diagnostics)

    must_fix: list[str] = []
    should_fix: list[str] = []
    nice_to_have: list[str] = []

    for d in diagnostics:
        msg = d.get("message", "")
        if d.get("fix_hint"):
            msg += f" — {d['fix_hint']}"
        if d.get("severity") == "error":
            must_fix.append(msg)
        elif d.get("severity") == "warning":
            should_fix.append(msg)
        else:
            nice_to_have.append(msg)

    # Modern patterns are not in charmlint — check directly.
    modern_patterns = _check_modern_patterns(charm_dir)
    for _pattern, name, desc in _MODERN_PATTERNS:
        if not modern_patterns.get(name):
            nice_to_have.append(f"Missing modern pattern: {desc}")

    # Build the Markdown report.
    lines = [f"# Audit Report: {charm_name}", ""]
    if must_fix:
        lines.append("## Must Fix")
        lines.append("")
        lines.extend(f"- {item}" for item in must_fix)
        lines.append("")
    if should_fix:
        lines.append("## Should Fix")
        lines.append("")
        lines.extend(f"- {item}" for item in should_fix)
        lines.append("")
    if nice_to_have:
        lines.append("## Nice to Have")
        lines.append("")
        lines.extend(f"- {item}" for item in nice_to_have)
        lines.append("")
    if not must_fix and not should_fix and not nice_to_have:
        lines.append("No issues found — the charm looks good!")
        lines.append("")

    findings = {
        "must_fix": must_fix,
        "should_fix": should_fix,
        "nice_to_have": nice_to_have,
    }

    rule_ids = {d.get("rule_id") for d in diagnostics}
    gaps.update(
        {
            "unit_tests": "TESTING-001" in rule_ids,
            "readme": "DOCUMENTATION-001" in rule_ids,
            "licence": "STRUCTURE-001" in rule_ids,
            "icon": "STRUCTURE-002" in rule_ids,
            "modern_patterns": any(not v for v in modern_patterns.values()),
        }
    )

    deprecated_apis = [
        {
            "api": d["rule_id"].removeprefix("deprecated:"),
            "file": d.get("path", ""),
            "advice": d.get("message", ""),
        }
        for d in diagnostics
        if d["rule_id"].startswith("deprecated:")
    ]

    fetch_libs = [
        {"lib_prefix": _lib_module(charm_dir, d.get("path", "")), "advice": d.get("message", "")}
        for d in diagnostics
        if d.get("rule_id", "").startswith("LIBRARY-")
    ]

    listing_present = dict.fromkeys(_LISTING_FIELDS, True)
    metadata_to_field = {
        "METADATA-002": "title",
        "METADATA-003": "summary",
        "METADATA-004": "description",
        "METADATA-005": "links.documentation",
        "METADATA-006": "links.issues",
        "METADATA-007": "links.source",
    }
    for rule_id, field in metadata_to_field.items():
        if rule_id in rule_ids:
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

    Runs charmlint plus the improvement checks charmlint does not cover.
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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        del arguments
        return "Auditing the charm…"

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
        charm_dir = pathlib.Path(path).resolve()
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

        try:
            report_text, _findings, data = _audit_report(charm_dir, charm_name)
        except charmlint_tool.CharmlintError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        total = data.get("total_issues", 0)
        caption = "clean" if total == 0 else f"{total} issue{'s' if total != 1 else ''}"

        return ToolResult(
            success=True,
            output=report_text,
            data=data,
            caption=caption,
        )
