"""Charm test runner and test template generation tools."""

import pathlib
import re
import shutil
import subprocess
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult


def _resolve_path_via_state(path: str, state: Any) -> pathlib.Path:
    """Resolve *path* against ``state.charm_path`` instead of the process cwd.

    The default ``pathlib.Path(path).resolve()`` anchors at the
    process cwd, which is fine in standalone use but wrong inside the
    agent: sprint mode reroots ``state.charm_path`` into a
    ``<launch>/<charm_name>`` subdir without changing cwd, so a
    naive resolve still returns the launch directory.  Falls back to
    the cwd-anchored resolve when ``state`` is not supplied — keeps
    the function safe for direct unit tests.
    """
    candidate = pathlib.Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if state is not None and getattr(state, "charm_path", None):
        return (state.charm_path / candidate).resolve()
    return candidate.resolve()


# Timeouts per test type (seconds).
_TIMEOUTS = {"unit": 120, "integration": 900}

# If output exceeds this many characters, truncate to the last N lines.
_MAX_OUTPUT_CHARS = 5000
_TAIL_LINES = 200

# Regex matching the pytest summary line, e.g. "3 passed, 1 failed, 2 error".
_SUMMARY_RE = re.compile(
    r"(?:=+)?\s*"
    r"(?:(?P<failed>\d+) failed)?"
    r"[, ]*(?:(?P<passed>\d+) passed)?"
    r"[, ]*(?:(?P<error>\d+) error)?"
    r"[, ]*(?:(?P<skipped>\d+) skipped)?"
)

# Matches the TOTAL line from ``coverage report``, e.g.:
#   TOTAL    1234    56    95%
_COVERAGE_TOTAL_RE = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", re.MULTILINE)


def _parse_pytest_summary(output: str) -> dict[str, int]:
    """Extract passed/failed/error/skipped counts from pytest output.

    Scans the output for the pytest summary line (e.g.
    ``=== 3 passed, 1 failed in 0.5s ===``) and returns a dict of counts.
    Returns an empty dict if no summary line is found.
    """
    # Pytest prints a final summary line starting with "=" characters.
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("="):
            continue
        # Try all patterns: "X failed", "X passed", "X error", "X skipped".
        counts: dict[str, int] = {}
        for key in ("passed", "failed", "error", "skipped"):
            match = re.search(rf"(\d+) {key}", stripped)
            if match:
                counts[key] = int(match.group(1))
        if counts:
            return counts
    return {}


def _parse_coverage_total(output: str) -> int | None:
    """Extract the total coverage percentage from ``coverage report`` output.

    Returns the integer percentage (e.g. 85) or ``None`` if no coverage
    summary is found.
    """
    match = _COVERAGE_TOTAL_RE.search(output)
    if match:
        return int(match.group(1))
    return None


def _truncate_output(output: str) -> str:
    """Truncate output to the last ``_TAIL_LINES`` lines if it exceeds the threshold."""
    if len(output) <= _MAX_OUTPUT_CHARS:
        return output
    lines = output.splitlines()
    tail = lines[-_TAIL_LINES:]
    return f"[...truncated — showing last {_TAIL_LINES} lines...]\n" + "\n".join(tail)


def _build_pytest_target(test_dir: pathlib.Path, pattern: str | None) -> list[str]:
    """Build the pytest positional arguments from an optional pattern.

    Supports three forms:
    - ``None`` → run the whole test directory
    - ``"test_deploy"`` → run a specific file (``tests/<type>/test_deploy.py``)
    - ``"test_deploy::test_foo"`` → run a specific test function
    - anything containing spaces or boolean operators → passed to ``-k``
    """
    if pattern is None:
        return [str(test_dir) + "/"]

    # A -k expression: contains spaces or boolean keywords.
    if " " in pattern or " or " in pattern or " and " in pattern:
        return [str(test_dir) + "/", "-k", pattern]

    # File::function form.
    if "::" in pattern:
        file_part, rest = pattern.split("::", 1)
        file_part = file_part.removesuffix(".py")
        candidate = test_dir / f"{file_part}.py"
        if candidate.exists():
            return [f"{candidate}::{rest}"]
        # Fall back to -k if the file doesn't exist.
        return [str(test_dir) + "/", "-k", rest]

    # Plain name — try as a file first, then fall back to -k.
    candidate = test_dir / f"{pattern}.py"
    if candidate.exists():
        return [str(candidate)]
    candidate = test_dir / pattern
    if candidate.exists():
        return [str(candidate)]
    return [str(test_dir) + "/", "-k", pattern]


