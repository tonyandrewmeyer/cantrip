"""Design proposal data structures and parsing."""

import re
from dataclasses import dataclass, field


@dataclass
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
    integrations: list[str] = field(default_factory=list)
    config_options: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    scaling_strategy: str = ""
    operational_patterns: str = ""
    questions_for_user: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
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

        if self.questions_for_user:
            items = "\n".join(f"- {q}" for q in self.questions_for_user)
            sections.append(f"**Questions:**\n{items}")

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
    proposal.questions_for_user = _get_list(heading_map, "questions")
    proposal.sources = _get_list(heading_map, "sources")

    return proposal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_heading_sections(text: str) -> dict[str, str]:
    """Split Markdown text into a map of lowercase heading → body content."""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        heading_match = re.match(r"^#{1,3}\s+(.+)", line)
        if heading_match:
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(1).strip().lower()
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
