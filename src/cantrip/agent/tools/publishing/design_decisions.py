"""Extract design decisions from the session transcript into the docs."""

import pathlib
import sqlite3
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.publishing._common import (
    _read_charm_metadata,
    generate_architecture_diagram,
)

# Marker that delimits the auto-generated section.  Anything above the
# marker is preserved across re-runs (charm-author intro); everything
# from the marker onwards gets refreshed.
_DECISIONS_MARKER = "<!-- cantrip-decisions-start -->"


def _read_decisions(db_path: pathlib.Path) -> list[dict[str, Any]]:
    """Read recorded design decisions from a Cantrip session SQLite file.

    Returns a chronologically-ordered list of ``{type, choice, reason,
    timestamp}`` dicts.  Returns an empty list when the file is missing,
    can't be opened, or doesn't have the ``decisions`` table — none of
    those should fail the documentation step.
    """
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT type, choice, reason, timestamp FROM decisions ORDER BY timestamp, id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": row["type"],
                "choice": row["choice"],
                "reason": row["reason"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def _scaffold_architecture_intro(charm_name: str, metadata: dict[str, Any]) -> str:
    """Render the same intro the docs scaffold would produce."""
    description = metadata.get("description", "")
    diagram = generate_architecture_diagram(charm_name, metadata)
    return (
        "# Architecture\n"
        "\n" + (f"{description}\n\n" if description else "") + "## Relation topology\n"
        "\n"
        "```mermaid\n"
        f"{diagram}"
        "```\n"
    )


def _resolve_architecture_intro(charm_dir: pathlib.Path) -> str:
    """Decide which intro content to put above the auto-generated decisions.

    Order of preference:

    1. ``docs/explanation/_intro.md`` — explicit charm-author override.
    2. Existing ``docs/explanation/architecture.md`` content above the
       :data:`_DECISIONS_MARKER` (everything below the marker is
       Cantrip-generated and gets refreshed).
    3. Existing ``docs/explanation/architecture.md`` with no marker —
       treated as fully user-authored, preserved verbatim.
    4. The scaffold's default intro (charm description + Mermaid
       relation diagram).
    """
    intro_path = charm_dir / "docs" / "explanation" / "_intro.md"
    if intro_path.is_file():
        return intro_path.read_text()

    arch_path = charm_dir / "docs" / "explanation" / "architecture.md"
    if arch_path.is_file():
        existing = arch_path.read_text()
        if _DECISIONS_MARKER in existing:
            return existing.split(_DECISIONS_MARKER, 1)[0]
        return existing

    metadata = _read_charm_metadata(charm_dir)
    charm_name = metadata.get("name", charm_dir.name)
    return _scaffold_architecture_intro(charm_name, metadata)


def _humanise_decision_type(type_label: str) -> str:
    """Render a snake_case decision type as a Title Case heading fragment."""
    # ``charm_path`` → ``Charm Path``; ``substrate`` → ``Substrate``.
    return " ".join(word.capitalize() for word in type_label.replace("-", "_").split("_"))


def format_decision_log(decisions: list[dict[str, Any]]) -> str:
    """Render *decisions* as a Markdown ``## Design decisions`` section.

    Each decision becomes a numbered ``###`` block with Decision, Recorded,
    Rationale, and Citation sub-fields when those values are present.
    Empty input yields a placeholder explaining that no decisions are
    recorded yet, so the page is still well-formed.
    """
    if not decisions:
        return (
            "## Design decisions\n"
            "\n"
            "No design decisions have been recorded yet.  This section "
            "fills in as the agent works through the design phase — "
            "substrate choice, charm path (12-Factor / Custom / "
            "Infrastructure), and any Charmhub recommendations land here "
            "with the rationale that drove them.\n"
        )

    lines = ["## Design decisions", ""]
    for index, decision in enumerate(decisions, start=1):
        type_label = _humanise_decision_type(decision["type"])
        lines.append(f"### {index}. {type_label}: {decision['choice']}")
        lines.append("")
        lines.append(f"- **Decision:** {decision['choice']}")
        if decision.get("timestamp"):
            lines.append(f"- **Recorded:** {decision['timestamp']}")
        lines.append(f"- **Citation:** session decisions table, entry {index}")
        if decision.get("reason"):
            lines.append("")
            lines.append(f"**Rationale:** {decision['reason']}")
        lines.append("")
    return "\n".join(lines)


def _compose_architecture_page(intro: str, decisions: list[dict[str, Any]]) -> str:
    """Stitch the intro and the auto-generated decision log together."""
    body = format_decision_log(decisions)
    intro = intro.rstrip()
    if not intro:
        intro = "# Architecture\n"
    return intro + "\n\n" + _DECISIONS_MARKER + "\n\n" + body


class ExtractDesignDecisionsTool(Tool):
    """Refresh ``docs/explanation/architecture.md`` with the chronological
    decision log mined from the session transcript.
    """

    @property
    def name(self) -> str:
        return "extract_design_decisions"

    @property
    def description(self) -> str:
        return (
            "Extract design decisions from the Cantrip session transcript "
            "(.cantrip SQLite) and render them as a chronological build "
            "log in docs/explanation/architecture.md.  Preserves any "
            "charm-author intro (docs/explanation/_intro.md or content "
            "above the cantrip-decisions-start marker)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "db_path": {
                    "type": "string",
                    "description": (
                        "Optional override for the .cantrip session-store "
                        "path.  Defaults to <path>/.cantrip."
                    ),
                },
            },
        }

    async def execute(self, path: str = ".", db_path: str | None = None) -> ToolResult:
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        store_path = pathlib.Path(db_path).expanduser() if db_path else charm_dir / ".cantrip"
        decisions = _read_decisions(store_path)
        intro = _resolve_architecture_intro(charm_dir)
        content = _compose_architecture_page(intro, decisions)

        target = charm_dir / "docs" / "explanation" / "architecture.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        summary = f"Refreshed {target.relative_to(charm_dir)} with {len(decisions)} decision(s)."
        if not decisions:
            summary += (
                "  No decisions recorded yet — the section explains "
                "that and refreshes when decisions land."
            )
        return ToolResult(
            success=True,
            output=summary,
            data={
                "path": str(target),
                "decision_count": len(decisions),
                "store_path": str(store_path),
            },
            caption=f"{len(decisions)} decision{'s' if len(decisions) != 1 else ''}",
        )
