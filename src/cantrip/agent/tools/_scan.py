"""Deterministic codebase pre-scan for Path B discovery.

The detection tables in this module are ported from the ``scan.py``
helper of the ``acquire-codebase-knowledge`` skill in
``github/awesome-copilot`` (MIT licence, Copyright GitHub, Inc.):

  https://github.com/github/awesome-copilot/blob/main/skills/acquire-codebase-knowledge/scripts/scan.py

Charm-specific additions (``charmcraft.yaml`` / ``rockcraft.yaml`` /
``.cantrip`` detection, workload-hint extras, and the ``ScanResult``
shape) are Cantrip-local work that the upstream version does not
cover.
"""

from __future__ import annotations

import collections
import dataclasses
import os
import pathlib
import subprocess
from typing import Any

from cantrip.agent.tools.framework_detection import detect_frameworks

# ---------------------------------------------------------------------------
# Detection tables — ported from awesome-copilot scan.py + Cantrip extensions.
# ---------------------------------------------------------------------------

# Directories that should never contribute to the scan: build
# artefacts, package caches, vendored dependencies, IDE metadata.
# The upstream list plus Cantrip-specific additions
# (.cantrip-worktrees, .cantrip SQLite directory if materialised).
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        # Upstream (awesome-copilot scan.py).
        "node_modules",
        ".git",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        "target",
        "vendor",
        "coverage",
        ".nyc_output",
        "generated",
        ".cache",
        ".turbo",
        ".yarn",
        ".pnp",
        "bin",
        "obj",
        # Cantrip-specific.
        ".cantrip-worktrees",
    }
)


# Manifest files keyed by language / ecosystem.  Ported verbatim from
# awesome-copilot with charm-ecosystem additions appended.  Glob
# patterns (``*.csproj`` etc.) are handled by the caller, not by list
# membership.
MANIFESTS: tuple[str, ...] = (
    # JavaScript / Node.js.
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "deno.json",
    "deno.jsonc",
    # Python.
    "requirements.txt",
    "Pipfile",
    "Pipfile.lock",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
    # Go.
    "go.mod",
    "go.sum",
    # Rust.
    "Cargo.toml",
    "Cargo.lock",
    # Java / Kotlin.
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    # PHP / Composer.
    "composer.json",
    "composer.lock",
    # Ruby.
    "Gemfile",
    "Gemfile.lock",
    "*.gemspec",
    # Elixir.
    "mix.exs",
    "mix.lock",
    # Dart / Flutter.
    "pubspec.yaml",
    "pubspec.lock",
    # .NET / C#.
    "*.csproj",
    "*.sln",
    "*.slnx",
    "global.json",
    "packages.config",
    # Swift.
    "Package.swift",
    "Package.resolved",
    # Scala.
    "build.sbt",
    "scala-cli.yml",
    # Build systems.
    "CMakeLists.txt",
    "Makefile",
    "GNUmakefile",
    "BUILD",
    "BUILD.bazel",
    "WORKSPACE",
    "justfile",
    ".justfile",
    "Taskfile.yml",
    "tox.ini",
    "Vagrantfile",
    # Cantrip-specific — charm ecosystem.
    "charmcraft.yaml",
    "rockcraft.yaml",
    "metadata.yaml",
    "actions.yaml",
    "config.yaml",
)


# CI/CD platform configuration paths.  When present, the value is the
# human-readable platform name.  Upstream list, no Cantrip additions
# yet (GitHub Actions covers the charm-ecosystem case).
CI_CD_CONFIGS: dict[str, str] = {
    ".github/workflows": "GitHub Actions",
    ".gitlab-ci.yml": "GitLab CI",
    "Jenkinsfile": "Jenkins",
    ".circleci/config.yml": "CircleCI",
    ".travis.yml": "Travis CI",
    "azure-pipelines.yml": "Azure Pipelines",
    "appveyor.yml": "AppVeyor",
    ".drone.yml": "Drone CI",
    ".woodpecker.yml": "Woodpecker CI",
    "bitbucket-pipelines.yml": "Bitbucket Pipelines",
}


# Container and orchestration artefacts — Dockerfile, compose, k8s,
# Helm, Vagrant, podman-compose.
CONTAINER_FILES: tuple[str, ...] = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    ".dockerignore",
    "Dockerfile.*",
    "k8s",
    "kustomization.yaml",
    "Chart.yaml",
    "Vagrantfile",
    "podman-compose.yml",
)


