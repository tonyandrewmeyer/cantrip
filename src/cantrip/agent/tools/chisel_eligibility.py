"""Chisel-eligibility rubric for 12-factor rocks.

Chisel produces sliced OCI images that contain only the filesystem slices
a workload actually needs.  A chiselled rock is smaller, has a reduced
attack surface, and pulls faster than an ubuntu-base rock — but it has a
higher cost to assemble because every OS package the workload needs must
have a published Chisel slice in the ``ubuntu-*`` repository.

This module contains the deterministic, filesystem-only eligibility check
that decides whether a given repository + framework combination is a
plausible chisel candidate *before* the agent tries to build the rock.
No network calls, no subprocess: reads and pattern-matching only.

The check is intentionally conservative: when in doubt it returns
``eligible=False`` and explains why, leaving the agent free to fall back
to a fuller Ubuntu base without any ceremony.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

# ---------------------------------------------------------------------------
# Framework eligibility table
# ---------------------------------------------------------------------------

# Frameworks whose upstream rock extension already produces a ``base: bare``
# image by default.  These are the best chisel candidates because the
# extension knows how to stage *only* the required slices.
_BARE_BY_DEFAULT: frozenset[str] = frozenset(
    {
        "flask",
        "django",
        "fastapi",
        "go",
        "express",
    }
)

# Spring Boot packages a fat JAR and the spring-boot-framework extension
# stages a JRE; the JRE slices are present in ubuntu-24.04 definitions, so
# Spring Boot is eligible but the check is slightly more cautious (the JRE
# slice set is large and Java agents / bytecode tools often need extras).
_SPRING_BOOT_ELIGIBLE = True

# All supported 12-factor frameworks.
CHISEL_ELIGIBLE_FRAMEWORKS: frozenset[str] = _BARE_BY_DEFAULT | {
    "spring-boot",
}


# ---------------------------------------------------------------------------
# Known-bad patterns — checked in the repo source tree
# ---------------------------------------------------------------------------

# Commands that only make sense with a shell present at runtime.
# A match anywhere in .py / .sh / .go / .js / .ts source is a blocker.
_SHELL_AT_RUNTIME: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("os.system() call", re.compile(r"\bos\.system\s*\(", re.MULTILINE)),
    (
        "subprocess shell=True",
        re.compile(
            r"\bsubprocess\.(run|Popen|call|check_output)\b[^)]*shell\s*=\s*True", re.MULTILINE
        ),
    ),
    (
        "subprocess invokes /bin/sh",
        re.compile(
            r"\bsubprocess\.(run|Popen|call|check_output)\b[^)]*['\"/](?:sh|bash|dash|ash)['\"\s,\)]",
            re.MULTILINE,
        ),
    ),
    (
        "exec /bin/sh",
        re.compile(r"\bexec\.Command\s*\([^)]*(?:sh|bash|dash|ash)[^)]*\)", re.MULTILINE),
    ),
    (
        "Runtime.exec shell",
        re.compile(r"Runtime\.getRuntime\(\)\.exec\s*\([^)]*(?:sh|bash)[^)]*\)", re.MULTILINE),
    ),
)

# apt / dpkg calls at runtime.
_APT_AT_RUNTIME: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "apt-get at runtime",
        re.compile(r"\bapt(?:-get)?\s+(install|update|upgrade)\b", re.MULTILINE),
    ),
    (
        "dpkg at runtime",
        re.compile(r"\bdpkg\s+-[iIr]", re.MULTILINE),
    ),
)

# Opaque vendor install scripts — patterns in package.json scripts that
# download and execute arbitrary code.
_VENDOR_INSTALL_SCRIPTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "curl|bash in npm lifecycle script",
        re.compile(r"(?:curl|wget)\b.+[|>]\s*(?:bash|sh)\b", re.MULTILINE),
    ),
    (
        "npx postinstall shell",
        re.compile(
            r'"(?:preinstall|postinstall)"\s*:\s*"[^"]*(?:curl|wget|bash|sh)[^"]*"', re.MULTILINE
        ),
    ),
)

# Source-file extensions that may contain runtime shell invocations.
_SCANNABLE_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".go", ".java", ".js", ".ts", ".sh", ".bash", ".kts"}
)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ChiselEligibilityReport:
    """Outcome of running :func:`check_chisel_eligibility` on a repo."""

    framework: str
    eligible: bool
    blockers: list[str]
    """Concrete reasons the workload cannot safely use a chiselled base."""
    advisories: list[str]
    """Non-blocking notes the agent should mention to the user."""
    rationale: str
    """Short prose suitable for including in the generation output."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_chisel_eligibility(repo: pathlib.Path, framework: str) -> ChiselEligibilityReport:
    """Evaluate whether *repo* + *framework* is a chisel candidate.

    The check is purely deterministic and filesystem-local: no network, no
    subprocess.  Callers should run this *after* :func:`check_rock_contract`
    confirms the repo fits the 12-factor contract — the two checks address
    orthogonal questions.

    ``eligible=True`` means the workload is a plausible chisel candidate.
    The caller should still mention the escape hatch (``base: ubuntu@24.04``)
    and the debug caveat in the generated output.
    """
    blockers: list[str] = []
    advisories: list[str] = []

    # Framework-level gate.
    if framework not in CHISEL_ELIGIBLE_FRAMEWORKS:
        blockers.append(
            f"Framework '{framework}' is not in the supported 12-factor set "
            f"({', '.join(sorted(CHISEL_ELIGIBLE_FRAMEWORKS))}) — chisel eligibility "
            "only applies to these frameworks."
        )
        return ChiselEligibilityReport(
            framework=framework,
            eligible=False,
            blockers=blockers,
            advisories=advisories,
            rationale=_rationale(framework, eligible=False, blockers=blockers),
        )

    if framework == "spring-boot":
        advisories.append(
            "Spring Boot rocks require a JRE slice set.  Verify the ubuntu-24.04 "
            "slice definitions include the JRE edition needed by the application "
            "(``openjdk-21-jre-headless`` or equivalent) before committing to the "
            "chiselled path."
        )

    # Scan source files for runtime shell / apt invocations.
    _scan_runtime_patterns(repo, blockers)

    # Scan package.json lifecycle scripts for opaque vendor installs.
    _scan_npm_lifecycle(repo, blockers)

    # Check for entrypoint scripts that explicitly rely on shell builtins.
    _check_entrypoint_scripts(repo, advisories)

    eligible = not blockers
    return ChiselEligibilityReport(
        framework=framework,
        eligible=eligible,
        blockers=blockers,
        advisories=advisories,
        rationale=_rationale(framework, eligible=eligible, blockers=blockers),
    )


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------


