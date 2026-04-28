"""Tests for the Phase 43 memory primitives."""

from __future__ import annotations

import datetime
import pathlib
from collections.abc import Iterator

import pytest

from cantrip.agent.memory import (
    DEFAULT_HARD_EXPIRY_DAYS,
    DEFAULT_SOFT_EXPIRY_DAYS,
    INDEX_FILENAME,
    MEMORY_INDEX_MAX_LINES,
    GlobalMemoryStore,
    MemoryManager,
    MemoryScopeError,
    sha_for_range,
    slugify_title,
    validate_citation,
)
from cantrip.agent.prompts.system import build_system_prompt
from cantrip.agent.store import SessionStore


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def global_store(tmp_path: pathlib.Path) -> GlobalMemoryStore:
    return GlobalMemoryStore(tmp_path / "globalmem")


@pytest.fixture
def manager(store: SessionStore, global_store: GlobalMemoryStore) -> MemoryManager:
    return MemoryManager(session_store=store, global_store=global_store)


# ── Schema v8 migration ─────────────────────────────────────────────────


class TestSchemaV8Migration:
    """Confirm the memory table appears after migration from v7."""

    def test_new_db_has_memory_table(self, store: SessionStore) -> None:
        # Newly-opened stores are already at the current schema.
        assert store._conn is not None
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(memory)").fetchall()}
        assert {
            "id",
            "title",
            "kind",
            "body",
            "source",
            "citations",
            "tags",
            "status",
            "created_at",
            "updated_at",
            "last_accessed_at",
            "last_validated_at",
            "access_count",
        } <= cols

    def test_migrates_from_v7(self, tmp_path: pathlib.Path) -> None:
        """A database saved at schema v7 upgrades cleanly and keeps decisions."""
        import sqlite3

        db_path = tmp_path / ".cantrip"
        conn = sqlite3.connect(str(db_path))
        # Minimal v7-shaped schema: only the bits we rely on.
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (7);
            CREATE TABLE session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                charm_name TEXT,
                charm_path TEXT,
                charm_type TEXT,
                framework TEXT,
                dev_model TEXT,
                cos_model TEXT,
                design_proposal TEXT,
                message_count INTEGER DEFAULT 0,
                compactions_attempted INTEGER NOT NULL DEFAULT 0,
                emergencies_attempted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                choice TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.open()
        try:
            assert store._conn is not None
            row = store._conn.execute("SELECT version FROM schema_version").fetchone()
            from cantrip.agent.store import SCHEMA_VERSION

            assert row[0] == SCHEMA_VERSION
            cols = {r[1] for r in store._conn.execute("PRAGMA table_info(memory)").fetchall()}
            assert "title" in cols
            assert "body" in cols
            # Round-trip still works post-migration.
            memory_id = store.record_memory(title="t", kind="fact", body="b", tags=["x"])
            fetched = store.get_memory(memory_id)
            assert fetched is not None
            assert fetched["title"] == "t"
        finally:
            store.close()


# ── SessionStore charm-scope memory ─────────────────────────────────────


class TestSessionStoreMemory:
    """Direct CRUD on the SessionStore memory table."""

    def test_record_and_get(self, store: SessionStore) -> None:
        memory_id = store.record_memory(
            title="trust-lxd",
            kind="rule",
            body="Always trust lxd when prompted by Concierge.",
            tags=["concierge"],
            citations=[{"path": "foo.py", "line_start": 1, "line_end": 2}],
        )
        row = store.get_memory(memory_id)
        assert row is not None
        assert row["title"] == "trust-lxd"
        assert row["kind"] == "rule"
        assert row["tags"] == ["concierge"]
        assert row["citations"] == [{"path": "foo.py", "line_start": 1, "line_end": 2}]
        assert row["status"] == "active"
        assert row["access_count"] == 0

    def test_unique_title(self, store: SessionStore) -> None:
        store.record_memory(title="dup", kind="fact", body="one")
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            store.record_memory(title="dup", kind="fact", body="two")

    def test_update_and_touch(self, store: SessionStore) -> None:
        memory_id = store.record_memory(title="t", kind="fact", body="old")
        assert store.update_memory(memory_id, body="new", tags=["a", "b"])
        row = store.get_memory(memory_id)
        assert row is not None
        assert row["body"] == "new"
        assert row["tags"] == ["a", "b"]
        store.touch_memory(memory_id)
        row = store.get_memory(memory_id)
        assert row is not None
        assert row["access_count"] == 1
        assert row["last_accessed_at"] is not None

    def test_delete(self, store: SessionStore) -> None:
        memory_id = store.record_memory(title="t", kind="fact", body="b")
        assert store.delete_memory(memory_id)
        assert store.get_memory(memory_id) is None
        assert not store.delete_memory(memory_id)

    def test_list_filters(self, store: SessionStore) -> None:
        store.record_memory(title="a", kind="fact", body="x", tags=["cos"])
        store.record_memory(title="b", kind="rule", body="y", tags=["cos"])
        store.record_memory(title="c", kind="fact", body="z", status="archived")
        active = store.list_memory()
        assert [r["title"] for r in active] == ["b", "a"]  # Newest first.
        facts = store.list_memory(kind="fact")
        assert {r["title"] for r in facts} == {"a"}
        archived = store.list_memory(status="archived")
        assert {r["title"] for r in archived} == {"c"}
        cos_tag = store.list_memory(tag="cos")
        assert {r["title"] for r in cos_tag} == {"a", "b"}

    def test_search(self, store: SessionStore) -> None:
        store.record_memory(title="alpha", kind="fact", body="hello world")
        store.record_memory(title="beta", kind="fact", body="goodbye")
        hits = store.search_memory("hello")
        assert [r["title"] for r in hits] == ["alpha"]
        hits = store.search_memory("BETA")  # Case-insensitive title.
        assert [r["title"] for r in hits] == ["beta"]


