"""Inspect environment-variable references in an application source tree.

The patterns and per-framework env contracts here are derived from the
canonical/skills repository:
``skills/engineering/12factor-charm/scripts/inspect_env_keys.py``
(PR #4, https://github.com/canonical/skills/pull/4), Apache-2.0 licensed.

Adapted for Cantrip: ``express`` replaces upstream ``expressjs`` in the
framework contracts; cache directories common in Python projects
(``.ruff_cache``, ``.pytest_cache``, ``.ty_cache``, ``.nox``) are added
to the walk-skip list so the regex sweep stays fast on Cantrip-shaped
repos.

The helper :func:`inspect_env_keys` is pure — no subprocess, no network,
just filesystem reads against the supplied repo path.  Useful for
charm⇄rock env-var contract validation, including paths outside the
12-factor flow.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib
import re
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Per-language regexes that capture env-var references.  Each capture
# group is the env-var name (uppercase by convention; Spring's dotted
# property names are also captured because the Spring extension reads
# them as env vars).
_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "python": (
        re.compile(r"""os\.getenv\(\s*["']([A-Z0-9_]+)["']"""),
        re.compile(r"""os\.environ(?:\.get)?\(\s*["']([A-Z0-9_]+)["']"""),
        re.compile(r"""os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]"""),
    ),
    "javascript": (
        re.compile(r"""process\.env\.([A-Z][A-Z0-9_]*)"""),
        re.compile(r"""process\.env\[\s*["']([A-Z0-9_]+)["']\s*\]"""),
    ),
    "go": (re.compile(r"""os\.(?:Getenv|LookupEnv)\(\s*"([A-Z0-9_]+)"\s*\)"""),),
    "java": (re.compile(r"""System\.getenv\(\s*"([A-Z0-9_]+)"\s*\)"""),),
    "java_spring": (
        re.compile(r"""\$\{([A-Z][A-Z0-9_.]+)\}"""),
        re.compile(r"""@Value\(\s*"\$\{([^}:]+)(?::[^}]*)?\}"\s*\)"""),
    ),
    "dotenv": (re.compile(r"""^([A-Z][A-Z0-9_]+)\s*=""", re.MULTILINE),),
}

# File suffixes scanned for env-var references.  ``.env`` and
# ``.env.sample`` etc. are handled separately by name.
_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".kt", ".yaml", ".yml", ".properties"}
)

# Walk-skip set.  Builds on the upstream's list with the Python tooling
# caches Cantrip's repos accumulate (ruff/ty/pytest/nox).
_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "target",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".ty_cache",
        "__pycache__",
    }
)

# Per-framework env-var contract.  ``built_in_env_examples`` are the
# vars the framework or paas-charm sets unconditionally; the user
# config prefix is what charm-config keys are mapped under; relation
# env families enumerate the ``DB_*`` / ``REDIS_*`` / ... sets that
# arrive via Juju relations.
_FRAMEWORK_CONTRACTS: dict[str, dict[str, Any]] = {
    "flask": {
        "built_in_env_examples": ["FLASK_DEBUG", "FLASK_ENV", "FLASK_SECRET_KEY"],
        "user_config_prefix": "FLASK_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "OTEL_*",
        ],
    },
    "django": {
        "built_in_env_examples": [
            "DJANGO_DEBUG",
            "DJANGO_SECRET_KEY",
            "DJANGO_ALLOWED_HOSTS",
        ],
        "user_config_prefix": "DJANGO_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "OTEL_*",
        ],
    },
    "fastapi": {
        "built_in_env_examples": [
            "UVICORN_PORT",
            "UVICORN_HOST",
            "WEB_CONCURRENCY",
            "UVICORN_LOG_LEVEL",
            "APP_SECRET_KEY",
        ],
        "user_config_prefix": "APP_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "OTEL_*",
        ],
    },
    "express": {
        "built_in_env_examples": ["PORT", "NODE_ENV", "APP_SECRET_KEY"],
        "user_config_prefix": "APP_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "OTEL_*",
        ],
    },
    "go": {
        "built_in_env_examples": ["APP_PORT", "APP_METRICS_PORT", "APP_SECRET_KEY"],
        "user_config_prefix": "APP_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "OTEL_*",
        ],
    },
    "spring-boot": {
        "built_in_env_examples": [
            "SERVER_PORT",
            "APP_PROFILES",
            "MANAGEMENT_SERVER_PORT",
            "spring.datasource.url",
        ],
        "user_config_prefix": "APP_",
        "relation_env_families": [
            "POSTGRESQL_DB_*",
            "MYSQL_DB_*",
            "REDIS_*",
            "SMTP_*",
            "spring.security.oauth2.*",
        ],
    },
}