def _read_text_safe(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _scan_runtime_patterns(
    repo: pathlib.Path,
    blockers: list[str],
) -> None:
    """Search source files for shell-at-runtime and apt-at-runtime patterns."""
    shell_hits: list[str] = []
    apt_hits: list[str] = []

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _SCANNABLE_SUFFIXES:
            continue
        # Skip vendored / generated directories that would produce noise.
        if any(
            part in {"vendor", "node_modules", ".git", "__pycache__", "venv", ".venv"}
            for part in path.parts
        ):
            continue

        text = _read_text_safe(path)
        rel = path.relative_to(repo)

        for label, pattern in _SHELL_AT_RUNTIME:
            if pattern.search(text):
                shell_hits.append(f"{rel}: {label}")
                break

        for label, pattern in _APT_AT_RUNTIME:
            if pattern.search(text):
                apt_hits.append(f"{rel}: {label}")
                break

    if shell_hits:
        blockers.append(
            "Shell-at-runtime pattern detected — a chiselled rock contains no "
            f"shell binary.  Affected file(s): {', '.join(shell_hits[:3])}"
            + ("…" if len(shell_hits) > 3 else ".")
        )
    if apt_hits:
        blockers.append(
            "apt/dpkg call detected — a chiselled rock has no apt binary.  "
            f"Affected file(s): {', '.join(apt_hits[:3])}" + ("…" if len(apt_hits) > 3 else ".")
        )


def _scan_npm_lifecycle(repo: pathlib.Path, blockers: list[str]) -> None:
    """Check npm package.json lifecycle scripts for opaque vendor installs."""
    for pkg_json in repo.rglob("package.json"):
        if any(p in {"node_modules", ".git"} for p in pkg_json.parts):
            continue
        text = _read_text_safe(pkg_json)
        for label, pattern in _VENDOR_INSTALL_SCRIPTS:
            if pattern.search(text):
                rel = pkg_json.relative_to(repo)
                blockers.append(
                    f"Opaque vendor install script in {rel}: {label}.  "
                    "These scripts often invoke shell commands that require "
                    "curl, wget, or bash — none of which are present in a "
                    "chiselled rock."
                )
                break


def _check_entrypoint_scripts(repo: pathlib.Path, advisories: list[str]) -> None:
    """Warn when shell scripts at known entrypoint paths use shell-only builtins.

    These may still work if the Pebble service can invoke them via a shell
    slice, but they warrant a mention so the user is aware of the dependency.
    """
    # Paths that 12-factor framework extensions treat as optional entrypoints.
    _ENTRYPOINT_CANDIDATES = ("migrate.sh", "entrypoint.sh", "start.sh", "docker-entrypoint.sh")
    _SHELL_ONLY_RE = re.compile(
        r"\b(source\b|\.[ \t]|export\b|\[\[|set -[euxo]|trap\b)", re.MULTILINE
    )

    for name in _ENTRYPOINT_CANDIDATES:
        script = repo / name
        if not script.is_file():
            continue
        text = _read_text_safe(script)
        if _SHELL_ONLY_RE.search(text):
            advisories.append(
                f"'{name}' uses shell-only constructs (source, [[, set -, …).  "
                "In a chiselled rock the shebang interpreter (bash/sh) must be "
                "available — either add a ``bash_bins`` or ``sh`` slice, or "
                "rewrite the script to be POSIX sh-compatible and add a sh slice."
            )


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

_ELIGIBLE_INTRO: dict[str, str] = {
    "flask": (
        "The Flask framework extension defaults to ``base: bare`` and stages only "
        "the Python interpreter slices and Gunicorn.  No shell is needed at runtime — "
        "paas-charm drives the lifecycle via Pebble, not shell scripts."
    ),
    "django": (
        "The Django framework extension defaults to ``base: bare`` and stages only "
        "the Python interpreter slices and Gunicorn.  The ``manage.py migrate`` path "
        "is invoked by paas-charm via the Python binary, not a shell."
    ),
    "fastapi": (
        "The FastAPI framework extension defaults to ``base: bare`` and stages only "
        "the Python interpreter slices and Uvicorn.  No shell is needed at runtime."
    ),
    "go": (
        "The Go framework extension compiles a static or semi-static binary and "
        "stages it into a ``base: bare`` rock.  The resulting image typically needs "
        "no OS libraries beyond libc slices."
    ),
    "express": (
        "The Express framework extension stages Node.js slices into a ``base: bare`` "
        "rock.  No shell is needed to start the application via ``npm start``."
    ),
    "spring-boot": (
        "The Spring Boot framework extension stages a JRE into the rock.  "
        "When the required JRE slices are available in ubuntu-24.04, a chiselled "
        "rock removes the shell, apt, and unneeded OS utilities while preserving "
        "the full JRE needed by the fat JAR."
    ),
}


def _rationale(framework: str, eligible: bool, blockers: list[str]) -> str:
    if not eligible:
        reasons = "; ".join(blockers[:2])
        return (
            f"Chiselled base not recommended for this {framework} workload: {reasons}.  "
            "Use an explicit ``base: ubuntu@24.04`` to retain the full Ubuntu "
            "filesystem, including the shell and apt."
        )
    intro = _ELIGIBLE_INTRO.get(
        framework,
        f"The {framework} framework extension is compatible with a chiselled base.",
    )
    return (
        f"{intro}  "
        "To generate a chiselled rock, keep the default ``base: bare`` in "
        "``rockcraft.yaml`` and let the extension select the appropriate slice set.  "
        "If you hit a missing-slice build failure, switch to "
        "``base: ubuntu@24.04`` — this retains all the runtime benefits of the "
        "extension while adding the full Ubuntu filesystem as a fallback."
    )
