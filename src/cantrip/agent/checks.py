"""Prompt-based review checks (Phase 70.4).

A *Check* is a single markdown file with YAML frontmatter that asks
the LLM to evaluate a judgment-based rule against the active charm —
"does the README narrative match what the code does?", "are action
names user-friendly?", "is the relation databag schema sensible?".
Each Check runs as exactly one structured LLM call (the
:data:`~cantrip.llm.schemas.CHECK_RESULT` schema constrains the
reply to ``{status, severity, message, evidence?, suggested_fix?}``)
so the report aggregator can surface a uniform view next to the
deterministic ``charmlint`` output.

This module is the loader + runner; the ``/review`` slash command in
:mod:`cantrip.agent.commands.slash` is the user-facing surface that
ties them together.

**Discovery precedence** (later wins on name conflict):

1. Bundled checks shipped under ``src/cantrip/checks/``.
2. User-scope ``~/.config/cantrip/checks/*.md``.
3. Repo-scope ``<charm>/.cantrip/checks/*.md``.

When a later layer shadows a name from an earlier one,
:meth:`CheckIndex.shadows` records a diagnostic so the
author can see they've replaced a default — quiet override is the
documented anti-pattern.

**Boundary with charmlint** — see ``design/CHECKS.md``.  Briefly:
charmlint is the place for deterministic AST/YAML rules; Checks are
the place for "an experienced human would notice this is off but
you can't write it as a regex".
"""

from __future__ import annotations

import dataclasses
import fnmatch
import logging
import pathlib
from typing import TYPE_CHECKING, Any

import yaml

from cantrip.agent import skills
from cantrip.llm import schemas
from cantrip.llm.base import LLMProvider, Message, Role
from cantrip.llm.structured import StructuredOutputError, complete_structured

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

log = logging.getLogger(__name__)

# Source tags so the report can show where a Check came from.
SOURCE_BUNDLED = "bundled"
SOURCE_USER = "user"
SOURCE_REPO = "repo"

# Default location of bundled checks (sibling of ``cantrip/skills/``).
_DEFAULT_BUNDLED_DIR = pathlib.Path(__file__).resolve().parent.parent / "checks"

# Allowed severities, in priority order (used for sort + display).
_SEVERITIES: tuple[str, ...] = ("critical", "high", "error", "medium", "warning", "low", "info")
_DEFAULT_SEVERITY = "warning"

# Cap on how many bytes of file content we feed into a single check
# prompt.  Keeps the LLM call cheap and bounded; a charm rule that
# needs the whole repo is the wrong shape for a Check (write a
# charmlint rule or a multi-step subagent task instead).
_MAX_FILE_BYTES_PER_CHECK = 32_000

# Cap on the number of files attached to one check prompt — same
# rationale.
_MAX_FILES_PER_CHECK = 20


@dataclasses.dataclass(frozen=True)
class Check:
    """One prompt-based check loaded from a ``.md`` file."""

    name: str
    description: str
    severity: str
    globs: tuple[str, ...]
    tools: tuple[str, ...]
    body: str
    path: pathlib.Path
    source: str


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """The outcome of running one :class:`Check`."""

    name: str
    status: str  # "pass" | "fail" | "skipped" | "error"
    severity: str
    message: str
    evidence: str | None = None
    suggested_fix: str | None = None
    source: str = SOURCE_BUNDLED

    def is_failure(self) -> bool:
        """Return ``True`` for a fail result, *not* skipped or error.

        Errors (LLM call failed, schema violation) are treated as
        diagnostic noise — the user wants to know the check ran but
        couldn't reach a verdict, not that the rule itself failed.
        """
        return self.status == "fail"