# Security- and compliance-related config files.
SECURITY_CONFIGS: tuple[str, ...] = (
    ".snyk",
    "security.txt",
    "SECURITY.md",
    ".dependabot.yml",
    ".whitesource",
    "sbom.json",
    "sbom.spdx",
    ".bandit.yaml",
)


# Linting and formatting configuration files — useful signal for
# "does this repo have maintainable conventions?" as a charm-upgrade
# pre-check.
LINT_FILES: tuple[str, ...] = (
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.yml",
    "eslint.config.js",
    "eslint.config.mjs",
    ".prettierrc",
    ".prettierrc.json",
    ".editorconfig",
    "tsconfig.json",
    ".golangci.yml",
    ".golangci.yaml",
    ".flake8",
    ".pylintrc",
    "mypy.ini",
    ".rubocop.yml",
    "biome.json",
)


# Entry-point files by language — candidate "where does this
# application start?" probes.  Trimmed to the most common shapes; the
# upstream list has ~40 patterns, we keep the ones charm authors are
# most likely to hit (Python, Go, JS/TS, Java, .NET).
ENTRY_CANDIDATES: tuple[str, ...] = (
    # Python.
    "main.py",
    "app.py",
    "server.py",
    "run.py",
    "cli.py",
    "src/main.py",
    "src/__main__.py",
    # Go.
    "main.go",
    "cmd/main.go",
    # JavaScript / TypeScript.
    "src/index.ts",
    "src/index.js",
    "src/main.ts",
    "src/main.js",
    "src/server.ts",
    "src/server.js",
    "index.ts",
    "index.js",
    # Java / Kotlin.
    "src/main/java/Main.java",
    "src/main/kotlin/Main.kt",
    # .NET.
    "Program.cs",
    "src/Program.cs",
    # Rust.
    "src/main.rs",
    "src/lib.rs",
)


# Environment-variable templates — signal that the app expects
# runtime config.  A charm's ``config.yaml`` often mirrors these
# keys.
ENV_TEMPLATES: tuple[str, ...] = (
    ".env.example",
    ".env.template",
    ".env.sample",
    ".env.defaults",
    ".env.local.example",
)


# Cantrip-specific: charm-ecosystem artefacts that signal "this repo
# is already a charm / already operated" and should route to the
# improvement path rather than fresh build.
CHARM_MARKERS: tuple[str, ...] = (
    "charmcraft.yaml",
    "metadata.yaml",
    ".cantrip",  # Session store — this repo has been built with Cantrip before.
)


_CONFIG_HINT_FILES: tuple[str, ...] = (
    "config.yaml",
    "config.yml",
    "config.json",
    "config.toml",
    "settings.yaml",
    "settings.yml",
)

_SYSTEMD_SEARCH_DIRS: tuple[str, ...] = ("systemd", "contrib", "deploy", "packaging")
_UPSTREAM_FRAMEWORK_MAP: dict[str, str] = {"expressjs": "express"}
_FRAMEWORK_LANGUAGE_MAP: dict[str, str] = {
    "flask": "python",
    "django": "python",
    "fastapi": "python",
    "go": "go",
    "express": "javascript",
    "spring-boot": "java",
}
_MANIFEST_LANGUAGE_HINTS: tuple[tuple[str, str], ...] = (
    ("go.mod", "go"),
    ("package.json", "javascript"),
    ("app/package.json", "javascript"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "java"),
    ("requirements.txt", "python"),
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("manage.py", "python"),
    ("Cargo.toml", "rust"),
    ("mix.exs", "elixir"),
    ("composer.json", "php"),
    ("Gemfile", "ruby"),
    ("pubspec.yaml", "dart"),
    ("Package.swift", "swift"),
    ("build.sbt", "scala"),
    ("Program.cs", "csharp"),
    ("src/Program.cs", "csharp"),
)
_SOURCE_SUFFIX_LANGUAGE_MAP: dict[str, str] = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".dart": "dart",
    ".el": "elisp",
    ".ex": "elixir",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
}
_MAX_SCAN_DEPTH = 8
_MAX_SCANNED_FILES = 4000
_RECENT_COMMIT_WINDOW = "30.days"


