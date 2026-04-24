"""Tests for Phase 74.3 — extracting design decisions from the session
transcript and rendering them as a build log in
``docs/explanation/architecture.md``.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools.publishing import (
    _DECISIONS_MARKER,
    ExtractDesignDecisionsTool,
    _compose_architecture_page,
    _read_decisions,
    _resolve_architecture_intro,
    format_decision_log,
)

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def temp_charm():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def _write_decisions(db_path: Path, decisions: list[dict[str, str]]) -> None:
    """Write a minimal Cantrip-shaped SQLite store with the supplied decisions."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "type TEXT NOT NULL, choice TEXT NOT NULL, reason TEXT, timestamp TEXT NOT NULL)"
        )
        for decision in decisions:
            conn.execute(
                "INSERT INTO decisions (type, choice, reason, timestamp) VALUES (?, ?, ?, ?)",
                (
                    decision["type"],
                    decision["choice"],
                    decision.get("reason"),
                    decision["timestamp"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# _read_decisions
# ===========================================================================


class TestReadDecisions:
    def test_missing_db_returns_empty(self, temp_charm) -> None:
        assert _read_decisions(temp_charm / ".cantrip") == []

    def test_db_without_decisions_table(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE foo (id INTEGER)")
        conn.close()
        # Missing decisions table → empty list rather than an exception.
        assert _read_decisions(db) == []

    def test_returns_chronological_order(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        _write_decisions(
            db,
            [
                {
                    "type": "charm_path",
                    "choice": "B",
                    "reason": "custom workload",
                    "timestamp": "2026-04-23T11:00:00",
                },
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "container-native",
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )
        rows = _read_decisions(db)
        assert [r["type"] for r in rows] == ["substrate", "charm_path"]

    def test_preserves_reason_and_timestamp(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        _write_decisions(
            db,
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "container-native workload",
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )
        row = _read_decisions(db)[0]
        assert row["choice"] == "kubernetes"
        assert row["reason"] == "container-native workload"
        assert row["timestamp"] == "2026-04-23T10:00:00"


# ===========================================================================
# format_decision_log
# ===========================================================================


class TestFormatDecisionLog:
    def test_empty_decisions_renders_placeholder(self) -> None:
        out = format_decision_log([])
        assert "## Design decisions" in out
        assert "No design decisions" in out

    def test_renders_one_per_decision_in_order(self) -> None:
        decisions = [
            {
                "type": "substrate",
                "choice": "kubernetes",
                "reason": "container-native",
                "timestamp": "2026-04-23T10:00:00",
            },
            {
                "type": "charm_path",
                "choice": "B",
                "reason": "custom workload",
                "timestamp": "2026-04-23T11:00:00",
            },
        ]
        out = format_decision_log(decisions)
        assert "### 1. Substrate: kubernetes" in out
        assert "### 2. Charm Path: B" in out
        # Substrate comes before charm-path in the output.
        assert out.index("Substrate") < out.index("Charm Path")

    def test_decision_block_includes_rationale_and_citation(self) -> None:
        out = format_decision_log(
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "container-native workload",
                    "timestamp": "2026-04-23T10:00:00",
                },
            ]
        )
        assert "**Decision:** kubernetes" in out
        assert "**Recorded:** 2026-04-23T10:00:00" in out
        assert "**Citation:** session decisions table, entry 1" in out
        assert "**Rationale:** container-native workload" in out

    def test_missing_reason_omits_rationale_block(self) -> None:
        out = format_decision_log(
            [
                {
                    "type": "charmhub",
                    "choice": "redis-k8s",
                    "reason": None,
                    "timestamp": "2026-04-23T10:00:00",
                },
            ]
        )
        assert "**Rationale:**" not in out
        assert "**Decision:** redis-k8s" in out


# ===========================================================================
# _resolve_architecture_intro
# ===========================================================================


class TestResolveArchitectureIntro:
    def test_uses_intro_md_when_present(self, temp_charm) -> None:
        intro_path = temp_charm / "docs" / "explanation"
        intro_path.mkdir(parents=True)
        (intro_path / "_intro.md").write_text("# My intro\n\nCustom.\n")
        # Even when architecture.md exists, _intro.md wins.
        (intro_path / "architecture.md").write_text("# Old\n")

        result = _resolve_architecture_intro(temp_charm)
        assert result.startswith("# My intro")
        assert "Custom." in result

    def test_preserves_existing_arch_above_marker(self, temp_charm) -> None:
        path = temp_charm / "docs" / "explanation"
        path.mkdir(parents=True)
        (path / "architecture.md").write_text(
            "# Architecture\n\nCharm-author intro.\n"
            f"\n{_DECISIONS_MARKER}\n"
            "stale auto-generated content here\n"
        )

        result = _resolve_architecture_intro(temp_charm)
        assert "Charm-author intro." in result
        # The auto-section is dropped.
        assert "stale auto-generated" not in result
        assert _DECISIONS_MARKER not in result

    def test_preserves_user_authored_arch_without_marker(self, temp_charm) -> None:
        path = temp_charm / "docs" / "explanation"
        path.mkdir(parents=True)
        (path / "architecture.md").write_text("# My arch\n\nFully hand-written.\n")

        result = _resolve_architecture_intro(temp_charm)
        assert result == "# My arch\n\nFully hand-written.\n"

    def test_falls_back_to_scaffold_intro(self, temp_charm) -> None:
        (temp_charm / "charmcraft.yaml").write_text(
            "name: hello\n"
            "description: A greeting service.\n"
            "requires:\n"
            "  db:\n"
            "    interface: pgsql\n"
        )

        result = _resolve_architecture_intro(temp_charm)
        assert "# Architecture" in result
        assert "A greeting service." in result
        assert "```mermaid" in result


# ===========================================================================
# _compose_architecture_page
# ===========================================================================


class TestComposeArchitecturePage:
    def test_marker_separates_intro_and_log(self) -> None:
        page = _compose_architecture_page(
            "# Architecture\n\nIntro paragraph.\n",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": None,
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )
        assert _DECISIONS_MARKER in page
        intro_part, log_part = page.split(_DECISIONS_MARKER, 1)
        assert "Intro paragraph." in intro_part
        assert "## Design decisions" in log_part

    def test_empty_decisions_still_includes_marker(self) -> None:
        page = _compose_architecture_page("# Architecture\n", [])
        assert _DECISIONS_MARKER in page
        assert "No design decisions" in page

    def test_empty_intro_falls_back_to_default_heading(self) -> None:
        page = _compose_architecture_page("", [])
        assert page.startswith("# Architecture\n")


# ===========================================================================
# ExtractDesignDecisionsTool
# ===========================================================================


class TestExtractDesignDecisionsTool:
    @pytest.fixture
    def tool(self) -> ExtractDesignDecisionsTool:
        return ExtractDesignDecisionsTool()

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, tool) -> None:
        result = await tool.execute(path="/nonexistent/path")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_db_writes_placeholder_page(self, tool, temp_charm) -> None:
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")

        result = await tool.execute(path=str(temp_charm))

        assert result.success
        assert result.data["decision_count"] == 0
        page = (temp_charm / "docs" / "explanation" / "architecture.md").read_text()
        assert _DECISIONS_MARKER in page
        assert "No design decisions" in page
        # Scaffold intro is present (no _intro.md, no existing arch).
        assert "# Architecture" in page
        assert "```mermaid" in page

    @pytest.mark.asyncio
    async def test_writes_decision_log_from_db(self, tool, temp_charm) -> None:
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")
        _write_decisions(
            temp_charm / ".cantrip",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "container-native",
                    "timestamp": "2026-04-23T10:00:00",
                },
                {
                    "type": "charm_path",
                    "choice": "B",
                    "reason": "custom workload with bespoke logic",
                    "timestamp": "2026-04-23T10:30:00",
                },
            ],
        )

        result = await tool.execute(path=str(temp_charm))

        assert result.success
        assert result.data["decision_count"] == 2
        page = (temp_charm / "docs" / "explanation" / "architecture.md").read_text()
        assert "### 1. Substrate: kubernetes" in page
        assert "### 2. Charm Path: B" in page
        assert "container-native" in page
        assert "custom workload" in page

    @pytest.mark.asyncio
    async def test_intro_md_is_preserved(self, tool, temp_charm) -> None:
        explanation = temp_charm / "docs" / "explanation"
        explanation.mkdir(parents=True)
        (explanation / "_intro.md").write_text("# My charm\n\nAuthored by me.\n")
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")
        _write_decisions(
            temp_charm / ".cantrip",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": None,
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )

        result = await tool.execute(path=str(temp_charm))

        assert result.success
        page = (explanation / "architecture.md").read_text()
        assert page.startswith("# My charm\n\nAuthored by me.")
        assert "## Design decisions" in page

    @pytest.mark.asyncio
    async def test_rerun_only_refreshes_below_marker(self, tool, temp_charm) -> None:
        # First run: writes intro + decision log.
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")
        _write_decisions(
            temp_charm / ".cantrip",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "first reason",
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )
        await tool.execute(path=str(temp_charm))

        # User edits the intro section above the marker.
        page_path = temp_charm / "docs" / "explanation" / "architecture.md"
        original = page_path.read_text()
        intro_part, _, log_part = original.partition(_DECISIONS_MARKER)
        edited_intro = intro_part + "\n\nA paragraph the user added later.\n"
        page_path.write_text(edited_intro + _DECISIONS_MARKER + log_part)

        # Add a second decision and re-run.
        _write_decisions(
            temp_charm / ".cantrip.new",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": "first reason",
                    "timestamp": "2026-04-23T10:00:00",
                },
                {
                    "type": "charmhub",
                    "choice": "redis-k8s",
                    "reason": "stable upstream",
                    "timestamp": "2026-04-23T11:00:00",
                },
            ],
        )

        result = await tool.execute(path=str(temp_charm), db_path=str(temp_charm / ".cantrip.new"))

        assert result.success
        page = page_path.read_text()
        assert "A paragraph the user added later." in page
        assert "redis-k8s" in page
        assert result.data["decision_count"] == 2

    @pytest.mark.asyncio
    async def test_existing_user_authored_page_without_marker(self, tool, temp_charm) -> None:
        # Charm author wrote architecture.md without ever running this tool.
        # First run should preserve the whole file as intro and append the
        # decision log below a freshly-added marker.
        explanation = temp_charm / "docs" / "explanation"
        explanation.mkdir(parents=True)
        (explanation / "architecture.md").write_text(
            "# My take on this charm\n\nWritten before I knew Cantrip existed.\n"
        )
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")
        _write_decisions(
            temp_charm / ".cantrip",
            [
                {
                    "type": "substrate",
                    "choice": "kubernetes",
                    "reason": None,
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )

        await tool.execute(path=str(temp_charm))

        page = (explanation / "architecture.md").read_text()
        assert "Written before I knew Cantrip existed." in page
        assert _DECISIONS_MARKER in page
        assert "Substrate: kubernetes" in page

    @pytest.mark.asyncio
    async def test_db_path_override_used(self, tool, temp_charm) -> None:
        # Default .cantrip absent; explicit db_path points at a sibling file.
        (temp_charm / "charmcraft.yaml").write_text("name: hello\n")
        sidecar = temp_charm / "alt.cantrip"
        _write_decisions(
            sidecar,
            [
                {
                    "type": "substrate",
                    "choice": "machine",
                    "reason": "lxd target",
                    "timestamp": "2026-04-23T10:00:00",
                },
            ],
        )

        result = await tool.execute(path=str(temp_charm), db_path=str(sidecar))

        assert result.success
        page = (temp_charm / "docs" / "explanation" / "architecture.md").read_text()
        assert "machine" in page
        assert result.data["store_path"] == str(sidecar)
