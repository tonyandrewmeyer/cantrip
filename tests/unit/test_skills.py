"""Tests for skills discovery, loading, and the LoadSkillTool."""

from pathlib import Path

import pytest

from cantrip.agent.skills import SkillMetadata, SkillsIndex
from cantrip.agent.tools.skills import LoadSkillTool


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory with two valid skills."""
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    (alpha / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: The alpha skill\n---\n\n# Alpha\n\nAlpha body content.\n"
    )

    beta = tmp_path / "beta"
    beta.mkdir()
    (beta / "SKILL.md").write_text(
        "---\nname: beta\ndescription: The beta skill\n---\n\n# Beta\n\nBeta body content.\n"
    )
    return tmp_path


class TestSkillsIndex:
    """Tests for SkillsIndex."""

    def test_discover_finds_skills(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        names = [s.name for s in index.list_skills()]
        assert names == ["alpha", "beta"]

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        index = SkillsIndex(tmp_path / "nope")
        index.discover()
        assert index.list_skills() == []

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_malformed_frontmatter(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter here\n")

        good = tmp_path / "good"
        good.mkdir()
        (good / "SKILL.md").write_text("---\nname: good\ndescription: A good skill\n---\nBody.\n")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert [s.name for s in index.list_skills()] == ["good"]

    def test_discover_skips_missing_fields(self, tmp_path: Path) -> None:
        """A SKILL.md with frontmatter but no name/description is skipped."""
        skill = tmp_path / "incomplete"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: incomplete\n---\nBody.\n")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_non_directory(self, tmp_path: Path) -> None:
        """Files at the top level of the skills dir are ignored."""
        (tmp_path / "README.md").write_text("not a skill")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_dir_without_skill_md(self, tmp_path: Path) -> None:
        """Directories without a SKILL.md are ignored."""
        (tmp_path / "empty-dir").mkdir()

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_list_skills_returns_metadata(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        skills = index.list_skills()
        assert len(skills) == 2
        assert all(isinstance(s, SkillMetadata) for s in skills)
        assert skills[0].name == "alpha"
        assert skills[0].description == "The alpha skill"

    def test_list_skills_sorted_by_name(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        names = [s.name for s in index.list_skills()]
        assert names == sorted(names)

    def test_load_skill_returns_body(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        body = index.load_skill("alpha")
        assert "Alpha body content." in body
        # Frontmatter should not be in the body.
        assert "---" not in body

    def test_load_skill_unknown_raises(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        with pytest.raises(KeyError):
            index.load_skill("nonexistent")

    def test_format_for_prompt_xml(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        xml = index.format_for_prompt()
        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<name>alpha</name>" in xml
        assert "<description>The alpha skill</description>" in xml
        assert "<name>beta</name>" in xml

    def test_format_for_prompt_empty(self, tmp_path: Path) -> None:
        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.format_for_prompt() == ""

    def test_discover_clears_previous(self, skills_dir: Path) -> None:
        """Calling discover() again replaces the old index."""
        index = SkillsIndex(skills_dir)
        index.discover()
        assert len(index.list_skills()) == 2

        # Remove one skill and rediscover.
        (skills_dir / "alpha" / "SKILL.md").unlink()
        (skills_dir / "alpha").rmdir()
        index.discover()
        assert [s.name for s in index.list_skills()] == ["beta"]


class TestSkillsIndexWithBundledSkills:
    """Test against the actual bundled skills directory."""

    def test_bundled_skills_discovered(self) -> None:
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        skills = index.list_skills()
        names = {s.name for s in skills}
        assert len(skills) >= 8
        assert "scenario-tests" in names
        assert "jubilant-tests" in names
        assert "relation-data-design" in names
        assert "observability" in names
        assert "ingress" in names
        assert "adding-actions" in names
        assert "adding-config" in names
        assert "custom-charm" in names

    def test_bundled_skills_loadable(self) -> None:
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        for skill in index.list_skills():
            body = index.load_skill(skill.name)
            assert len(body) > 0, f"Skill {skill.name!r} has empty body"

    def test_security_review_skill_covers_charm_risks(self) -> None:
        """The security-review skill should name charm-specific risks so the
        subagent doesn't treat it as a generic OWASP pass."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "security-review" in names
        body = index.load_skill("security-review").lower()
        for anchor in (
            "shell injection",
            "juju secret",
            "relation data",
            "ssrf",
            "path traversal",
            "confidence",
        ):
            assert anchor in body, f"security-review missing anchor: {anchor!r}"

    def test_find_bugs_skill_covers_charm_bugs(self) -> None:
        """The find-bugs skill should cover charm-specific bug classes."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "find-bugs" in names
        body = index.load_skill("find-bugs").lower()
        for anchor in (
            "status",
            "pebble",
            "relation data",
            "is_leader",
            "update-status",
            "secret",
        ):
            assert anchor in body, f"find-bugs missing anchor: {anchor!r}"

    def test_charm_debug_skill_covers_diagnostic_workflow(self) -> None:
        """The charm-debug skill must prescribe the five-step inspection
        and the symptom → cause → action table."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "charm-debug" in names
        body = index.load_skill("charm-debug").lower()
        # Five-step inspection anchors.
        for anchor in (
            "juju_status",
            "juju_debug_log",
            "juju_read_relation_data",
            "juju_get_app_config",
            "juju_list_secrets",
            "juju_show_secret",
        ):
            assert anchor in body, f"charm-debug missing inspection tool anchor: {anchor!r}"
        # Symptom / cause / action coverage — table must be present.
        for anchor in ("symptom", "likely cause", "next action", "pebble"):
            assert anchor in body, f"charm-debug missing diagnostic anchor: {anchor!r}"
        # Must stay read-only — no write tools.
        assert "read-only" in body, "charm-debug must advertise itself as read-only"

    def test_benchmark_skill_covers_hook_benchmark_and_comparison(self) -> None:
        """The benchmark skill must wrap hook_benchmark and prescribe the
        before/after comparison pattern."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "benchmark" in names
        body = index.load_skill("benchmark").lower()
        for anchor in (
            "hook_benchmark",
            "threshold_ms",
            "data.timings",
            "baseline",
            "candidate",
            "delta",
            "before/after",
            "update-status",
            "config-changed",
        ):
            assert anchor in body, f"benchmark missing anchor: {anchor!r}"

    def test_workspace_skill_covers_multi_charm_work(self) -> None:
        """The workspace skill must cover the manifest, cross-charm relation
        design, and coordinated integration tests — and actively discourage
        bundle authoring."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "workspace" in names
        body = index.load_skill("workspace").lower()
        # Manifest schema anchors.
        for anchor in (
            "cantrip.workspace.yaml",
            "workspace:",
            "charms:",
            "relations:",
            "interface",
            "shared_config",
            "workspace_info",
        ):
            assert anchor in body, f"workspace skill missing schema anchor: {anchor!r}"
        # Cross-charm design anchors.
        for anchor in (
            "provider",
            "requirer",
            "app databag",
            "juju secret",
            "charm-library",
        ):
            assert anchor in body, f"workspace skill missing design anchor: {anchor!r}"
        # Coordination anchors: Jubilant integration + sequenced deploy.
        for anchor in (
            "jubilant",
            "juju.integrate",
            "juju_deploy",
            "juju_relate",
            "terraform",
        ):
            assert anchor in body, f"workspace skill missing coordination anchor: {anchor!r}"
        # Explicit "do not write a new bundle" stance.
        assert "do not write a new `bundle.yaml`" in body, (
            "workspace skill must repeat the anti-bundle stance from the bundle skill"
        )

    def test_bundle_skill_covers_read_modify_deploy_and_refuses_new(self) -> None:
        """The bundle skill must cover existing-bundle consumption *and*
        actively steer the agent away from authoring new bundles."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "bundle" in names
        body = index.load_skill("bundle").lower()
        # Explicit deprecation + migration stance.
        for anchor in ("deprecated", "do not", "do not create new bundles"):
            assert anchor in body, f"bundle missing anti-authoring anchor: {anchor!r}"
        # Tooling pointers — bundle_deploy + juju_deploy/juju_relate fallback.
        for anchor in ("bundle_deploy", "juju_deploy", "juju_relate"):
            assert anchor in body, f"bundle missing tool anchor: {anchor!r}"
        # Structure and overlay coverage.
        for anchor in (
            "bundle: kubernetes",
            "applications:",
            "relations:",
            "overlay",
            "offers",
            "trust",
        ):
            assert anchor in body, f"bundle missing structure anchor: {anchor!r}"

    def test_charm_migration_skill_covers_all_four_migrations(self) -> None:
        """The charm-migration skill must cover all four legacy patterns end-to-end."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "charm-migration" in names
        body = index.load_skill("charm-migration").lower()
        # Audit rule IDs the skill maps migrations to.
        for rule_id in ("dep001", "dep002", "dep003", "dep004", "lib001", "lib002"):
            assert rule_id in body, f"charm-migration missing rule mapping: {rule_id!r}"
        # Reactive framework anchors.
        for anchor in ("charms.reactive", "@when", "framework.observe", "_reconcile"):
            assert anchor in body, f"charm-migration missing reactive anchor: {anchor!r}"
        # StoredState replacement anchors — decision tree keywords.
        for anchor in (
            "storedstate",
            "peer relation data",
            "juju secret",
            "instance attribute",
        ):
            assert anchor in body, f"charm-migration missing StoredState anchor: {anchor!r}"
        # Harness and its delegation to the companion skill.
        for anchor in ("harness", "scenario", "harness-migration"):
            assert anchor in body, f"charm-migration missing Harness anchor: {anchor!r}"
        # fetch-libs → PyPI anchors.
        for anchor in ("fetch-libs", "charmlibs-", "from charmlibs"):
            assert anchor in body, f"charm-migration missing fetch-libs anchor: {anchor!r}"

    def test_charm_library_skill_covers_authoring(self) -> None:
        """The charm-library skill should cover the end-to-end authoring flow."""
        index = SkillsIndex(extra_dirs=[])
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert "charm-library" in names
        body = index.load_skill("charm-library").lower()
        for anchor in (
            "libid",
            "libapi",
            "libpatch",
            "pydeps",
            "charmcraft create-lib",
            "charmcraft register-lib",
            "charmcraft publish-lib",
            "charmcraft fetch-libs",
            "charm-libs:",
            "lib/charms/",
            "scenario",
            "charmlibs-",
        ):
            assert anchor in body, f"charm-library missing anchor: {anchor!r}"