class RunCharmTestsTool(Tool):
    """Tool to run unit or integration tests for a charm."""

    def __init__(self, state: Any = None) -> None:
        # ``state`` is optional so existing instantiations (and tests
        # that build the tool without a full agent) keep working.  When
        # set, ``path="."`` resolves against ``state.charm_path``
        # rather than the process cwd — sprint mode reroots
        # ``state.charm_path`` into a ``<launch>/<charm_name>`` subdir
        # but does not chdir, so without this hook the test runner
        # walks the launch directory instead of the charm subdir.
        self._state = state

    @property
    def name(self) -> str:
        return "run_charm_tests"

    @property
    def description(self) -> str:
        return (
            "Run unit or integration tests for a charm. "
            "Prefers tox if available, otherwise falls back to pytest. "
            "Returns test output and a parsed summary of pass/fail counts. "
            "Use the optional pattern parameter to run a specific test file "
            "or test function (e.g. 'test_deploy' or 'test_relations::test_db')."
        )

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        test_type = arguments.get("test_type", "unit")
        pattern = arguments.get("pattern")
        if pattern:
            return f"Running {test_type} tests ({pattern})…"
        return f"Running {test_type} tests…"

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
                "test_type": {
                    "type": "string",
                    "description": "Type of tests to run",
                    "enum": ["unit", "integration"],
                    "default": "unit",
                },
                "pattern": {
                    "type": "string",
                    "description": (
                        "Optional filter to run specific tests. Can be a file name "
                        "(e.g. 'test_deploy'), a file::function pattern "
                        "(e.g. 'test_relations::test_db_connect'), or a pytest -k "
                        "expression (e.g. 'deploy or relation'). Only used with the "
                        "pytest runner — ignored when tox is used."
                    ),
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        test_type: str = "unit",
        pattern: str | None = None,
    ) -> ToolResult:
        """Run charm tests using tox or pytest."""
        charm_path = _resolve_path_via_state(path, self._state)
        if not charm_path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        timeout = _TIMEOUTS.get(test_type, _TIMEOUTS["unit"])

        # Prefer tox if tox.ini exists and tox is on PATH — but fall back to
        # pytest when a pattern is given so we can target specific tests.
        use_tox = (
            (charm_path / "tox.ini").exists()
            and shutil.which("tox") is not None
            and pattern is None
        )

        if use_tox:
            cmd = ["tox", "-e", test_type]
            runner = "tox"
        else:
            # Fall back to pytest.
            if not shutil.which("python"):
                return ToolResult(
                    success=False,
                    output="",
                    error="Neither tox nor python found on PATH.",
                )
            test_dir = charm_path / "tests" / test_type
            if not test_dir.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Test directory not found: tests/{test_type}/",
                )
            cmd = ["python", "-m", "pytest", "-v", "--tb=short"]
            cmd.extend(_build_pytest_target(test_dir, pattern))
            runner = "pytest"

        try:
            result = subprocess.run(
                cmd,
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Tests timed out after {timeout}s",
            )

        combined = result.stdout
        if result.stderr:
            combined += "\n" + result.stderr

        summary = _parse_pytest_summary(combined)
        coverage_pct = _parse_coverage_total(combined)
        output = _truncate_output(combined)

        success = result.returncode == 0
        data: dict[str, Any] = {"summary": summary, "runner": runner}
        if coverage_pct is not None:
            data["coverage_pct"] = coverage_pct

        # Caption: "12 passed, 1 failed" / "0 collected" / runner-fell-over
        # case has no summary so synthesise from the exit code.
        caption_parts = [
            f"{summary[k]} {k}" for k in ("passed", "failed", "error", "skipped") if summary.get(k)
        ]
        if caption_parts:
            caption = ", ".join(caption_parts)
        elif success:
            caption = "tests ran (no summary)"
        else:
            caption = f"tests failed (exit {result.returncode})"

        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"Tests failed (exit code {result.returncode})",
            data=data,
            caption=caption,
        )


# ---------------------------------------------------------------------------
# Integration test template generation
# ---------------------------------------------------------------------------


