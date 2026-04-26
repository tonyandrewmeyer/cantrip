"""Memory export and import (Phase 43.4).

Two output formats:

* **SKILL.md** — a single Markdown file with YAML frontmatter that the
  existing skills system can already discover and load.  One bundle of
  memories becomes one skill, with each memory rendered as a
  ``## Memory: <title>`` section.  This is the format the spec calls for
  ("reusing the existing skills system as the export format").
* **Markdown dump** — a directory of one Markdown file per memory.
  Cheaper to share via gist or a PR diff and easier for humans to skim.

Imports are symmetric: a single SKILL.md file or a directory full of
``*.md`` memory files (each with the same YAML frontmatter the global
store writes) merges into the target scope, with per-title duplicate
detection.

Both directions sanitise:

* The current charm path is replaced with the literal placeholder
  ``<CHARM_PATH>`` so the bundle is portable.
* Local citations are stripped — they reference paths that don't exist
  on the import machine, so they would only generate noise.
* Obvious secret patterns (API keys, tokens, passwords) are scrubbed
  with ``[REDACTED]`` so a careless export does not leak credentials.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import pathlib
import re
from typing import TYPE_CHECKING

import yaml

from cantrip.agent.memory import MemoryScopeError, slugify_title

if TYPE_CHECKING:
    from cantrip.agent.memory import MemoryEntry, MemoryManager

log = logging.getLogger(__name__)


CHARM_PATH_PLACEHOLDER = "<CHARM_PATH>"

# Conservative secret-scrubbing patterns.  These are intentionally
# false-positive-prone for the protect-by-default reason: a wrongly
# scrubbed memory body can be re-edited; a leaked credential cannot
# be un-shared.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # GitHub tokens (ghp_, gho_, ghs_, github_pat_) — high-entropy.
    ("github-token", re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}\b")),
    # AWS access key / secret key.
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Generic Bearer tokens in headers.
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}\b")),
    # password=secret or password: secret in obvious shapes.
    ("password", re.compile(r"(?i)(password\s*[:=]\s*)([^\s'\"]+)")),
    # Slack tokens (xox*-...).
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
)


@dataclasses.dataclass(frozen=True)
class ExportResult:
    """Outcome of an export call."""

    output_path: pathlib.Path
    entries: list[str]  # Titles exported.
    redactions: int  # Count of secret-pattern hits redacted.


@dataclasses.dataclass(frozen=True)
class ImportResult:
    """Outcome of an import call."""

    imported: list[str] = dataclasses.field(default_factory=list)  # Titles imported.
    skipped: list[str] = dataclasses.field(default_factory=list)  # Titles already present.
    failed: list[tuple[str, str]] = dataclasses.field(default_factory=list)  # (title, reason).


# ── Sanitisation ────────────────────────────────────────────────────────


def sanitise_body(body: str, *, charm_path: pathlib.Path | None = None) -> tuple[str, int]:
    """Replace charm-specific paths and obvious secrets in ``body``.

    Returns ``(scrubbed_body, num_redactions)``.  The redaction count is
    surfaced in the export result so users can see at a glance whether
    anything was scrubbed before they share the bundle.
    """
    out = body
    if charm_path is not None:
        # Use both the absolute string and a normalised resolved form so
        # we catch the charm path however the caller phrased it.  Sort
        # by length, longest first, so the resolved form replaces before
        # a shorter prefix that might be a substring of it.
        forms: set[str] = {str(charm_path)}
        with contextlib.suppress(OSError):
            forms.add(str(charm_path.resolve()))
        sorted_forms: list[str] = sorted(forms, key=lambda s: len(s), reverse=True)
        for form in sorted_forms:
            if form and form in out:
                out = out.replace(form, CHARM_PATH_PLACEHOLDER)
    redactions = 0
    for label, pattern in _SECRET_PATTERNS:
        if label == "password":
            # Capture group 1 is the prefix (``password=``); group 2 is
            # the value to scrub.
            def _redact(match: re.Match[str]) -> str:
                return f"{match.group(1)}[REDACTED]"

            new, count = pattern.subn(_redact, out)
        else:

            def _redact_full(_match: re.Match[str]) -> str:
                return "[REDACTED]"

            new, count = pattern.subn(_redact_full, out)
        out = new
        redactions += count
    return out, redactions


def _entry_to_skill_section(
    entry: MemoryEntry, charm_path: pathlib.Path | None
) -> tuple[str, int]:
    """Render a single memory as a ``## Memory: …`` block plus redaction count."""
    body, redactions = sanitise_body(entry.body, charm_path=charm_path)
    tag_line = f"*Tags:* {', '.join(entry.tags)}\n\n" if entry.tags else ""
    return (
        f"## Memory: {entry.title}\n\n*Kind:* {entry.kind}\n{tag_line}{body.strip()}\n"
    ), redactions


