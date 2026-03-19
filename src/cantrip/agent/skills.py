"""Skills discovery and loading following the agentskills.io pattern."""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Default location of bundled skill definitions.
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Separator between YAML frontmatter and Markdown body in SKILL.md files.
_FRONTMATTER_DELIMITER = "---"


@dataclass
class SkillMetadata:
    """Lightweight metadata for a single skill."""

    name: str
    description: str
    path: Path


class SkillsIndex:
    """Discovers, indexes, and loads agent skills from SKILL.md files.

    The index is kept lightweight — only names and descriptions are held in
    memory.  Full skill content is loaded on demand via :meth:`load_skill`.
    """

    def __init__(self, skills_dir: Path = _DEFAULT_SKILLS_DIR) -> None:
        self._skills_dir = skills_dir
        self._skills: dict[str, SkillMetadata] = {}

    def discover(self) -> None:
        """Scan the skills directory for SKILL.md files and index them."""
        self._skills.clear()

        if not self._skills_dir.is_dir():
            log.warning("Skills directory does not exist: %s", self._skills_dir)
            return

        for child in sorted(self._skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue

            try:
                metadata = self._parse_frontmatter(skill_file)
            except (yaml.YAMLError, ValueError):
                log.warning("Skipping malformed skill file: %s", skill_file)
                continue

            self._skills[metadata.name] = metadata
            log.debug("Discovered skill: %s", metadata.name)

    def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for all discovered skills, sorted by name."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    def load_skill(self, name: str) -> str:
        """Load the full body content of a skill by name.

        Raises:
            KeyError: If no skill with the given name exists.
        """
        metadata = self._skills.get(name)
        if metadata is None:
            raise KeyError(name)

        raw = metadata.path.read_text()
        return self._extract_body(raw)

    def format_for_prompt(self) -> str:
        """Render an XML block listing all skills for inclusion in a system prompt."""
        if not self._skills:
            return ""

        lines = ["<available_skills>"]
        for skill in self.list_skills():
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{skill.description}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(path: Path) -> SkillMetadata:
        """Parse YAML frontmatter from a SKILL.md file.

        Expects the file to start with ``---``, followed by YAML, followed
        by a closing ``---``.
        """
        raw = path.read_text()
        lines = raw.split("\n")

        if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
            raise ValueError(f"Missing opening frontmatter delimiter in {path}")

        # Find the closing delimiter.
        end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == _FRONTMATTER_DELIMITER:
                end = i
                break

        if end is None:
            raise ValueError(f"Missing closing frontmatter delimiter in {path}")

        frontmatter_text = "\n".join(lines[1:end])
        data = yaml.safe_load(frontmatter_text)

        if not data or not isinstance(data, dict):
            raise ValueError(f"Frontmatter is not a mapping in {path}")

        name = data.get("name")
        description = data.get("description")
        if not name or not description:
            raise ValueError(f"Frontmatter must contain 'name' and 'description' in {path}")

        return SkillMetadata(name=str(name), description=str(description), path=path)

    @staticmethod
    def _extract_body(raw: str) -> str:
        """Return the Markdown body after the YAML frontmatter."""
        lines = raw.split("\n")

        if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
            return raw

        end = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == _FRONTMATTER_DELIMITER:
                end = i
                break

        if end is None:
            return raw

        return "\n".join(lines[end + 1 :]).strip()
