"""Charm audit tool — deterministic checks for existing charm quality."""

import re
from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult

# COS relation interfaces that a well-integrated charm should provide/require.
_COS_RELATIONS = {
    "tracing": "ops-tracing / Tempo integration",
    "metrics-endpoint": "Prometheus metrics",
    "logging": "Loki log forwarding",
    "grafana-dashboard": "Grafana dashboard",
}

# Metadata fields expected for a polished Charmhub listing.
_LISTING_FIELDS = {
    "display-name": "Human-readable charm name",
    "summary": "One-line summary",
    "description": "Detailed description",
    "docs": "Documentation URL",
    "issues": "Issue tracker URL",
    "source": "Source code URL",
    "tags": "Charmhub tags",
}

# Patterns indicating deprecated ops framework APIs.
_DEPRECATED_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bStoredState\b", "StoredState", "Use instance attributes or Juju secrets instead"),
    (r"\bfrom\s+ops\.testing\s+import\s+Harness\b", "Harness", "Use Scenario (ops.testing)"),
    (r"\bHarness\s*\(", "Harness", "Use Scenario (ops.testing)"),
    (r"\bself\.framework\.breakpoint\b", "framework.breakpoint", "Removed in modern ops"),
    (
        r"\bfrom\s+charms\.\w+\.v\d+\.",
        "charmcraft fetch-libs import",
        "Prefer PyPI versions of charm libraries",
    ),
]


# Known charm libraries that have PyPI equivalents.  Keys are the charm
# library module prefix (after ``from charms.``), values are the PyPI
# package name and minimum version.
_FETCH_LIBS_PYPI_MAP: dict[str, str] = {
    "data_platform_libs": "data-platform-libs",
    "grafana_k8s": "grafana-k8s-lib",
    "loki_k8s": "loki-k8s-lib",
    "prometheus_k8s": "prometheus-k8s-lib",
    "tempo_coordinator_k8s": "tempo-coordinator-k8s-lib",
    "tempo_k8s": "tempo-k8s-lib",
    "traefik_k8s": "traefik-k8s-lib",
    "catalogue_k8s": "catalogue-k8s-lib",
    "certificate_transfer_interface": "certificate-transfer-interface-lib",
    "tls_certificates_interface": "tls-certificates-interface-lib",
    "observability_libs": "observability-libs",
    "operator_libs_linux": "operator-libs-linux",
    "sdcore_nms_k8s": "sdcore-nms-k8s-lib",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, OSError):
        return {}


def _collect_python_files(charm_dir: Path) -> list[Path]:
    """Collect all Python files in src/ and lib/ directories."""
    files: list[Path] = []
    for subdir in ("src", "lib"):
        d = charm_dir / subdir
        if d.is_dir():
            files.extend(d.rglob("*.py"))
    return files


def _scan_deprecated_apis(python_files: list[Path]) -> list[dict[str, str]]:
    """Scan Python files for deprecated ops API usage."""
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in python_files:
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        for pattern, name, advice in _DEPRECATED_PATTERNS:
            if name in seen:
                continue
            if re.search(pattern, content):
                seen.add(name)
                findings.append(
                    {
                        "api": name,
                        "file": str(path),
                        "advice": advice,
                    }
                )
    return findings


def _check_fetch_libs(python_files: list[Path]) -> list[dict[str, str]]:
    """Detect charm library imports that have PyPI equivalents.

    Scans for ``from charms.<lib_prefix>.v<N>.<module>`` patterns and
    returns a list of findings with the import, the charm library prefix,
    and the recommended PyPI replacement.
    """
    _IMPORT_RE = re.compile(r"from\s+charms\.(\w+)\.v\d+\.\w+")
    findings: list[dict[str, str]] = []
    seen_prefixes: set[str] = set()

    for path in python_files:
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        for match in _IMPORT_RE.finditer(content):
            prefix = match.group(1)
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            pypi_name = _FETCH_LIBS_PYPI_MAP.get(prefix)
            if pypi_name:
                findings.append(
                    {
                        "lib_prefix": prefix,
                        "pypi_package": pypi_name,
                        "file": str(path),
                        "advice": f"Replace with `pip install {pypi_name}`",
                    }
                )
            else:
                findings.append(
                    {
                        "lib_prefix": prefix,
                        "pypi_package": "",
                        "file": str(path),
                        "advice": "Check PyPI for a published equivalent",
                    }
                )
    return findings


