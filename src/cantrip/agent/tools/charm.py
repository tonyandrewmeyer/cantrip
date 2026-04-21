"""Charm scaffolding and management tools."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.testing import RunCharmTestsTool
from cantrip.agent.tools.workflows import inject_github_workflows
from cantrip.charm import terraform

_PAAS_PROFILES = frozenset(
    {
        "flask-framework",
        "django-framework",
        "fastapi-framework",
        "go-framework",
        "express-framework",
        "spring-boot-framework",
    }
)

_TRACING_RELATION_BLOCK = """
requires:
  tracing:
    interface: tracing
    limit: 1
"""

# Canonical PaaS charm dependency lines.  When a charm uses a 12-factor
# framework extension, its ``requirements.txt`` must carry ``ops`` and
# ``paas-charm`` — without them the charm's ``src/charm.py`` fails at
# import time with ``ModuleNotFoundError: No module named 'paas_charm'``.
_PAAS_OPS_LINE = "ops ~= 2.17"
_PAAS_CHARM_LINE = "paas-charm>=1.0,<2"


def _charm_uses_paas_extension(charm_path: Path) -> bool:
    """Return ``True`` when *charm_path*'s charmcraft.yaml uses a PaaS extension.

    Inspects ``extensions:`` in ``charmcraft.yaml``.  A missing file or a
    parse error counts as "no PaaS extension" — safer than failing the
    whole tool run for a cosmetic check.
    """
    charmcraft_yaml = charm_path / "charmcraft.yaml"
    if not charmcraft_yaml.exists():
        return False
    try:
        parsed = yaml.safe_load(charmcraft_yaml.read_text()) or {}
    except yaml.YAMLError:
        return False
    extensions = parsed.get("extensions") or []
    if not isinstance(extensions, list):
        return False
    return any(
        isinstance(ext, str) and ext.endswith("-framework") and ext in _PAAS_PROFILES
        for ext in extensions
    )


def _ensure_paas_requirements(charm_path: Path) -> list[str]:
    """Guarantee ``ops`` and ``paas-charm`` are in the charm's requirements.txt.

    The agent sometimes overwrites the charm's scaffolded
    ``requirements.txt`` with the application's own (e.g. when copying
    a Flask app's sources into the charm directory).  That wipes out the
    charm-side ``paas-charm`` dependency and the deployed charm crashes
    at install time with ``ModuleNotFoundError: No module named
    'paas_charm'``.  This helper is a belt-and-braces re-assertion: it
    leaves any existing lines alone (so app deps like ``flask`` survive)
    and only prepends what's missing.

    Returns a list of human-readable descriptions of what was done.
    Does nothing when the charm is not a PaaS charm.
    """
    actions: list[str] = []
    if not _charm_uses_paas_extension(charm_path):
        return actions

    requirements = charm_path / "requirements.txt"
    existing = requirements.read_text() if requirements.exists() else ""
    existing_lower = existing.lower()

    lines_to_prepend: list[str] = []
    if "paas-charm" not in existing_lower and "paas_charm" not in existing_lower:
        lines_to_prepend.append(_PAAS_CHARM_LINE)
    # Match ``ops`` as a requirements-file token only — avoid false
    # positives on ``ops-tracing``, ``ops-scenario``, etc.
    has_ops = any(
        line.strip().lower().split("=")[0].split(">")[0].split("<")[0].split("~")[0].strip()
        == "ops"
        for line in existing.splitlines()
    )
    if not has_ops:
        lines_to_prepend.append(_PAAS_OPS_LINE)

    if not lines_to_prepend:
        return actions

    prefix = "\n".join(lines_to_prepend) + "\n"
    requirements.write_text(prefix + existing)
    actions.append(
        f"Re-asserted PaaS charm deps in requirements.txt: "
        f"{', '.join(line.split('>')[0].split('~')[0].strip() for line in lines_to_prepend)}"
    )
    return actions


def _inject_ops_tracing(target_path: Path, profile: str) -> list[str]:
    """Inject ops-tracing into a freshly scaffolded charm.

    For standard profiles (``kubernetes``, ``machine``) the full stack is injected:
    ``requirements.txt``, ``charmcraft.yaml``, and ``src/charm.py``.  For PaaS /
    framework profiles only the tracing relation is added to ``charmcraft.yaml``
    (PaaS charms have no user-editable ``src/charm.py`` or ``requirements.txt``).

    Returns a list of human-readable descriptions of what was done.
    """
    actions: list[str] = []
    is_paas = profile in _PAAS_PROFILES

    # --- charmcraft.yaml: add tracing relation ---
    charmcraft_yaml = target_path / "charmcraft.yaml"
    if charmcraft_yaml.exists():
        content = charmcraft_yaml.read_text()
        if "tracing" not in content:
            charmcraft_yaml.write_text(content.rstrip("\n") + "\n" + _TRACING_RELATION_BLOCK)
            actions.append("Added tracing relation to charmcraft.yaml")
        else:
            actions.append("charmcraft.yaml already declares tracing — skipped")
    else:
        actions.append("charmcraft.yaml not found — skipped tracing relation")

    if is_paas:
        return actions

    # --- requirements.txt: append ops-tracing ---
    requirements = target_path / "requirements.txt"
    if requirements.exists():
        content = requirements.read_text()
        if "ops-tracing" not in content:
            requirements.write_text(content.rstrip("\n") + "\nops-tracing\n")
            actions.append("Added ops-tracing to requirements.txt")
        else:
            actions.append("requirements.txt already contains ops-tracing — skipped")
    else:
        requirements.write_text("ops-tracing\n")
        actions.append("Created requirements.txt with ops-tracing")

    # --- src/charm.py: insert import and setup call ---
    charm_py = target_path / "src" / "charm.py"
    if charm_py.exists():
        content = charm_py.read_text()
        if "ops_tracing" in content:
            actions.append("src/charm.py already contains ops_tracing — skipped")
        else:
            patched = _inject_ops_tracing_into_charm_py(content)
            if patched is not None:
                charm_py.write_text(patched)
                actions.append("Injected ops_tracing import and setup into src/charm.py")
            else:
                actions.append(
                    "src/charm.py did not match expected patterns — skipped ops-tracing"
                )
    else:
        actions.append("src/charm.py not found — skipped ops-tracing injection")

    return actions


# Anchor a bare ``import ops`` line — not ``import ops.charm`` or
# ``import ops_tracing``.  ``\r?$`` tolerates CRLF files that slipped
# through without newline translation; ``re.MULTILINE`` makes ``$``
# match at any line end.
_IMPORT_OPS_RE = re.compile(r"^import ops\r?$", re.MULTILINE)

# Match ``super().__init__(...)`` as a whole line and capture its leading
# indent so the injected follow-up line uses the same indentation.  The
# argument list is matched up to the first ``)`` — enough to handle
# ``super().__init__(framework)``, ``super().__init__()``, and
# keyword-argument variants.
_SUPER_INIT_RE = re.compile(
    r"^(?P<indent>[ \t]*)super\(\)\.__init__\([^)]*\)[ \t]*\r?$",
    re.MULTILINE,
)


def _inject_ops_tracing_into_charm_py(content: str) -> str | None:
    """Return updated ``src/charm.py`` content with ops-tracing wired in.

    Inserts ``import ops_tracing`` after the first bare ``import ops`` line
    and ``ops_tracing.setup(self)`` (using the matched indent) after the
    first ``super().__init__(...)`` call.  Both anchors must match,
    otherwise returns ``None`` — partially patching a charm would leave the
    setup call without its import (or vice versa).  Callers that receive
    ``None`` should report a skip rather than writing back unchanged
    content.  Content that already contains ``ops_tracing`` is out of scope
    for this helper; the caller guards that case.
    """
    if not _IMPORT_OPS_RE.search(content):
        return None
    if not _SUPER_INIT_RE.search(content):
        return None

    patched = _IMPORT_OPS_RE.sub("import ops\nimport ops_tracing", content, count=1)

    def _add_setup(match: re.Match[str]) -> str:
        return f"{match.group(0)}\n{match.group('indent')}ops_tracing.setup(self)"

    patched = _SUPER_INIT_RE.sub(_add_setup, patched, count=1)
    return patched


_PRE_COMMIT_CONFIG = """\
repos:
  - repo: local
    hooks:
      - id: format
        name: format (ruff)
        entry: tox -e format
        language: system
        types: [python]
        pass_filenames: false
      - id: lint
        name: lint (ruff + pyright)
        entry: tox -e lint
        language: system
        types: [python]
        pass_filenames: false
      - id: unit
        name: unit tests
        entry: tox -e unit
        language: system
        types: [python]
        pass_filenames: false
