"""Rock-fit validators for the 12-factor PaaS framework extensions.

The per-framework checks here are derived from the canonical/skills
repository:
``skills/engineering/12factor-rock/scripts/check_rock_contract.py``
(PR #4, https://github.com/canonical/skills/pull/4), Apache-2.0 licensed.

Adapted for Cantrip: ``express`` is used everywhere instead of upstream
``expressjs``; the ``tomli`` fallback is dropped (Python 3.12+); the
shared dep-parsing helpers are reused from
:mod:`cantrip.agent.tools.framework_detection` so the dep-extraction
logic lives in exactly one place.

The helper exposed here, :func:`check_rock_contract`, is a pure
function: no subprocess, no network, only filesystem reads against the
given repo path.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from typing import Any

from cantrip.agent.tools.framework_detection import (
    parse_pyproject,
    parse_requirements,
    python_entrypoint_candidates,
)

# Per-framework list of supported ``base:`` values for the rock.  Sourced
# verbatim from the upstream check (FastAPI / Go / Express / Spring Boot
# are still experimental and only support ``bare`` + ``ubuntu@24.04``).
SUPPORTED_BASES: dict[str, list[str]] = {
    "flask": ["bare", "ubuntu@22.04", "ubuntu:22.04", "ubuntu@24.04"],
    "django": ["bare", "ubuntu@22.04", "ubuntu:22.04", "ubuntu@24.04"],
    "fastapi": ["bare", "ubuntu@24.04"],
    "express": ["bare", "ubuntu@24.04"],
    "go": ["bare", "ubuntu@24.04"],
    "spring-boot": ["bare", "ubuntu@24.04"],
}

# Frameworks the upstream contract validator knows how to check.
SUPPORTED_FRAMEWORKS: frozenset[str] = frozenset(SUPPORTED_BASES)


@dataclasses.dataclass(frozen=True)
class RockContractReport:
    """Outcome of running :func:`check_rock_contract` on a repo."""

    framework: str
    fit: bool
    issues: list[str]
    warnings: list[str]
    supported_bases: list[str]


class UnknownFrameworkError(ValueError):
    """Raised when ``check_rock_contract`` is called with an unsupported framework."""


def check_rock_contract(repo: pathlib.Path, framework: str) -> RockContractReport:
    """Validate that *repo* fits the rock contract for *framework*.

    ``fit`` is ``True`` when no blocking issues were found.  Warnings
    are advisory — a fitting repo can still produce warnings (e.g. Go
    cmd directory naming) and a non-fitting repo can still produce
    none beyond the issues themselves.
    """
    if framework not in _CHECKS:
        raise UnknownFrameworkError(
            f"Unknown framework {framework!r}; supported: {sorted(SUPPORTED_FRAMEWORKS)}"
        )
    issues, warnings = _CHECKS[framework](repo)
    return RockContractReport(
        framework=framework,
        fit=not issues,
        issues=issues,
        warnings=warnings,
        supported_bases=list(SUPPORTED_BASES[framework]),
    )


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _normalise_name(name: str) -> str:
    return name.replace("-", "_").lower()


def _has_pattern(path: pathlib.Path, pattern: str) -> bool:
    if not path.exists():
        return False
    return re.search(pattern, _read_text(path), re.MULTILINE) is not None


def _python_project_metadata_warnings(repo: pathlib.Path) -> list[str]:
    """Warnings that apply to any Python framework's rock contract."""
    warnings: list[str] = []
    has_metadata = (repo / "pyproject.toml").exists() or (repo / "setup.py").exists()
    if has_metadata:
        warnings.append(
            "Python plugin will try to install the local project; validate "
            "`pip install .` during execution."
        )
    if has_metadata and (repo / "charm").exists():
        warnings.append(
            "`pyproject.toml` or `setup.py` plus `charm/` can break Craft "
            "Python plugin metadata discovery; preflight this before build."
        )
    return warnings


