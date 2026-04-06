"""Core linter engine — loads charm context, discovers rules, runs them."""

import contextlib
import pathlib
from typing import Any

import yaml

from . import config as _config
from . import models
from . import rules as _rules


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


def _collect_python_files(charm_dir: pathlib.Path) -> list[pathlib.Path]:
    """Collect all Python files in src/ and lib/ directories."""
    files: list[pathlib.Path] = []
    for subdir in ("src", "lib"):
        d = charm_dir / subdir
        if d.is_dir():
            files.extend(sorted(d.rglob("*.py")))
    return files


def _read_python_sources(python_files: list[pathlib.Path]) -> dict[pathlib.Path, str]:
    """Read all Python files into a content cache."""
    sources: dict[pathlib.Path, str] = {}
    for path in python_files:
        with contextlib.suppress(OSError):
            sources[path] = path.read_text(errors="replace")
    return sources


def _check_tests(charm_dir: pathlib.Path) -> tuple[bool, bool]:
    """Return (has_unit_tests, has_integration_tests)."""
    unit_dir = charm_dir / "tests" / "unit"
    integration_dir = charm_dir / "tests" / "integration"
    has_unit = unit_dir.is_dir() and bool(list(unit_dir.glob("test_*.py")))
    has_integration = integration_dir.is_dir() and bool(list(integration_dir.glob("test_*.py")))
    return has_unit, has_integration


def build_context(charm_dir: pathlib.Path) -> models.CharmContext:
    """Load all charm data into a CharmContext for rule evaluation."""
    charm_dir = charm_dir.resolve()

    # Load metadata from charmcraft.yaml or legacy metadata.yaml.
    metadata = _load_yaml(charm_dir / "charmcraft.yaml")
    if not metadata:
        metadata = _load_yaml(charm_dir / "metadata.yaml")

    # Load actions (charmcraft.yaml or actions.yaml).
    actions: dict[str, Any] = metadata.get("actions", {})
    if not actions:
        actions_data = _load_yaml(charm_dir / "actions.yaml")
        actions = actions_data if isinstance(actions_data, dict) else {}

    # Load config options (charmcraft.yaml or config.yaml).
    config_section = metadata.get("config", {})
    if isinstance(config_section, dict) and config_section.get("options"):
        config_options = config_section["options"]
    elif isinstance(config_section, dict) and config_section:
        config_options = config_section
    else:
        config_data = _load_yaml(charm_dir / "config.yaml")
        config_options = config_data.get("options", config_data) if config_data else {}

    # Collect Python files and read their contents.
    python_files = _collect_python_files(charm_dir)
    python_sources = _read_python_sources(python_files)

    # Read README.
    readme_content = ""
    readme_path = charm_dir / "README.md"
    if readme_path.exists():
        with contextlib.suppress(OSError):
            readme_content = readme_path.read_text(errors="replace")

    has_unit, has_integration = _check_tests(charm_dir)

    return models.CharmContext(
        charm_dir=charm_dir,
        metadata=metadata,
        actions=actions,
        config_options=config_options,
        python_files=python_files,
        python_sources=python_sources,
        readme_content=readme_content,
        has_tests_unit=has_unit,
        has_tests_integration=has_integration,
    )


def _should_run_rule(rule: _rules.Rule, config: _config.LintConfig) -> bool:
    """Determine whether a rule should run given the config."""
    rule_id = rule.id
    category = rule_id.rstrip("0123456789")

    # Explicit disable via severity override.
    if config.severity_overrides.get(rule_id) == "off":
        return False

    # Category-level disable.
    if config.severity_overrides.get(category) == "off":
        return False

    # If select is set, only run rules in those categories.
    if config.select and category not in config.select:
        return False

    # If ignore contains this specific rule or category, skip it.
    return not (rule_id in config.ignore or category in config.ignore)


def _effective_severity(rule: _rules.Rule, config: _config.LintConfig) -> models.Severity | None:
    """Resolve the effective severity for a rule, applying config overrides."""
    rule_id = rule.id
    override = config.severity_overrides.get(rule_id)
    if override and override != "off":
        try:
            return models.Severity(override)
        except ValueError:
            pass
    return None


def lint(
    charm_dir: pathlib.Path,
    config: _config.LintConfig | None = None,
) -> models.LintReport:
    """Run all enabled rules against a charm directory.

    This is the main public API.
    """
    if config is None:
        config = _config.LintConfig()

    # Ensure all rule modules are imported so rules register themselves.
    _ensure_rules_loaded()

    context = build_context(charm_dir)

    if not context.metadata:
        return models.LintReport(
            charm_dir=charm_dir,
            diagnostics=[
                models.Diagnostic(
                    rule_id="FATAL",
                    severity=models.Severity.ERROR,
                    message=(
                        "No charmcraft.yaml or metadata.yaml found — is this a charm directory?"
                    ),
                )
            ],
        )

    all_diagnostics: list[models.Diagnostic] = []

    for rule in _rules.get_all_rules().values():
        if not _should_run_rule(rule, config):
            continue

        diagnostics = rule.check(context)

        # Apply severity overrides.
        override = _effective_severity(rule, config)
        if override is not None:
            diagnostics = [
                models.Diagnostic(
                    rule_id=d.rule_id,
                    severity=override,
                    message=d.message,
                    path=d.path,
                    line=d.line,
                    fix_hint=d.fix_hint,
                )
                for d in diagnostics
            ]

        # Filter by minimum severity.
        if config.min_severity:
            severity_order = {
                models.Severity.ERROR: 0,
                models.Severity.WARNING: 1,
                models.Severity.INFO: 2,
            }
            min_order = severity_order.get(config.min_severity, 2)
            diagnostics = [
                d for d in diagnostics if severity_order.get(d.severity, 2) <= min_order
            ]

        all_diagnostics.extend(diagnostics)

    return models.LintReport(charm_dir=charm_dir, diagnostics=all_diagnostics)


_rules_loaded = False


def _ensure_rules_loaded() -> None:
    """Import all rule modules so their Rule subclasses register."""
    global _rules_loaded  # noqa: PLW0603
    if _rules_loaded:
        return
    _rules_loaded = True

    from .rules import (
        actions,  # noqa: F401
        charmcraft_compat,  # noqa: F401
        config_quality,  # noqa: F401
        deprecated,  # noqa: F401
        documentation,  # noqa: F401
        libraries,  # noqa: F401
        metadata,  # noqa: F401
        observability,  # noqa: F401
        security,  # noqa: F401
        status,  # noqa: F401
        structure,  # noqa: F401
        testing,  # noqa: F401
    )
