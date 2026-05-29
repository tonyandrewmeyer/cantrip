"""Design proposal data structures and parsing."""

import dataclasses
import re


@dataclasses.dataclass
class CompanionCharm:
    """A companion charm that should be co-deployed with the primary charm.

    Parsed from the ``## Companion charms`` section of a design proposal.
    Each entry identifies a Charmhub charm, the endpoint to relate through,
    and the Juju interface used.
    """

    charm_name: str
    endpoint: str
    interface: str


@dataclasses.dataclass
class DesignQuestion:
    """A single design question with suggested answers.

    The synthesis subagent produces questions with 2-3 suggested answers
    so the TUI can present them interactively one at a time.
    """

    key: str
    text: str
    suggestions: list[str] = dataclasses.field(default_factory=list)
    answer: str | None = None


@dataclasses.dataclass
class DesignProposal:
    """Structured design proposal extracted from a synthesis task result.

    Fields are best-effort parsed from the task result Markdown.  The
    ``raw_design_md`` always contains the full text, regardless of how
    well the structured fields were extracted.
    """

    workload_name: str = ""
    substrate: str = ""
    substrate_reasoning: str = ""
    charm_path: str = ""
    charm_path_reasoning: str = ""
    charmhub_recommendation: str = ""
    charmhub_details: str = ""
    integrations: list[str] = dataclasses.field(default_factory=list)
    config_options: list[str] = dataclasses.field(default_factory=list)
    actions: list[str] = dataclasses.field(default_factory=list)
    scaling_strategy: str = ""
    operational_patterns: str = ""
    questions_for_user: list[DesignQuestion] = dataclasses.field(default_factory=list)
    security_surface: list[str] = dataclasses.field(default_factory=list)
    security_event_types: list[str] = dataclasses.field(default_factory=list)
    companions: list[CompanionCharm] = dataclasses.field(default_factory=list)
    sources: list[str] = dataclasses.field(default_factory=list)
    raw_design_md: str = ""

    def format_for_chat(self) -> str:
        """Format the proposal as structured Markdown for the chat panel."""
        sections: list[str] = []

        heading = self.workload_name or "Design Proposal"
        sections.append(f"# {heading}")

        if self.substrate:
            line = f"**Substrate:** {self.substrate}"
            if self.substrate_reasoning:
                line += f" — {self.substrate_reasoning}"
            sections.append(line)

        if self.charm_path:
            line = f"**Charm path:** {self.charm_path}"
            if self.charm_path_reasoning:
                line += f" — {self.charm_path_reasoning}"
            sections.append(line)

        if self.charmhub_recommendation:
            line = f"**Charmhub:** {self.charmhub_recommendation}"
            if self.charmhub_details:
                line += f"\n{self.charmhub_details}"
            sections.append(line)

        if self.integrations:
            items = "\n".join(f"- {i}" for i in self.integrations)
            sections.append(f"**Integrations:**\n{items}")

        if self.companions:
            items = "\n".join(
                f"- {c.charm_name} via `{c.endpoint}` ({c.interface})" for c in self.companions
            )
            sections.append(f"**Companion charms:**\n{items}")

        if self.config_options:
            items = "\n".join(f"- {c}" for c in self.config_options)
            sections.append(f"**Config options:**\n{items}")

        if self.actions:
            items = "\n".join(f"- {a}" for a in self.actions)
            sections.append(f"**Actions:**\n{items}")

        if self.scaling_strategy:
            sections.append(f"**Scaling:** {self.scaling_strategy}")

        if self.operational_patterns:
            sections.append(f"**Operational patterns:**\n{self.operational_patterns}")

        if self.security_surface:
            items = "\n".join(f"- {s}" for s in self.security_surface)
            sections.append(f"**Security surface:**\n{items}")

        if self.questions_for_user:
            items = []
            for q in self.questions_for_user:
                line = f"- **{q.key}**: {q.text}"
                for s in q.suggestions:
                    line += f"\n  - {s}"
                items.append(line)
            sections.append("**Questions:**\n" + "\n".join(items))

        if self.sources:
            items = "\n".join(f"- {s}" for s in self.sources)
            sections.append(f"**Sources:**\n{items}")

        return "\n\n".join(sections)

    def to_design_md(self) -> str:
        """Return the raw DESIGN.md content for downstream consumption."""
        return self.raw_design_md


