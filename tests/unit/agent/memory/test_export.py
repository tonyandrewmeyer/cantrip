"""Tests for memory export and import (Phase 43.4)."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.agent.memory.export import (
    CHARM_PATH_PLACEHOLDER,
    export_to_markdown,
    export_to_skill,
    import_from_path,
    sanitise_body,
)
from cantrip.agent.store import SessionStore


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / "src.cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def global_store(tmp_path: pathlib.Path) -> GlobalMemoryStore:
    return GlobalMemoryStore(tmp_path / "src-globalmem")


@pytest.fixture
def manager(store: SessionStore, global_store: GlobalMemoryStore) -> MemoryManager:
    return MemoryManager(session_store=store, global_store=global_store)


@pytest.fixture
def import_target(tmp_path: pathlib.Path) -> MemoryManager:
    """A second manager with separate stores — for round-trip imports."""
    s = SessionStore(tmp_path / "dst.cantrip")
    s.open()
    g = GlobalMemoryStore(tmp_path / "dst-globalmem")
    return MemoryManager(session_store=s, global_store=g)


# ── sanitise_body ──────────────────────────────────────────────────────


class TestSanitiseBody:
    def test_charm_path_replaced(self, tmp_path: pathlib.Path) -> None:
        body = f"In {tmp_path}/src/charm.py we set foo=1"
        sanitised, redactions = sanitise_body(body, charm_path=tmp_path)
        assert CHARM_PATH_PLACEHOLDER in sanitised
        assert str(tmp_path) not in sanitised
        assert redactions == 0

    def test_no_charm_path_no_replace(self) -> None:
        body = "/some/random/path is here"
        sanitised, redactions = sanitise_body(body)
        assert sanitised == body
        assert redactions == 0

    def test_redacts_github_token(self) -> None:
        body = "auth: ghp_123456789012345678abcdef stuff"
        sanitised, redactions = sanitise_body(body)
        assert "ghp_" not in sanitised
        assert "[REDACTED]" in sanitised
        assert redactions == 1

    def test_redacts_aws_key(self) -> None:
        body = "AKIAIOSFODNN7EXAMPLE is the key"
        sanitised, redactions = sanitise_body(body)
        assert "AKIA" not in sanitised
        assert redactions == 1

    def test_redacts_bearer_token(self) -> None:
        body = "Authorization: Bearer abc123def456ghi789jklmnop"
        sanitised, redactions = sanitise_body(body)
        assert "abc123" not in sanitised
        assert "Bearer" not in sanitised  # Whole match scrubbed.
        assert redactions == 1

    def test_redacts_password_assignment(self) -> None:
        body = "password=hunter2 in the config"
        sanitised, redactions = sanitise_body(body)
        assert "hunter2" not in sanitised
        assert "password=[REDACTED]" in sanitised
        assert redactions == 1

    def test_multiple_redactions_counted(self) -> None:
        body = "ghp_123456789012345678abcdef and AKIAIOSFODNN7EXAMPLE"
        sanitised, redactions = sanitise_body(body)
        assert redactions == 2

    def test_clean_body_no_changes(self) -> None:
        body = "Just normal text without anything sensitive."
        sanitised, redactions = sanitise_body(body)
        assert sanitised == body
        assert redactions == 0


# ── export_to_skill ────────────────────────────────────────────────────


class TestExportToSkill:
    def test_creates_skill_file(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        manager.write(scope="charm", title="t1", kind="fact", body="body one")
        manager.write(scope="charm", title="t2", kind="rule", body="body two")
        result = export_to_skill(manager, name="my-bundle", output_path=tmp_path / "out")
        assert result.output_path == tmp_path / "out" / "my-bundle" / "SKILL.md"
        assert result.output_path.is_file()
        content = result.output_path.read_text()
        assert "name: my-bundle" in content
        assert "## Memory: t1" in content
        assert "## Memory: t2" in content
        assert "body one" in content
        assert "body two" in content
        assert sorted(result.entries) == ["t1", "t2"]
        assert result.redactions == 0

    def test_explicit_md_path_honoured(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        target = tmp_path / "explicit.md"
        result = export_to_skill(manager, name="x", output_path=target)
        assert result.output_path == target
        assert target.is_file()

    def test_charm_path_sanitised(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        body = f"See {tmp_path}/charm.py for details"
        manager.write(scope="charm", title="t", kind="fact", body=body)
        result = export_to_skill(
            manager,
            name="b",
            output_path=tmp_path / "out",
            charm_path=tmp_path,
        )
        content = result.output_path.read_text()
        assert CHARM_PATH_PLACEHOLDER in content
        assert str(tmp_path) not in content

    def test_secrets_redacted_in_export(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        manager.write(
            scope="charm",
            title="t",
            kind="lesson",
            body="leaked: ghp_abcdef0123456789abcdef0123456789",
        )
        result = export_to_skill(manager, name="b", output_path=tmp_path / "out")
        content = result.output_path.read_text()
        assert "ghp_" not in content
        assert "[REDACTED]" in content
        assert result.redactions == 1

    def test_empty_scope_writes_placeholder(
        self, manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        result = export_to_skill(manager, name="empty", output_path=tmp_path / "out")
        content = result.output_path.read_text()
        assert "no memories" in content
        assert result.entries == []

    def test_name_required(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        with pytest.raises(ValueError, match="name is required"):
            export_to_skill(manager, name="  ", output_path=tmp_path / "out")


# ── export_to_markdown ────────────────────────────────────────────────


class TestExportToMarkdown:
    def test_one_file_per_memory(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        manager.write(scope="charm", title="alpha", kind="fact", body="A")
        manager.write(scope="global", title="beta", kind="rule", body="B")
        result = export_to_markdown(manager, output_dir=tmp_path / "dump")
        assert sorted(result.entries) == ["alpha", "beta"]
        files = list((tmp_path / "dump").glob("*.md"))
        assert len(files) == 2
        for path in files:
            text = path.read_text()
            assert "title:" in text  # Frontmatter present.

    def test_charm_path_sanitised(self, manager: MemoryManager, tmp_path: pathlib.Path) -> None:
        body = f"path: {tmp_path}/charm.py"
        manager.write(scope="charm", title="t", kind="fact", body=body)
        export_to_markdown(manager, output_dir=tmp_path / "dump", charm_path=tmp_path)
        content = next((tmp_path / "dump").glob("*.md")).read_text()
        assert CHARM_PATH_PLACEHOLDER in content
        # Note: the frontmatter `title:` field will not contain the path.
        assert str(tmp_path) not in content.split("---", 2)[2]


# ── import_from_path ──────────────────────────────────────────────────


class TestImport:
    def test_round_trip_via_skill(
        self,
        manager: MemoryManager,
        import_target: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        manager.write(scope="charm", title="t1", kind="fact", body="body 1", tags=["a"])
        manager.write(scope="charm", title="t2", kind="rule", body="body 2")
        export_to_skill(manager, name="b", output_path=tmp_path / "out")
        result = import_from_path(
            import_target, tmp_path / "out" / "b" / "SKILL.md", target_scope="global"
        )
        assert sorted(result.imported) == ["t1", "t2"]
        assert result.skipped == []
        # Verify what landed in the target.
        for title in ["t1", "t2"]:
            entry = import_target.read(title=title, scope="global")
            assert entry is not None
            assert entry.title == title

    def test_round_trip_via_markdown_dump(
        self,
        manager: MemoryManager,
        import_target: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        manager.write(scope="charm", title="alpha", kind="fact", body="A", tags=["x"])
        manager.write(scope="charm", title="beta", kind="rule", body="B")
        export_to_markdown(manager, output_dir=tmp_path / "dump")
        result = import_from_path(import_target, tmp_path / "dump", target_scope="global")
        assert sorted(result.imported) == ["alpha", "beta"]
        alpha = import_target.read(title="alpha", scope="global")
        assert alpha is not None
        assert alpha.body == "A"
        assert alpha.tags == ["x"]
        assert alpha.kind == "fact"

    def test_skip_duplicates(self, import_target: MemoryManager, tmp_path: pathlib.Path) -> None:
        # Write a memory once via export.
        src = SessionStore(tmp_path / "src.cantrip")
        src.open()
        try:
            src_manager = MemoryManager(session_store=src)
            src_manager.write(scope="charm", title="t", kind="fact", body="orig")
            export_to_skill(src_manager, name="b", output_path=tmp_path / "out")
        finally:
            src.close()
        # First import lands; second skips.
        first = import_from_path(import_target, tmp_path / "out" / "b" / "SKILL.md")
        second = import_from_path(import_target, tmp_path / "out" / "b" / "SKILL.md")
        assert first.imported == ["t"]
        assert first.skipped == []
        assert second.imported == []
        assert second.skipped == ["t"]

    def test_overwrite_replaces(
        self, import_target: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        src = SessionStore(tmp_path / "src.cantrip")
        src.open()
        try:
            src_manager = MemoryManager(session_store=src)
            src_manager.write(scope="charm", title="t", kind="fact", body="v2")
            export_to_skill(src_manager, name="b", output_path=tmp_path / "out")
        finally:
            src.close()
        # Pre-load with v1.
        import_target.write(scope="global", title="t", kind="fact", body="v1")
        result = import_from_path(
            import_target,
            tmp_path / "out" / "b" / "SKILL.md",
            overwrite=True,
        )
        assert result.imported == ["t"]
        entry = import_target.read(title="t", scope="global")
        assert entry is not None
        assert entry.body == "v2"

    def test_missing_source(self, import_target: MemoryManager, tmp_path: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            import_from_path(import_target, tmp_path / "missing.md")

    def test_unknown_target_scope(
        self, import_target: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        f = tmp_path / "x.md"
        f.write_text("---\nname: x\ndescription: x\n---\n\n## Memory: t\n\n*Kind:* fact\n\nb\n")
        with pytest.raises(Exception, match="unknown scope"):
            import_from_path(import_target, f, target_scope="elsewhere")

    def test_handles_skill_with_only_frontmatter(
        self, import_target: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        """A SKILL.md with no Memory sections imports zero entries cleanly."""
        f = tmp_path / "skill.md"
        f.write_text("---\nname: empty\ndescription: nothing\n---\n\n# Empty\n\n_(no memories)_\n")
        result = import_from_path(import_target, f)
        assert result.imported == []
        assert result.failed == []


# ── Round trip with sanitisation preserved ─────────────────────────────


class TestRoundTripSanitised:
    def test_charm_path_in_export_persists_through_import(
        self,
        manager: MemoryManager,
        import_target: MemoryManager,
        tmp_path: pathlib.Path,
    ) -> None:
        # Write a memory referencing the charm path.
        body = f"See {tmp_path}/src/charm.py"
        manager.write(scope="charm", title="t", kind="fact", body=body)
        export_to_skill(
            manager,
            name="b",
            output_path=tmp_path / "out",
            charm_path=tmp_path,
        )
        # Import on the other manager (different path entirely).
        import_from_path(import_target, tmp_path / "out" / "b" / "SKILL.md")
        entry = import_target.read(title="t", scope="global")
        assert entry is not None
        # The import preserves the placeholder rather than the original
        # absolute path.
        assert CHARM_PATH_PLACEHOLDER in entry.body
        assert str(tmp_path) not in entry.body
