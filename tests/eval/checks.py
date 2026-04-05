"""Rubric checker functions.

Each function takes a ``charm_dir`` (Path) as the first argument plus
optional keyword arguments from the criterion's ``args`` dict.  It returns
``(passed: bool, detail: str)``.

Checker names are referenced from ``spec.yaml`` rubric entries via the
``check`` field (e.g. ``check: file_exists``).
"""

import pathlib
import re

import yaml

# ---------------------------------------------------------------------------
# Structure checks
# ---------------------------------------------------------------------------


def file_exists(charm_dir: pathlib.Path, *, path: str) -> tuple[bool, str]:
    """Check that a file exists at the given relative path."""
    target = charm_dir / path
    if target.exists():
        return True, f"{path} exists"
    return False, f"{path} missing"


def dir_exists(charm_dir: pathlib.Path, *, path: str) -> tuple[bool, str]:
    """Check that a directory exists at the given relative path."""
    target = charm_dir / path
    if target.is_dir():
        return True, f"{path}/ exists"
    return False, f"{path}/ missing"


def file_matches_pattern(
    charm_dir: pathlib.Path, *, glob: str, min_count: int = 1
) -> tuple[bool, str]:
    """Check that at least *min_count* files match a glob pattern."""
    matches = list(charm_dir.glob(glob))
    if len(matches) >= min_count:
        return True, f"{len(matches)} file(s) matching {glob}"
    return False, f"only {len(matches)} file(s) matching {glob} (need {min_count})"


# ---------------------------------------------------------------------------
# Metadata checks
# ---------------------------------------------------------------------------


def metadata_field(
    charm_dir: pathlib.Path,
    *,
    field: str,
    expected: str | None = None,
) -> tuple[bool, str]:
    """Check that a metadata field exists (and optionally matches a value).

    Looks in ``charmcraft.yaml`` first, then falls back to ``metadata.yaml``.
    Supports dotted paths for nested fields (e.g. ``assumes.0``).
    """
    data = _load_metadata(charm_dir)
    if data is None:
        return False, "no charmcraft.yaml or metadata.yaml found"

    value = _nested_get(data, field)
    if value is None:
        return False, f"field '{field}' not found in metadata"

    if expected is not None and str(value) != expected:
        return False, f"'{field}' is '{value}', expected '{expected}'"

    return True, f"'{field}' = '{value}'"


def has_relation(
    charm_dir: pathlib.Path,
    *,
    relation: str,
    interface: str | None = None,
) -> tuple[bool, str]:
    """Check that the charm declares a specific relation endpoint."""
    data = _load_metadata(charm_dir)
    if data is None:
        return False, "no metadata found"

    for section in ("requires", "provides", "peers"):
        endpoints = data.get(section, {})
        if relation in endpoints:
            if interface is not None:
                actual = endpoints[relation].get("interface", "")
                if actual != interface:
                    return False, (
                        f"{relation} found but interface is '{actual}', expected '{interface}'"
                    )
            return True, f"{relation} found in {section}"

    return False, f"relation '{relation}' not declared"


def has_config_option(
    charm_dir: pathlib.Path,
    *,
    option: str,
    type: str | None = None,
) -> tuple[bool, str]:
    """Check that a config option is declared."""
    data = _load_metadata(charm_dir)
    if data is None:
        return False, "no metadata found"

    # charmcraft.yaml nests config under config.options; metadata.yaml
    # uses a separate config.yaml.
    options = _nested_get(data, "config.options") or {}
    if not options:
        config_yaml = charm_dir / "config.yaml"
        if config_yaml.exists():
            cfg = yaml.safe_load(config_yaml.read_text()) or {}
            options = cfg.get("options", {})

    if option not in options:
        return False, f"config option '{option}' not found"

    if type is not None:
        actual = options[option].get("type", "")
        if actual != type:
            return False, f"'{option}' type is '{actual}', expected '{type}'"

    return True, f"config option '{option}' found"


def has_action(
    charm_dir: pathlib.Path,
    *,
    action: str,
) -> tuple[bool, str]:
    """Check that an action is declared."""
    # charmcraft.yaml may embed actions; otherwise check actions.yaml.
    data = _load_metadata(charm_dir)
    actions = (data or {}).get("actions", {})
    if not actions:
        actions_yaml = charm_dir / "actions.yaml"
        if actions_yaml.exists():
            actions = yaml.safe_load(actions_yaml.read_text()) or {}

    if action in actions:
        return True, f"action '{action}' declared"
    return False, f"action '{action}' not found"


# ---------------------------------------------------------------------------
# Code quality checks
# ---------------------------------------------------------------------------


def file_contains(
    charm_dir: pathlib.Path,
    *,
    path: str,
    pattern: str,
    message: str = "",
) -> tuple[bool, str]:
    """Check that a file contains a regex pattern."""
    target = charm_dir / path
    if not target.exists():
        return False, f"{path} missing"
    content = target.read_text()
    if re.search(pattern, content):
        return True, message or f"{path} contains /{pattern}/"
    return False, message or f"{path} does not contain /{pattern}/"