@dataclasses.dataclass(frozen=True)
class CheckReport:
    """Aggregate of every check that ran for a single ``/review`` invocation."""

    results: tuple[CheckResult, ...] = ()
    shadows: tuple[str, ...] = ()

    def has_failures(self) -> bool:
        """Return ``True`` if any check returned ``status="fail"``."""
        return any(r.is_failure() for r in self.results)

    def counts_by_status(self) -> dict[str, int]:
        """Count results bucketed by status — the report header summary."""
        counts: dict[str, int] = {"pass": 0, "fail": 0, "skipped": 0, "error": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def to_text(self) -> str:
        """Render as a Markdown summary suitable for chat surfaces.

        Failures lead, then errors (couldn't reach a verdict), then
        skipped (no matching files), then passes — the user reads
        top-down and the most actionable items are at the top.
        """
        if not self.results and not self.shadows:
            return "_No checks configured for this charm._"

        counts = self.counts_by_status()
        lines: list[str] = []
        summary_parts = [
            f"{counts[status]} {status}"
            for status in ("pass", "fail", "error", "skipped")
            if counts.get(status)
        ]
        lines.append(f"**Review checks** ({', '.join(summary_parts) or 'no results'})")
        lines.append("")

        ordered = sorted(self.results, key=_result_sort_key)
        for r in ordered:
            badge = _status_badge(r.status)
            header = f"{badge} **{r.name}** — {r.severity}"
            lines.append(header)
            lines.append(f"  {r.message}")
            if r.evidence:
                lines.append(f"  _evidence:_ {r.evidence}")
            if r.suggested_fix:
                lines.append(f"  _suggested fix:_ {r.suggested_fix}")
            lines.append("")

        if self.shadows:
            lines.append("---")
            lines.append("**Shadowed checks** (later layer overrides earlier):")
            lines.extend(f"- {note}" for note in self.shadows)

        return "\n".join(lines).rstrip()

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form for the Phase 24 reporter shape."""
        return {
            "total": len(self.results),
            "counts": self.counts_by_status(),
            "results": [dataclasses.asdict(r) for r in self.results],
            "shadows": list(self.shadows),
        }


def _status_badge(status: str) -> str:
    """Return a short Markdown badge per status — keeps the list scannable."""
    return {
        "pass": "✓",
        "fail": "✗",
        "error": "!",
        "skipped": "·",
    }.get(status, "·")


def _result_sort_key(r: CheckResult) -> tuple[int, str]:
    """Sort key: failures first, errors second, skipped, then passes."""
    order = {"fail": 0, "error": 1, "skipped": 2, "pass": 3}
    return (order.get(r.status, 4), r.name)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class CheckIndex:
    """Discovers and loads :class:`Check` files from layered locations.

    Three roots, layered later-wins:

    * Bundled checks shipped with Cantrip (``src/cantrip/checks/``).
    * User-scope ``~/.config/cantrip/checks/``.
    * Project-scope ``<charm>/.cantrip/checks/``.

    The class itself has no LLM dependency — it parses files and
    sorts them.  :func:`run_all_checks` is the runner.
    """

    def __init__(
        self,
        *,
        project_root: pathlib.Path | None = None,
        user_dir: pathlib.Path | None = None,
        bundled_dir: pathlib.Path | None = None,
    ) -> None:
        self._project_root = project_root
        # Resolve the user dir lazily so tests can override via
        # ``CANTRIP_*`` env vars without a parameter dance.  The
        # default mirrors the skills convention.
        self._user_dir = user_dir or (pathlib.Path.home() / ".config" / "cantrip" / "checks")
        self._bundled_dir = bundled_dir or _DEFAULT_BUNDLED_DIR
        self._checks: dict[str, Check] = {}
        self._shadows: list[str] = []

    def discover(self) -> list[Check]:
        """Walk every layer in precedence order and return the merged set.

        Side-effect: populates :attr:`shadows` so the report can warn
        when a name was overridden silently.  Calling :meth:`discover`
        more than once resets state — caller pays for re-scan.
        """
        self._checks = {}
        self._shadows = []

        for source, root in (
            (SOURCE_BUNDLED, self._bundled_dir),
            (SOURCE_USER, self._user_dir),
            (SOURCE_REPO, self._repo_dir()),
        ):
            if root is None or not root.is_dir():
                continue
            for path in sorted(root.glob("*.md")):
                try:
                    check = _parse_check_file(path, source=source)
                except (yaml.YAMLError, ValueError, RecursionError) as exc:
                    log.warning("Skipping malformed check %s: %s", path, exc)
                    continue
                if check.name in self._checks:
                    prior = self._checks[check.name]
                    self._shadows.append(
                        f"`{check.name}` from {check.source} ({check.path}) "
                        f"shadows {prior.source} ({prior.path})"
                    )
                self._checks[check.name] = check

        return sorted(self._checks.values(), key=lambda c: c.name)

    @property
    def shadows(self) -> list[str]:
        """Diagnostics emitted by the most recent :meth:`discover` call."""
        return list(self._shadows)

    def _repo_dir(self) -> pathlib.Path | None:
        if self._project_root is None:
            return None
        return self._project_root / ".cantrip" / "checks"


def _parse_check_file(path: pathlib.Path, *, source: str) -> Check:
    """Parse one ``<name>.md`` Check file.

    Frontmatter shape::

        ---
        name: charm-readme-coherence
        description: Does the README explain what the charm actually does?
        severity: warning             # optional — defaults to "warning"
        globs: ["README.md", "src/**/*.py"]   # optional — default unscoped
        tools: []                     # optional — default read-only
        ---

        <markdown body — the prompt the model sees>
    """
    raw = path.read_text()
    lines = raw.split("\n")

    if not lines or lines[0].strip() != "---":
        raise ValueError(f"missing opening frontmatter delimiter in {path}")

    end: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError(f"missing closing frontmatter delimiter in {path}")

    frontmatter_text = "\n".join(lines[1:end])
    data = yaml.safe_load(frontmatter_text)
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter is not a mapping in {path}")

    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        raise ValueError(f"frontmatter must contain 'name' and 'description' in {path}")

    severity = str(data.get("severity") or _DEFAULT_SEVERITY).lower()
    if severity not in _SEVERITIES:
        # Unknown severity — keep the file but coerce to default and
        # warn so the author can see they used a non-canonical value.
        log.warning(
            "Check %s declares unknown severity %r; coercing to %s",
            path,
            severity,
            _DEFAULT_SEVERITY,
        )
        severity = _DEFAULT_SEVERITY

    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise ValueError(f"check body is empty in {path}")

    return Check(
        name=str(name),
        description=str(description),
        severity=severity,
        globs=tuple(skills._coerce_string_list(data.get("globs"))),
        tools=tuple(skills._coerce_string_list(data.get("tools"))),
        body=body,
        path=path,
        source=source,
    )


# ---------------------------------------------------------------------------
# Glob scoping
# ---------------------------------------------------------------------------


def _matches_globs(path: pathlib.Path, globs: Sequence[str], charm_root: pathlib.Path) -> bool:
    """Return ``True`` when *path* matches any of *globs* under *charm_root*.

    Patterns containing ``/`` match the path relative to *charm_root*
    (with ``**`` for any number of segments); bare patterns like
    ``README.md`` or ``*.py`` match the basename only.  Same
    semantics as :func:`cantrip.agent.skills._any_glob_matches` so an
    author writing both kinds of files learns one rule.
    """
    try:
        rel = path.relative_to(charm_root)
    except ValueError:
        rel = path
    rel_str = str(rel).replace("\\", "/")
    name = path.name
    for pattern in globs:
        if "/" in pattern:
            if fnmatch.fnmatchcase(rel_str, pattern):
                return True
            # Support ``**`` by manual segmenting — fnmatch treats ``*``
            # as "any characters except /" implicitly via the pattern,
            # so explicit ``**`` requires the recursive fallback below.
            if "**" in pattern and _recursive_glob_match(rel_str, pattern):
                return True
        else:
            if fnmatch.fnmatchcase(name, pattern):
                return True
    return False


def _recursive_glob_match(rel_path: str, pattern: str) -> bool:
    """Match a ``**``-bearing glob against *rel_path*.

    Implements the conventional ``**`` semantics shared by zsh, git, and
    Python's own ``pathlib.PurePath.full_match`` (3.13+):

    * ``a/**/b`` matches ``a/b``, ``a/x/b``, ``a/x/y/b`` — zero or more
      intermediate segments.
    * ``**/foo`` matches ``foo``, ``a/foo``, ``a/b/foo``.
    * ``foo/**`` matches ``foo``, ``foo/x``, ``foo/x/y``.
    * Bare ``*`` matches any run of characters except ``/``; ``?``
      matches a single non-``/`` character.

    Implemented as a hand-rolled regex translation so the codebase
    keeps targeting 3.12.  Walking the pattern char-by-char (rather
    than ``split("**")`` and re-joining) lets us notice the
    surrounding ``/`` context and emit ``(?:/.*)?/`` for ``/**/``,
    which is what gives us the zero-segment case.
    """
    import re

    out: list[str] = ["^"]
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i : i + 3] == "/**" and (i + 3 == n or pattern[i + 3] == "/"):
            if i + 3 < n and pattern[i + 3] == "/":
                # ``/**/`` — zero or more path segments plus the
                # trailing slash before the next literal segment.
                out.append("(?:/.*)?/")
                i += 4
            else:
                # ``/**`` at end — optional trailing sub-path.
                out.append("(?:/.*)?")
                i += 3
        elif pattern[i : i + 3] == "**/" and i == 0:
            # Leading ``**/`` — optional leading sub-path.
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            # Bare or non-segment-aligned ``**`` — same as ``*`` with
            # the cross-segment exemption.
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.match("".join(out), rel_path) is not None


def _scope_files(
    check: Check,
    *,
    charm_root: pathlib.Path,
    candidate_files: Sequence[pathlib.Path],
) -> list[pathlib.Path]:
    """Return the subset of *candidate_files* matching *check*'s globs.

    Empty globs means "every file is in scope" — including no files,
    which is the no-op-on-empty-checkout case.  Matching is bounded
    by :data:`_MAX_FILES_PER_CHECK` so a check with a wide glob over
    a large repo doesn't pull tens of MB into the prompt.
    """
    if not check.globs:
        return list(candidate_files)[:_MAX_FILES_PER_CHECK]

    matches = [
        f for f in candidate_files if f.is_file() and _matches_globs(f, check.globs, charm_root)
    ]
    return matches[:_MAX_FILES_PER_CHECK]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_REVIEWER_SYSTEM = (
    "You are a code-quality reviewer evaluating a single named rule "
    "against an open-source charm.  Read the rule and the supplied "
    "files, then return a JSON object that matches the CheckResult "
    "schema exactly: ``status`` is `pass` when the charm satisfies "
    "the rule and `fail` when it does not.  Quote the smallest "
    "evidence excerpt that justifies your verdict.  Do not invent "
    "files or rules outside the supplied context."
)


async def run_check(
    check: Check,
    *,
    provider: LLMProvider,
    charm_root: pathlib.Path,
    files: Sequence[pathlib.Path],
) -> CheckResult:
    """Run *check* once against *files* and return a structured verdict.

    The model receives a system prompt that names the schema, a user
    prompt that quotes the rule body and the file contents (capped
    by :data:`_MAX_FILE_BYTES_PER_CHECK` per file), and a
    ``response_schema`` that pins the reply shape.  Errors at any
    stage — no files in scope, LLM call failed, schema violation —
    surface as a :class:`CheckResult` with a non-``fail`` status so
    the report can still render.
    """
    if not files:
        return CheckResult(
            name=check.name,
            status="skipped",
            severity=check.severity,
            message="No files in scope for this check.",
            source=check.source,
        )

    user_prompt = _build_user_prompt(check, files=files, charm_root=charm_root)
    messages = [
        Message(role=Role.SYSTEM, content=_REVIEWER_SYSTEM),
        Message(role=Role.USER, content=user_prompt),
    ]

    try:
        payload = await complete_structured(
            provider,
            messages,
            schemas.CHECK_RESULT,
            temperature=0.2,  # judgement task — keep it tight
        )
    except StructuredOutputError as exc:
        log.warning("Check %s could not validate response: %s", check.name, exc)
        return CheckResult(
            name=check.name,
            status="error",
            severity=check.severity,
            message=f"Model output did not match schema: {exc}",
            source=check.source,
        )
    except (RuntimeError, OSError, TimeoutError) as exc:
        log.warning("Check %s LLM call failed: %s", check.name, exc)
        return CheckResult(
            name=check.name,
            status="error",
            severity=check.severity,
            message=f"LLM call failed: {exc}",
            source=check.source,
        )

    return _result_from_payload(check, payload)


def _result_from_payload(check: Check, payload: dict[str, Any]) -> CheckResult:
    """Convert a CHECK_RESULT-shaped dict into a :class:`CheckResult`.

    ``severity`` falls back to the rule's declared severity when the
    model omits or mistypes it — the rule author's intent wins over
    a model that doesn't pay attention to defaults.
    """
    status = str(payload.get("status", "error"))
    if status not in ("pass", "fail"):
        status = "error"

    severity = str(payload.get("severity") or check.severity).lower()
    if severity not in _SEVERITIES:
        severity = check.severity

    return CheckResult(
        name=check.name,
        status=status,
        severity=severity,
        message=str(payload.get("message", "")),
        evidence=_optional_str(payload.get("evidence")),
        suggested_fix=_optional_str(payload.get("suggested_fix")),
        source=check.source,
    )


def _optional_str(value: object) -> str | None:
    """Coerce a JSON value into ``str | None``, dropping empty strings."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_user_prompt(
    check: Check,
    *,
    files: Sequence[pathlib.Path],
    charm_root: pathlib.Path,
) -> str:
    """Assemble the user-message text — rule body plus quoted file contents."""
    parts: list[str] = [
        f"# Rule: {check.name}",
        f"_{check.description}_",
        "",
        "## Rule body",
        check.body,
        "",
        "## Files in scope",
    ]
    for path in files:
        try:
            rel = path.relative_to(charm_root)
        except ValueError:
            rel = path
        try:
            content = path.read_text(errors="replace")
        except OSError as exc:
            parts.append(f"### {rel}\n\n_Could not read: {exc}_\n")
            continue
        if len(content) > _MAX_FILE_BYTES_PER_CHECK:
            content = content[:_MAX_FILE_BYTES_PER_CHECK] + "\n…[truncated]"
        parts.append(f"### {rel}\n\n```\n{content}\n```\n")

    parts.append(
        "Return a JSON object matching the CheckResult schema with "
        "``status`` (`pass` or `fail`), ``severity``, ``message``, "
        "and — when relevant — ``evidence`` and ``suggested_fix``."
    )
    return "\n".join(parts)