def generate_integration_tests(
    charm_name: str,
    metadata: dict[str, Any],
) -> dict[str, str]:
    """Generate integration test files from charm metadata.

    Returns a ``{relative_path: content}`` map with:
    - ``tests/integration/conftest.py`` — Jubilant fixtures
    - ``tests/integration/test_deploy.py`` — basic deploy test
    - ``tests/integration/test_relations.py`` — one test per relation (if any)
    - ``tests/integration/test_actions.py`` — one test per action (if any)
    - ``tests/integration/test_config.py`` — one test per config option (if any)

    Tests follow Jubilant patterns and are designed to be runnable (and
    failing) before any charm code is written — the "red" phase of the
    red/green build cycle.
    """
    requires = metadata.get("requires", {})
    provides = metadata.get("provides", {})
    actions = metadata.get("actions", {})
    config = metadata.get("config", {}).get("options", {})

    files: dict[str, str] = {}

    # -- conftest.py --------------------------------------------------------
    #
    # ``pytest-jubilant`` supplies a module-scoped ``juju`` fixture that
    # creates and tears down a temporary Juju model and dumps debug logs
    # on failure.  We only need a ``charm`` fixture pointing at the packed
    # ``.charm`` file (honouring ``CHARM_PATH`` so CI can override).

    files["tests/integration/conftest.py"] = (
        '"""Shared fixtures for integration tests."""\n'
        "\n"
        "import os\n"
        "import pathlib\n"
        "\n"
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.fixture(scope="session")\n'
        "def charm():\n"
        '    """Return the path of the charm under test."""\n'
        '    charm = os.environ.get("CHARM_PATH")\n'
        "    if not charm:\n"
        "        charm_dir = pathlib.Path()\n"
        '        charms = list(charm_dir.glob("*.charm"))\n'
        '        assert charms, f"No charms were found in {charm_dir.absolute()}"\n'
        '        assert len(charms) == 1, f"Found more than one charm: {charms}"\n'
        "        charm = charms[0]\n"
        "    path = pathlib.Path(charm).resolve()\n"
        '    assert path.is_file(), f"{path} is not a file"\n'
        "    return path\n"
    )

    # -- test_deploy.py -----------------------------------------------------

    files["tests/integration/test_deploy.py"] = (
        '"""Deploy tests — verify the charm reaches active/idle."""\n'
        "\n"
        "import jubilant\n"
        "\n"
        "\n"
        f'APP_NAME = "{charm_name}"\n'
        "\n"
        "\n"
        "def test_deploy(juju: jubilant.Juju, charm):\n"
        '    """Deploy the charm and wait for active status."""\n'
        "    juju.deploy(charm)\n"
        "    juju.wait(jubilant.all_active, timeout=300)\n"
        "    status = juju.status()\n"
        "    assert status.apps[APP_NAME].is_active\n"
    )

    # -- test_relations.py (only if relations exist) ------------------------

    all_relations = {}
    all_relations.update(requires)
    all_relations.update(provides)

    if all_relations:
        rel_tests: list[str] = [
            '"""Relation tests — verify each integration endpoint."""\n',
            "\n",
            "import jubilant\n",
            "\n",
            f'APP_NAME = "{charm_name}"\n',
            "\n",
            "\n",
        ]
        for rel_name, rel_data in requires.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            fn_name = re.sub(r"[^a-z0-9]", "_", rel_name.lower())
            rel_tests.append(
                f"def test_relate_{fn_name}(juju: jubilant.Juju, charm):\n"
                f'    """Relate {charm_name} to a provider for {rel_name} ({iface})."""\n'
                f"    juju.deploy(charm)\n"
                f"    # TODO: deploy a provider charm for interface '{iface}'\n"
                f"    # juju.deploy('<provider-charm>')\n"
                f'    # juju.integrate(f"{{APP_NAME}}:{rel_name}", "<provider-charm>")\n'
                f"    # juju.wait(jubilant.all_active, timeout=600)\n"
                f"    # status = juju.status()\n"
                f"    # assert status.apps[APP_NAME].is_active\n"
                f"\n"
                f"\n"
            )
        for rel_name, rel_data in provides.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            fn_name = re.sub(r"[^a-z0-9]", "_", rel_name.lower())
            rel_tests.append(
                f"def test_provide_{fn_name}(juju: jubilant.Juju, charm):\n"
                f'    """Verify {charm_name} provides {rel_name} ({iface})."""\n'
                f"    juju.deploy(charm)\n"
                f"    # TODO: deploy a requirer charm for interface '{iface}'\n"
                f"    # juju.deploy('<requirer-charm>')\n"
                f'    # juju.integrate("<requirer-charm>", f"{{APP_NAME}}:{rel_name}")\n'
                f"    # juju.wait(jubilant.all_active, timeout=600)\n"
                f"    # status = juju.status()\n"
                f"    # assert status.apps[APP_NAME].is_active\n"
                f"\n"
                f"\n"
            )
        files["tests/integration/test_relations.py"] = "".join(rel_tests).rstrip() + "\n"

    # -- test_actions.py (only if actions exist) ----------------------------

    if actions:
        action_tests: list[str] = [
            '"""Action tests — verify each action executes successfully."""\n',
            "\n",
            "import jubilant\n",
            "\n",
            f'APP_NAME = "{charm_name}"\n',
            "\n",
            "\n",
        ]
        for action_name, _action_data in actions.items():
            fn_name = re.sub(r"[^a-z0-9]", "_", action_name.lower())
            action_tests.append(
                f"def test_action_{fn_name}(juju: jubilant.Juju):\n"
                f'    """Run the {action_name} action and verify it completes."""\n'
                f'    task = juju.run(f"{{APP_NAME}}/leader", "{action_name}")\n'
                f'    assert task.status == "completed"\n'
                f"\n"
                f"\n"
            )
        files["tests/integration/test_actions.py"] = "".join(action_tests).rstrip() + "\n"

    # -- test_config.py (only if config options exist) ----------------------

    if config:
        config_tests: list[str] = [
            '"""Config tests — verify each config option can be set."""\n',
            "\n",
            "import jubilant\n",
            "\n",
            f'APP_NAME = "{charm_name}"\n',
            "\n",
            "\n",
        ]
        for opt_name, opt_data in config.items():
            fn_name = re.sub(r"[^a-z0-9]", "_", opt_name.lower())
            opt_type = opt_data.get("type", "string")
            # Generate a plausible non-default test value.
            if opt_type == "boolean":
                test_val = "true"
            elif opt_type == "int":
                test_val = "42"
            elif opt_type == "float":
                test_val = "3.14"
            else:
                test_val = "test-value"
            config_tests.append(
                f"def test_config_{fn_name}(juju: jubilant.Juju):\n"
                f'    """Set {opt_name} and verify the charm remains active."""\n'
                f'    juju.config(APP_NAME, {{"{opt_name}": "{test_val}"}})\n'
                f"    juju.wait(jubilant.all_active, timeout=120)\n"
                f"    status = juju.status()\n"
                f"    assert status.apps[APP_NAME].is_active\n"
                f"\n"
                f"\n"
            )
        files["tests/integration/test_config.py"] = "".join(config_tests).rstrip() + "\n"

    return files