def _check_cos_relations(metadata: dict[str, Any]) -> dict[str, bool]:
    """Check which COS relation interfaces are present in the metadata."""
    all_relations: dict[str, Any] = {}
    for section in ("requires", "provides", "peers"):
        all_relations.update(metadata.get(section, {}))

    present: dict[str, bool] = {}
    for interface, _desc in _COS_RELATIONS.items():
        present[interface] = any(
            rel.get("interface") == interface
            for rel in all_relations.values()
            if isinstance(rel, dict)
        )
    return present


def _check_listing_fields(metadata: dict[str, Any]) -> dict[str, bool]:
    """Check which Charmhub listing metadata fields are populated."""
    return {field: bool(metadata.get(field)) for field in _LISTING_FIELDS}


def _check_tests(charm_dir: Path) -> dict[str, bool]:
    """Check for existence of test directories and files."""
    unit_dir = charm_dir / "tests" / "unit"
    integration_dir = charm_dir / "tests" / "integration"
    return {
        "unit_tests": unit_dir.is_dir() and bool(list(unit_dir.glob("test_*.py"))),
        "integration_tests": (
            integration_dir.is_dir() and bool(list(integration_dir.glob("test_*.py")))
        ),
    }


def _check_ops_tracing(charm_dir: Path, python_files: list[Path]) -> bool:
    """Check whether ops-tracing is set up in the charm."""
    # Check requirements for ops-tracing dependency.
    for req_file in ("requirements.txt", "pyproject.toml"):
        path = charm_dir / req_file
        if path.exists():
            try:
                content = path.read_text(errors="replace")
                if "ops-tracing" in content:
                    return True
            except OSError:
                pass

    # Check source for setup call.
    for path in python_files:
        try:
            content = path.read_text(errors="replace")
            if "ops_tracing" in content or "setup_tracing" in content:
                return True
        except OSError:
            pass

    return False


def _check_type_annotations(python_files: list[Path]) -> bool:
    """Check whether charm source files use type annotations.

    Returns True if at least one function definition in src/ has a
    return-type annotation.  This is a lightweight heuristic — we are
    not running a type checker, just looking for evidence that the
    codebase uses type hints.
    """
    for path in python_files:
        # Only check src/ files (skip lib/).
        if "lib" in path.parts:
            continue
        try:
            content = path.read_text(errors="replace")
        except OSError:
            continue
        # Look for `def foo(...) -> ...:` pattern.
        if re.search(r"def\s+\w+\([^)]*\)\s*->", content):
            return True
    return False


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


def _check_modern_patterns(python_files: list[Path]) -> dict[str, bool]:
    """Check whether the charm uses modern Ops framework patterns.

    Returns a dict of pattern name → whether the pattern is present.
    """
    results: dict[str, bool] = {name: False for _, name, _ in _MODERN_PATTERNS}

    all_source = ""
    for path in python_files:
        if "lib" in path.parts:
            continue
        try:
            all_source += path.read_text(errors="replace") + "\n"
        except OSError:
            continue

    for pattern, name, _desc in _MODERN_PATTERNS:
        if re.search(pattern, all_source):
            results[name] = True

    return results


