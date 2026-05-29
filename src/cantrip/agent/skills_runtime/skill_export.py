"""Skill export to the standard SKILL.md format (Phase 50.2).

Companion to :mod:`cantrip.agent.skills_runtime.skills` (discovery / import, Phase 50.1).
The exporter re-emits a Cantrip skill as the same YAML-frontmatter + Markdown
shape the vendor-neutral Skills ecosystem uses, so an exported bundle drops
straight into ``~/.claude/skills/`` or a teammate's
``~/.config/cantrip/skills/`` and is picked up by :class:`SkillsIndex`
without translation.

Sanitisation reuses :func:`cantrip.agent.memory.export.sanitise_body` so a
shared skill is scrubbed the same way a shared memory bundle is: the current
charm path becomes ``<CHARM_PATH>`` and obvious credential shapes are
replaced with ``[REDACTED]``.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import TYPE_CHECKING

import yaml

from cantrip.agent.memory.export import sanitise_body

if TYPE_CHECKING:
    from cantrip.agent.skills_runtime.skills import SkillsIndex

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SkillExportResult:
    """Outcome of a skill export call."""

    name: str
    output_path: pathlib.Path
    redactions: int


class SkillExportError(Exception):
    """Raised when a skill cannot be exported (unknown name, target clash)."""


def export_skill(
    name: str,
    output_path: pathlib.Path,
    *,
    index: SkillsIndex,
    charm_path: pathlib.Path | None = None,
    force: bool = False,
) -> SkillExportResult:
    """Write a discovered skill to *output_path* in standard SKILL.md format.

    ``output_path`` may be either a directory (the file is written as
    ``<output_path>/<name>/SKILL.md`` — the directory-style layout) or an
    explicit ``.md`` file path (written verbatim — the single-file layout).
    Parent directories are created as needed.  Existing targets are refused
    unless ``force=True`` so an accidental overwrite does not silently
    clobber a user's file.

    ``charm_path`` feeds :func:`sanitise_body` — the current charm path
    becomes ``<CHARM_PATH>`` in the exported body so the bundle is
    portable.  Pass ``None`` to skip charm-path scrubbing (secret
    scrubbing still runs).
    """
    metadata = index.metadata_for(name)
    if metadata is None:
        known = ", ".join(sorted(s.name for s in index.list_skills()))
        raise SkillExportError(
            f"Unknown skill {name!r}. Known skills: {known}"
            if known
            else f"Unknown skill {name!r}."
        )

    body = index.load_skill(name)
    sanitised, redactions = sanitise_body(body, charm_path=charm_path)

    target = _resolve_target(output_path, name)
    if target.exists() and not force:
        raise SkillExportError(
            f"Refusing to overwrite existing file {target} (pass --force to overwrite)."
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except (NotADirectoryError, FileExistsError) as exc:
        # ``output_path`` was a regular file (or a non-directory like
        # ``/dev/null``) so the synthesised ``<output_path>/<name>``
        # parent cannot be created.  Surface a friendly error rather
        # than dumping ``NotADirectoryError`` at the user.
        raise SkillExportError(
            f"Cannot write under {output_path}: not a directory. "
            f"Pass an existing directory, or an explicit ``.md`` file path."
        ) from exc
    except OSError as exc:
        # Permission denied (e.g. ``cantrip skill export find-bugs /``)
        # or read-only filesystem.  Surface as a friendly export error
        # instead of leaking the raw ``OSError``.
        raise SkillExportError(f"Cannot create {target.parent}: {exc}") from exc

    frontmatter: dict[str, object] = {
        "name": metadata.name,
        "description": metadata.description,
    }
    if metadata.tools:
        frontmatter["tools"] = list(metadata.tools)
    if metadata.mcp_servers:
        frontmatter["mcp_servers"] = list(metadata.mcp_servers)

    rendered_frontmatter = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    target.write_text(f"---\n{rendered_frontmatter}\n---\n\n{sanitised.rstrip()}\n")

    return SkillExportResult(name=metadata.name, output_path=target, redactions=redactions)


def _resolve_target(output_path: pathlib.Path, name: str) -> pathlib.Path:
    """Pick the final file path for a skill export.

    An explicit ``.md`` path is honoured verbatim (single-file layout);
    anything else is treated as a parent directory and expanded to
    ``<dir>/<name>/SKILL.md`` so the result drops straight into a skills
    tree alongside directory-style skills.
    """
    if output_path.suffix.lower() == ".md":
        return output_path
    return output_path / name / "SKILL.md"


__all__ = [
    "SkillExportError",
    "SkillExportResult",
    "export_skill",
]
