"""Charm scaffolding and management tools."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.testing import RunCharmTestsTool

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
        changed = False

        if "ops_tracing" not in content:
            # Insert ``import ops_tracing`` after ``import ops``.
            if "import ops" in content:
                content = content.replace("import ops\n", "import ops\nimport ops_tracing\n", 1)
                changed = True

            # Insert ``ops_tracing.setup(self)`` after the super().__init__ call.
            if "super().__init__(framework)" in content:
                content = content.replace(
                    "super().__init__(framework)",
                    "super().__init__(framework)\n        ops_tracing.setup(self)",
                    1,
                )
                changed = True

            if changed:
                charm_py.write_text(content)
                actions.append("Injected ops_tracing import and setup into src/charm.py")
            else:
                actions.append(
                    "src/charm.py did not match expected patterns — skipped ops-tracing"
                )
        else:
            actions.append("src/charm.py already contains ops_tracing — skipped")
    else:
        actions.append("src/charm.py not found — skipped ops-tracing injection")

    return actions


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
        subprocess.run(
            ["pre-commit", "install"],
            cwd=target_path,
            capture_output=True,
            timeout=30,
        )
        actions.append("Ran pre-commit install")
    else:
        actions.append("pre-commit not found on PATH — run 'pre-commit install' manually")

    return actions


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

            # Set up pre-commit hooks delegating to tox environments.
            pre_commit_actions = _inject_pre_commit(target_path)

            post_init_summary = "\n".join(tracing_actions + pre_commit_actions)

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
        except Exception as e:
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
        return "Pack the charm into a .charm file for deployment."

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
        """Run charmcraft pack."""
        try:
            charm_path = Path(path).resolve()

            result = subprocess.run(
                ["charmcraft", "pack"],
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=600,  # 12-factor charms need LXD builds
            )

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
        except Exception as e:
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

        # Step 1 — Unit tests.
        tests_status = "skipped"
        tests_summary: dict[str, Any] = {}
        tests_detail = "skipped"

        if not skip_tests:
            test_dir = charm_path / "tests" / "unit"
            if test_dir.is_dir():
                test_result = await RunCharmTestsTool().execute(
                    path=str(charm_path), test_type="unit"
                )
                tests_summary = test_result.data.get("summary", {})
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

        report = (
            "## Validation Report\n\n"
            f"- Unit tests: {tests_detail}\n"
            f"- Charmcraft pack: {pack_detail}\n\n"
            f"Overall: {overall.upper()}"
        )

        return ToolResult(
            success=overall == "passed",
            output=report,
            data={
                "tests": {"status": tests_status, "summary": tests_summary},
                "pack": {"status": pack_status, "charm_file": pack_charm_file},
                "overall": overall,
            },
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
        except Exception as e:
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
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
