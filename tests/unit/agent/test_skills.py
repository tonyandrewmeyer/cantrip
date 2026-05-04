"""Tests for skills discovery, loading, and the LoadSkillTool."""

import pathlib

import pytest

from cantrip.agent.skills import SkillMetadata, SkillsIndex
from cantrip.agent.tools.skills import LoadSkillTool


@pytest.fixture()
def skills_dir(tmp_path: pathlib.Path) -> pathlib.Path:
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

    def test_discover_finds_skills(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        names = [s.name for s in index.list_skills()]
        assert names == ["alpha", "beta"]

    def test_discover_nonexistent_dir(self, tmp_path: pathlib.Path) -> None:
        index = SkillsIndex(tmp_path / "nope")
        index.discover()
        assert index.list_skills() == []

    def test_discover_empty_dir(self, tmp_path: pathlib.Path) -> None:
        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_malformed_frontmatter(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter here\n")

        good = tmp_path / "good"
        good.mkdir()
        (good / "SKILL.md").write_text("---\nname: good\ndescription: A good skill\n---\nBody.\n")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert [s.name for s in index.list_skills()] == ["good"]

    def test_discover_skips_deeply_nested_frontmatter(self, tmp_path: pathlib.Path) -> None:
        """A SKILL.md with frontmatter past Python's recursion limit is skipped.

        Regression: ``SkillsIndex.discover`` caught
        ``(yaml.YAMLError, ValueError)`` only.  PyYAML's tokeniser
        raises ``RecursionError`` (a ``RuntimeError``, not a YAMLError)
        on heavily nested input, so a malicious or accidentally-deep
        SKILL.md crashed ``cantrip skill export`` and any agent flow
        that triggered skills discovery.
        """
        deep = tmp_path / "deep"
        deep.mkdir()
        body = "---\nname: deep\ndescription: nested\n"
        for i in range(800):
            body += "  " * i + f"k{i}:\n"
        body += "  " * 800 + "leaf: x\n"
        body += "---\n\nbody\n"
        (deep / "SKILL.md").write_text(body)

        good = tmp_path / "good"
        good.mkdir()
        (good / "SKILL.md").write_text("---\nname: good\ndescription: A good skill\n---\nBody.\n")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert [s.name for s in index.list_skills()] == ["good"]

    def test_discover_skips_missing_fields(self, tmp_path: pathlib.Path) -> None:
        """A SKILL.md with frontmatter but no name/description is skipped."""
        skill = tmp_path / "incomplete"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: incomplete\n---\nBody.\n")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_non_directory(self, tmp_path: pathlib.Path) -> None:
        """Files at the top level of the skills dir are ignored."""
        (tmp_path / "README.md").write_text("not a skill")

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_discover_skips_dir_without_skill_md(self, tmp_path: pathlib.Path) -> None:
        """Directories without a SKILL.md are ignored."""
        (tmp_path / "empty-dir").mkdir()

        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.list_skills() == []

    def test_list_skills_returns_metadata(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        skills = index.list_skills()
        assert len(skills) == 2
        assert all(isinstance(s, SkillMetadata) for s in skills)
        assert skills[0].name == "alpha"
        assert skills[0].description == "The alpha skill"

    def test_list_skills_sorted_by_name(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        names = [s.name for s in index.list_skills()]
        assert names == sorted(names)

    def test_load_skill_returns_body(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        body = index.load_skill("alpha")
        assert "Alpha body content." in body
        # Frontmatter should not be in the body.
        assert "---" not in body

    def test_load_skill_unknown_raises(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        with pytest.raises(KeyError):
            index.load_skill("nonexistent")

    def test_format_for_prompt_xml(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        xml = index.format_for_prompt()
        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<name>alpha</name>" in xml
        assert "<description>The alpha skill</description>" in xml
        assert "<name>beta</name>" in xml

    def test_format_for_prompt_empty(self, tmp_path: pathlib.Path) -> None:
        index = SkillsIndex(tmp_path)
        index.discover()
        assert index.format_for_prompt() == ""

    def test_discover_clears_previous(self, skills_dir: pathlib.Path) -> None:
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

    def test_missing_external_dir_is_silent(self, tmp_path: pathlib.Path) -> None:
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

    def test_external_dir_skill_appears_alongside_bundled(self, tmp_path: pathlib.Path) -> None:
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
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
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

    def test_external_single_file_skill_is_discovered(self, tmp_path: pathlib.Path) -> None:
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

    def test_frontmatter_tools_parsed_as_list(self, tmp_path: pathlib.Path) -> None:
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

    def test_frontmatter_tools_parsed_as_comma_string(self, tmp_path: pathlib.Path) -> None:
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

    def test_malformed_tools_falls_back_to_empty_list(self, tmp_path: pathlib.Path) -> None:
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

    def test_source_tag_identifies_provenance(self, tmp_path: pathlib.Path) -> None:
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

    def test_default_external_dirs_are_most_shared_first(self) -> None:
        """Precedence ordering: universal → Claude Code → Cantrip-specific.

        ``~/.config/agents/skills/`` is the ``gh skill install`` user-scope
        ``universal`` bucket (shared by opencode, kimi-cli, warp, replit
        and several others); it's the least specific and loses to every
        Claude or Cantrip skill on name conflict.  ``~/.claude/skills/``
        is shared with Claude Code.  ``~/.config/cantrip/skills/`` is
        Cantrip-only and wins the insertion-order contest against both.
        """
        from cantrip.agent.skills import _default_external_skill_dirs

        dirs = _default_external_skill_dirs()
        paths = [str(d) for d in dirs]
        assert any(".config/agents/skills" in p for p in paths)
        assert any(".claude/skills" in p for p in paths)
        assert any(".config/cantrip/skills" in p for p in paths)
        agents_idx = next(i for i, p in enumerate(paths) if ".config/agents/skills" in p)
        claude_idx = next(i for i, p in enumerate(paths) if ".claude/skills" in p)
        cantrip_idx = next(i for i, p in enumerate(paths) if ".config/cantrip/skills" in p)
        assert agents_idx < claude_idx < cantrip_idx, (
            "Expected universal → Claude → Cantrip-specific order "
            "so Cantrip's wins name conflicts on later-wins semantics."
        )

    def test_project_root_adds_gh_skill_project_scope_dirs(self, tmp_path: pathlib.Path) -> None:
        """``project_root=`` unlocks the project-scope ``gh skill install`` paths."""
        from cantrip.agent.skills import _default_project_skill_dirs

        project = tmp_path / "charm-repo"
        project.mkdir()
        (project / ".agents" / "skills").mkdir(parents=True)
        (project / ".agents" / "skills" / "from-gh").mkdir()
        (project / ".agents" / "skills" / "from-gh" / "SKILL.md").write_text(
            "---\nname: from-gh\ndescription: installed via gh skill\n---\nBody\n"
        )
        (project / ".claude" / "skills").mkdir(parents=True)
        (project / ".claude" / "skills" / "claude-only").mkdir()
        (project / ".claude" / "skills" / "claude-only" / "SKILL.md").write_text(
            "---\nname: claude-only\ndescription: Claude Code user-scope\n---\nBody\n"
        )

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        index = SkillsIndex(bundled, project_root=project)
        index.discover()
        names = {s.name for s in index.list_skills()}
        assert {"from-gh", "claude-only"} <= names

        # _default_project_skill_dirs returns the two project paths in
        # the documented order.
        dirs = _default_project_skill_dirs(project)
        paths = [str(d) for d in dirs]
        agents_idx = next(i for i, p in enumerate(paths) if ".agents/skills" in p)
        claude_idx = next(i for i, p in enumerate(paths) if ".claude/skills" in p)
        assert agents_idx < claude_idx

    def test_project_scope_skill_overrides_user_scope(self, tmp_path: pathlib.Path) -> None:
        """A repo-local ``gh skill install`` copy wins over the same-named user-scope one."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        (external / "shared").mkdir()
        (external / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: user-scope version\n---\nUser body\n"
        )

        project = tmp_path / "charm"
        project.mkdir()
        (project / ".agents" / "skills" / "shared").mkdir(parents=True)
        (project / ".agents" / "skills" / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: project-scope version\n---\nProject body\n"
        )

        index = SkillsIndex(bundled, extra_dirs=[external], project_root=project)
        index.discover()
        [metadata] = index.list_skills()
        assert metadata.description == "project-scope version"
        assert "Project body" in index.load_skill("shared")

    def test_project_root_none_skips_project_discovery(self, tmp_path: pathlib.Path) -> None:
        """Without ``project_root=`` the project paths are not scanned at all."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        project = tmp_path / "charm"
        (project / ".agents" / "skills" / "ghost").mkdir(parents=True)
        (project / ".agents" / "skills" / "ghost" / "SKILL.md").write_text(
            "---\nname: ghost\ndescription: should not be picked up\n---\nBody\n"
        )

        # No project_root kwarg → the .agents/skills tree is invisible.
        index = SkillsIndex(bundled)
        index.discover()
        assert [s.name for s in index.list_skills()] == []

    def test_explicit_dir_does_not_pick_up_host_external_dirs(
        self, tmp_path: pathlib.Path
    ) -> None:
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
    async def test_load_existing_skill(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        tool = LoadSkillTool(index)
        result = await tool.execute(skill_name="alpha")
        assert result.success
        assert "Alpha body content." in result.output

    @pytest.mark.asyncio()
    async def test_load_unknown_skill(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        index.discover()
        tool = LoadSkillTool(index)
        result = await tool.execute(skill_name="nonexistent")
        assert not result.success
        assert "Unknown skill" in (result.error or "")
        assert "alpha" in (result.error or "")
        assert "beta" in (result.error or "")

    def test_tool_metadata(self, skills_dir: pathlib.Path) -> None:
        index = SkillsIndex(skills_dir)
        tool = LoadSkillTool(index)
        assert tool.name == "load_skill"
        assert "skill" in tool.description.lower()
        assert "skill_name" in tool.parameters["properties"]


class TestMCPAwareSkills:
    """Phase 50.4: skills can declare MCP server dependencies.

    The loader doesn't filter skills — it surfaces them all and prepends
    a warning banner to the body when declared servers aren't
    configured.  Gating at discovery would silently hide skills the
    agent might still extract value from; a visible warning is a
    better failure mode.
    """

    @staticmethod
    def _build_index(
        tmp_path: pathlib.Path, frontmatter: str, body: str = "Body\n"
    ) -> SkillsIndex:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "deployer").mkdir()
        (bundled / "deployer" / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}")
        index = SkillsIndex(bundled)
        index.discover()
        return index

    def test_mcp_servers_parsed_as_yaml_list(self, tmp_path: pathlib.Path) -> None:
        index = self._build_index(
            tmp_path,
            "name: deployer\n"
            "description: Deploys via MCP\n"
            "mcp_servers:\n  - filesystem\n  - github",
        )
        [metadata] = index.list_skills()
        assert metadata.mcp_servers == ["filesystem", "github"]

    def test_mcp_servers_parsed_as_comma_string(self, tmp_path: pathlib.Path) -> None:
        """Same comma-string shape the ``tools`` field accepts."""
        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers: filesystem, github",
        )
        [metadata] = index.list_skills()
        assert metadata.mcp_servers == ["filesystem", "github"]

    def test_mcp_servers_missing_defaults_to_empty(self, tmp_path: pathlib.Path) -> None:
        index = self._build_index(tmp_path, "name: deployer\ndescription: d")
        [metadata] = index.list_skills()
        assert metadata.mcp_servers == []

    def test_mcp_servers_malformed_falls_back_to_empty(self, tmp_path: pathlib.Path) -> None:
        """A non-list, non-string entry doesn't crash discovery."""
        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers: 42",
        )
        [metadata] = index.list_skills()
        assert metadata.mcp_servers == []

    def test_format_for_prompt_includes_required_mcp_servers(self, tmp_path: pathlib.Path) -> None:
        """Declared servers surface in the prompt-level skill index."""
        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers:\n  - filesystem",
        )
        xml = index.format_for_prompt()
        assert "<required_mcp_servers>filesystem</required_mcp_servers>" in xml

    def test_format_for_prompt_omits_required_mcp_servers_when_none(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Skills without MCP deps don't add noise to the prompt."""
        index = self._build_index(tmp_path, "name: deployer\ndescription: d")
        xml = index.format_for_prompt()
        assert "<required_mcp_servers>" not in xml

    @pytest.mark.asyncio()
    async def test_load_skill_warns_when_server_missing(self, tmp_path: pathlib.Path) -> None:
        """A skill declaring an unconfigured server loads with a warning banner."""
        from cantrip.mcp.registry import MCPRegistry

        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers:\n  - filesystem",
            body="# Skill body.\n\nStep 1: do something.\n",
        )
        empty_registry = MCPRegistry([])  # No servers configured.
        tool = LoadSkillTool(index, mcp_registry=empty_registry)
        result = await tool.execute(skill_name="deployer")
        assert result.success
        assert "filesystem" in result.output
        assert "NOT configured" in result.output
        # Body still there after the banner.
        assert "Step 1: do something." in result.output

    @pytest.mark.asyncio()
    async def test_load_skill_no_warning_when_servers_configured(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Every declared server configured → no banner."""
        from cantrip.mcp.registry import MCPRegistry
        from cantrip.mcp.types import ServerConfig

        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers:\n  - filesystem",
            body="# Clean body.\n",
        )
        registry = MCPRegistry([ServerConfig(name="filesystem")])
        tool = LoadSkillTool(index, mcp_registry=registry)
        result = await tool.execute(skill_name="deployer")
        assert result.success
        assert "NOT configured" not in result.output
        assert "# Clean body." in result.output

    @pytest.mark.asyncio()
    async def test_load_skill_banner_lists_only_missing_servers(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Banner names the unconfigured subset only."""
        from cantrip.mcp.registry import MCPRegistry
        from cantrip.mcp.types import ServerConfig

        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers:\n  - filesystem\n  - github\n  - slack",
        )
        registry = MCPRegistry([ServerConfig(name="filesystem")])
        tool = LoadSkillTool(index, mcp_registry=registry)
        result = await tool.execute(skill_name="deployer")
        assert "github" in result.output
        assert "slack" in result.output
        # ``filesystem`` is configured so it should NOT be named as missing.
        # Check the banner section specifically (first ~300 chars).
        banner = result.output.split("\n\n", 1)[0]
        assert "filesystem" not in banner
        assert "github" in banner

    @pytest.mark.asyncio()
    async def test_load_skill_without_registry_treats_all_as_missing(
        self, tmp_path: pathlib.Path
    ) -> None:
        """No registry wired in at all → every declared server is flagged."""
        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\nmcp_servers:\n  - filesystem",
        )
        tool = LoadSkillTool(index)  # No mcp_registry.
        result = await tool.execute(skill_name="deployer")
        assert result.success
        assert "filesystem" in result.output
        assert "NOT configured" in result.output

    @pytest.mark.asyncio()
    async def test_load_skill_without_deps_never_adds_banner(self, tmp_path: pathlib.Path) -> None:
        """A skill with no ``mcp_servers:`` is unaffected by the registry check."""
        from cantrip.mcp.registry import MCPRegistry

        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: no deps",
            body="# Pristine body.\n",
        )
        tool = LoadSkillTool(index, mcp_registry=MCPRegistry([]))
        result = await tool.execute(skill_name="deployer")
        assert result.success
        assert result.output.strip() == "# Pristine body."

    def test_export_round_trips_mcp_servers(self, tmp_path: pathlib.Path) -> None:
        """``cantrip skill export`` emits ``mcp_servers`` when present."""
        from cantrip.agent.skill_export import export_skill

        index = self._build_index(
            tmp_path,
            "name: deployer\ndescription: d\n"
            "tools:\n  - juju_status\n"
            "mcp_servers:\n  - filesystem\n  - github",
        )
        target = tmp_path / "out.md"
        export_skill("deployer", target, index=index)

        # Re-import via a fresh isolated index.
        reload_dir = tmp_path / "reload"
        reload_dir.mkdir()
        (reload_dir / "deployer.md").write_text(target.read_text())
        reload_index = SkillsIndex(reload_dir)
        reload_index.discover()
        [metadata] = reload_index.list_skills()
        assert metadata.tools == ["juju_status"]
        assert metadata.mcp_servers == ["filesystem", "github"]

    def test_export_omits_mcp_servers_when_empty(self, tmp_path: pathlib.Path) -> None:
        """A skill without ``mcp_servers`` exports clean frontmatter."""
        from cantrip.agent.skill_export import export_skill

        index = self._build_index(tmp_path, "name: deployer\ndescription: d")
        target = tmp_path / "out.md"
        export_skill("deployer", target, index=index)
        assert "mcp_servers:" not in target.read_text()


class TestExportSkill:
    """Phase 50.2: export a discovered skill as a standard SKILL.md file."""

    def test_export_to_directory_writes_under_name_subdir(self, tmp_path: pathlib.Path) -> None:
        """A directory target expands to ``<dir>/<name>/SKILL.md``."""
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: The alpha skill\n---\n\n# Alpha\n\nBody content.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target_dir = tmp_path / "out"
        result = export_skill("alpha", target_dir, index=index)

        assert result.output_path == target_dir / "alpha" / "SKILL.md"
        assert result.output_path.is_file()
        written = result.output_path.read_text()
        assert written.startswith("---\n")
        assert "name: alpha" in written
        assert "description: The alpha skill" in written
        assert "Body content." in written

    def test_export_to_explicit_md_path_is_verbatim(self, tmp_path: pathlib.Path) -> None:
        """An explicit ``.md`` path is written exactly where the caller asked."""
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "my-export.md"
        result = export_skill("alpha", target, index=index)

        assert result.output_path == target
        assert target.is_file()

    def test_refuses_to_overwrite_without_force(self, tmp_path: pathlib.Path) -> None:
        """Refuses to clobber an existing target; pointing at --force flag in the message."""
        from cantrip.agent.skill_export import SkillExportError, export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "existing.md"
        target.write_text("pre-existing\n")

        with pytest.raises(SkillExportError) as exc_info:
            export_skill("alpha", target, index=index)
        assert "--force" in str(exc_info.value)
        # File left untouched.
        assert target.read_text() == "pre-existing\n"

    def test_force_overwrites_existing_target(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "existing.md"
        target.write_text("pre-existing\n")

        export_skill("alpha", target, index=index, force=True)
        assert "pre-existing" not in target.read_text()
        assert "Body." in target.read_text()

    def test_unknown_skill_raises_with_known_names(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.skill_export import SkillExportError, export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        with pytest.raises(SkillExportError) as exc_info:
            export_skill("nonexistent", tmp_path / "out", index=index)
        message = str(exc_info.value)
        assert "nonexistent" in message
        assert "alpha" in message

    def test_target_under_regular_file_raises_friendly(self, tmp_path: pathlib.Path) -> None:
        """A non-directory target (e.g. ``/dev/null``) yields a clean error.

        Regression: when the user passed an output path that points at a
        regular file, ``_resolve_target`` synthesised
        ``<output_path>/<name>/SKILL.md`` and the subsequent
        ``parent.mkdir(parents=True)`` raised ``NotADirectoryError`` —
        leaking a Python traceback to the CLI.
        """
        from cantrip.agent.skill_export import SkillExportError, export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        # Create a regular file and ask the exporter to use it as a parent.
        regular_file = tmp_path / "not-a-dir"
        regular_file.write_text("placeholder\n")

        with pytest.raises(SkillExportError) as exc_info:
            export_skill("alpha", regular_file, index=index)
        message = str(exc_info.value)
        assert "not a directory" in message.lower()

    def test_target_under_unwritable_parent_raises_friendly(self, tmp_path: pathlib.Path) -> None:
        """Permission denied on the synthesised parent yields a clean error.

        Regression: pointing the exporter at an unwritable directory
        (``cantrip skill export find-bugs /`` for an unprivileged user)
        leaked ``PermissionError`` past the previous
        ``except (NotADirectoryError, FileExistsError)`` catch.  The
        export now wraps ``OSError`` more broadly.
        """
        from cantrip.agent.skill_export import SkillExportError, export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        # Create a read-only directory and aim under it.
        ro_parent = tmp_path / "ro"
        ro_parent.mkdir(mode=0o500)
        try:
            target = ro_parent / "child"
            with pytest.raises(SkillExportError, match="Cannot create"):
                export_skill("alpha", target, index=index)
        finally:
            ro_parent.chmod(0o700)

    def test_charm_path_scrubbed_to_placeholder(self, tmp_path: pathlib.Path) -> None:
        """The current charm path becomes ``<CHARM_PATH>`` in the exported body."""
        from cantrip.agent.memory.export import CHARM_PATH_PLACEHOLDER
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        charm = tmp_path / "my-charm"
        charm.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            f"---\nname: alpha\ndescription: desc\n---\n"
            f"Run the tests from {charm} before deploying.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "out.md"
        result = export_skill("alpha", target, index=index, charm_path=charm)

        written = target.read_text()
        assert str(charm) not in written
        assert CHARM_PATH_PLACEHOLDER in written
        assert result.redactions == 0  # Path replacement is not a "secret redaction".

    def test_secrets_redacted_and_counted(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\n"
            "Use the token ghp_abcdef0123456789abcdef0123456789 to sync.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "out.md"
        result = export_skill("alpha", target, index=index)

        written = target.read_text()
        assert "ghp_abcdef" not in written
        assert "[REDACTED]" in written
        assert result.redactions >= 1

    def test_tools_preserved_on_export(self, tmp_path: pathlib.Path) -> None:
        """Frontmatter ``tools`` round-trips verbatim on export."""
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha.md").write_text(
            "---\nname: alpha\ndescription: desc\n"
            "tools:\n  - juju_status\n  - juju_deploy\n---\n\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "out.md"
        export_skill("alpha", target, index=index)

        reload_index = SkillsIndex(tmp_path / "reload")
        # Import the exported file back via a fresh index.
        reload_dir = tmp_path / "reload"
        reload_dir.mkdir()
        (reload_dir / "alpha.md").write_text(target.read_text())
        reload_index = SkillsIndex(reload_dir)
        reload_index.discover()

        [metadata] = reload_index.list_skills()
        assert metadata.tools == ["juju_status", "juju_deploy"]

    def test_tools_omitted_when_source_has_none(self, tmp_path: pathlib.Path) -> None:
        """A skill without ``tools`` exports clean frontmatter (no empty list)."""
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        index = SkillsIndex(source)
        index.discover()

        target = tmp_path / "out.md"
        export_skill("alpha", target, index=index)

        assert "tools:" not in target.read_text()

    def test_round_trip_preserves_name_description_body_tools(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Export → clear → re-import via a fresh SkillsIndex preserves all fields."""
        from cantrip.agent.skill_export import export_skill

        source = tmp_path / "source"
        source.mkdir()
        (source / "my-skill").mkdir()
        original_body = (
            "# My skill\n\n"
            "Step 1: do a thing.\n"
            "Step 2: do another thing.\n"
            "\n"
            "See also the [twelve-factor skill](twelve-factor)."
        )
        (source / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill for round-trip\n"
            "tools:\n  - juju_status\n---\n\n" + original_body + "\n"
        )
        source_index = SkillsIndex(source)
        source_index.discover()

        # Export into an empty tree.
        export_root = tmp_path / "exported"
        export_root.mkdir()
        export_skill("my-skill", export_root, index=source_index)

        # Clear the original source; re-discover must come entirely from
        # the exported copy, proving the export carries everything needed.
        import shutil

        shutil.rmtree(source)

        reload_index = SkillsIndex(export_root)
        reload_index.discover()
        [metadata] = reload_index.list_skills()

        assert metadata.name == "my-skill"
        assert metadata.description == "A test skill for round-trip"
        assert metadata.tools == ["juju_status"]
        reloaded_body = reload_index.load_skill("my-skill")
        assert "Step 1: do a thing." in reloaded_body
        assert "Step 2: do another thing." in reloaded_body
        assert "twelve-factor" in reloaded_body


class TestSkillExportCLI:
    """Phase 50.2: the ``cantrip skill export`` CLI subcommand dispatcher."""

    @staticmethod
    def _isolated_index_factory(source: pathlib.Path) -> type:
        """Return a ``SkillsIndex`` subclass that always reads from *source*.

        ``_skill_export`` constructs the index with no arguments so it picks
        up the user's real ``~/.claude/skills/``.  Tests swap this subclass
        into the module for deterministic discovery on the CI box.
        """
        from cantrip.agent.skills import SkillsIndex as _SkillsIndexCls

        class _IsolatedIndex(_SkillsIndexCls):
            def __init__(self, *a: object, **kw: object) -> None:  # noqa: D401
                super().__init__(source)

        return _IsolatedIndex

    def test_happy_path(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exports a skill, writes the file, and prints the destination."""
        import argparse

        from cantrip.agent import skills as skills_module
        from cantrip.main import _skill_export

        source = tmp_path / "source"
        source.mkdir()
        (source / "alpha").mkdir()
        (source / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: desc\n---\nBody.\n"
        )
        monkeypatch.setattr(skills_module, "SkillsIndex", self._isolated_index_factory(source))

        target = tmp_path / "out.md"
        args = argparse.Namespace(name="alpha", path=target, charm_path=None, force=False)
        rc = _skill_export(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        assert str(target) in out
        assert target.is_file()

    def test_unknown_skill_exits_nonzero(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unknown skill name exits with code 2 and an informative message."""
        import argparse

        from cantrip.agent import skills as skills_module
        from cantrip.main import _skill_export

        empty_source = tmp_path / "empty"
        empty_source.mkdir()
        monkeypatch.setattr(
            skills_module, "SkillsIndex", self._isolated_index_factory(empty_source)
        )

        args = argparse.Namespace(
            name="nonexistent",
            path=tmp_path / "out.md",
            charm_path=None,
            force=False,
        )
        rc = _skill_export(args)

        assert rc == 2
        assert "nonexistent" in capsys.readouterr().err