async def run_all_checks(
    checks: Iterable[Check],
    *,
    provider: LLMProvider,
    charm_root: pathlib.Path,
    candidate_files: Sequence[pathlib.Path] | None = None,
    shadows: Sequence[str] = (),
) -> CheckReport:
    """Run every check sequentially and aggregate results.

    Sequential rather than concurrent because rate limits + cost
    dominate over wall-clock here — a charm review that takes 90s
    instead of 30s is fine, a 429 storm is not.  Future versions
    may opt into concurrency once the rate limiter (Phase 31) is
    aware of structured-output cost.
    """
    if candidate_files is None:
        candidate_files = _enumerate_charm_files(charm_root)

    results: list[CheckResult] = []
    for check in checks:
        scoped = _scope_files(check, charm_root=charm_root, candidate_files=candidate_files)
        result = await run_check(
            check,
            provider=provider,
            charm_root=charm_root,
            files=scoped,
        )
        results.append(result)

    return CheckReport(results=tuple(results), shadows=tuple(shadows))


def _enumerate_charm_files(charm_root: pathlib.Path) -> list[pathlib.Path]:
    """Return source / config / docs files worth offering to checks.

    Skips obvious build artefacts (``.git``, ``.cantrip``,
    ``__pycache__``, ``.venv``, ``build``, ``dist``) so the prompt
    isn't padded with junk.  Cap at a couple of thousand entries
    per pass — well above any realistic charm but well below "scan
    the entire mono-repo accidentally pointed at a charm dir".
    """
    skip_dirs = {".git", ".cantrip", "__pycache__", ".venv", "build", "dist", "node_modules"}
    files: list[pathlib.Path] = []
    for entry in charm_root.rglob("*"):
        if not entry.is_file():
            continue
        if any(part in skip_dirs for part in entry.parts):
            continue
        files.append(entry)
        if len(files) >= 2000:
            break
    return files