SUPPORTED_CONTRACT_FRAMEWORKS: frozenset[str] = frozenset(_FRAMEWORK_CONTRACTS)


@dataclasses.dataclass(frozen=True)
class EnvKeysReport:
    """Outcome of running :func:`inspect_env_keys` on a repo."""

    detected_env_keys: list[str]
    per_file: dict[str, list[str]]
    framework: str | None
    framework_contract: dict[str, Any] | None


def inspect_env_keys(repo: pathlib.Path, framework: str | None = None) -> EnvKeysReport:
    """Scan *repo* for env-var references and return what was found.

    ``framework`` is optional: when supplied, the report carries the
    framework's expected env-var contract (built-in vars, user-config
    prefix, relation env families) so the agent can compare detected
    keys against what paas-charm would deliver.  An unknown framework
    yields a ``None`` contract — the helper does *not* raise so the
    caller can still get the detected-keys output.
    """
    matches: dict[str, set[str]] = collections.defaultdict(set)
    env_keys: set[str] = set()

    for path in _iter_files(repo):
        content = _read_text(path)
        for regexes in _PATTERNS.values():
            for regex in regexes:
                for match in regex.findall(content):
                    key = match[0] if isinstance(match, tuple) else match
                    env_keys.add(key)
                    matches[str(path.relative_to(repo))].add(key)

    return EnvKeysReport(
        detected_env_keys=sorted(env_keys),
        per_file={path: sorted(keys) for path, keys in sorted(matches.items())},
        framework=framework,
        framework_contract=_FRAMEWORK_CONTRACTS.get(framework) if framework else None,
    )


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _is_allowed_file(path: pathlib.Path) -> bool:
    if path.suffix in _ALLOWED_SUFFIXES:
        return True
    return path.name == ".env" or path.name.startswith(".env.")


def _iter_files(repo: pathlib.Path) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in repo.rglob("*"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and _is_allowed_file(path):
            files.append(path)
    return files


class InspectEnvKeysTool(Tool):
    """Inspect a codebase for environment-variable references.

    Sweeps Python / JavaScript / TypeScript / Go / Java / Spring source
    plus YAML, ``.properties``, and ``.env*`` files for env-var lookups
    (``os.getenv``, ``process.env.X``, ``System.getenv``, Spring
    ``${...}`` properties, ``KEY=`` rows in ``.env``).  Returns a
    deduplicated sorted key list plus a per-file map of which files
    reference which keys.

    When ``framework`` is supplied, the response also carries that
    framework's expected env contract — built-in vars, user-config
    prefix, and relation env families — so the agent can spot keys the
    workload reads that paas-charm won't deliver.
    """

    @property
    def name(self) -> str:
        return "inspect_env_keys"

    @property
    def description(self) -> str:
        return (
            "Inspect application source for environment-variable references "
            "(``os.getenv``, ``process.env.X``, ``System.getenv``, Spring "
            "``${...}``, ``.env`` rows, etc.) and return a deduplicated key "
            "list plus a per-file usage map. Pass ``framework`` (flask, "
            "django, fastapi, express, go, spring-boot) to additionally "
            "receive the framework's expected env-var contract — built-in "
            "vars, user-config prefix, and relation env families. Useful "
            "for charm⇄rock env-var contract validation."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository path to inspect.",
                },
                "framework": {
                    "type": "string",
                    "description": "Optional framework — when set, the response carries the framework's expected env contract.",
                    "enum": sorted(SUPPORTED_CONTRACT_FRAMEWORKS),
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, framework: str | None = None) -> ToolResult:
        repo = pathlib.Path(path).resolve()
        if not repo.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        report = inspect_env_keys(repo, framework=framework)

        lines = [
            f"Inspected {repo} — {len(report.detected_env_keys)} env keys "
            f"across {len(report.per_file)} file(s)",
        ]
        if report.detected_env_keys:
            lines.append("Detected keys:")
            lines.extend(f"  - {key}" for key in report.detected_env_keys)
        if report.framework_contract is not None:
            contract = report.framework_contract
            lines.append(f"\nFramework contract ({framework}):")
            lines.append("  built-in: " + ", ".join(contract["built_in_env_examples"]))
            lines.append(f"  user-config prefix: {contract['user_config_prefix']}")
            lines.append("  relation families: " + ", ".join(contract["relation_env_families"]))

        caption = (
            f"inspect_env_keys → {len(report.detected_env_keys)} keys"
            if report.detected_env_keys
            else "inspect_env_keys → 0 keys"
        )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "framework": report.framework,
                "detected_env_keys": list(report.detected_env_keys),
                "per_file": {k: list(v) for k, v in report.per_file.items()},
                "framework_contract": report.framework_contract,
            },
            caption=caption,
        )