def parse_design_from_result(text: str) -> DesignProposal:
    """Best-effort heading-based parser for a design proposal result.

    Extracts structured fields from the task result Markdown by
    matching common heading patterns.  Always preserves the raw text.
    """
    proposal = DesignProposal(raw_design_md=text)

    # Extract workload name from the first H1 heading.
    h1 = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if h1:
        proposal.workload_name = h1.group(1).strip()

    # Build a map of heading → content for heading-based extraction.
    heading_map = _extract_heading_sections(text)

    proposal.substrate = _get_field(heading_map, "substrate")
    proposal.substrate_reasoning = _get_field(heading_map, "substrate reasoning")
    proposal.charm_path = _get_field(heading_map, "charm path")
    proposal.charm_path_reasoning = _get_field(heading_map, "charm path reasoning")
    proposal.charmhub_recommendation = _get_field(heading_map, "charmhub")
    proposal.charmhub_details = _get_field(heading_map, "charmhub details")
    proposal.integrations = _get_list(heading_map, "integrations")
    proposal.config_options = _get_list(heading_map, "config")
    proposal.actions = _get_list(heading_map, "actions")
    proposal.scaling_strategy = _get_field(heading_map, "scaling")
    proposal.operational_patterns = _get_field(heading_map, "operational")
    proposal.security_surface = _get_list(heading_map, "security surface")
    proposal.security_event_types = _get_list(heading_map, "security event")
    proposal.questions_for_user = _get_questions(heading_map, "questions")
    proposal.companions = _get_companions(heading_map)
    proposal.sources = _get_list(heading_map, "sources")

    return proposal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_heading_sections(text: str) -> dict[str, str]:
    """Split Markdown text into a map of lowercase heading → body content.

    Only ``##``/``###`` content sections are recorded.  The H1 heading is
    the document title (the workload name) — keeping it out of the map
    stops a title such as ``# myconfig-app`` from shadowing the real
    ``## Config`` section, since :func:`_get_field` matches by substring.
    """
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        heading_match = re.match(r"^(#{1,3})\s+(.+)", line)
        if heading_match:
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            # An H1 is the title, not a content section: treat it as a
            # boundary that discards any preamble but is not retrievable.
            if len(heading_match.group(1)) == 1:
                current_heading = ""
            else:
                current_heading = heading_match.group(2).strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def _get_field(heading_map: dict[str, str], key: str) -> str:
    """Find a heading whose lowercase name contains *key* and return its body."""
    key_lower = key.lower()
    for heading, body in heading_map.items():
        if key_lower in heading:
            return body
    return ""


def _get_list(heading_map: dict[str, str], key: str) -> list[str]:
    """Extract a bullet list from the section matching *key*."""
    body = _get_field(heading_map, key)
    if not body:
        return []
    items: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip())
    return items


_COMPANION_RE = re.compile(r"^[-*]\s+(\S+)\s+via\s+`?(\S+?)`?\s+\(([^)]+)\)\s*$")


def _get_companions(heading_map: dict[str, str]) -> list[CompanionCharm]:
    """Extract companion charm entries from the section matching 'companion'.

    Expected line format: ``- <charm-name> via <endpoint> (<interface>)``
    Lines that do not match the pattern are silently skipped.
    """
    body = _get_field(heading_map, "companion")
    if not body:
        return []
    companions: list[CompanionCharm] = []
    for line in body.split("\n"):
        match = _COMPANION_RE.match(line.strip())
        if match:
            companions.append(
                CompanionCharm(
                    charm_name=match.group(1),
                    endpoint=match.group(2),
                    interface=match.group(3),
                )
            )
    return companions


def _get_questions(heading_map: dict[str, str], key: str) -> list[DesignQuestion]:
    """Extract structured questions with suggestions from the section matching *key*.

    Expects top-level bullets as questions (optionally with a **key**: prefix)
    and indented sub-bullets as suggested answers.
    """
    body = _get_field(heading_map, key)
    if not body:
        return []

    questions: list[DesignQuestion] = []
    current_q: DesignQuestion | None = None

    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Indented sub-bullet — suggestion for the current question.
        # Must check before top-level to avoid matching indented lines.
        if (
            current_q is not None
            and line != line.lstrip()
            and (stripped.startswith("- ") or stripped.startswith("* "))
        ):
            current_q.suggestions.append(stripped[2:].strip())
        # Top-level bullet — new question (no leading whitespace).
        elif line == line.lstrip() and (stripped.startswith("- ") or stripped.startswith("* ")):
            raw = stripped[2:].strip()
            q_key, q_text = _split_question_key(raw)
            current_q = DesignQuestion(key=q_key, text=q_text)
            questions.append(current_q)

    return questions


def _split_question_key(raw: str) -> tuple[str, str]:
    """Split a ``**key**: text`` pattern into (key, text).

    Falls back to generating a slug from the first few words if no bold
    key prefix is found.
    """
    # Match **key**: text or **key** — text.
    match = re.match(r"\*\*(.+?)\*\*\s*[:—–-]\s*(.*)", raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    # No bold prefix — use first few words as key.
    words = raw.split()
    key = "-".join(words[:3]).lower().rstrip("?:,.")
    return key, raw