# ---------------------------------------------------------------------------
# Output shape.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ScanResult:
    """Structured output of :func:`scan`.

    Consumed by the agent's planner at the first discovery turn so
    Path B classification (custom application) doesn't require an
    LLM round-trip just to enumerate manifests.  Kept JSON-friendly
    so it slots into the checkpoint envelope (Phase 52.3) if the
    scan itself gets wrapped by :func:`cantrip.agent.durability.checkpoint`
    in the future.
    """

    # Manifests found at the scan root.  Canonical filenames only
    # (globs are expanded by :func:`scan`).
    manifests: tuple[str, ...] = ()

    # Detected primary language, if any, derived from manifests and
    # source-file extensions.
    language: str | None = None

    # Detected framework (Flask, Django, Go, Express, …), if any.
    # Charm-aware: when a PaaS framework is detected, this matches
    # the keys of ``AnalyseFrameworkTool._PROFILE_MAP``.
    framework: str | None = None

    # Entry-point files that exist.  Ordered by confidence.
    entry_points: tuple[str, ...] = ()

    # CI/CD platform names that have configuration in the repo.
    ci_cd: tuple[str, ...] = ()

    # Container / orchestration artefacts present.
    containers: tuple[str, ...] = ()

    # Security / compliance config files present.
    security_configs: tuple[str, ...] = ()

    # Linter / formatter config files present.
    lint_configs: tuple[str, ...] = ()

    # Env-var templates present (``.env.example`` etc.).
    env_templates: tuple[str, ...] = ()

    # Whether this repo is already a Cantrip-built charm (``charmcraft.yaml``
    # and/or ``.cantrip`` present at root).  When True, the planner
    # should route to the improvement path instead of fresh build.
    is_existing_charm: bool = False

    # Recent commit count (last ~30 days).  Used for churn signalling.
    recent_commit_count: int | None = None

    # Freeform data the detection passes may attach for debugging /
    # forward compatibility.  Opaque to the planner.
    extras: dict[str, Any] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def _is_glob(pattern: str) -> bool:
    return any(token in pattern for token in ("*", "?", "["))


def _expand_patterns(
    patterns: tuple[str, ...],
    files_found: set[str],
    directories_found: set[str] | None = None,
) -> tuple[str, ...]:
    directories = directories_found or set()
    matches: set[str] = set()
    for pattern in patterns:
        if _is_glob(pattern):
            for relative_path in files_found:
                if pathlib.PurePosixPath(relative_path).match(pattern):
                    matches.add(relative_path)
            continue
        if pattern in files_found or pattern in directories:
            matches.add(pattern)
    return tuple(sorted(matches))


def _detect_ci_cd(files_found: set[str], directories_found: set[str]) -> tuple[str, ...]:
    detected: list[str] = []
    for relative_path, platform_name in CI_CD_CONFIGS.items():
        if relative_path == ".github/workflows":
            has_workflow = any(
                path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
                for path in files_found
            )
            if has_workflow:
                detected.append(platform_name)
            continue
        if relative_path in files_found or relative_path in directories_found:
            detected.append(platform_name)
    return tuple(detected)


def _detect_systemd_units(files_found: set[str]) -> tuple[str, ...]:
    units: list[str] = []
    for relative_path in sorted(files_found):
        candidate = pathlib.PurePosixPath(relative_path)
        if candidate.suffix != ".service":
            continue
        if len(candidate.parts) == 1 or (
            len(candidate.parts) == 2 and candidate.parts[0] in _SYSTEMD_SEARCH_DIRS
        ):
            units.append(relative_path)
    return tuple(units)


def _infer_language(
    files_found: set[str],
    manifests: tuple[str, ...],
    suffix_counts: collections.Counter[str],
) -> str | None:
    seen = set(manifests) | files_found
    for evidence, language in _MANIFEST_LANGUAGE_HINTS:
        if evidence in seen:
            return language

    language_counts: collections.Counter[str] = collections.Counter()
    for suffix, count in suffix_counts.items():
        language = _SOURCE_SUFFIX_LANGUAGE_MAP.get(suffix)
        if language:
            language_counts[language] += count
    if not language_counts:
        return None
    return min(
        language_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]


def _count_recent_commits(root: pathlib.Path) -> int | None:
    if not (root / ".git").exists():
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-list",
                "--count",
                f"--since={_RECENT_COMMIT_WINDOW}",
                "HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    return int(output) if output.isdigit() else None


