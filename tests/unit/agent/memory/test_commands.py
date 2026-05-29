"""Tests for memory slash-command handlers (Phase 43.3)."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.agent.memory import export as memory_export
from cantrip.agent.memory.commands import (
    handle_forget,
    handle_memory,
    handle_remember,
    memory_help_text,
)
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


# ── /memory ─────────────────────────────────────────────────────────────


class TestHandleMemory:
    def test_empty_no_memories(self, manager: MemoryManager) -> None:
        assert "No memories" in handle_memory(manager, "")

    def test_lists_existing(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t1", kind="fact", body="b")
        manager.write(scope="global", title="t2", kind="rule", body="b")
        out = handle_memory(manager, "")
        assert "t1" in out
        assert "t2" in out
        assert "fact" in out
        assert "rule" in out
        assert "charm" in out
        assert "global" in out

    def test_filters_by_scope(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t1", kind="fact", body="b")
        manager.write(scope="global", title="t2", kind="rule", body="b")
        out = handle_memory(manager, "charm")
        assert "t1" in out
        assert "t2" not in out

    def test_unknown_scope(self, manager: MemoryManager) -> None:
        out = handle_memory(manager, "unknown")
        assert "Error" in out
        assert "unknown scope" in out

    def test_help(self, manager: MemoryManager) -> None:
        out = handle_memory(manager, "help")
        assert "Memory commands" in out
        assert "/remember" in out


# ── /remember ──────────────────────────────────────────────────────────


class TestHandleRemember:
    def test_minimal_charm(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "fact -- my-title -- the body")
        assert "Wrote fact memory" in out
        assert "my-title" in out
        assert "charm" in out
        entry = manager.read(title="my-title")
        assert entry is not None
        assert entry.body == "the body"
        assert entry.kind == "fact"
        assert entry.scope == "charm"

    def test_explicit_global(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "rule global -- title -- body")
        assert "global" in out
        entry = manager.read(title="title", scope="global")
        assert entry is not None
        assert entry.kind == "rule"

    def test_missing_separator(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "fact title body")
        assert "Error" in out
        assert "expected three" in out

    def test_empty_args(self, manager: MemoryManager) -> None:
        assert "Error" in handle_remember(manager, "")
        assert "Error" in handle_remember(manager, "   ")

    def test_unknown_kind(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "blob -- t -- b")
        assert "Error" in out
        assert "unknown kind" in out

    def test_unknown_scope(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "fact elsewhere -- t -- b")
        assert "Error" in out
        assert "unknown scope" in out

    def test_too_many_head_tokens(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "fact charm extra -- t -- b")
        assert "Error" in out
        assert "too many tokens" in out

    def test_empty_body(self, manager: MemoryManager) -> None:
        out = handle_remember(manager, "fact -- t -- ")
        assert "Error" in out
        # Trailing whitespace is stripped, so the trailing `--` is the
        # second separator — the result is two fields and we report a
        # field-count mismatch.  Either response is an acceptable refusal.
        assert "body" in out or "expected three" in out

    def test_write_scope_error_surfaced(
        self, manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cantrip.agent.memory.core import MemoryScopeError

        def _raise(**_kwargs: object) -> object:
            raise MemoryScopeError("charm scope unavailable")

        monkeypatch.setattr(manager, "write", _raise)
        out = handle_remember(manager, "fact -- t -- b")
        assert "Error" in out
        assert "charm scope unavailable" in out


# ── /forget ────────────────────────────────────────────────────────────


class TestHandleForget:
    def test_explicit_scope(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        out = handle_forget(manager, "t charm")
        assert "Forgot memory" in out
        assert manager.read(title="t", scope="charm") is None

    def test_no_scope_with_one_match(self, manager: MemoryManager) -> None:
        manager.write(scope="global", title="t", kind="fact", body="b")
        out = handle_forget(manager, "t")
        assert "Forgot memory" in out
        assert manager.read(title="t", scope="global") is None

    def test_no_scope_ambiguous(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        manager.write(scope="global", title="t", kind="fact", body="b")
        out = handle_forget(manager, "t")
        assert "Error" in out
        assert "ambiguous" in out
        # Neither scope was deleted.
        assert manager.read(title="t", scope="charm") is not None
        assert manager.read(title="t", scope="global") is not None

    def test_quoted_multi_word_title(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="hello world", kind="fact", body="b")
        out = handle_forget(manager, '"hello world"')
        assert "Forgot memory" in out
        assert manager.read(title="hello world", scope="charm") is None

    def test_quoted_with_explicit_scope(self, manager: MemoryManager) -> None:
        manager.write(scope="global", title="hello world", kind="fact", body="b")
        out = handle_forget(manager, '"hello world" global')
        assert "Forgot memory" in out

    def test_missing_title(self, manager: MemoryManager) -> None:
        out = handle_forget(manager, "")
        assert "Error" in out
        assert "missing title" in out

    def test_unknown_title(self, manager: MemoryManager) -> None:
        out = handle_forget(manager, "nope")
        assert "Error" in out
        assert "no memory" in out

    def test_explicit_scope_unknown_title(self, manager: MemoryManager) -> None:
        out = handle_forget(manager, "nope charm")
        assert "Error" in out

    def test_unparseable_quotes_reported(self, manager: MemoryManager) -> None:
        # An unbalanced quote makes shlex raise; the handler turns it into
        # a friendly parse-error rather than letting it escape.
        out = handle_forget(manager, '"unclosed')
        assert "Error" in out
        assert "could not parse" in out

    def test_help_text_mentions_all_commands(self) -> None:
        text = memory_help_text()
        for cmd in ("/memory", "/remember", "/forget", "export", "import"):
            assert cmd in text


# ── /memory export and /memory import ──────────────────────────────────


class TestExportImportSlashCommands:
    def test_export_dispatch(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        out = handle_memory(
            manager,
            f"export my-bundle {tmp_path / 'out'}",
        )
        assert "Exported 1 memories" in out
        assert (tmp_path / "out" / "my-bundle" / "SKILL.md").is_file()

    def test_export_md_dispatch(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        out = handle_memory(manager, f"export-md {tmp_path / 'dump'}")
        assert "Exported 1 memories" in out
        files = list((tmp_path / "dump").glob("*.md"))
        assert len(files) == 1

    def test_export_missing_args(self, manager: MemoryManager) -> None:
        out = handle_memory(manager, "export")
        assert "Error" in out
        assert "expected" in out

    def test_export_unknown_scope(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"export b {tmp_path / 'out'} elsewhere")
        assert "Error" in out
        assert "unknown scope" in out

    def test_import_round_trip(
        self,
        manager: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        handle_memory(manager, f"export b {tmp_path / 'out'}")
        # Import into the same manager's global scope.
        out = handle_memory(manager, f"import {tmp_path / 'out' / 'b' / 'SKILL.md'}")
        assert "Imported 1 memories" in out
        # And it landed in global, not charm (charm already had it).
        assert manager.read(title="t", scope="global") is not None

    def test_import_missing_source(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"import {tmp_path / 'nope.md'}")
        assert "Error" in out
        assert "import failed" in out

    def test_export_valid_scope_filters(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        out = handle_memory(manager, f"export bundle {tmp_path / 'out'} charm")
        assert "Exported 1 memories" in out

    def test_export_too_many_args(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"export bundle {tmp_path / 'out'} charm extra")
        assert "Error" in out
        assert "too many arguments to export" in out

    def test_export_failure_surfaces_reason(
        self, manager: MemoryManager, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> object:
            raise OSError("disk full")

        monkeypatch.setattr(memory_export, "export_to_skill", _boom)
        out = handle_memory(manager, f"export bundle {tmp_path / 'out'}")
        assert "export failed" in out
        assert "disk full" in out

    def test_export_md_missing_args(self, manager: MemoryManager) -> None:
        out = handle_memory(manager, "export-md")
        assert "Error" in out
        assert "expected" in out

    def test_export_md_unknown_scope(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"export-md {tmp_path / 'dump'} elsewhere")
        assert "unknown scope" in out

    def test_export_md_too_many_args(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"export-md {tmp_path / 'dump'} charm extra")
        assert "too many arguments to export-md" in out

    def test_export_md_failure_surfaces_reason(
        self, manager: MemoryManager, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> object:
            raise ValueError("bad dir")

        monkeypatch.setattr(memory_export, "export_to_markdown", _boom)
        out = handle_memory(manager, f"export-md {tmp_path / 'dump'}")
        assert "export failed" in out
        assert "bad dir" in out

    def test_import_missing_args(self, manager: MemoryManager) -> None:
        out = handle_memory(manager, "import")
        assert "Error" in out
        assert "expected" in out

    def test_import_unknown_scope(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"import {tmp_path / 'x.md'} elsewhere")
        assert "unknown scope" in out

    def test_import_too_many_args(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        out = handle_memory(manager, f"import {tmp_path / 'x.md'} global extra")
        assert "too many arguments to import" in out

    def test_import_reports_skipped_and_failed(
        self, manager: MemoryManager, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = memory_export.ImportResult(
            imported=["a"],
            skipped=["dup1", "dup2"],
            failed=[("bad", "parse error")],
        )
        monkeypatch.setattr(memory_export, "import_from_path", lambda *_a, **_k: result)
        out = handle_memory(manager, f"import {tmp_path / 'src.md'}")
        assert "Imported 1 memories" in out
        assert "Skipped 2 duplicates" in out
        assert "1 failed" in out
        assert "parse error" in out
