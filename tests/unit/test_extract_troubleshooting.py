"""Tests for Phase 74.4 — extracting troubleshooting entries from the
session transcript and rendering them as ``docs/how-to/troubleshooting.md``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import tempfile

import pytest

from cantrip.agent.tools.publishing import (
    _CATEGORY_ORDER,
    _MIN_DIAGNOSTIC_LINES,
    _TROUBLESHOOTING_MARKER,
    ExtractTroubleshootingTool,
    TroubleshootingEntry,
    _categorise_error,
    _ensure_troubleshooting_in_toctree,
    _read_transcript_pairs,
    _resolve_troubleshooting_intro,
    _strip_tool_result_wrapper,
    format_troubleshooting_page,
)

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def temp_charm():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


def _wrap_tool_result(content: str, name: str = "run_command") -> str:
    """Mimic the ``<tool_result>`` envelope core.py adds around tool output."""
    return f"<tool_result name='{name}'>\n{content}\n</tool_result>"


def _setup_message_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT,
            tool_results TEXT,
            metadata TEXT,
            token_usage_id INTEGER,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE subagent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            message_index INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT,
            tool_results TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def _write_main_message(
    conn: sqlite3.Connection,
    *,
    role: str,
    content: str = "",
    tool_results: list[dict] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (role, content, tool_results) VALUES (?, ?, ?)",
        (role, content, json.dumps(tool_results) if tool_results else None),
    )


def _write_subagent_message(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    message_index: int,
    role: str,
    content: str = "",
    tool_results: list[dict] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO subagent_messages "
        "(task_id, message_index, role, content, tool_results) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            task_id,
            message_index,
            role,
            content,
            json.dumps(tool_results) if tool_results else None,
        ),
    )


# ===========================================================================
# Categoriser
# ===========================================================================


class TestCategoriseError:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("ImagePullBackOff: failed to pull image", "image"),
            ("ErrImagePull: rpc error: code = Unknown", "image"),
            ("dial tcp: connection refused", "network"),
            ("Name or service not known", "network"),
            ("connection timed out after 30s", "network"),
            ("secret-not-found: my-secret", "secret"),
            ("relation-not-found: db", "relation"),
            ("ENDPOINT_NOT_FOUND in unit hello/0", "relation"),
            ("hook failed: install", "hook"),
            ("hook 'install' failed: signal: killed", "hook"),
            ("tempo backend unreachable", "observability"),
            ("storage-not-found: persistent-data", "storage"),
            ("a totally unrelated error message", "general"),
        ],
    )
    def test_keyword_buckets(self, text: str, expected: str) -> None:
        assert _categorise_error(text) == expected

    def test_categories_are_known(self) -> None:
        for text in (
            "image pull",
            "connection refused",
            "relation not found",
            "anything else",
        ):
            assert _categorise_error(text) in _CATEGORY_ORDER


# ===========================================================================
# Wrapper stripping + excerpts
# ===========================================================================


class TestStripToolResultWrapper:
    def test_strips_wrapper(self) -> None:
        wrapped = "<tool_result name='x'>\nhello\nworld\n</tool_result>"
        assert _strip_tool_result_wrapper(wrapped) == "hello\nworld"

    def test_passthrough_when_no_wrapper(self) -> None:
        assert _strip_tool_result_wrapper("plain text") == "plain text"


# ===========================================================================
# _read_transcript_pairs
# ===========================================================================


class TestReadTranscriptPairs:
    def test_missing_db_returns_empty(self, temp_charm) -> None:
        assert _read_transcript_pairs(temp_charm / ".cantrip") == []

    def test_db_without_tables(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        sqlite3.connect(db).close()
        assert _read_transcript_pairs(db) == []

    def test_extracts_main_error_with_diagnosis_and_resolution(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            error_text = (
                "Error: failed to deploy hello\n"
                "ImagePullBackOff: rpc error: code = Unknown\n"
                "  pulling from index.docker.io/library/hello\n"
                "  manifest unknown\n"
                "  retrying...\n"
                "  giving up after 5 attempts"
            )
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result(error_text),
                        "is_error": True,
                    }
                ],
            )
            _write_main_message(
                conn,
                role="assistant",
                content="Image pull failed because the tag doesn't exist; trying the canonical-org image instead.",
            )
            _write_main_message(
                conn,
                role="tool",
                tool_results=[
                    {
                        "tool_call_id": "2",
                        "content": _wrap_tool_result("Deployed application 'hello'"),
                        "is_error": False,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()

        entries = _read_transcript_pairs(db)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.category == "image"
        assert "ImagePullBackOff" in entry.symptom
        assert entry.cause is not None
        assert "tag doesn't exist" in entry.cause
        assert entry.resolution is not None
        assert "Deployed application" in entry.resolution
        assert "main message" in entry.citation

    def test_drops_trivial_general_error(self, temp_charm) -> None:
        # A single-line unclassified error is dropped (typo-shaped).
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("typo: missing semicolon"),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
        assert _read_transcript_pairs(db) == []

    def test_keeps_short_categorised_error(self, temp_charm) -> None:
        # Even a one-line error survives if it matches a category.
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("relation-not-found: db"),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
        entries = _read_transcript_pairs(db)
        assert len(entries) == 1
        assert entries[0].category == "relation"

    def test_keeps_long_general_error(self, temp_charm) -> None:
        # Non-categorised but long enough to be useful.
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            long_text = "\n".join(f"diagnostic line {i}" for i in range(_MIN_DIAGNOSTIC_LINES + 1))
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result(long_text),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
        entries = _read_transcript_pairs(db)
        assert len(entries) == 1
        assert entries[0].category == "general"

    def test_walks_subagent_messages(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_subagent_message(
                conn,
                task_id="build-1",
                message_index=0,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("hook failed: install"),
                        "is_error": True,
                    }
                ],
            )
            _write_subagent_message(
                conn,
                task_id="build-1",
                message_index=1,
                role="assistant",
                content="The install hook crashed because the workload package wasn't pre-fetched.",
            )
            conn.commit()
        finally:
            conn.close()
        entries = _read_transcript_pairs(db)
        assert len(entries) == 1
        assert entries[0].category == "hook"
        assert "subagent/build-1" in entries[0].citation

    def test_non_error_tool_result_ignored(self, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="tool",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("ok"),
                        "is_error": False,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
        assert _read_transcript_pairs(db) == []


# ===========================================================================
# format_troubleshooting_page
# ===========================================================================


class TestFormatTroubleshootingPage:
    def test_empty_returns_placeholder(self) -> None:
        assert "No troubleshooting entries" in format_troubleshooting_page([])

    def test_groups_by_category_in_stable_order(self) -> None:
        entries = [
            TroubleshootingEntry(
                category="image",
                symptom="ImagePullBackOff",
                cause="tag missing",
                resolution="use full repo name",
                citation="main message #1",
            ),
            TroubleshootingEntry(
                category="relation",
                symptom="relation-not-found",
                cause="db not deployed",
                resolution="juju deploy postgresql",
                citation="main message #2",
            ),
        ]
        out = format_troubleshooting_page(entries)
        # Relation ordering precedes image per _CATEGORY_ORDER.
        assert out.index("Relation errors") < out.index("Image pull")

    def test_omits_empty_buckets(self) -> None:
        entries = [
            TroubleshootingEntry(
                category="hook",
                symptom="hook failed: install",
                cause=None,
                resolution=None,
                citation="main message #1",
            )
        ]
        out = format_troubleshooting_page(entries)
        assert "Hook failures" in out
        assert "Image pull" not in out

    def test_entry_includes_symptom_cause_resolution_citation(self) -> None:
        entry = TroubleshootingEntry(
            category="network",
            symptom="connection refused",
            cause="service hadn't bound the port yet",
            resolution="waited 30s and retried",
            citation="main message #4",
        )
        out = format_troubleshooting_page([entry])
        assert "**Symptom:**" in out
        assert "connection refused" in out
        assert "**Cause:** service hadn't bound" in out
        assert "**Resolution:** waited 30s and retried" in out
        assert "**See also:** main message #4" in out

    def test_optional_cause_and_resolution_omitted(self) -> None:
        entry = TroubleshootingEntry(
            category="general",
            symptom="some long error\n" * 6,
            cause=None,
            resolution=None,
            citation="main message #4",
        )
        out = format_troubleshooting_page([entry])
        assert "**Cause:**" not in out
        assert "**Resolution:**" not in out
        assert "**See also:**" in out


# ===========================================================================
# Intro preservation
# ===========================================================================


class TestResolveTroubleshootingIntro:
    def test_no_existing_file_uses_default(self, temp_charm) -> None:
        intro = _resolve_troubleshooting_intro(temp_charm)
        assert intro.startswith("# Troubleshooting")

    def test_marker_preserves_above(self, temp_charm) -> None:
        path = temp_charm / "docs" / "how-to"
        path.mkdir(parents=True)
        (path / "troubleshooting.md").write_text(
            "# Troubleshooting\n\nCustom intro.\n"
            f"\n{_TROUBLESHOOTING_MARKER}\n"
            "stale auto-section\n"
        )
        intro = _resolve_troubleshooting_intro(temp_charm)
        assert "Custom intro." in intro
        assert "stale auto-section" not in intro
        assert _TROUBLESHOOTING_MARKER not in intro

    def test_marker_less_file_preserved_verbatim(self, temp_charm) -> None:
        path = temp_charm / "docs" / "how-to"
        path.mkdir(parents=True)
        (path / "troubleshooting.md").write_text("# My troubleshooting\n\nHand-written.\n")
        intro = _resolve_troubleshooting_intro(temp_charm)
        assert intro == "# My troubleshooting\n\nHand-written.\n"


# ===========================================================================
# Toctree update
# ===========================================================================


class TestEnsureToctreeEntry:
    def test_no_index_no_op(self, temp_charm) -> None:
        assert _ensure_troubleshooting_in_toctree(temp_charm) is False

    def test_already_present_no_op(self, temp_charm) -> None:
        index = temp_charm / "docs" / "how-to" / "index.md"
        index.parent.mkdir(parents=True)
        index.write_text(
            "# How-to guides\n\n"
            "```{toctree}\n:maxdepth: 1\n\ndeploy\nconfigure\ntroubleshooting\n```\n"
        )
        assert _ensure_troubleshooting_in_toctree(temp_charm) is False
        # Untouched.
        assert index.read_text().count("troubleshooting") == 1

    def test_appends_to_toctree(self, temp_charm) -> None:
        index = temp_charm / "docs" / "how-to" / "index.md"
        index.parent.mkdir(parents=True)
        index.write_text(
            "# How-to guides\n\n```{toctree}\n:maxdepth: 1\n\ndeploy\nconfigure\n```\n"
        )
        assert _ensure_troubleshooting_in_toctree(temp_charm) is True
        text = index.read_text()
        assert "troubleshooting\n```" in text


# ===========================================================================
# ExtractTroubleshootingTool end-to-end
# ===========================================================================


class TestExtractTroubleshootingTool:
    @pytest.fixture
    def tool(self) -> ExtractTroubleshootingTool:
        return ExtractTroubleshootingTool()

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, tool) -> None:
        result = await tool.execute(path="/nonexistent/xyz")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_db_writes_placeholder(self, tool, temp_charm) -> None:
        result = await tool.execute(path=str(temp_charm))
        assert result.success
        assert result.data["entry_count"] == 0
        page = (temp_charm / "docs" / "how-to" / "troubleshooting.md").read_text()
        assert _TROUBLESHOOTING_MARKER in page
        assert "No troubleshooting entries" in page
        assert page.startswith("# Troubleshooting")

    @pytest.mark.asyncio
    async def test_writes_entries_grouped_by_category(self, tool, temp_charm) -> None:
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result(
                            "Error pulling image:\n"
                            "ImagePullBackOff: rpc error: code = Unknown\n"
                            "manifest unknown\n"
                            "retrying...\n"
                            "still failing"
                        ),
                        "is_error": True,
                    }
                ],
            )
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "2",
                        "content": _wrap_tool_result("relation-not-found: db"),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()

        result = await tool.execute(path=str(temp_charm))
        assert result.success
        assert result.data["entry_count"] == 2
        page = (temp_charm / "docs" / "how-to" / "troubleshooting.md").read_text()
        assert "Image pull" in page
        assert "Relation errors" in page
        assert result.data["category_counts"] == {"image": 1, "relation": 1}

    @pytest.mark.asyncio
    async def test_user_intro_preserved_across_run(self, tool, temp_charm) -> None:
        # First run: tool writes a page with default intro.
        await tool.execute(path=str(temp_charm))
        page_path = temp_charm / "docs" / "how-to" / "troubleshooting.md"
        original = page_path.read_text()
        intro_part, _, _ = original.partition(_TROUBLESHOOTING_MARKER)
        edited_intro = intro_part + "\nUser-added paragraph that must survive.\n"
        page_path.write_text(edited_intro + _TROUBLESHOOTING_MARKER + "\n\nold body\n")

        # Second run with a real error.
        db = temp_charm / ".cantrip"
        conn = sqlite3.connect(db)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("relation-not-found: db"),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()

        await tool.execute(path=str(temp_charm))
        page = page_path.read_text()
        assert "User-added paragraph that must survive." in page
        assert "old body" not in page
        assert "Relation errors" in page

    @pytest.mark.asyncio
    async def test_marker_less_existing_page_preserved(self, tool, temp_charm) -> None:
        page_path = temp_charm / "docs" / "how-to" / "troubleshooting.md"
        page_path.parent.mkdir(parents=True)
        page_path.write_text("# My troubleshooting\n\nHand-written content.\n")

        result = await tool.execute(path=str(temp_charm))
        assert result.success
        page = page_path.read_text()
        assert "Hand-written content." in page
        assert _TROUBLESHOOTING_MARKER in page

    @pytest.mark.asyncio
    async def test_amends_howto_index_toctree(self, tool, temp_charm) -> None:
        index = temp_charm / "docs" / "how-to" / "index.md"
        index.parent.mkdir(parents=True)
        index.write_text(
            "# How-to guides\n\n```{toctree}\n:maxdepth: 1\n\ndeploy\nconfigure\n```\n"
        )
        result = await tool.execute(path=str(temp_charm))
        assert result.success
        assert result.data["toctree_updated"] is True
        assert "troubleshooting" in index.read_text()

    @pytest.mark.asyncio
    async def test_db_path_override(self, tool, temp_charm) -> None:
        sidecar = temp_charm / "alt.cantrip"
        conn = sqlite3.connect(sidecar)
        try:
            _setup_message_schema(conn)
            _write_main_message(
                conn,
                role="assistant",
                tool_results=[
                    {
                        "tool_call_id": "1",
                        "content": _wrap_tool_result("hook failed: install"),
                        "is_error": True,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
        result = await tool.execute(path=str(temp_charm), db_path=str(sidecar))
        assert result.success
        assert result.data["entry_count"] == 1
        assert result.data["store_path"] == str(sidecar)