def _format_audit_report(
    charm_name: str,
    cos_present: dict[str, bool],
    listing_present: dict[str, bool],
    tests_present: dict[str, bool],
    has_ops_tracing: bool,
    deprecated_apis: list[dict[str, str]],
    fetch_libs: list[dict[str, str]],
    has_readme: bool,
    has_licence: bool,
    has_icon: bool,
    has_type_annotations: bool = True,
    modern_patterns: dict[str, bool] | None = None,
) -> tuple[str, dict[str, list[str]]]:
    """Format an AUDIT.md report and categorised findings dict."""
    must_fix: list[str] = []
    should_fix: list[str] = []
    nice_to_have: list[str] = []

    # COS integration gaps.
    for interface, desc in _COS_RELATIONS.items():
        if not cos_present.get(interface):
            should_fix.append(f"Missing COS relation: {interface} ({desc})")

    if not has_ops_tracing:
        should_fix.append("ops-tracing not detected — add for distributed tracing")

    # Test gaps.
    if not tests_present["unit_tests"]:
        must_fix.append("No unit tests found in tests/unit/")
    if not tests_present["integration_tests"]:
        should_fix.append("No integration tests found in tests/integration/")

    # Deprecated APIs.
    for finding in deprecated_apis:
        must_fix.append(
            f"Deprecated API: {finding['api']} in {finding['file']} — {finding['advice']}"
        )

    # Fetch-libs that should be replaced with PyPI packages.
    for finding in fetch_libs:
        pypi = finding["pypi_package"]
        prefix = finding["lib_prefix"]
        if pypi:
            should_fix.append(
                f"charmcraft fetch-libs import: charms.{prefix} — "
                f"replace with PyPI package `{pypi}`"
            )
        else:
            nice_to_have.append(
                f"charmcraft fetch-libs import: charms.{prefix} — "
                f"check PyPI for a published equivalent"
            )

    # Type annotations.
    if not has_type_annotations:
        nice_to_have.append(
            "No type annotations found — add return-type hints to functions"
        )

    # Modern patterns.
    if modern_patterns is not None:
        for _pattern, name, desc in _MODERN_PATTERNS:
            if not modern_patterns.get(name):
                nice_to_have.append(f"Missing modern pattern: {desc}")

    # Listing completeness.
    for field_name, desc in _LISTING_FIELDS.items():
        if not listing_present.get(field_name):
            category = nice_to_have if field_name == "tags" else should_fix
            category.append(f"Missing metadata: {field_name} ({desc})")

    # Files.
    if not has_readme:
        should_fix.append("No README.md found")
    if not has_licence:
        nice_to_have.append("No LICENSE file found")
    if not has_icon:
        nice_to_have.append("No icon.svg found")

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

    return "\n".join(lines), findings


class CharmAuditTool(Tool):
    """Tool to audit an existing charm against best practices."""

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
            "(must-fix, should-fix, nice-to-have)."
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

        # Load metadata from charmcraft.yaml or legacy metadata.yaml.
        metadata = _load_yaml(charm_dir / "charmcraft.yaml")
        if not metadata:
            metadata = _load_yaml(charm_dir / "metadata.yaml")
        if not metadata:
            return ToolResult(
                success=False,
                output="",
                error=("No charmcraft.yaml or metadata.yaml found — is this a charm directory?"),
            )

        charm_name = metadata.get("name", charm_dir.name)

        # Collect source files.
        python_files = _collect_python_files(charm_dir)

        # Run all checks.
        cos_present = _check_cos_relations(metadata)
        listing_present = _check_listing_fields(metadata)
        tests_present = _check_tests(charm_dir)
        has_ops_tracing = _check_ops_tracing(charm_dir, python_files)
        deprecated_apis = _scan_deprecated_apis(python_files)
        fetch_libs = _check_fetch_libs(python_files)
        has_readme = (charm_dir / "README.md").exists()
        has_licence = (charm_dir / "LICENSE").exists() or (charm_dir / "LICENCE").exists()
        has_icon = (charm_dir / "icon.svg").exists()
        has_type_annotations = _check_type_annotations(python_files)
        modern_patterns = _check_modern_patterns(python_files)

        report, findings = _format_audit_report(
            charm_name=charm_name,
            cos_present=cos_present,
            listing_present=listing_present,
            tests_present=tests_present,
            has_ops_tracing=has_ops_tracing,
            deprecated_apis=deprecated_apis,
            fetch_libs=fetch_libs,
            has_readme=has_readme,
            has_licence=has_licence,
            has_icon=has_icon,
            has_type_annotations=has_type_annotations,
            modern_patterns=modern_patterns,
        )

        total_issues = sum(len(v) for v in findings.values())

        return ToolResult(
            success=True,
            output=report,
            data={
                "charm_name": charm_name,
                "total_issues": total_issues,
                "findings": findings,
                "gaps": {
                    "cos_tracing": not cos_present.get("tracing", False),
                    "cos_metrics": not cos_present.get("metrics-endpoint", False),
                    "cos_logging": not cos_present.get("logging", False),
                    "cos_dashboards": not cos_present.get("grafana-dashboard", False),
                    "ops_tracing": not has_ops_tracing,
                    "unit_tests": not tests_present["unit_tests"],
                    "integration_tests": not tests_present["integration_tests"],
                    "readme": not has_readme,
                    "licence": not has_licence,
                    "icon": not has_icon,
                    "type_annotations": not has_type_annotations,
                    "modern_patterns": any(
                        not v for v in modern_patterns.values()
                    ),
                },
                "modern_patterns": modern_patterns,
                "deprecated_apis": deprecated_apis,
                "fetch_libs": fetch_libs,
                "listing_fields": listing_present,
            },
        )
