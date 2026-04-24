"""Skills discovery and loading following the agentskills.io pattern."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Default location of bundled skill definitions.
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Separator between YAML frontmatter and Markdown body in SKILL.md files.
_FRONTMATTER_DELIMITER = "---"

# Source tags so callers (and logs) can tell where a skill came from.
SOURCE_BUNDLED = "bundled"
SOURCE_EXTERNAL = "external"


@dataclass
class SkillMetadata:
    """Lightweight metadata for a single skill."""

    name: str
    description: str
    path: Path
    # Tag telling which root directory the skill was discovered in.
    # Bundled skills ship with Cantrip; external skills come from
    # ``~/.claude/skills/`` or ``~/.config/cantrip/skills/``.
    source: str = SOURCE_BUNDLED
    # Optional tool allowlist declared in the skill's frontmatter.
    # Preserved for cross-vendor skill round-tripping; the loader
    # does not enforce it.
    tools: list[str] = field(default_factory=list)
    # Optional MCP server dependencies (Phase 50.4).  Names here are
    # checked against the configured ``MCPRegistry`` at load time;
    # ``LoadSkillTool`` prepends a clear warning banner when any
    # declared server is not configured, so a skill that relies on
    # ``filesystem`` tools from an MCP server degrades gracefully
    # rather than silently producing nonsense when the server is
    # missing.  Accepts a YAML list or a comma-separated string in
    # frontmatter — the same coercion that applies to ``tools``.
    mcp_servers: list[str] = field(default_factory=list)


def _default_external_skill_dirs() -> list[Path]:
    """Return the user-scoped skill directories searched by default.

    Order matters: later directories override earlier ones on name
    conflict.  The principle is *most-shared → most-specific*:

    - ``~/.config/agents/skills/`` is the ``universal`` bucket
      ``gh skill install --scope user`` writes into when no agent is
      named; it's also shared by several individual agents (opencode,
      kimi-cli, warp, replit).  Least specific, so indexed first.
    - ``~/.claude/skills/`` is the Claude Code user-scope dir (and the
      Claude Code convention a chunk of the vendor-neutral ecosystem
      follows).  More specific — a Cantrip user deliberately using
      this location wants it to beat the universal dir.
    - ``~/.config/cantrip/skills/`` is Cantrip-specific, so it takes
      precedence over both shared locations when a user wants to
      override.
    """
    home = Path.home()
    return [
        home / ".config" / "agents" / "skills",
        home / ".claude" / "skills",
        home / ".config" / "cantrip" / "skills",
    ]


def _default_project_skill_dirs(project_root: Path) -> list[Path]:
    """Return project-scoped skill directories for a charm repo.

    These correspond to the paths ``gh skill install`` writes into
    when run without ``--scope user`` (the default is project scope).
    ``.agents/skills/`` is the shared project dir for ~20 agents;
    ``.claude/skills/`` is Claude Code's project dir.  Project-scope
    paths are the most specific — they win over user-scope conflicts.
    """
    return [
        project_root / ".agents" / "skills",
        project_root / ".claude" / "skills",
    ]


class SkillsIndex:
    """Discovers, indexes, and loads agent skills from SKILL.md files.

    The index is kept lightweight — only names and descriptions are held in
    memory.  Full skill content is loaded on demand via :meth:`load_skill`.

    Two on-disk layouts are accepted, matching the vendor-neutral Skills
    ecosystem (Claude Code, ``gh skill``, Cursor, and friends):

    - ``<root>/<name>/SKILL.md`` — directory-style (the bundled Cantrip
      skills and the Claude Code convention).
    - ``<root>/<name>.md`` — single-file style (Cantrip user skills, and
      some Claude Code plugin bundles).

    Discovery iterates the roots in insertion order; the last root to
    provide a given skill name wins, so Cantrip-specific user
    directories take precedence over shared ones, which in turn take
    precedence over the bundled set.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        *,
        extra_dirs: Iterable[Path] | None = None,
        project_root: Path | None = None,
    ) -> None:
        """Build an index.

        - ``skills_dir=None`` (default): the bundled directory is used as
          the baseline and the result of :func:`_default_external_skill_dirs`
          is appended.  This is the production configuration.
        - ``skills_dir=<path>``: the given directory is used as the
          baseline **instead of** the bundled one, and no external dirs
          are added by default — so unit tests passing a ``tmp_path``
          get a fully isolated index.
        - ``extra_dirs=...`` may be supplied in either mode to override
          or extend the set of external directories; pass ``[]`` to
          explicitly disable external discovery even in default mode.
        - ``project_root=<charm_path>``: when set, project-scope
          directories (``<root>/.agents/skills/`` and
          ``<root>/.claude/skills/``) are appended *after* the
          user-scope dirs.  This is how ``gh skill install`` (default
          ``--scope project``) ships skills into a charm repo.
          Project-scope paths are the most specific — they win over
          any user-scope conflict.
        """
        if skills_dir is None:
            baseline: list[Path] = [_DEFAULT_SKILLS_DIR]
            if extra_dirs is None:
                baseline.extend(_default_external_skill_dirs())
            else:
                baseline.extend(extra_dirs)
        else:
            baseline = [skills_dir]
            if extra_dirs:
                baseline.extend(extra_dirs)

        if project_root is not None:
            baseline.extend(_default_project_skill_dirs(project_root))

        # Preserve the baseline order for precedence decisions.
        self._skills_dirs: list[Path] = baseline
        # Retained for backwards compatibility with tests that introspect
        # the single-directory constructor.  New code should not rely on it.
        self._skills_dir: Path = baseline[0]
        self._skills: dict[str, SkillMetadata] = {}

    def discover(self) -> None:
        """Scan every configured skills directory and index what's there.

        On name collision, the later directory wins.  Missing or
        non-existent directories are silently skipped — external
        directories are optional, so a missing ``~/.claude/skills/`` is
        not a warning.
        """
        self._skills.clear()

        bundled_root = self._skills_dirs[0]
        for root in self._skills_dirs:
            if not root.is_dir():
                # Missing bundled dir is a real problem; missing external
                # dirs are routine.  Use the directory identity to decide.
                if root == bundled_root:
                    log.warning("Skills directory does not exist: %s", root)
                else:
                    log.debug("Skipping missing external skills dir: %s", root)
                continue

            source = SOURCE_BUNDLED if root == bundled_root else SOURCE_EXTERNAL
            self._discover_one_root(root, source)

    def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for all discovered skills, sorted by name."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    def metadata_for(self, name: str) -> SkillMetadata | None:
        """Return the metadata for *name*, or ``None`` if no such skill is indexed."""
        return self._skills.get(name)

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
        """Render an XML block listing all skills for inclusion in a system prompt.

        Skills with declared MCP server dependencies (Phase 50.4) get a
        ``<required_mcp_servers>`` child element so the LLM can tell at
        the index level which skills need extra infrastructure.  The
        per-server availability check still happens in
        ``LoadSkillTool`` — the prompt index doesn't filter, it just
        informs.
        """
        if not self._skills:
            return ""

        lines = ["<available_skills>"]
        for skill in self.list_skills():
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{skill.description}</description>")
            if skill.mcp_servers:
                joined = ", ".join(skill.mcp_servers)
                lines.append(f"    <required_mcp_servers>{joined}</required_mcp_servers>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_one_root(self, root: Path, source: str) -> None:
        """Index every skill found directly under *root*."""
        for child in sorted(root.iterdir()):
            skill_file = self._resolve_skill_file(child)
            if skill_file is None:
                continue

            try:
                metadata = self._parse_frontmatter(skill_file, source=source)
            except (yaml.YAMLError, ValueError):
                log.warning("Skipping malformed skill file: %s", skill_file)
                continue

            if metadata.name in self._skills:
                prior = self._skills[metadata.name]
                log.info(
                    "Skill %r from %s overrides %s at %s",
                    metadata.name,
                    metadata.path,
                    prior.source,
                    prior.path,
                )
            self._skills[metadata.name] = metadata
            log.debug("Discovered skill: %s (from %s)", metadata.name, source)

    @staticmethod
    def _resolve_skill_file(child: Path) -> Path | None:
        """Return the SKILL.md / single-file path for *child*, or ``None``.

        ``<child>/SKILL.md`` wins over a bare ``.md`` file: if both shapes
        exist with the same basename in the same root, the
        directory-with-SKILL.md form is the one the directory sort
        surfaces first, so this function never sees the ``.md`` in that
        case.
        """
        if child.is_dir():
            skill_file = child / "SKILL.md"
            return skill_file if skill_file.is_file() else None
        if child.is_file() and child.suffix == ".md" and child.name != "SKILL.md":
            return child
        return None

    @staticmethod
    def _parse_frontmatter(path: Path, source: str = SOURCE_BUNDLED) -> SkillMetadata:
        """Parse YAML frontmatter from a SKILL.md or single-file skill.

        Expects the file to start with ``---``, followed by YAML, followed
        by a closing ``---``.  ``tools`` is accepted as either a YAML
        list or a comma-separated string (the Claude Code frontmatter
        shape).
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

        tools = _coerce_string_list(data.get("tools"))
        mcp_servers = _coerce_string_list(data.get("mcp_servers"))

        return SkillMetadata(
            name=str(name),
            description=str(description),
            path=path,
            source=source,
            tools=tools,
            mcp_servers=mcp_servers,
        )

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


def _coerce_string_list(value: object) -> list[str]:
    """Normalise a frontmatter list-of-strings entry into ``list[str]``.

    Shared between the ``tools`` and ``mcp_servers`` frontmatter
    fields.  Accepts a list (typical Cantrip shape), a comma-separated
    string (Claude Code's shape for ``tools``, and a natural shorthand
    for the single-server case in ``mcp_servers``), or ``None``.
    Anything else becomes an empty list so malformed entries don't
    derail discovery.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


# Legacy internal name — kept as an alias so any stale import path keeps
# working.  Prefer ``_coerce_string_list`` in new code.
_coerce_tools = _coerce_string_list