def _walk_filesystem(
    root: pathlib.Path,
) -> tuple[set[str], set[str], collections.Counter[str], dict[str, Any]]:
    files_found: set[str] = set()
    directories_found: set[str] = set()
    suffix_counts: collections.Counter[str] = collections.Counter()
    traversed_directories = 0
    scanned_files = 0
    truncated = False

    for current_root, dirnames, filenames in os.walk(root, topdown=True):
        current_path = pathlib.Path(current_root)
        traversed_directories += 1
        relative_dir = (
            pathlib.Path(".") if current_path == root else current_path.relative_to(root)
        )
        depth = 0 if current_path == root else len(relative_dir.parts)

        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            if dirname in EXCLUDE_DIRS:
                continue
            candidate = current_path / dirname
            if candidate.is_symlink():
                continue
            candidate_relative = candidate.relative_to(root)
            if len(candidate_relative.parts) > _MAX_SCAN_DEPTH:
                continue
            kept_dirs.append(dirname)
            directories_found.add(candidate_relative.as_posix())
        dirnames[:] = kept_dirs

        for filename in sorted(filenames):
            relative_path = (current_path / filename).relative_to(root).as_posix()
            files_found.add(relative_path)
            suffix = pathlib.Path(filename).suffix.lower()
            if suffix:
                suffix_counts[suffix] += 1
            scanned_files += 1
            if scanned_files >= _MAX_SCANNED_FILES:
                truncated = True
                dirnames[:] = []
                break

        if truncated or depth >= _MAX_SCAN_DEPTH:
            dirnames[:] = []
        if truncated:
            break

    stats = {
        "directories_scanned": traversed_directories,
        "files_scanned": scanned_files,
        "max_depth": _MAX_SCAN_DEPTH,
        "max_files": _MAX_SCANNED_FILES,
        "truncated": truncated,
    }
    return files_found, directories_found, suffix_counts, stats


def scan(path: str | os.PathLike[str] | Any) -> ScanResult:
    """Scan a codebase root and return a structured summary.

    The scan is deliberately cheap and deterministic: one bounded
    filesystem walk with excluded-directory pruning, then shallow
    pattern matching and framework inference via the existing
    ``framework_detection`` helper.
    """
    root = pathlib.Path(path).resolve()
    if not root.exists():
        raise ValueError(f"Scan path not found: {path}")
    if not root.is_dir():
        raise ValueError(f"Scan path is not a directory: {path}")

    files_found, directories_found, suffix_counts, scan_stats = _walk_filesystem(root)

    manifests = _expand_patterns(MANIFESTS, files_found)
    entry_points = _expand_patterns(ENTRY_CANDIDATES, files_found)
    containers = _expand_patterns(CONTAINER_FILES, files_found, directories_found)
    security_configs = _expand_patterns(SECURITY_CONFIGS, files_found)
    lint_configs = _expand_patterns(LINT_FILES, files_found)
    env_templates = _expand_patterns(ENV_TEMPLATES, files_found)
    config_files = _expand_patterns(_CONFIG_HINT_FILES, files_found)
    systemd_units = _detect_systemd_units(files_found)
    ci_cd = _detect_ci_cd(files_found, directories_found)

    detection = detect_frameworks(root)
    framework = _UPSTREAM_FRAMEWORK_MAP.get(detection.detected, detection.detected)
    language = (
        _FRAMEWORK_LANGUAGE_MAP.get(framework)
        if framework
        else _infer_language(files_found, manifests, suffix_counts)
    )

    root_markers = {marker for marker in CHARM_MARKERS if (root / marker).exists()}

    return ScanResult(
        manifests=manifests,
        language=language,
        framework=framework,
        entry_points=entry_points,
        ci_cd=ci_cd,
        containers=containers,
        security_configs=security_configs,
        lint_configs=lint_configs,
        env_templates=env_templates,
        is_existing_charm=bool(root_markers),
        recent_commit_count=_count_recent_commits(root),
        extras={
            "config_files": list(config_files),
            "framework_candidates": [
                {
                    **candidate,
                    "framework": _UPSTREAM_FRAMEWORK_MAP.get(
                        str(candidate["framework"]),
                        candidate["framework"],
                    ),
                }
                for candidate in detection.candidates
            ],
            "framework_detection_notes": list(detection.notes),
            "root_markers": sorted(root_markers),
            "scan_stats": scan_stats,
            "systemd_units": list(systemd_units),
            "web_app_guess": detection.web_app_guess,
            "web_app_signals": {
                "positive": list(detection.web_app_signals_positive),
                "negative": list(detection.web_app_signals_negative),
            },
        },
    )


__all__ = [
    "CHARM_MARKERS",
    "CI_CD_CONFIGS",
    "CONTAINER_FILES",
    "ENTRY_CANDIDATES",
    "ENV_TEMPLATES",
    "EXCLUDE_DIRS",
    "LINT_FILES",
    "MANIFESTS",
    "SECURITY_CONFIGS",
    "ScanResult",
    "scan",
]