# ── GlobalMemoryStore ───────────────────────────────────────────────────


class TestGlobalMemoryStore:
    """Filesystem-backed memory at ~/.config/cantrip/memory/."""

    def test_write_read_round_trip(self, global_store: GlobalMemoryStore) -> None:
        entry = global_store.write(
            "Charm Skill",
            "lesson",
            "Always run `make check` before pushing.",
            tags=["workflow"],
        )
        assert entry.title == "Charm Skill"
        assert entry.kind == "lesson"
        assert entry.scope == "global"
        assert entry.tags == ["workflow"]
        loaded = global_store.get("Charm Skill")
        assert loaded is not None
        assert loaded.body == "Always run `make check` before pushing."
        assert loaded.created_at is not None

    def test_list_filters(self, global_store: GlobalMemoryStore) -> None:
        global_store.write("a", "fact", "x", tags=["cos"])
        global_store.write("b", "rule", "y")
        global_store.write("c", "fact", "z", status="archived")
        active = global_store.list_entries()
        assert {e.title for e in active} == {"a", "b"}
        facts = global_store.list_entries(kind="fact")
        assert {e.title for e in facts} == {"a"}
        archived = global_store.list_entries(status="archived")
        assert {e.title for e in archived} == {"c"}
        cos_tag = global_store.list_entries(tag="cos")
        assert {e.title for e in cos_tag} == {"a"}

    def test_search_substring(self, global_store: GlobalMemoryStore) -> None:
        global_store.write("alpha", "fact", "hello world")
        global_store.write("beta", "fact", "goodbye")
        hits = global_store.search("HELLO")
        assert [h.title for h in hits] == ["alpha"]

    def test_update_preserves_created(self, global_store: GlobalMemoryStore) -> None:
        entry = global_store.write("t", "fact", "old")
        created = entry.created_at
        updated = global_store.update("t", body="new body", tags=["x"])
        assert updated is not None
        assert updated.body == "new body"
        assert updated.tags == ["x"]
        assert updated.created_at == created  # Original creation preserved.

    def test_delete(self, global_store: GlobalMemoryStore) -> None:
        global_store.write("t", "fact", "b")
        assert global_store.delete("t")
        assert global_store.get("t") is None
        assert not global_store.delete("t")

    def test_index_rebuilt_on_write(self, global_store: GlobalMemoryStore) -> None:
        global_store.write("Alpha Memory", "fact", "First line matters.\nSecond line.")
        global_store.write("Beta Memory", "rule", "Short note.")
        index = global_store.read_index()
        assert "# Memory Index" in index
        assert "Alpha Memory" in index
        assert "First line matters." in index
        assert "Beta Memory" in index
        assert INDEX_FILENAME == "MEMORY.md"

    def test_index_truncation(self, global_store: GlobalMemoryStore) -> None:
        """Oversized indexes are truncated with a marker line."""
        # Write the index manually with more than the cap.
        global_store._ensure_dir()
        body = "\n".join(f"- line {i}" for i in range(MEMORY_INDEX_MAX_LINES + 50))
        global_store.index_path.write_text(body)
        rendered = global_store.read_index()
        assert "[truncated" in rendered
        kept_lines = rendered.splitlines()
        # Cap + truncation marker.
        assert len(kept_lines) == MEMORY_INDEX_MAX_LINES + 1

    def test_path_traversal_sanitised(self, global_store: GlobalMemoryStore) -> None:
        """A title with path separators cannot escape the memory directory."""
        entry = global_store.write("../evil/name", "fact", "x")
        assert entry is not None
        # The produced filename is flattened.
        assert "../" not in (global_store.directory / "x").as_posix()
        files = list(global_store.directory.glob("*.md"))
        # Only MEMORY.md and one memory file exist.
        assert sorted(f.name for f in files) == sorted(
            ["MEMORY.md", global_store._path_for("../evil/name").name]
        )

    def test_slugify(self) -> None:
        assert slugify_title("Hello World") == "hello_world"
        assert slugify_title("../evil") == "evil"
        assert slugify_title("") == "memory"
        assert slugify_title("foo.bar-baz") == "foo.bar-baz"