class TestSkillsIndexExternalDirs:
    """Tests for Phase 50.1: standard-format skill dirs alongside bundled."""

    def test_missing_external_dir_is_silent(self, tmp_path: Path) -> None:
        """Non-existent external dirs must not emit a warning — they're optional."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "b").mkdir()
        (bundled / "b" / "SKILL.md").write_text("---\nname: b\ndescription: b\n---\n\nBody\n")
        missing = tmp_path / "does-not-exist"
        index = SkillsIndex(bundled, extra_dirs=[missing])
        index.discover()
        # Only the bundled skill is indexed; no error.
        assert [s.name for s in index.list_skills()] == ["b"]

    def test_external_dir_skill_appears_alongside_bundled(self, tmp_path: Path) -> None:
        """Skills in an external dir surface together with bundled ones."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "a").mkdir()
        (bundled / "a" / "SKILL.md").write_text(
            "---\nname: a\ndescription: a skill\n---\nBody a\n"
        )

        external = tmp_path / "external"
        external.mkdir()
        (external / "x").mkdir()
        (external / "x" / "SKILL.md").write_text(
            "---\nname: x\ndescription: x skill\n---\nBody x\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        names = [s.name for s in index.list_skills()]
        assert names == ["a", "x"]

    def test_external_dir_skill_overrides_bundled_on_name_conflict(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Later dirs win so user customisation trumps the bundled default."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "shared").mkdir()
        (bundled / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: bundled version\n---\nBundled body\n"
        )

        external = tmp_path / "external"
        external.mkdir()
        (external / "shared").mkdir()
        (external / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: user version\n---\nUser body\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        with caplog.at_level("INFO", logger="cantrip.agent.skills"):
            index.discover()

        [metadata] = index.list_skills()
        assert metadata.description == "user version"
        assert index.load_skill("shared") == "User body"
        assert any("overrides" in record.message for record in caplog.records)

    def test_external_single_file_skill_is_discovered(self, tmp_path: Path) -> None:
        """A bare ``<name>.md`` at the top of the external dir is a valid skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "notes.md").write_text(
            "---\nname: notes\ndescription: single-file skill\n---\n\nBody text.\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        [metadata] = index.list_skills()
        assert metadata.name == "notes"
        assert metadata.source == "external"
        assert "Body text." in index.load_skill("notes")

    def test_frontmatter_tools_parsed_as_list(self, tmp_path: Path) -> None:
        """A ``tools`` list in frontmatter is preserved on the metadata."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "gh.md").write_text(
            "---\nname: gh\ndescription: GitHub ops\ntools:\n  - git_clone\n  - gh_pr_create\n---\nBody\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        [metadata] = index.list_skills()
        assert metadata.tools == ["git_clone", "gh_pr_create"]

    def test_frontmatter_tools_parsed_as_comma_string(self, tmp_path: Path) -> None:
        """Claude Code's comma-string ``tools`` shape is accepted too."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "ops.md").write_text(
            "---\nname: ops\ndescription: Ops helpers\ntools: juju_status, juju_deploy\n---\nBody\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        [metadata] = index.list_skills()
        assert metadata.tools == ["juju_status", "juju_deploy"]

    def test_malformed_tools_falls_back_to_empty_list(self, tmp_path: Path) -> None:
        """A non-list, non-string ``tools`` entry doesn't crash discovery."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "bad.md").write_text(
            "---\nname: bad\ndescription: bad tools\ntools: 42\n---\nBody\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        [metadata] = index.list_skills()
        assert metadata.tools == []

    def test_source_tag_identifies_provenance(self, tmp_path: Path) -> None:
        """``source`` distinguishes bundled vs external skills at load time."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "core").mkdir()
        (bundled / "core" / "SKILL.md").write_text(
            "---\nname: core\ndescription: core\n---\nBody\n"
        )
        external = tmp_path / "external"
        external.mkdir()
        (external / "user").mkdir()
        (external / "user" / "SKILL.md").write_text(
            "---\nname: user\ndescription: user skill\n---\nBody\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external])
        index.discover()
        by_name = {s.name: s for s in index.list_skills()}
        assert by_name["core"].source == "bundled"
        assert by_name["user"].source == "external"

    def test_default_external_dirs_are_cantrip_then_claude(self) -> None:
        """Cantrip-specific dir trumps shared Claude Code dir on name conflicts."""
        from cantrip.agent.skills import _default_external_skill_dirs

        dirs = _default_external_skill_dirs()
        paths = [str(d) for d in dirs]
        # Claude Code first (shared), Cantrip second (user-specific) — so
        # Cantrip's wins the insertion-order contest in ``SkillsIndex``.
        assert any(".claude/skills" in p for p in paths)
        assert any(".config/cantrip/skills" in p for p in paths)
        claude_idx = next(i for i, p in enumerate(paths) if ".claude/skills" in p)
        cantrip_idx = next(i for i, p in enumerate(paths) if ".config/cantrip/skills" in p)
        assert claude_idx < cantrip_idx, (
            "Cantrip-specific dir must come after the shared Claude Code dir "
            "so it wins the later-wins override."
        )

    def test_explicit_dir_does_not_pick_up_host_external_dirs(self, tmp_path: Path) -> None:
        """Passing an explicit ``skills_dir`` isolates from the host environment.

        Test authors rely on this isolation — a fixture that hands a
        ``tmp_path`` to ``SkillsIndex`` must not accidentally read the
        developer's real ``~/.claude/skills/``.
        """
        (tmp_path / "only").mkdir()
        (tmp_path / "only" / "SKILL.md").write_text(
            "---\nname: only\ndescription: the only skill\n---\nBody\n"
        )
        index = SkillsIndex(tmp_path)
        index.discover()
        assert [s.name for s in index.list_skills()] == ["only"]


class TestLoadSkillTool:
    """Tests for the LoadSkillTool."""

    @pytest.mark.asyncio()
    async def test_load_existing_skill(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        tool = LoadSkillTool(index)
        result = await tool.execute(skill_name="alpha")
        assert result.success
        assert "Alpha body content." in result.output

    @pytest.mark.asyncio()
    async def test_load_unknown_skill(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        tool = LoadSkillTool(index)
        result = await tool.execute(skill_name="nonexistent")
        assert not result.success
        assert "Unknown skill" in (result.error or "")
        assert "alpha" in (result.error or "")
        assert "beta" in (result.error or "")

    def test_tool_metadata(self, skills_dir: Path) -> None:
        index = SkillsIndex(skills_dir)
        tool = LoadSkillTool(index)
        assert tool.name == "load_skill"
        assert "skill" in tool.description.lower()
        assert "skill_name" in tool.parameters["properties"]
