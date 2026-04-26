"""Deterministic codebase pre-scan for Path B discovery (Phase 55.7 stub).

This module is a **stub** filed by Phase 55.7 of the roadmap to anchor
the port decision.  It defines the target library surface — data
tables + ``ScanResult`` dataclass + a ``scan(path)`` entry point —
without actually implementing the detection passes.  The accompanying
roadmap entry records *why* we're porting rather than vendoring or
subprocess-invoking the upstream script; the accompanying
``design/TOOLS.md`` section records the output shape contract.

Attribution
-----------
The detection tables in this module are ported from the
``scan.py`` helper of the ``acquire-codebase-knowledge`` skill in
``github/awesome-copilot`` (MIT licence, Copyright GitHub, Inc.):

  https://github.com/github/awesome-copilot/blob/main/skills/acquire-codebase-knowledge/scripts/scan.py

Charm-specific additions (``charmcraft.yaml`` / ``rockcraft.yaml`` /
``.cantrip`` detection, ``ops``-version hints, the ``ScanResult``
shape) are Cantrip-local work that the upstream version does not
cover.

Status
------
- Data tables and ``ScanResult`` shape: authored.
- ``scan(path)`` function: stub with TODO markers for each pass.
- Tests: none — the stub isn't wired into a ``Tool`` yet.

Wiring into ``AnalyseFrameworkTool`` (``tools/charm.py``) and
populating the detection passes is the follow-up work Phase 55.7
sized and deferred.  When that lands, convert this module from a
stub to a full implementation; add unit tests under
``tests/unit/test_scan.py`` exercising each detection pass against
small in-process charm-directory fixtures.
"""

from __future__ import annotations

import dataclasses
from typing import Any

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
# Entry point — stub.
# ---------------------------------------------------------------------------


def scan(path: str | Any) -> ScanResult:  # noqa: ARG001
    """Scan a codebase root and return a structured summary.

    **Stub implementation** — Phase 55.7 ships the surface proposal;
    the detection passes are TODO.  Returning an empty
    :class:`ScanResult` keeps callers un-broken while the
    implementation lands.

    Implementation plan (each bullet is a pass over the tree):

    1. Walk the filesystem with :data:`EXCLUDE_DIRS` pruning; cap
       depth and file count so pathological repos don't explode.
    2. Resolve :data:`MANIFESTS` patterns against the tree
       (expanding ``*.csproj`` / ``*.gemspec`` / etc.); build
       ``manifests``.
    3. Detect language + framework from manifest contents — re-use
       the Python/Go/JS/Java decisions already in
       :class:`AnalyseFrameworkTool` rather than duplicating them
       here; the port converges the tool onto this helper.
    4. Probe :data:`ENTRY_CANDIDATES` and keep the existing ones.
    5. Probe :data:`CI_CD_CONFIGS`; include ``.github/workflows``
       only when the directory contains at least one ``.yml``
       file.
    6. Probe :data:`CONTAINER_FILES`; expand ``Dockerfile.*`` via
       glob.
    7. Probe :data:`SECURITY_CONFIGS`, :data:`LINT_FILES`,
       :data:`ENV_TEMPLATES`.
    8. Set ``is_existing_charm`` when any :data:`CHARM_MARKERS`
       are present at root.
    9. If the path is a git checkout, count commits in the last
       30 days for ``recent_commit_count``.

    Budget: the whole scan should complete in well under a second
    on a typical charm repo; skip any pass that starts scaling
    with repo size (line counts, per-file AST parsing) — those
    belong in a heavier follow-up tool.
    """
    return ScanResult()


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
