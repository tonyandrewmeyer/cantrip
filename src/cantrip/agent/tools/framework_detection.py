"""Framework-detection helpers for the analyse_framework tool.

The scoring algorithm and web-fit signal collection here are derived
from the canonical/skills repository:
``skills/engineering/12factor-fit/scripts/detect_framework.py`` (PR #4,
https://github.com/canonical/skills/pull/4), Apache-2.0 licensed.

Adapted for Cantrip: dropped the ``tomli`` fallback (Python 3.12+),
restructured for module-style imports, and split into pure helpers so
``AnalyseFrameworkTool`` can call them without spawning a subprocess.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import pathlib
import re
import tomllib
from typing import Any

# Suffixes scanned when collecting web-fit signals.  Restricted so the
# walk stays fast on large monorepos — the upstream uses the same set.
_SOURCE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".kt",
        ".properties",
        ".yml",
        ".yaml",
    }
)

# Per-framework source-pattern regexes used to confirm a route or
# controller signal once a candidate framework has been picked.
_ROUTE_PATTERNS: dict[str, tuple[str, ...]] = {
    "django": (r"\burlpatterns\b", r"\bpath\s*\(", r"\bre_path\s*\("),
    "expressjs": (
        r"\bapp\.(get|post|put|patch|delete|use)\s*\(",
        r"\brouter\.(get|post|put|patch|delete|use)\s*\(",
    ),
    "fastapi": (r"@(app|router)\.(get|post|put|patch|delete)\s*\(",),
    "flask": (r"@app\.route\s*\(", r"\bFlask\s*\("),
    "go": (
        r"\bhttp\.Handle(Func)?\s*\(",
        r"\bgin\.(Default|New)\s*\(",
        r"\brouter\.(GET|POST|PUT|PATCH|DELETE)\s*\(",
    ),
    "spring-boot": (
        r"@(RestController|Controller)\b",
        r"@(Get|Post|Put|Delete|Request)Mapping\b",
    ),
}

# Cross-framework patterns that suggest the workload binds an HTTP
# port — independent of the specific framework signals above.
_LISTEN_PATTERNS: tuple[str, ...] = (
    r"\blisten\s*\(",
    r"\bPORT\b",
    r"\bSERVER_PORT\b",
    r"\bUVICORN_PORT\b",
)

# Minimum score for a framework to count as confidently detected.
# A bare ``package.json`` (no ``express`` dep) scores 2 in the upstream
# algorithm, which would mislabel a Next.js or Vite app as Express;
# requiring 3 keeps the strong signals (deps, go.mod, pom.xml mention,
# manage.py) without picking up that noise.
_MIN_DETECTION_SCORE = 3


@dataclasses.dataclass(frozen=True)
class FrameworkDetection:
    """Result of running :func:`detect_frameworks` on a repo."""

    detected: str | None
    candidates: list[dict[str, Any]]
    web_app_guess: bool
    web_app_signals_positive: list[str]
    web_app_signals_negative: list[str]
    notes: list[str]


def detect_frameworks(repo: pathlib.Path) -> FrameworkDetection:
    """Score known frameworks against *repo* and pick the best fit.

    Returns the top candidate (or ``None`` when nothing scored), the
    full ranked candidate list, and web-app-fit signals collected
    against the chosen framework.  Pure: no subprocess, no network.
    """
    results = _score_frameworks(repo)
    ordered = sorted(
        ({"framework": framework, **details} for framework, details in results.items()),
        key=lambda item: (-int(item["score"]), str(item["framework"])),
    )
    detected = (
        str(ordered[0]["framework"])
        if ordered and int(ordered[0]["score"]) >= _MIN_DETECTION_SCORE
        else None
    )
    positive, negative = _collect_web_signals(repo, detected)
    web_app_guess = bool(detected and positive)

    notes: list[str] = []
    if not detected:
        notes.append("No supported framework was confidently detected.")
    elif not positive:
        notes.append(
            "Framework detected, but web-service confidence is low. "
            "Confirm manually before proceeding."
        )
    notes.extend(negative)

    return FrameworkDetection(
        detected=detected,
        candidates=ordered,
        web_app_guess=web_app_guess,
        web_app_signals_positive=positive,
        web_app_signals_negative=negative,
        notes=notes,
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


def _parse_requirement_file(path: pathlib.Path, visited: set[pathlib.Path]) -> set[str]:
    deps: set[str] = set()
    if path in visited or not path.exists():
        return deps
    visited.add(path)
    for raw_line in _read_text(path).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            include = line.split(maxsplit=1)[1].strip()
            deps |= _parse_requirement_file(
                (path.parent / include).resolve(),
                visited,
            )
            continue
        if line.startswith(("-", "git+", "http:", "https:")):
            continue
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower().replace("_", "-")
        if name:
            deps.add(name)
    return deps


def _parse_requirements(repo: pathlib.Path) -> set[str]:
    return _parse_requirement_file((repo / "requirements.txt").resolve(), set())


def _parse_pyproject(repo: pathlib.Path) -> set[str]:
    deps: set[str] = set()
    path = repo / "pyproject.toml"
    if not path.exists():
        return deps
    try:
        data = tomllib.loads(_read_text(path))
    except tomllib.TOMLDecodeError:
        return deps
    for item in data.get("project", {}).get("dependencies", []):
        name = re.split(r"[<>=!~\[]", str(item), maxsplit=1)[0].strip().lower().replace("_", "-")
        if name:
            deps.add(name)
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if isinstance(poetry, dict):
        for name in poetry:
            lowered = str(name).strip().lower().replace("_", "-")
            if lowered and lowered != "python":
                deps.add(lowered)
    return deps


def _score_frameworks(repo: pathlib.Path) -> dict[str, dict[str, Any]]:
    scores: dict[str, int] = collections.defaultdict(int)
    signals: dict[str, list[str]] = collections.defaultdict(list)

    deps = _parse_requirements(repo) | _parse_pyproject(repo)
    project_name = _normalise_name(repo.name)

    def add(framework: str, score: int, signal: str) -> None:
        scores[framework] += score
        signals[framework].append(signal)

    if (repo / "go.mod").exists():
        add("go", 5, "found go.mod")

    for package_rel, base_score in (
        (pathlib.Path("app/package.json"), 3),
        (pathlib.Path("package.json"), 2),
    ):
        package_path = repo / package_rel
        if not package_path.exists():
            continue
        try:
            package = json.loads(_read_text(package_path))
        except json.JSONDecodeError:
            package = {}
        add("expressjs", base_score, f"found {package_rel}")
        if isinstance(package, dict):
            if package.get("name"):
                add("expressjs", 1, f"{package_rel} defines name")
            if package.get("scripts", {}).get("start"):
                add("expressjs", 2, f"{package_rel} defines scripts.start")
            package_deps = {
                *package.get("dependencies", {}).keys(),
                *package.get("devDependencies", {}).keys(),
            }
            if "express" in package_deps:
                add("expressjs", 2, f"{package_rel} depends on express")

    if any(
        (repo / file).exists()
        for file in ("pom.xml", "build.gradle", "build.gradle.kts", "mvnw", "gradlew")
    ):
        add("spring-boot", 3, "found Java build files or wrappers")
        for build_file in ("pom.xml", "build.gradle", "build.gradle.kts"):
            path = repo / build_file
            if not path.exists():
                continue
            text = _read_text(path)
            # Both the kebab-case ``spring-boot`` (Maven, Gradle Groovy
            # DSL) and the dotted ``springframework.boot`` (Kotlin DSL,
            # Spring Initializr output) count as evidence.
            if "spring-boot" in text or "springframework.boot" in text:
                add("spring-boot", 2, f"{build_file} mentions spring-boot")

    if "django" in deps:
        add("django", 4, "Python metadata includes django")
    if (repo / "manage.py").exists():
        add("django", 3, "found manage.py")
    for rel in (
        pathlib.Path(project_name) / project_name / "wsgi.py",
        pathlib.Path(project_name) / "mysite" / "wsgi.py",
    ):
        if _has_pattern(repo / rel, r"\bapplication\b"):
            add("django", 2, f"found Django wsgi entrypoint at {rel}")

    if "flask" in deps:
        add("flask", 4, "Python metadata includes flask")
    for rel in _python_entrypoint_candidates(project_name):
        path = repo / rel
        if not path.exists():
            continue
        if _has_pattern(path, r"\bFlask\s*\(") or _has_pattern(
            path, r"\b(create_app|make_app)\s*\("
        ):
            add("flask", 2, f"found Flask entrypoint signal at {rel}")
            break

    if {"fastapi", "starlette"} & deps:
        add("fastapi", 4, "Python metadata includes fastapi or starlette")
    for rel in _python_entrypoint_candidates(project_name):
        path = repo / rel
        if not path.exists():
            continue
        text = _read_text(path)
        if re.search(r"^\s*app\s*=", text, re.MULTILINE) and (
            "FastAPI" in text or "Starlette" in text
        ):
            add("fastapi", 2, f"found ASGI app signal at {rel}")
            break

    return {
        framework: {"score": score, "signals": signals[framework]}
        for framework, score in scores.items()
    }


def _python_entrypoint_candidates(project_name: str) -> tuple[pathlib.Path, ...]:
    """Return the standard list of paths that hold a Python web-app entrypoint."""
    return (
        pathlib.Path("app.py"),
        pathlib.Path("main.py"),
        pathlib.Path("app") / "__init__.py",
        pathlib.Path("app") / "app.py",
        pathlib.Path("app") / "main.py",
        pathlib.Path("src") / "__init__.py",
        pathlib.Path("src") / "app.py",
        pathlib.Path("src") / "main.py",
        pathlib.Path(project_name) / "__init__.py",
        pathlib.Path(project_name) / "app.py",
        pathlib.Path(project_name) / "main.py",
    )


def _collect_web_signals(
    repo: pathlib.Path,
    framework: str | None,
) -> tuple[list[str], list[str]]:
    if not framework:
        return [], []

    positive: list[str] = []
    negative: list[str] = []

    procfile = repo / "Procfile"
    if procfile.exists() and re.search(r"^\s*web\s*:", _read_text(procfile), re.MULTILINE):
        positive.append("Procfile declares a web process")

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        text = _read_text(pyproject)
        if re.search(r"(?m)^\s*\[project\.scripts\]\s*$", text) or re.search(
            r"console_scripts", text
        ):
            negative.append("pyproject.toml exposes console-style entry points")

    framework_patterns = _ROUTE_PATTERNS.get(framework, ())
    found_route_signal = False
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        content = _read_text(path)
        if any(re.search(p, content, re.MULTILINE) for p in framework_patterns):
            positive.append(f"route or controller signal in {path.relative_to(repo)}")
            found_route_signal = True
            break

    if not found_route_signal and framework == "django" and (repo / "manage.py").exists():
        positive.append("manage.py suggests a Django web project")

    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        if any(re.search(pattern, _read_text(path), re.MULTILINE) for pattern in _LISTEN_PATTERNS):
            positive.append(f"listen-port signal in {path.relative_to(repo)}")
            break

    return positive, negative