"""


def _inject_pre_commit(target_path: Path) -> list[str]:
    """Set up pre-commit hooks that delegate to tox environments.

    Writes a ``.pre-commit-config.yaml`` that runs the ``format``, ``lint``,
    and ``unit`` tox environments on every commit, then runs ``pre-commit
    install`` if the binary is available.

    Returns a list of human-readable descriptions of what was done.
    """
    actions: list[str] = []

    config_path = target_path / ".pre-commit-config.yaml"
    if config_path.exists():
        actions.append(".pre-commit-config.yaml already exists — skipped")
        return actions

    tox_ini = target_path / "tox.ini"
    if not tox_ini.exists():
        actions.append("tox.ini not found — skipped pre-commit setup")
        return actions

    config_path.write_text(_PRE_COMMIT_CONFIG)
    actions.append("Created .pre-commit-config.yaml with format, lint, and unit hooks")

    if shutil.which("pre-commit"):
        try:
            subprocess.run(
                ["pre-commit", "install"],
                cwd=target_path,
                capture_output=True,
                timeout=30,
            )
            actions.append("Ran pre-commit install")
        except (subprocess.TimeoutExpired, OSError):
            actions.append("pre-commit install failed — run manually")
    else:
        actions.append("pre-commit not found on PATH — run 'pre-commit install' manually")

    return actions


# Minimum unit-test coverage percentage for generated charms.
_COVERAGE_THRESHOLD = 80


def _inject_coverage_threshold(target_path: Path) -> list[str]:
    """Add a ``fail_under`` threshold to the charm's coverage configuration.

    Reads the generated ``pyproject.toml``, locates (or creates) the
    ``[tool.coverage.report]`` section, and sets ``fail_under`` so that
    ``tox -e unit`` fails when coverage drops below the threshold.

    Returns a list of human-readable descriptions of what was done.
    """
    pyproject = target_path / "pyproject.toml"
    if not pyproject.exists():
        return ["pyproject.toml not found — skipped coverage threshold injection"]

    content = pyproject.read_text()

    # Already has fail_under — don't duplicate.
    if "fail_under" in content:
        return ["Coverage fail_under already configured in pyproject.toml"]

    if "[tool.coverage.report]" in content:
        content = content.replace(
            "[tool.coverage.report]",
            f"[tool.coverage.report]\nfail_under = {_COVERAGE_THRESHOLD}",
        )
    elif "[tool.coverage.run]" in content:
        # Has a run section but no report section — add one after it.
        # Append a report section at the end.
        content = content.rstrip("\n") + (
            f"\n\n[tool.coverage.report]\n"
            f"fail_under = {_COVERAGE_THRESHOLD}\n"
            f"show_missing = true\n"
        )
    else:
        # No coverage config at all — add both sections.
        content = content.rstrip("\n") + (
            f"\n\n[tool.coverage.run]\n"
            f"branch = true\n"
            f"\n[tool.coverage.report]\n"
            f"fail_under = {_COVERAGE_THRESHOLD}\n"
            f"show_missing = true\n"
        )

    pyproject.write_text(content)
    return [f"Set coverage fail_under = {_COVERAGE_THRESHOLD}% in pyproject.toml"]


class CharmcraftInitTool(Tool):
    """Tool to initialise a new charm with charmcraft."""

    @property
    def name(self) -> str:
        return "charmcraft_init"

    @property
    def description(self) -> str:
        return (
            "Initialise a new charm using charmcraft init. "
            "This creates the basic charm structure with src/charm.py, "
            "charmcraft.yaml, and test scaffolding."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the charm (e.g., 'my-app')",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to create the charm in",
                    "default": ".",
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "Charm profile. Use 'machine' or 'kubernetes' for custom charms, "
                        "or a framework profile for 12-factor apps."
                    ),
                    "enum": [
                        "machine",
                        "kubernetes",
                        "flask-framework",
                        "django-framework",
                        "fastapi-framework",
                        "go-framework",
                        "express-framework",
                        "spring-boot-framework",
                    ],
                    "default": "kubernetes",
                },
            },
            "required": ["name"],
        }

    async def execute(
        self,
        name: str,
        path: str = ".",
        profile: str = "kubernetes",
    ) -> ToolResult:
        """Run charmcraft init."""
        try:
            target_path = Path(path) / name
            target_path.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["charmcraft", "init", f"--profile={profile}", f"--name={name}"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft init failed",
                )

            # Ensure Cantrip-managed paths are in the charm's .gitignore.
            gitignore = target_path / ".gitignore"
            entries_to_add = [".cantrip", ".source/"]
            if gitignore.exists():
                content = gitignore.read_text()
                missing = [e for e in entries_to_add if e not in content]
                if missing:
                    gitignore.write_text(content.rstrip("\n") + "\n" + "\n".join(missing) + "\n")
            else:
                gitignore.write_text("\n".join(entries_to_add) + "\n")

            # Inject ops-tracing into the scaffolded charm.
            tracing_actions = _inject_ops_tracing(target_path, profile)

            # For PaaS profiles, guarantee ops + paas-charm are in
            # requirements.txt even if a prior step (or the agent) left
            # only the application's deps behind.
            paas_actions = _ensure_paas_requirements(target_path)

            # Set up pre-commit hooks delegating to tox environments.
            pre_commit_actions = _inject_pre_commit(target_path)

            # Ensure unit-test coverage has a fail_under threshold.
            coverage_actions = _inject_coverage_threshold(target_path)

            # Scaffold secure-by-default GitHub Actions workflows, Dependabot,
            # and SECURITY.md.
            workflow_actions = inject_github_workflows(target_path, name)

            post_init_summary = "\n".join(
                tracing_actions
                + paas_actions
                + pre_commit_actions
                + coverage_actions
                + workflow_actions
            )

            return ToolResult(
                success=True,
                output=(
                    f"Initialised charm '{name}' at {target_path}\n"
                    f"{result.stdout}\n{post_init_summary}"
                ),
                data={
                    "path": str(target_path),
                    "profile": profile,
                    "tracing_injected": True,
                    "pre_commit_installed": True,
                },
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft init timed out",
            )
        except (subprocess.SubprocessError, OSError, yaml.YAMLError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class CharmcraftPackTool(Tool):
    """Tool to pack a charm."""

    @property
    def name(self) -> str:
        return "charmcraft_pack"

    @property
    def description(self) -> str:
        return (
            "Pack the charm into a .charm file for deployment. "
            "Use destructive_mode=true for faster builds (builds locally "
            "instead of in an LXD container)."
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
                "destructive_mode": {
                    "type": "boolean",
                    "description": (
                        "Build locally instead of in an LXD container. "
                        "Much faster but requires build dependencies on the host."
                    ),
                    "default": False,
                },
            },
        }

    async def execute(self, path: str = ".", destructive_mode: bool = False) -> ToolResult:
        """Run charmcraft pack."""
        try:
            charm_path = Path(path).resolve()

            # Re-assert PaaS charm dependencies before packing.  The
            # agent has been observed overwriting the charm's
            # requirements.txt with the app's, which silently produces a
            # broken charm that crashes at install time.  Fixing this
            # here means ``charmcraft pack`` never ships a PaaS charm
            # without ``ops`` and ``paas-charm``.
            _ensure_paas_requirements(charm_path)

            cmd = ["charmcraft", "pack"]
            if destructive_mode:
                cmd.append("--destructive-mode")

            result = subprocess.run(
                cmd,
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=600,  # 12-factor charms need LXD builds
            )

            # Destructive mode may fail due to package install permissions.
            # Retry with sudo if the error mentions build-packages or permissions.
            if (
                destructive_mode
                and result.returncode != 0
                and (
                    "build packages" in (result.stderr or "").lower()
                    or "build-packages" in (result.stderr or "").lower()
                    or "permission" in (result.stderr or "").lower()
                )
            ):
                result = subprocess.run(
                    ["sudo"] + cmd,
                    cwd=charm_path,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                # Fix ownership of output files created by sudo.
                if result.returncode == 0:
                    import os

                    uid = os.getuid()
                    gid = os.getgid()
                    for charm_file in charm_path.glob("*.charm"):
                        os.chown(charm_file, uid, gid)

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft pack failed",
                )

            # Find the created .charm file
            charm_files = list(charm_path.glob("*.charm"))
            charm_file = charm_files[0] if charm_files else None

            return ToolResult(
                success=True,
                output=f"Packed charm successfully\n{result.stdout}",
                data={
                    "path": str(charm_path),
                    "charm_file": str(charm_file) if charm_file else None,
                },
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft pack timed out",
            )
        except (subprocess.SubprocessError, OSError, yaml.YAMLError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class CharmValidateTool(Tool):
    """Pre-completion validation: unit tests + charmcraft pack."""

    @property
    def name(self) -> str:
        return "charm_validate"

    @property
    def description(self) -> str:
        return (
            "Validate a charm before declaring it done. "
            "Runs unit tests and charmcraft pack, producing a pass/fail checklist. "
            "Call this before telling the user a charm is complete."
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
                "skip_tests": {
                    "type": "boolean",
                    "description": "Skip unit tests (only run charmcraft pack)",
                    "default": False,
                },
            },
        }

    async def execute(self, path: str = ".", skip_tests: bool = False) -> ToolResult:
        """Run unit tests and charmcraft pack, returning a checklist report."""
        charm_path = Path(path).resolve()
        if not charm_path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        # Step 1 — Unit tests (with coverage).
        tests_status = "skipped"
        tests_summary: dict[str, Any] = {}
        tests_detail = "skipped"
        coverage_pct: int | None = None
        coverage_detail = ""

        if not skip_tests:
            test_dir = charm_path / "tests" / "unit"
            if test_dir.is_dir():
                test_result = await RunCharmTestsTool().execute(
                    path=str(charm_path), test_type="unit"
                )
                tests_summary = test_result.data.get("summary", {})
                coverage_pct = test_result.data.get("coverage_pct")
                if test_result.success:
                    tests_status = "passed"
                    passed = tests_summary.get("passed", 0)
                    failed = tests_summary.get("failed", 0)
                    tests_detail = f"PASSED ({passed} passed, {failed} failed)"
                else:
                    tests_status = "failed"
                    passed = tests_summary.get("passed", 0)
                    failed = tests_summary.get("failed", 0)
                    tests_detail = f"FAILED ({passed} passed, {failed} failed)"

                if coverage_pct is not None:
                    if coverage_pct >= _COVERAGE_THRESHOLD:
                        coverage_detail = f"PASSED ({coverage_pct}%)"
                    else:
                        coverage_detail = f"LOW ({coverage_pct}%, target {_COVERAGE_THRESHOLD}%)"
                else:
                    coverage_detail = "not reported"
            else:
                tests_detail = "SKIPPED (no tests/unit/ directory)"

        # Step 2 — Charmcraft pack (always runs).
        pack_status = "failed"
        pack_charm_file: str | None = None

        pack_result = await CharmcraftPackTool().execute(path=str(charm_path))
        if pack_result.success:
            pack_status = "passed"
            pack_charm_file = pack_result.data.get("charm_file")
            charm_label = Path(pack_charm_file).name if pack_charm_file else "unknown"
            pack_detail = f"PASSED ({charm_label})"
        else:
            pack_detail = f"FAILED ({pack_result.error or 'unknown error'})"

        # Build report.
        overall = "passed" if tests_status != "failed" and pack_status == "passed" else "failed"

        report_lines = [
            "## Validation Report\n",
            f"- Unit tests: {tests_detail}",
        ]
        if coverage_detail:
            report_lines.append(f"- Coverage: {coverage_detail}")
        report_lines.append(f"- Charmcraft pack: {pack_detail}")
        report_lines.append(f"\nOverall: {overall.upper()}")
        report = "\n".join(report_lines)

        return ToolResult(
            success=overall == "passed",
            output=report,
            data={
                "tests": {"status": tests_status, "summary": tests_summary},
                "coverage": {"pct": coverage_pct, "threshold": _COVERAGE_THRESHOLD},
                "pack": {"status": pack_status, "charm_file": pack_charm_file},
                "overall": overall,
            },
        )


class QuickPackTool(Tool):
    """Fast local charm packing for development workflows."""

    @property
    def name(self) -> str:
        return "quick_pack"

    @property
    def description(self) -> str:
        return (
            "Pack a charm into a .charm file using the fast local packer. "
            "Much faster than charmcraft pack — skips LXD, linting, and "
            "analysis. Only supports charms using the uv plugin. "
            "Use this for initial deploys and upgrade testing."
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
                "output_dir": {
                    "type": "string",
                    "description": "Directory to write the .charm file to (default: charm dir)",
                },
            },
        }

    @staticmethod
    def _find_rust_binary() -> str | None:
        """Return the path to the Rust quickpack binary, or None."""
        # Check PATH first.
        rust_bin = shutil.which("quickpack-rs")
        if rust_bin:
            return rust_bin
        # Check the in-tree build location.
        import cantrip

        pkg_dir = Path(cantrip.__file__).resolve().parent
        candidate = pkg_dir.parent.parent / "quickpack-rs" / "target" / "release" / "quickpack"
        if candidate.is_file():
            return str(candidate)
        return None

    async def execute(self, path: str = ".", output_dir: str | None = None) -> ToolResult:
        """Run quick pack, preferring the Rust binary when available."""
        rust_bin = self._find_rust_binary()
        if rust_bin is not None:
            return self._execute_rust(rust_bin, path, output_dir)
        return self._execute_python(path, output_dir)

    def _execute_rust(self, binary: str, path: str, output_dir: str | None) -> ToolResult:
        """Pack using the compiled Rust binary."""
        charm_path = Path(path).resolve()
        cmd = [binary, str(charm_path), "--quiet"]
        if output_dir is not None:
            cmd.extend(["--output-dir", output_dir])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            # Binary disappeared between check and exec — fall back.
            return self._execute_python(path, output_dir)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="quickpack timed out")

        if result.returncode != 0:
            error = (result.stderr or result.stdout or "quickpack failed").strip()
            return ToolResult(success=False, output="", error=error)

        # Locate the produced .charm file.
        out = Path(output_dir) if output_dir else charm_path
        charm_files = sorted(out.glob("*.charm"))
        charm_file = charm_files[-1] if charm_files else None

        return ToolResult(
            success=True,
            output=f"Packed charm successfully (rust): {charm_file.name if charm_file else '?'}",
            data={
                "path": str(charm_path),
                "charm_file": str(charm_file) if charm_file else None,
                "backend": "rust",
            },
        )

    @staticmethod
    def _execute_python(path: str, output_dir: str | None) -> ToolResult:
        """Pack using the Python quickpack library."""
        try:
            from quickpack import pack as _pack

            charm_path = Path(path).resolve()
            kwargs: dict[str, Any] = {}
            if output_dir is not None:
                kwargs["output_dir"] = output_dir

            result_path = _pack.quick_pack(charm_path, **kwargs)

            return ToolResult(
                success=True,
                output=f"Packed charm successfully: {result_path.name}",
                data={
                    "path": str(charm_path),
                    "charm_file": str(result_path),
                    "backend": "python",
                },
            )
        except FileNotFoundError as e:
            return ToolResult(success=False, output="", error=str(e))
        except (ValueError, RuntimeError, OSError) as e:
            return ToolResult(success=False, output="", error=str(e))
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            return ToolResult(
                success=False,
                output=e.stdout or "",
                error=f"Command failed: {e.cmd}\n{stderr}",
            )


class CharmcraftFetchLibsTool(Tool):
    """Tool to fetch charm libraries."""

    @property
    def name(self) -> str:
        return "charmcraft_fetch_libs"

    @property
    def description(self) -> str:
        return "Fetch charm libraries defined in charmcraft.yaml."

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
        """Run charmcraft fetch-libs."""
        try:
            charm_path = Path(path).resolve()

            result = subprocess.run(
                ["charmcraft", "fetch-libs"],
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft fetch-libs failed",
                )

            return ToolResult(
                success=True,
                output=f"Fetched libraries\n{result.stdout}",
                data={"path": str(charm_path)},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft fetch-libs timed out",
            )
        except (subprocess.SubprocessError, OSError, yaml.YAMLError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class AnalyseFrameworkTool(Tool):
    """Tool to analyse a codebase and detect its framework."""

    @property
    def name(self) -> str:
        return "analyse_framework"

    @property
    def description(self) -> str:
        return (
            "Analyse a codebase to detect its framework "
            "(Flask, Django, FastAPI, Go, Express, Spring Boot, etc.) "
            "and gather information for charm creation. Returns a profile name "
            "suitable for charmcraft_init and rockcraft_init."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the application codebase",
                },
            },
            "required": ["path"],
        }

    # Maps framework name to its charmcraft/rockcraft profile.
    _PROFILE_MAP: dict[str, str] = {
        "flask": "flask-framework",
        "django": "django-framework",
        "fastapi": "fastapi-framework",
        "go": "go-framework",
        "express": "express-framework",
        "spring-boot": "spring-boot-framework",
    }

    # Frameworks requiring ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS.
    _EXPERIMENTAL_FRAMEWORKS: frozenset[str] = frozenset({"go", "fastapi", "express"})

    async def execute(self, path: str) -> ToolResult:
        """Analyse the codebase."""
        try:
            app_path = Path(path).resolve()
            if not app_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path not found: {path}",
                )

            findings: dict[str, Any] = {
                "framework": None,
                "language": None,
                "profile": None,
                "needs_experimental": False,
                "files_found": [],
                "suggestions": [],
            }

            paas_hint = (
                "Use 12-factor paas-charm base. "
                "Load the 'twelve-factor' skill for step-by-step instructions."
            )

            # Check for Python frameworks.
            requirements = app_path / "requirements.txt"
            pyproject = app_path / "pyproject.toml"
            setup_py = app_path / "setup.py"

            python_deps = ""
            if requirements.exists():
                findings["files_found"].append("requirements.txt")
                python_deps = requirements.read_text().lower()
            if pyproject.exists():
                findings["files_found"].append("pyproject.toml")
                python_deps += pyproject.read_text().lower()
            if setup_py.exists():
                findings["files_found"].append("setup.py")

            if python_deps:
                findings["language"] = "python"
                if "flask" in python_deps:
                    findings["framework"] = "flask"
                    findings["suggestions"].append(paas_hint)
                elif "django" in python_deps:
                    findings["framework"] = "django"
                    findings["suggestions"].append(paas_hint)
                elif "fastapi" in python_deps:
                    findings["framework"] = "fastapi"
                    findings["suggestions"].append(paas_hint)

            # Check for Go.
            go_mod = app_path / "go.mod"
            if go_mod.exists():
                findings["files_found"].append("go.mod")
                findings["language"] = "go"
                findings["framework"] = "go"
                findings["suggestions"].append(paas_hint)

            # Check for Node.js / Express.
            package_json = app_path / "package.json"
            if package_json.exists():
                findings["files_found"].append("package.json")
                findings["language"] = "javascript"
                pkg_content = package_json.read_text().lower()
                if "express" in pkg_content:
                    findings["framework"] = "express"
                    findings["suggestions"].append(paas_hint)

            # Check for Spring Boot (Maven or Gradle).
            pom_xml = app_path / "pom.xml"
            build_gradle = app_path / "build.gradle"
            build_gradle_kts = app_path / "build.gradle.kts"

            for java_file in (pom_xml, build_gradle, build_gradle_kts):
                if java_file.exists():
                    findings["files_found"].append(java_file.name)
                    java_content = java_file.read_text().lower()
                    if (
                        "spring-boot" in java_content
                        or "spring.boot" in java_content
                        or "springframework" in java_content
                    ):
                        findings["language"] = "java"
                        findings["framework"] = "spring-boot"
                        findings["suggestions"].append(paas_hint)
                        break

            # Map framework to profile.
            framework = findings["framework"]
            if framework and framework in self._PROFILE_MAP:
                findings["profile"] = self._PROFILE_MAP[framework]
                findings["needs_experimental"] = framework in self._EXPERIMENTAL_FRAMEWORKS

            # --- Custom workload hints (when no PaaS framework was detected) ---
            workload_hints: dict[str, Any] = {
                "has_dockerfile": False,
                "has_docker_compose": False,
                "has_systemd": False,
                "has_config_files": False,
                "suggested_substrate": None,
            }

            dockerfile = app_path / "Dockerfile"
            if dockerfile.exists():
                findings["files_found"].append("Dockerfile")
                workload_hints["has_dockerfile"] = True

            for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
                compose_file = app_path / compose_name
                if compose_file.exists():
                    findings["files_found"].append(compose_name)
                    workload_hints["has_docker_compose"] = True
                    break

            # Look for systemd .service files in the repo root or common locations.
            service_locations = [app_path] + [
                app_path / d for d in ("systemd", "contrib", "deploy", "packaging")
            ]
            for location in service_locations:
                if location.is_dir() and list(location.glob("*.service")):
                    workload_hints["has_systemd"] = True
                    break

            # Check for common config file patterns.
            config_patterns = [
                "config.yaml",
                "config.yml",
                "config.json",
                "config.toml",
                ".env.example",
                ".env.sample",
                "settings.yaml",
                "settings.yml",
            ]
            for pattern in config_patterns:
                if (app_path / pattern).exists():
                    workload_hints["has_config_files"] = True
                    break

            # Suggest a substrate when no PaaS framework was detected.
            if not findings["framework"]:
                if workload_hints["has_systemd"]:
                    workload_hints["suggested_substrate"] = "machine"
                elif workload_hints["has_dockerfile"] or workload_hints["has_docker_compose"]:
                    workload_hints["suggested_substrate"] = "k8s"

                findings["suggestions"].append(
                    "No recognised PaaS framework. "
                    "Load the 'custom-charm' skill for the step-by-step custom charm workflow."
                )

            findings["workload_hints"] = workload_hints

            # Check for existing charm structure.
            charmcraft_yaml = app_path / "charmcraft.yaml"
            if charmcraft_yaml.exists():
                findings["files_found"].append("charmcraft.yaml")
                findings["suggestions"].append("Existing charm found - will modify")

            # Build output.
            output_lines = []
            if findings["language"]:
                output_lines.append(f"Language: {findings['language']}")
            if findings["framework"]:
                output_lines.append(f"Framework: {findings['framework']}")
            if findings["profile"]:
                output_lines.append(f"Profile: {findings['profile']}")
            if findings["needs_experimental"]:
                output_lines.append("Note: requires ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS")
            if findings["files_found"]:
                output_lines.append(f"Files found: {', '.join(findings['files_found'])}")
            if findings["suggestions"]:
                output_lines.append(f"Suggestions: {'; '.join(findings['suggestions'])}")

            if not output_lines:
                output_lines.append("Could not detect framework. Manual configuration needed.")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data=findings,
            )
        except (subprocess.SubprocessError, OSError, yaml.YAMLError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class GenerateTerraformTool(Tool):
    """Generate a Terraform module for a Juju charm."""

    @property
    def name(self) -> str:
        return "generate_terraform"

    @property
    def description(self) -> str:
        return (
            "Generate a Terraform module (main.tf, variables.tf, outputs.tf, "
            "terraform.tf) from a charm's charmcraft.yaml. Creates a terraform/ "
            "directory in the charm path."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "charm_path": {
                    "type": "string",
                    "description": ("Path to the charm directory containing charmcraft.yaml"),
                },
            },
            "required": ["charm_path"],
        }

    async def execute(self, charm_path: str) -> ToolResult:
        """Generate Terraform module files from a charm's charmcraft.yaml."""
        charm_dir = Path(charm_path).resolve()
        charmcraft_yaml = charm_dir / "charmcraft.yaml"

        if not charmcraft_yaml.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"charmcraft.yaml not found at {charm_dir}",
            )

        try:
            files = terraform.generate_terraform_module(charmcraft_yaml)
        except (KeyError, TypeError, yaml.YAMLError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse charmcraft.yaml: {exc}",
            )

        tf_dir = charm_dir / "terraform"
        tf_dir.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        for filename, content in files.items():
            (tf_dir / filename).write_text(content)
            written.append(filename)

        summary = (
            f"Generated Terraform module in {tf_dir}\nFiles written: {', '.join(sorted(written))}"
        )
        return ToolResult(
            success=True,
            output=summary,
            data={"terraform_path": str(tf_dir), "files": sorted(written)},
        )