def _check_flask(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings = _python_project_metadata_warnings(repo)
    deps = parse_requirements(repo) | parse_pyproject(repo)
    if "flask" not in deps:
        issues.append("Flask dependency not found in requirements.txt or pyproject.toml.")
    project = _normalise_name(repo.name)
    if not any(
        _has_pattern(repo / candidate, r"\bFlask\s*\(")
        or _has_pattern(repo / candidate, r"\b(create_app|make_app)\s*\(")
        or _has_pattern(repo / candidate, r"^\s*(app|application)\s*=")
        for candidate in python_entrypoint_candidates(project)
    ):
        issues.append(
            "No supported Flask WSGI entrypoint was found in the default search locations."
        )
    return issues, warnings


def _check_django(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings = _python_project_metadata_warnings(repo)
    if not (repo / "requirements.txt").exists():
        issues.append("Django rock requires a root requirements.txt.")
    project = _normalise_name(repo.name)
    wsgi_paths = (
        repo / project / project / "wsgi.py",
        repo / project / "mysite" / "wsgi.py",
    )
    if not any(_has_pattern(path, r"\bapplication\b") for path in wsgi_paths):
        issues.append("No supported Django wsgi.py with `application` was found.")
        warnings.append(
            "Django extension expects the runtime app under <repo>/<project-name>/ "
            "with either <project-name>/wsgi.py or mysite/wsgi.py."
        )
    return issues, warnings


def _check_fastapi(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings = _python_project_metadata_warnings(repo)
    deps = parse_requirements(repo) | parse_pyproject(repo)
    if not deps:
        issues.append(
            "FastAPI rock requires a root requirements.txt or pyproject.toml with dependencies."
        )
    elif not {"fastapi", "starlette"} & deps:
        issues.append("Python metadata must include fastapi or starlette.")
    project = _normalise_name(repo.name)
    if not any(
        _has_pattern(repo / candidate, r"^\s*app\s*=")
        for candidate in python_entrypoint_candidates(project)
    ):
        issues.append(
            "No supported FastAPI ASGI `app` object was found in the default search locations."
        )
    return issues, warnings


def _check_express(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    package_json = repo / "app" / "package.json"
    if not package_json.exists():
        issues.append("Express rock requires app/package.json.")
        return issues, warnings
    try:
        package = json.loads(_read_text(package_json))
    except json.JSONDecodeError:
        issues.append("app/package.json is not valid JSON.")
        return issues, warnings
    if not isinstance(package, dict):
        issues.append("app/package.json must be a JSON object.")
        return issues, warnings
    if not package.get("name"):
        issues.append("package.json must define `name`.")
    if not package.get("scripts", {}).get("start"):
        issues.append("package.json must define `scripts.start`.")
    warnings.append(
        "Verify the app really wants to run from /app with `npm start` before proceeding."
    )
    return issues, warnings


_GO_MODULE_RE = re.compile(r"^\s*module\s+(\S+)\s*$")


def _parse_go_module_name(repo: pathlib.Path) -> str | None:
    go_mod = repo / "go.mod"
    if not go_mod.exists():
        return None
    for line in _read_text(go_mod).splitlines():
        match = _GO_MODULE_RE.match(line)
        if match:
            return match.group(1)
    return None


def _find_go_cmd_dirs(repo: pathlib.Path) -> list[str]:
    cmd_root = repo / "cmd"
    if not cmd_root.exists():
        return []
    return sorted(
        str(path.relative_to(repo))
        for path in cmd_root.iterdir()
        if path.is_dir() and any(child.suffix == ".go" for child in path.rglob("*.go"))
    )


def _check_go(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    if not (repo / "go.mod").exists():
        issues.append("Go rock requires go.mod in the repository root.")
        return issues, warnings

    module_name = _parse_go_module_name(repo)
    cmd_dirs = _find_go_cmd_dirs(repo)
    rock_name = repo.name
    if cmd_dirs:
        warnings.append(f"Detected Go main-package directories: {', '.join(cmd_dirs)}.")
    if module_name:
        warnings.append(f"Detected Go module path: {module_name}.")
    if cmd_dirs and all(pathlib.Path(path).name != rock_name for path in cmd_dirs):
        warnings.append(
            "No cmd/* directory matches the rock name; if you override the "
            "service command, add an explicit go-framework/install-app.organize "
            "mapping."
        )
    else:
        warnings.append(
            "If the built binary name differs from the rock name, adjust "
            "organize in go-framework/install-app."
        )
    return issues, warnings


def _check_spring_boot(repo: pathlib.Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    pom = repo / "pom.xml"
    gradle = repo / "build.gradle"
    gradle_kts = repo / "build.gradle.kts"
    mvnw = repo / "mvnw"
    gradlew = repo / "gradlew"
    has_gradle = gradle.exists() or gradle_kts.exists()
    if pom.exists() and has_gradle:
        issues.append(
            "Spring Boot extension rejects repositories that expose both "
            "pom.xml and build.gradle (or build.gradle.kts)."
        )
    if mvnw.exists() and gradlew.exists():
        issues.append(
            "Spring Boot extension rejects repositories that expose both mvnw and gradlew."
        )
    if not pom.exists() and not has_gradle:
        issues.append(
            "Spring Boot extension requires pom.xml or build.gradle (or build.gradle.kts)."
        )
    for wrapper in (mvnw, gradlew):
        if wrapper.exists() and not wrapper.stat().st_mode & 0o111:
            issues.append(f"{wrapper.name} exists but is not executable.")
    warnings.append(
        "If both Maven and Gradle exist in upstream, ask the user which build "
        "path to keep in the trial copy."
    )
    return issues, warnings


_CHECKS: dict[str, Any] = {
    "flask": _check_flask,
    "django": _check_django,
    "fastapi": _check_fastapi,
    "express": _check_express,
    "go": _check_go,
    "spring-boot": _check_spring_boot,
}