# ── MemoryManager unified interface ─────────────────────────────────────


class TestMemoryManager:
    """End-to-end round-trips through the unified manager."""

    def test_write_and_list_both_scopes(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="c1", kind="fact", body="c-body")
        manager.write(scope="global", title="g1", kind="rule", body="g-body")
        entries = manager.list_entries()
        titles = sorted((e.scope, e.title) for e in entries)
        assert titles == [("charm", "c1"), ("global", "g1")]
        charm_only = manager.list_entries(scope="charm")
        assert [e.title for e in charm_only] == ["c1"]
        global_only = manager.list_entries(scope="global")
        assert [e.title for e in global_only] == ["g1"]

    def test_read_charm_wins_over_global(self, manager: MemoryManager) -> None:
        """Same title in both scopes — charm-scope is returned first."""
        manager.write(scope="charm", title="shared", kind="fact", body="charm body")
        manager.write(scope="global", title="shared", kind="fact", body="global body")
        entry = manager.read(title="shared")
        assert entry is not None
        assert entry.scope == "charm"
        assert entry.body == "charm body"

    def test_read_missing(self, manager: MemoryManager) -> None:
        assert manager.read(title="nope") is None

    def test_search_both_scopes(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="c", kind="fact", body="apple")
        manager.write(scope="global", title="g", kind="fact", body="apple-pie")
        hits = manager.search("apple")
        assert {h.title for h in hits} == {"c", "g"}

    def test_update_forget_charm(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="old")
        updated = manager.update(scope="charm", title="t", body="new")
        assert updated is not None
        assert updated.body == "new"
        assert manager.forget(scope="charm", title="t")
        assert manager.read(title="t", scope="charm") is None

    def test_update_forget_global(self, manager: MemoryManager) -> None:
        manager.write(scope="global", title="t", kind="fact", body="old")
        updated = manager.update(scope="global", title="t", body="new")
        assert updated is not None
        assert updated.body == "new"
        assert manager.forget(scope="global", title="t")
        assert manager.read(title="t", scope="global") is None

    def test_invalid_kind_rejected(self, manager: MemoryManager) -> None:
        with pytest.raises(MemoryScopeError):
            manager.write(scope="charm", title="x", kind="bogus", body="b")

    def test_invalid_status_rejected(self, manager: MemoryManager) -> None:
        with pytest.raises(MemoryScopeError):
            manager.write(scope="charm", title="x", kind="fact", body="b", status="bogus")

    def test_charm_scope_without_store(self, global_store: GlobalMemoryStore) -> None:
        m = MemoryManager(session_store=None, global_store=global_store)
        with pytest.raises(MemoryScopeError):
            m.write(scope="charm", title="t", kind="fact", body="b")
        # Global still works.
        m.write(scope="global", title="g", kind="fact", body="b")
        assert m.read(title="g") is not None

    def test_render_prompt_index(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="c", kind="fact", body="c-body")
        manager.write(scope="global", title="g", kind="rule", body="g-body")
        rendered = manager.render_prompt_index()
        assert "### Global" in rendered
        assert "### Charm" in rendered
        assert "- **c** (fact)" in rendered
        assert "g" in rendered

    def test_render_prompt_index_empty(self, manager: MemoryManager) -> None:
        assert manager.render_prompt_index() == ""


# ── Tool layer ──────────────────────────────────────────────────────────


