"""Tests for the Phase 43 memory primitives."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cantrip.agent.memory import (
    INDEX_FILENAME,
    MEMORY_INDEX_MAX_LINES,
    GlobalMemoryStore,
    MemoryManager,
    MemoryScopeError,
    slugify_title,
)
from cantrip.agent.prompts.system import build_system_prompt
from cantrip.agent.store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def global_store(tmp_path: Path) -> GlobalMemoryStore:
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

    def test_migrates_from_v7(self, tmp_path: Path) -> None:
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