class ValidateTerraformTool(Tool):
    """Validate a Terraform module."""

    @property
    def name(self) -> str:
        return "validate_terraform"

    @property
    def description(self) -> str:
        return (
            "Run terraform fmt --check and terraform validate on a Terraform "
            "module directory. Requires terraform CLI to be installed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "terraform_path": {
                    "type": "string",
                    "description": "Path to the terraform directory",
                },
            },
            "required": ["terraform_path"],
        }

    async def execute(self, terraform_path: str) -> ToolResult:
        """Run terraform fmt --check and terraform validate."""
        if not shutil.which("terraform"):
            return ToolResult(
                success=True,
                output="terraform CLI not installed — skipping validation.",
                data={"skipped": True},
            )

        tf_dir = Path(terraform_path).resolve()
        if not tf_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {terraform_path}",
            )

        # Step 1: terraform fmt --check.
        fmt_result = subprocess.run(
            ["terraform", "fmt", "--check"],
            cwd=tf_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Step 2: terraform init -backend=false.
        init_result = subprocess.run(
            ["terraform", "init", "-backend=false"],
            cwd=tf_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if init_result.returncode != 0:
            return ToolResult(
                success=False,
                output=init_result.stdout,
                error=f"terraform init failed: {init_result.stderr}",
            )

        # Step 3: terraform validate.
        validate_result = subprocess.run(
            ["terraform", "validate"],
            cwd=tf_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        fmt_ok = fmt_result.returncode == 0
        validate_ok = validate_result.returncode == 0
        overall = fmt_ok and validate_ok

        output_parts: list[str] = []
        if fmt_ok:
            output_parts.append("fmt: PASSED")
        else:
            output_parts.append(f"fmt: FAILED\n{fmt_result.stdout}")
        if validate_ok:
            output_parts.append("validate: PASSED")
        else:
            output_parts.append(
                f"validate: FAILED\n{validate_result.stderr or validate_result.stdout}"
            )

        return ToolResult(
            success=overall,
            output="\n".join(output_parts),
            data={"fmt_ok": fmt_ok, "validate_ok": validate_ok},
        )