class TestMemoryTools:
    """Exercise the six memory tools through their async ``execute`` entry point."""

    @pytest.fixture
    def tools(self, manager: MemoryManager) -> dict[str, object]:
        from cantrip.agent.tools.memory import build_memory_tools

        return {t.name: t for t in build_memory_tools(manager)}

    @pytest.mark.asyncio
    async def test_write_then_read(self, tools: dict[str, object]) -> None:
        result = await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="charm",
            title="hello",
            kind="fact",
            body="world",
        )
        assert result.success
        read = await tools["memory_read"].execute(title="hello")  # type: ignore[attr-defined]
        assert read.success
        assert "world" in read.output

    @pytest.mark.asyncio
    async def test_write_validates_required_fields(self, tools: dict[str, object]) -> None:
        result = await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="charm", title="x", kind="fact", body=""
        )
        assert not result.success
        assert "body" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_kind_surfaces_error(self, tools: dict[str, object]) -> None:
        result = await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="charm", title="x", kind="wat", body="b"
        )
        assert not result.success
        assert "kind" in (result.error or "")

    @pytest.mark.asyncio
    async def test_list_shows_summaries_only(self, tools: dict[str, object]) -> None:
        await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="charm", title="t", kind="fact", body="SECRET BODY"
        )
        result = await tools["memory_list"].execute()  # type: ignore[attr-defined]
        assert result.success
        # Bodies are not part of the summary.
        assert "SECRET BODY" not in result.output
        assert "t" in result.output

    @pytest.mark.asyncio
    async def test_search_finds_substring(self, tools: dict[str, object]) -> None:
        await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="global", title="a", kind="fact", body="pebble tips"
        )
        result = await tools["memory_search"].execute(query="PEBBLE")  # type: ignore[attr-defined]
        assert result.success
        assert "a" in result.output

    @pytest.mark.asyncio
    async def test_update_and_forget(self, tools: dict[str, object]) -> None:
        await tools["memory_write"].execute(  # type: ignore[attr-defined]
            scope="charm", title="t", kind="fact", body="old"
        )
        upd = await tools["memory_update"].execute(  # type: ignore[attr-defined]
            scope="charm", title="t", body="new"
        )
        assert upd.success
        read = await tools["memory_read"].execute(title="t")  # type: ignore[attr-defined]
        assert "new" in read.output

        forget = await tools["memory_forget"].execute(  # type: ignore[attr-defined]
            scope="charm", title="t"
        )
        assert forget.success
        missing = await tools["memory_read"].execute(title="t")  # type: ignore[attr-defined]
        assert not missing.success

    @pytest.mark.asyncio
    async def test_forget_missing(self, tools: dict[str, object]) -> None:
        result = await tools["memory_forget"].execute(  # type: ignore[attr-defined]
            scope="charm", title="nope"
        )
        assert not result.success


# ── System-prompt integration ───────────────────────────────────────────


class TestSystemPromptInjection:
    """The Memory Index section appears when non-empty and is sanitised."""

    def test_section_absent_when_none(self) -> None:
        rendered = build_system_prompt()
        assert "Memory Index" not in rendered

    def test_section_renders_when_provided(self) -> None:
        rendered = build_system_prompt(
            memory_index="### Global\n\n- foo\n### Charm\n\n- **bar** (fact)"
        )
        assert "## Memory Index" in rendered
        assert "foo" in rendered
        assert "bar" in rendered

    def test_template_injection_sanitised(self) -> None:
        """Jinja syntax inside the memory index is stripped before rendering."""
        rendered = build_system_prompt(memory_index="{{ leaked }} %%{")
        assert "{{" not in rendered
        assert "%%" not in rendered
        assert "leaked" in rendered  # The word itself is kept; braces are removed.

    def test_compact_template_also_injects(self) -> None:
        rendered = build_system_prompt(memory_index="- charm memory", compact=True)
        assert "Memory Index" in rendered
        assert "charm memory" in rendered

    def test_prompt_index_size_bounded(self, manager: MemoryManager) -> None:
        """Even with many memories the rendered index stays under a sensible budget."""
        for i in range(50):
            manager.write(
                scope="charm",
                title=f"title-{i}",
                kind="fact",
                body=f"body content for memory {i}",
            )
        rendered = build_system_prompt(memory_index=manager.render_prompt_index())
        # A generous ceiling — well under a 10k-token prefix.  Well-formed
        # indexes should stay far below this.
        assert len(rendered) < 50_000


# ── Citation validation and revalidation ────────────────────────────────