def file_not_contains(
    charm_dir: pathlib.Path,
    *,
    path: str,
    pattern: str,
    message: str = "",
) -> tuple[bool, str]:
    """Check that a file does NOT contain a regex pattern (anti-pattern)."""
    target = charm_dir / path
    if not target.exists():
        # File not existing means it can't contain the anti-pattern.
        return True, f"{path} does not exist (OK)"
    content = target.read_text()
    if re.search(pattern, content):
        return False, message or f"{path} contains anti-pattern /{pattern}/"
    return True, message or f"{path} clean of /{pattern}/"


def uses_ops_framework(charm_dir: pathlib.Path) -> tuple[bool, str]:
    """Check that the charm uses the ops framework."""
    charm_py = _find_charm_py(charm_dir)
    if charm_py is None:
        return False, "no charm.py found"
    content = charm_py.read_text()
    if "import ops" in content or "from ops" in content:
        return True, "uses ops framework"
    return False, "does not import ops"


def uses_scenario_tests(charm_dir: pathlib.Path) -> tuple[bool, str]:
    """Check that unit tests use Scenario (ops.testing), not Harness."""
    test_dir = charm_dir / "tests" / "unit"
    if not test_dir.is_dir():
        return False, "no tests/unit/ directory"

    test_files = list(test_dir.glob("test_*.py"))
    if not test_files:
        return False, "no test files in tests/unit/"

    all_content = "\n".join(f.read_text() for f in test_files)

    if "Harness" in all_content:
        return False, "tests use deprecated Harness (should use Scenario)"

    if "ops.testing" in all_content or "scenario" in all_content.lower():
        return True, "tests use Scenario"

    return False, "tests do not appear to use Scenario"


def no_harness(charm_dir: pathlib.Path) -> tuple[bool, str]:
    """Check that no test file imports or uses Harness."""
    test_dir = charm_dir / "tests" / "unit"
    if not test_dir.is_dir():
        return True, "no unit tests (cannot use Harness)"

    for f in test_dir.glob("test_*.py"):
        if "Harness" in f.read_text():
            return False, f"{f.name} uses deprecated Harness"
    return True, "no Harness usage"


# ---------------------------------------------------------------------------
# COS / observability checks
# ---------------------------------------------------------------------------


def has_cos_integration(charm_dir: pathlib.Path) -> tuple[bool, str]:
    """Check that the charm integrates with COS (metrics, logging, or tracing)."""
    data = _load_metadata(charm_dir)
    if data is None:
        return False, "no metadata found"

    cos_interfaces = {
        "grafana-dashboard",
        "prometheus_scrape",
        "loki_push_api",
        "tracing",
        "cos-agent",
    }
    for section in ("requires", "provides"):
        for endpoint in (data.get(section) or {}).values():
            iface = endpoint.get("interface", "")
            if iface in cos_interfaces:
                return True, f"COS integration via {iface}"

    # Also check for ops-tracing in requirements or charm code.
    charm_py = _find_charm_py(charm_dir)
    if charm_py and "ops_tracing" in charm_py.read_text():
        return True, "uses ops-tracing"

    return False, "no COS integration found"


# ---------------------------------------------------------------------------
# Testing checks
# ---------------------------------------------------------------------------


def has_unit_tests(charm_dir: pathlib.Path, *, min_files: int = 1) -> tuple[bool, str]:
    """Check that unit tests exist."""
    test_dir = charm_dir / "tests" / "unit"
    if not test_dir.is_dir():
        return False, "no tests/unit/ directory"
    files = list(test_dir.glob("test_*.py"))
    if len(files) >= min_files:
        return True, f"{len(files)} unit test file(s)"
    return False, f"only {len(files)} unit test file(s) (need {min_files})"


def has_integration_tests(charm_dir: pathlib.Path, *, min_files: int = 1) -> tuple[bool, str]:
    """Check that integration tests exist."""
    test_dir = charm_dir / "tests" / "integration"
    if not test_dir.is_dir():
        return False, "no tests/integration/ directory"
    files = list(test_dir.glob("test_*.py"))
    if len(files) >= min_files:
        return True, f"{len(files)} integration test file(s)"
    return False, f"only {len(files)} integration test file(s) (need {min_files})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_metadata(charm_dir: pathlib.Path) -> dict | None:
    """Load charm metadata from charmcraft.yaml or metadata.yaml."""
    for name in ("charmcraft.yaml", "metadata.yaml"):
        path = charm_dir / name
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
    return None


def _nested_get(data: dict, dotted_key: str):
    """Get a nested value via dotted path (e.g. ``config.options``)."""
    current = data
    for part in dotted_key.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _find_charm_py(charm_dir: pathlib.Path) -> pathlib.Path | None:
    """Find the main charm.py file."""
    for candidate in (
        charm_dir / "src" / "charm.py",
        charm_dir / "charm.py",
    ):
        if candidate.exists():
            return candidate
    return None