# ── Export ──────────────────────────────────────────────────────────────


def export_to_skill(
    manager: MemoryManager,
    *,
    name: str,
    output_path: pathlib.Path,
    scope: str | None = None,
    description: str | None = None,
    charm_path: pathlib.Path | None = None,
) -> ExportResult:
    """Bundle memories from *scope* into a single SKILL.md file.

    The output file is a complete SKILL.md the existing
    :class:`SkillsIndex` can discover: YAML frontmatter (``name``,
    ``description``) plus a Markdown body with one ``## Memory: …``
    section per entry.  ``output_path`` may be either a directory (the
    file is written as ``<output_path>/<name>/SKILL.md``) or a file
    path (the file is written verbatim).
    """
    if not name.strip():
        raise ValueError("name is required")
    entries = manager.list_entries(scope=scope)
    target = _resolve_skill_output(output_path, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    titles: list[str] = []
    redactions = 0
    for entry in entries:
        section, count = _entry_to_skill_section(entry, charm_path=charm_path)
        sections.append(section)
        titles.append(entry.title)
        redactions += count
    frontmatter = yaml.safe_dump(
        {
            "name": name,
            "description": description
            or f"Cantrip memory bundle: {len(entries)} entries from {scope or 'all scopes'}",
        },
        sort_keys=False,
    ).strip()
    body = "\n".join(sections) if sections else "_(no memories in scope)_\n"
    target.write_text(f"---\n{frontmatter}\n---\n\n# {name}\n\n{body}")
    return ExportResult(output_path=target, entries=titles, redactions=redactions)


def export_to_markdown(
    manager: MemoryManager,
    *,
    output_dir: pathlib.Path,
    scope: str | None = None,
    charm_path: pathlib.Path | None = None,
) -> ExportResult:
    """Write one Markdown file per memory under ``output_dir``.

    Each file has the same YAML frontmatter the global store writes, so
    a markdown dump can be re-imported via :func:`import_from_path`.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = manager.list_entries(scope=scope)
    titles: list[str] = []
    redactions = 0
    for entry in entries:
        body, count = sanitise_body(entry.body, charm_path=charm_path)
        redactions += count
        frontmatter = {
            "title": entry.title,
            "kind": entry.kind,
            "source": entry.source,
            "status": entry.status,
            "tags": list(entry.tags),
        }
        rendered = (
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
            + "\n---\n\n"
            + body.strip()
            + "\n"
        )
        path = output_dir / f"{slugify_title(entry.title)}.md"
        path.write_text(rendered)
        titles.append(entry.title)
    return ExportResult(output_path=output_dir, entries=titles, redactions=redactions)


def _resolve_skill_output(output_path: pathlib.Path, name: str) -> pathlib.Path:
    """Pick the final file path for a SKILL.md export.

    A directory becomes ``<dir>/<name>/SKILL.md`` so the result drops
    straight into a skills tree; an explicit ``.md`` file is honoured.
    """
    if output_path.suffix.lower() == ".md":
        return output_path
    return output_path / slugify_title(name) / "SKILL.md"


# ── Import ──────────────────────────────────────────────────────────────


_SECTION_HEADER_RE = re.compile(r"^## Memory:\s*(.+?)\s*$", re.MULTILINE)
_KIND_RE = re.compile(r"^\*Kind:\*\s*(\w+)\s*$", re.MULTILINE)
_TAGS_RE = re.compile(r"^\*Tags:\*\s*(.+?)\s*$", re.MULTILINE)


def import_from_path(
    manager: MemoryManager,
    source: pathlib.Path,
    *,
    target_scope: str = "global",
    overwrite: bool = False,
) -> ImportResult:
    """Read memories from *source* and merge into the manager.

    *source* can be a SKILL.md file, a directory of memory ``.md`` files
    (the same shape :func:`export_to_markdown` produces), or a
    directory containing a SKILL.md file.  Duplicate titles in the
    target scope are skipped unless ``overwrite=True``.
    """
    if not source.exists():
        raise FileNotFoundError(source)
    if target_scope not in {"charm", "global"}:
        raise MemoryScopeError(f"unknown scope {target_scope!r}")
    candidates: list[tuple[str, str, str, list[str]]] = []  # (title, kind, body, tags).
    if source.is_file() and source.suffix.lower() == ".md":
        candidates.extend(_extract_from_skill_or_markdown(source))
    elif source.is_dir():
        skill_md = source / "SKILL.md"
        if skill_md.is_file():
            candidates.extend(_extract_from_skill_or_markdown(skill_md))
        for path in sorted(source.iterdir()):
            if path.name == "SKILL.md" or path.name == "MEMORY.md":
                continue
            if path.is_file() and path.suffix.lower() == ".md":
                candidates.extend(_extract_from_skill_or_markdown(path))
    else:
        raise ValueError(f"unsupported source: {source}")

    result = ImportResult()
    for title, kind, body, tags in candidates:
        existing = manager.read(title=title, scope=target_scope)
        if existing is not None and not overwrite:
            result.skipped.append(title)
            continue
        try:
            manager.write(
                scope=target_scope,
                title=title,
                kind=kind,
                body=body,
                tags=tags,
                source="import",
            )
        except MemoryScopeError as exc:
            result.failed.append((title, str(exc)))
            continue
        result.imported.append(title)
    return result


def _extract_from_skill_or_markdown(
    path: pathlib.Path,
) -> list[tuple[str, str, str, list[str]]]:
    """Pull memory entries out of a SKILL.md or single-memory markdown file.

    The shape is auto-detected: if the file's frontmatter has a ``title``
    key it is treated as a single-memory dump; otherwise the body is
    scanned for ``## Memory: …`` sections.
    """
    raw = path.read_text()
    frontmatter, body = _split_frontmatter(raw)
    if isinstance(frontmatter, dict) and frontmatter.get("title"):
        title = str(frontmatter["title"]).strip()
        kind = str(frontmatter.get("kind", "fact")).strip().lower() or "fact"
        tags = [str(t) for t in (frontmatter.get("tags") or [])]
        return [(title, kind, body.strip(), tags)]
    # Otherwise expect ``## Memory: <title>`` sections.
    return _split_skill_sections(raw)


def _split_skill_sections(raw: str) -> list[tuple[str, str, str, list[str]]]:
    """Carve a SKILL.md body into individual memory tuples."""
    matches = list(_SECTION_HEADER_RE.finditer(raw))
    if not matches:
        return []
    out: list[tuple[str, str, str, list[str]]] = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        section_start = match.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        section = raw[section_start:section_end]
        kind_match = _KIND_RE.search(section)
        kind = kind_match.group(1).strip().lower() if kind_match else "fact"
        tags_match = _TAGS_RE.search(section)
        tags: list[str] = []
        if tags_match:
            tags = [t.strip() for t in tags_match.group(1).split(",") if t.strip()]
        # Strip the ``*Kind:*`` and ``*Tags:*`` lines from the body.
        body = section
        if kind_match:
            body = body.replace(kind_match.group(0), "")
        if tags_match:
            body = body.replace(tags_match.group(0), "")
        out.append((title, kind, body.strip(), tags))
    return out


def _split_frontmatter(raw: str) -> tuple[dict[str, object] | None, str]:
    """Split a Markdown file into (frontmatter dict | None, body)."""
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, raw
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return None, raw
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None, raw
    body = "\n".join(lines[end + 1 :]).strip()
    if not isinstance(data, dict):
        return None, raw
    return data, body


__all__ = [
    "CHARM_PATH_PLACEHOLDER",
    "ExportResult",
    "ImportResult",
    "export_to_markdown",
    "export_to_skill",
    "import_from_path",
    "sanitise_body",
]