class TestCitationHelpers:
    """Low-level helpers for citation validation."""

    def test_sha_for_whole_file(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("hello\nworld\n")
        import hashlib

        expected = hashlib.sha256(b"hello\nworld\n").hexdigest()
        assert sha_for_range(path, None, None) == expected

    def test_sha_for_line_range(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("a\nb\nc\nd\n")
        import hashlib

        # Lines 2..3 inclusive.
        expected = hashlib.sha256(b"b\nc\n").hexdigest()
        assert sha_for_range(path, 2, 3) == expected

    def test_sha_clamps_past_eof(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("a\nb\n")
        import hashlib

        expected = hashlib.sha256(b"a\nb\n").hexdigest()
        assert sha_for_range(path, 1, 999) == expected

    def test_validate_citation_happy_path(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("foo\nbar\n")
        sha = sha_for_range(path, 1, 2)
        check = validate_citation(
            {
                "path": str(path),
                "line_start": 1,
                "line_end": 2,
                "sha": sha,
            }
        )
        assert check.ok
        assert "sha match" in check.reason

    def test_validate_citation_missing_file(self, tmp_path: pathlib.Path) -> None:
        check = validate_citation({"path": str(tmp_path / "nope.py"), "sha": "deadbeef"})
        assert not check.ok
        assert "file not found" in check.reason

    def test_validate_citation_sha_mismatch(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("one\n")
        check = validate_citation({"path": str(path), "sha": "deadbeef"})
        assert not check.ok
        assert "sha mismatch" in check.reason

    def test_validate_citation_no_sha_existence_only(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "src.py"
        path.write_text("hi\n")
        check = validate_citation({"path": str(path)})
        assert check.ok
        assert "file exists" in check.reason

    def test_validate_citation_relative_without_base(self) -> None:
        check = validate_citation({"path": "src/charm.py"})
        assert not check.ok
        assert "no base" in check.reason

    def test_validate_citation_relative_resolves_against_base(
        self, tmp_path: pathlib.Path
    ) -> None:
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "charm.py"
        f.write_text("x")
        check = validate_citation({"path": "src/charm.py"}, base_path=tmp_path)
        assert check.ok

    def test_validate_citation_missing_path(self) -> None:
        check = validate_citation({})
        assert not check.ok
        assert "missing path" in check.reason


class TestMemoryRevalidate:
    """End-to-end revalidation through the MemoryManager."""

    def _write_with_citation(
        self,
        manager: MemoryManager,
        tmp_path: pathlib.Path,
        *,
        title: str = "t",
        body: str = "b",
        scope: str = "charm",
    ) -> pathlib.Path:
        source = tmp_path / "src.py"
        source.write_text("alpha\nbeta\ngamma\n")
        sha = sha_for_range(source, 1, 3)
        manager.write(
            scope=scope,
            title=title,
            kind="lesson",
            body=body,
            citations=[
                {
                    "path": str(source),
                    "line_start": 1,
                    "line_end": 3,
                    "sha": sha,
                }
            ],
        )
        return source

    def test_revalidate_happy_path(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        self._write_with_citation(manager, tmp_path)
        result = manager.revalidate(scope="charm", title="t")
        assert result.ok
        assert result.new_status is None
        assert result.validated_at is not None
        entry = manager.read(title="t", scope="charm")
        assert entry is not None
        assert entry.status == "active"
        assert entry.last_validated_at == result.validated_at

    def test_revalidate_quarantines_on_drift(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        source = self._write_with_citation(manager, tmp_path)
        # Drift the source after the memory was written.
        source.write_text("DIFFERENT CONTENT\n")
        result = manager.revalidate(scope="charm", title="t")
        assert not result.ok
        assert result.new_status == "quarantined"
        entry = manager.read(title="t", scope="charm")
        assert entry is not None
        assert entry.status == "quarantined"

    def test_revalidate_recovers_when_fixed(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        source = self._write_with_citation(manager, tmp_path)
        original = source.read_text()
        source.write_text("drift")
        manager.revalidate(scope="charm", title="t")
        # Restore the source.
        source.write_text(original)
        result = manager.revalidate(scope="charm", title="t")
        assert result.ok
        assert result.new_status == "active"
        entry = manager.read(title="t", scope="charm")
        assert entry is not None
        assert entry.status == "active"

    def test_revalidate_no_citations_is_ok(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        result = manager.revalidate(scope="charm", title="t")
        assert result.ok
        assert result.reason == "no citations"
        assert result.new_status is None
        entry = manager.read(title="t", scope="charm")
        assert entry is not None
        assert entry.last_validated_at is not None

    def test_revalidate_missing_entry(self, manager: MemoryManager) -> None:
        result = manager.revalidate(scope="charm", title="nope")
        assert not result.ok
        assert result.reason == "not found"

    def test_revalidate_quarantined_excluded_from_prompt_index(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        source = self._write_with_citation(manager, tmp_path, title="drifted")
        source.write_text("moved on")
        manager.revalidate(scope="charm", title="drifted")
        rendered = manager.render_prompt_index()
        assert "drifted" not in rendered

    def test_revalidate_all_summary(
        self,
        manager: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        # Three memories: one clean, one drifted, one with no citations.
        (tmp_path / "a.py").write_text("A")
        (tmp_path / "b.py").write_text("B")
        sha_a = sha_for_range(tmp_path / "a.py", None, None)
        sha_b_stale = sha_for_range(tmp_path / "b.py", None, None)
        manager.write(
            scope="charm",
            title="clean",
            kind="lesson",
            body="b",
            citations=[{"path": str(tmp_path / "a.py"), "sha": sha_a}],
        )
        manager.write(
            scope="charm",
            title="drifted",
            kind="lesson",
            body="b",
            citations=[{"path": str(tmp_path / "b.py"), "sha": sha_b_stale}],
        )
        manager.write(scope="charm", title="no_cites", kind="fact", body="b")
        # Drift b.py after the memory was recorded.
        (tmp_path / "b.py").write_text("CHANGED")
        results = manager.revalidate_all(scope="charm")
        by_title = {r.title: r for r in results}
        assert by_title["clean"].ok
        assert not by_title["drifted"].ok
        assert by_title["drifted"].new_status == "quarantined"
        assert by_title["no_cites"].ok


class TestMemoryRevalidateTool:
    """The agent tool wrapper around revalidation."""

    @pytest.fixture
    def tools(self, manager: MemoryManager) -> dict[str, object]:
        from cantrip.agent.tools.memory import build_memory_tools

        return {t.name: t for t in build_memory_tools(manager)}

    @pytest.mark.asyncio
    async def test_single_memory(
        self,
        tools: dict[str, object],
        manager: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        source = tmp_path / "src.py"
        source.write_text("x\n")
        sha = sha_for_range(source, None, None)
        manager.write(
            scope="charm",
            title="t",
            kind="lesson",
            body="b",
            citations=[{"path": str(source), "sha": sha}],
        )
        result = await tools["memory_revalidate"].execute(  # type: ignore[attr-defined]
            scope="charm", title="t"
        )
        assert result.success
        assert "sha match" in result.output

    @pytest.mark.asyncio
    async def test_single_memory_requires_scope(self, tools: dict[str, object]) -> None:
        result = await tools["memory_revalidate"].execute(title="t")  # type: ignore[attr-defined]
        assert not result.success
        assert "scope is required" in (result.error or "")

    @pytest.mark.asyncio
    async def test_single_missing(self, tools: dict[str, object]) -> None:
        result = await tools["memory_revalidate"].execute(  # type: ignore[attr-defined]
            scope="charm", title="nope"
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_bulk_sweep(
        self,
        tools: dict[str, object],
        manager: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        (tmp_path / "a.py").write_text("A")
        sha_a = sha_for_range(tmp_path / "a.py", None, None)
        manager.write(
            scope="charm",
            title="clean",
            kind="lesson",
            body="b",
            citations=[{"path": str(tmp_path / "a.py"), "sha": sha_a}],
        )
        manager.write(
            scope="charm",
            title="drifted",
            kind="lesson",
            body="b",
            citations=[{"path": str(tmp_path / "a.py"), "sha": "deadbeef"}],
        )
        result = await tools["memory_revalidate"].execute()  # type: ignore[attr-defined]
        assert result.success
        assert "Revalidated 2 memories" in result.output
        assert "1 clean" in result.output
        assert "1 newly quarantined" in result.output
        assert "drifted" in result.output


# ── TTL sweep ──────────────────────────────────────────────────────────


class TestMemorySweep:
    """TTL sweep archives stale memories without touching quarantined/archived."""

    def _age_entry(self, store: SessionStore, title: str, days: int) -> None:
        """Shift a charm-scope memory's access/validate timestamps N days into the past."""
        past = (
            (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days))
            .replace(microsecond=0)
            .isoformat()
        )
        row = store.get_memory_by_title(title)
        assert row is not None
        store._conn.execute(  # type: ignore[union-attr]
            "UPDATE memory SET last_accessed_at = ?, last_validated_at = ?, "
            "created_at = ?, updated_at = ? WHERE id = ?",
            (past, past, past, past, row["id"]),
        )
        store._conn.commit()  # type: ignore[union-attr]

    def test_sweep_default_threshold(self, manager: MemoryManager, store: SessionStore) -> None:
        manager.write(scope="charm", title="old", kind="fact", body="x")
        manager.write(scope="charm", title="new", kind="fact", body="y")
        self._age_entry(store, "old", DEFAULT_SOFT_EXPIRY_DAYS + 5)
        result = manager.sweep_stale()
        assert ("charm", "old") in result.archived
        assert result.kept == 1
        stale_entry = manager.read(title="old", scope="charm")
        assert stale_entry is not None
        assert stale_entry.status == "archived"
        fresh = manager.read(title="new", scope="charm")
        assert fresh is not None
        assert fresh.status == "active"

    def test_sweep_respects_custom_threshold(
        self, manager: MemoryManager, store: SessionStore
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="x")
        self._age_entry(store, "t", 10)
        # Threshold 30 days: not stale yet.
        keep_result = manager.sweep_stale(soft_days=30)
        assert keep_result.archived == []
        # Threshold 5 days: now stale.
        archive_result = manager.sweep_stale(soft_days=5)
        assert ("charm", "t") in archive_result.archived

    def test_sweep_leaves_quarantined_alone(
        self, manager: MemoryManager, store: SessionStore, tmp_path: pathlib.Path
    ) -> None:
        # Write a memory with a broken citation and quarantine it.
        manager.write(
            scope="charm",
            title="bad",
            kind="lesson",
            body="b",
            citations=[{"path": str(tmp_path / "missing.py"), "sha": "deadbeef"}],
        )
        manager.revalidate(scope="charm", title="bad")
        self._age_entry(store, "bad", DEFAULT_SOFT_EXPIRY_DAYS + 10)
        result = manager.sweep_stale()
        assert result.archived == []
        entry = manager.read(title="bad", scope="charm")
        assert entry is not None
        assert entry.status == "quarantined"

    def test_sweep_idempotent(self, manager: MemoryManager, store: SessionStore) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="x")
        self._age_entry(store, "t", DEFAULT_SOFT_EXPIRY_DAYS + 5)
        first = manager.sweep_stale()
        assert len(first.archived) == 1
        # Second pass: nothing to archive, since status is now 'archived'.
        second = manager.sweep_stale()
        assert second.archived == []
        assert second.kept == 0

    def test_sweep_global_scope(
        self, manager: MemoryManager, global_store: GlobalMemoryStore
    ) -> None:
        manager.write(scope="global", title="g", kind="fact", body="x")
        # Age the frontmatter of the global file.
        path = global_store._path_for("g")
        raw = path.read_text()
        past = (
            (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(days=DEFAULT_SOFT_EXPIRY_DAYS + 5)
            )
            .replace(microsecond=0)
            .isoformat()
        )
        raw = raw.replace("created: ", f"last_accessed: {past}\nlast_validated: {past}\ncreated: ")
        # Also shift the created line so fallback is old too.
        import re

        raw = re.sub(r"created: .+", f"created: {past}", raw)
        raw = re.sub(r"updated: .+", f"updated: {past}", raw)
        path.write_text(raw)
        result = manager.sweep_stale()
        assert ("global", "g") in result.archived
        entry = manager.read(title="g", scope="global")
        assert entry is not None
        assert entry.status == "archived"

    def test_env_override(
        self,
        manager: MemoryManager,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="x")
        self._age_entry(store, "t", 10)
        monkeypatch.setenv("CANTRIP_MEMORY_SOFT_EXPIRY_DAYS", "5")
        result = manager.sweep_stale()
        assert ("charm", "t") in result.archived

    def test_env_override_invalid_falls_back_to_default(
        self,
        manager: MemoryManager,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A corrupt env var must not silently disable expiry — falls back to 60 days."""
        manager.write(scope="charm", title="t", kind="fact", body="x")
        self._age_entry(store, "t", 10)
        monkeypatch.setenv("CANTRIP_MEMORY_SOFT_EXPIRY_DAYS", "not-a-number")
        result = manager.sweep_stale()
        assert result.archived == []  # 60-day default keeps it.

    def test_env_override_non_positive_falls_back(
        self,
        manager: MemoryManager,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="x")
        self._age_entry(store, "t", 10)
        monkeypatch.setenv("CANTRIP_MEMORY_SOFT_EXPIRY_DAYS", "0")
        result = manager.sweep_stale()
        assert result.archived == []


class TestMemorySweepTool:
    """The memory_sweep tool wraps the manager method."""

    @pytest.fixture
    def tools(self, manager: MemoryManager) -> dict[str, object]:
        from cantrip.agent.tools.memory import build_memory_tools

        return {t.name: t for t in build_memory_tools(manager)}

    @pytest.mark.asyncio
    async def test_happy_path(
        self,
        tools: dict[str, object],
        manager: MemoryManager,
        store: SessionStore,
    ) -> None:
        manager.write(scope="charm", title="old", kind="fact", body="x")
        past = (
            (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(days=DEFAULT_SOFT_EXPIRY_DAYS + 5)
            )
            .replace(microsecond=0)
            .isoformat()
        )
        row = store.get_memory_by_title("old")
        assert row is not None
        store._conn.execute(  # type: ignore[union-attr]
            "UPDATE memory SET last_accessed_at = ?, last_validated_at = ?, "
            "created_at = ? WHERE id = ?",
            (past, past, past, row["id"]),
        )
        store._conn.commit()  # type: ignore[union-attr]

        result = await tools["memory_sweep"].execute()  # type: ignore[attr-defined]
        assert result.success
        assert "1 archived" in result.output
        assert "archived: old" in result.output

    @pytest.mark.asyncio
    async def test_rejects_invalid_soft_days(self, tools: dict[str, object]) -> None:
        bad = await tools["memory_sweep"].execute(soft_days="huh")  # type: ignore[attr-defined]
        assert not bad.success
        neg = await tools["memory_sweep"].execute(soft_days=-1)  # type: ignore[attr-defined]
        assert not neg.success


# ── 180-day purge candidates ───────────────────────────────────────────


class TestPurgeCandidates:
    """list_due_for_purge surfaces archived memories past the hard threshold."""

    def _archive_with_age(self, store: SessionStore, title: str, days_archived: int) -> None:
        """Mark a memory as archived with ``updated_at`` set to ``days_archived`` ago."""
        past = (
            (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_archived))
            .replace(microsecond=0)
            .isoformat()
        )
        row = store.get_memory_by_title(title)
        assert row is not None
        store._conn.execute(  # type: ignore[union-attr]
            "UPDATE memory SET status='archived', updated_at = ? WHERE id = ?",
            (past, row["id"]),
        )
        store._conn.commit()  # type: ignore[union-attr]

    def test_no_candidates_when_nothing_archived(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        assert manager.list_due_for_purge() == []

    def test_archived_but_fresh_skipped(self, manager: MemoryManager, store: SessionStore) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        self._archive_with_age(store, "t", 30)
        assert manager.list_due_for_purge() == []

    def test_archived_past_threshold_returned(
        self, manager: MemoryManager, store: SessionStore
    ) -> None:
        manager.write(scope="charm", title="ancient", kind="fact", body="b")
        self._archive_with_age(store, "ancient", DEFAULT_HARD_EXPIRY_DAYS + 5)
        candidates = manager.list_due_for_purge()
        assert [c.title for c in candidates] == ["ancient"]

    def test_custom_threshold_overrides_default(
        self, manager: MemoryManager, store: SessionStore
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        self._archive_with_age(store, "t", 100)
        # Default 180 → keep; explicit 30 → return.
        assert manager.list_due_for_purge() == []
        assert [c.title for c in manager.list_due_for_purge(hard_days=30)] == ["t"]

    def test_env_override(
        self,
        manager: MemoryManager,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        self._archive_with_age(store, "t", 50)
        monkeypatch.setenv("CANTRIP_MEMORY_HARD_EXPIRY_DAYS", "30")
        assert [c.title for c in manager.list_due_for_purge()] == ["t"]


class TestMemoryPurgeCheckTool:
    """The tool wraps list_due_for_purge."""

    @pytest.fixture
    def tools(self, manager: MemoryManager) -> dict[str, object]:
        from cantrip.agent.tools.memory import build_memory_tools

        return {t.name: t for t in build_memory_tools(manager)}

    @pytest.mark.asyncio
    async def test_no_candidates(self, tools: dict[str, object]) -> None:
        result = await tools["memory_purge_check"].execute()  # type: ignore[attr-defined]
        assert result.success
        assert "no memories due" in result.output

    @pytest.mark.asyncio
    async def test_returns_candidates(
        self,
        tools: dict[str, object],
        manager: MemoryManager,
        store: SessionStore,
    ) -> None:
        manager.write(scope="charm", title="ancient", kind="fact", body="b")
        # Inline aging — duplicate of helper, kept here to show the
        # tool independently of the manager-level test fixture.
        past = (
            (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(days=DEFAULT_HARD_EXPIRY_DAYS + 1)
            )
            .replace(microsecond=0)
            .isoformat()
        )
        row = store.get_memory_by_title("ancient")
        assert row is not None
        store._conn.execute(  # type: ignore[union-attr]
            "UPDATE memory SET status='archived', updated_at = ? WHERE id = ?",
            (past, row["id"]),
        )
        store._conn.commit()  # type: ignore[union-attr]
        result = await tools["memory_purge_check"].execute()  # type: ignore[attr-defined]
        assert result.success
        assert "ancient" in result.output
        assert "1 memories due for purge" in result.output

    @pytest.mark.asyncio
    async def test_rejects_invalid_hard_days(self, tools: dict[str, object]) -> None:
        bad = await tools["memory_purge_check"].execute(hard_days="x")  # type: ignore[attr-defined]
        assert not bad.success
        neg = await tools["memory_purge_check"].execute(hard_days=0)  # type: ignore[attr-defined]
        assert not neg.success