class GenerateTestsTool(Tool):
    """Generate integration test templates from charm metadata."""

    @property
    def name(self) -> str:
        return "generate_tests"

    @property
    def description(self) -> str:
        return (
            "Generate Jubilant-based integration test templates from "
            "charmcraft.yaml. Produces tests/integration/ files with one "
            "test per relation, action, and config option. Tests are "
            "designed to fail initially (red phase) and pass once the "
            "charm code is written (green phase)."
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
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate integration test files in the charm directory."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        charmcraft_yaml = charm_dir / "charmcraft.yaml"
        if not charmcraft_yaml.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"charmcraft.yaml not found in {path}",
            )

        try:
            metadata = yaml.safe_load(charmcraft_yaml.read_text(errors="replace"))
            if not isinstance(metadata, dict):
                metadata = {}
        except (yaml.YAMLError, RecursionError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse charmcraft.yaml: {exc}",
            )

        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        files = generate_integration_tests(charm_name, metadata)

        written: list[str] = []
        for rel_path, content in files.items():
            full_path = charm_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            written.append(rel_path)

        test_count = sum(content.count("\ndef test_") for content in files.values())

        summary = (
            f"Generated integration test templates for '{charm_name}' "
            f"({len(written)} files, {test_count} tests):\n"
            + "\n".join(f"  {f}" for f in sorted(written))
            + "\n\nRun with: uv run pytest tests/integration/ -v"
        )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "charm_name": charm_name,
                "file_count": len(written),
                "test_count": test_count,
                "files": sorted(written),
            },
            caption=f"Wrote {len(written)} file{'s' if len(written) != 1 else ''}, {test_count} tests",
        )
