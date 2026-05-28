"""Tests for Phase 70.3 — glob-conditional guidance frontmatter.

The tests below cover the pieces that compose conditional loading
of skill guidance:

1. Frontmatter parsing: ``globs:`` field accepted as a YAML list or a
   comma-separated string, defaults to empty when missing.
2. Glob matcher: ``**`` segments, bare-filename and path-shaped
   patterns, ``fnmatch``-style per-segment wildcards.
3. ``SkillsIndex.format_for_prompt`` filtering: skills with non-empty
   globs only enter the rendered XML when at least one of
   ``current_files`` matches; skills with empty globs stay
   unconditional (backwards compatibility).
4. ``SkillsIndex.filtering_report`` for transcript observability.
5. ``_extract_user_mentioned_files`` predicate covers user-message
   file mentions and ignores non-path tokens.
6. ``CantripAgent._build_system_prompt`` emits a ``skill_filter``
   transcript event when the loaded set changes.
"""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.core import CantripAgent, _extract_user_mentioned_files
from cantrip.agent.skills import (
    SkillsIndex,
    _any_glob_matches,
    _glob_matches,
    _segments_match,
)
from cantrip.llm.base import Message, Response, Role
from tests.conftest import FakeProvider

# --------------------------------------------------------------------
# Frontmatter parsing
# --------------------------------------------------------------------


class TestGlobFrontmatter:
    """``globs:`` field is parsed alongside ``tools`` and ``mcp_servers``."""

    def _write_skill(self, root: pathlib.Path, name: str, frontmatter: str) -> None:
        skill_dir = root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(frontmatter + "\n# Body\n")

    def test_globs_yaml_list(self, tmp_path: pathlib.Path) -> None:
        self._write_skill(
            tmp_path,
            "metadata",
            "---\n"
            "name: metadata\n"
            "description: metadata authoring\n"
            "globs:\n  - metadata.yaml\n  - charmcraft.yaml\n"
            "---\n",
        )
        index = SkillsIndex(tmp_path)
        index.discover()
        meta = index.metadata_for("metadata")
        assert meta is not None
        assert meta.globs == ["metadata.yaml", "charmcraft.yaml"]

    def test_globs_comma_separated_string(self, tmp_path: pathlib.Path) -> None:
        self._write_skill(
            tmp_path,
            "tests",
            "---\n"
            "name: tests\n"
            "description: jubilant tests\n"
            "globs: tests/integration/**, tests/test_*.py\n"
            "---\n",
        )
        index = SkillsIndex(tmp_path)
        index.discover()
        meta = index.metadata_for("tests")
        assert meta is not None
        assert meta.globs == ["tests/integration/**", "tests/test_*.py"]

    def test_globs_absent_defaults_to_empty(self, tmp_path: pathlib.Path) -> None:
        self._write_skill(
            tmp_path,
            "broad",
            "---\nname: broad\ndescription: broadly applicable\n---\n",
        )
        index = SkillsIndex(tmp_path)
        index.discover()
        meta = index.metadata_for("broad")
        assert meta is not None
        assert meta.globs == []

    def test_globs_invalid_value_silently_ignored(self, tmp_path: pathlib.Path) -> None:
        # A bare integer is not a list of strings — coercion drops it,
        # matching how malformed ``tools`` entries are handled.  Skill
        # discovery should still succeed.
        self._write_skill(
            tmp_path,
            "weird",
            "---\nname: weird\ndescription: weirdly typed\nglobs: 42\n---\n",
        )
        index = SkillsIndex(tmp_path)
        index.discover()
        meta = index.metadata_for("weird")
        assert meta is not None
        assert meta.globs == []


# --------------------------------------------------------------------
# Low-level glob matcher
# --------------------------------------------------------------------


class TestGlobMatcher:
    """``_glob_matches`` and ``_segments_match`` mechanics."""

    @pytest.fixture()
    def charm_root(self, tmp_path: pathlib.Path) -> pathlib.Path:
        return tmp_path / "my-charm"

    def test_bare_basename_pattern(self, charm_root: pathlib.Path) -> None:
        assert _glob_matches(
            "metadata.yaml",
            charm_root / "metadata.yaml",
            charm_root,
        )
        # No charm root: the same bare-pattern still matches by basename.
        assert _glob_matches("metadata.yaml", pathlib.Path("/tmp/x/metadata.yaml"), None)

    def test_bare_extension_wildcard(self, charm_root: pathlib.Path) -> None:
        assert _glob_matches("*.py", charm_root / "src" / "charm.py", charm_root)
        assert not _glob_matches("*.py", charm_root / "metadata.yaml", charm_root)

    def test_double_star_matches_zero_or_more_segments(self, charm_root: pathlib.Path) -> None:
        assert _glob_matches(
            "tests/integration/**",
            charm_root / "tests" / "integration" / "test_x.py",
            charm_root,
        )
        # ``**`` matches zero segments too — the directory itself.
        assert _segments_match(["tests", "integration", "**"], ["tests", "integration"])

    def test_double_star_in_middle(self, charm_root: pathlib.Path) -> None:
        assert _glob_matches(
            "src/**/charm.py",
            charm_root / "src" / "charm.py",
            charm_root,
        )
        assert _glob_matches(
            "src/**/charm.py",
            charm_root / "src" / "subpkg" / "charm.py",
            charm_root,
        )
        assert not _glob_matches(
            "src/**/charm.py",
            charm_root / "lib" / "subpkg" / "charm.py",
            charm_root,
        )

    def test_path_outside_charm_root_does_not_falsely_match(
        self, charm_root: pathlib.Path
    ) -> None:
        # Path-shaped globs are anchored: a file outside ``charm_root``
        # must be matched against its full filesystem-rooted POSIX form,
        # so a glob like ``tests/integration/**`` does *not* secretly
        # match ``/var/elsewhere/tests/integration/test.py``.  This
        # avoids surprising hits when the agent is reading something
        # outside the charm dir (a sibling clone, a system file).
        assert not _glob_matches(
            "tests/integration/**",
            pathlib.Path("/var/elsewhere/tests/integration/test.py"),
            charm_root,
        )

    def test_no_charm_root_uses_full_posix_path(self) -> None:
        # When ``charm_path`` is ``None``, the matcher uses the path's
        # own POSIX form (with the leading ``/`` stripped).  An
        # un-anchored ``tests/**`` glob therefore won't match an
        # absolute path that doesn't start with ``tests/``.
        assert not _glob_matches(
            "tests/integration/**",
            pathlib.Path("/var/foo/tests/integration/test.py"),
            None,
        )

    def test_any_glob_matches_short_circuits(self, charm_root: pathlib.Path) -> None:
        files = [charm_root / "src" / "charm.py", charm_root / "metadata.yaml"]
        # Match wins on second pattern, second file.
        assert _any_glob_matches(["actions.yaml", "metadata.yaml"], files, charm_root)
        # No pattern matches any file.
        assert not _any_glob_matches(["actions.yaml"], files, charm_root)

    def test_no_paths_no_match(self, charm_root: pathlib.Path) -> None:
        assert not _any_glob_matches(["metadata.yaml"], [], charm_root)


# --------------------------------------------------------------------
# format_for_prompt filtering
# --------------------------------------------------------------------


class TestFormatForPromptFiltering:
    """Skill index respects ``globs:`` when ``current_files`` is supplied."""

    def _build_index(self, tmp_path: pathlib.Path) -> SkillsIndex:
        # Three skills: one unconditional, one for tests, one for metadata.
        for name, fm in [
            (
                "broad",
                "---\nname: broad\ndescription: applies everywhere\n---\n",
            ),
            (
                "tests",
                "---\nname: tests\ndescription: jubilant tests\n"
                "globs: [tests/integration/**]\n---\n",
            ),
            (
                "metadata",
                "---\nname: metadata\ndescription: metadata authoring\n"
                "globs: [metadata.yaml, charmcraft.yaml]\n---\n",
            ),
        ]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(fm + "# Body\n")
        index = SkillsIndex(tmp_path)
        index.discover()
        return index

    def test_no_current_files_renders_everything(self, tmp_path: pathlib.Path) -> None:
        index = self._build_index(tmp_path)
        # Backwards-compat path: callers that don't thread file context
        # through still get the historical "all skills always" behaviour.
        rendered = index.format_for_prompt()
        assert "<name>broad</name>" in rendered
        assert "<name>tests</name>" in rendered
        assert "<name>metadata</name>" in rendered

    def test_filter_includes_unconditional_and_matching(self, tmp_path: pathlib.Path) -> None:
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        rendered = index.format_for_prompt(
            current_files=[charm_root / "metadata.yaml"],
            charm_path=charm_root,
        )
        assert "<name>broad</name>" in rendered
        assert "<name>metadata</name>" in rendered
        assert "<name>tests</name>" not in rendered

    def test_filter_excludes_non_matching(self, tmp_path: pathlib.Path) -> None:
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        rendered = index.format_for_prompt(
            current_files=[charm_root / "src" / "charm.py"],
            charm_path=charm_root,
        )
        assert "<name>broad</name>" in rendered
        assert "<name>metadata</name>" not in rendered
        assert "<name>tests</name>" not in rendered

    def test_filter_multiple_globs_one_matches(self, tmp_path: pathlib.Path) -> None:
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        # ``charmcraft.yaml`` is the *second* of the metadata globs —
        # one match is enough to pull the skill in.
        rendered = index.format_for_prompt(
            current_files=[charm_root / "charmcraft.yaml"],
            charm_path=charm_root,
        )
        assert "<name>metadata</name>" in rendered

    def test_empty_current_files_filters_globbed_skills_out(self, tmp_path: pathlib.Path) -> None:
        # An *empty* sequence is meaningfully different from ``None``:
        # the agent has no files in scope this turn, so globbed skills
        # don't load.  Unconditional skills still do.
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        rendered = index.format_for_prompt(
            current_files=[],
            charm_path=charm_root,
        )
        assert "<name>broad</name>" in rendered
        assert "<name>metadata</name>" not in rendered
        assert "<name>tests</name>" not in rendered


# --------------------------------------------------------------------
# Filtering report (transcript observability)
# --------------------------------------------------------------------


class TestFilteringReport:
    """``filtering_report`` returns the loaded/skipped split for audit."""

    def _build_index(self, tmp_path: pathlib.Path) -> SkillsIndex:
        for name, fm in [
            ("a", "---\nname: a\ndescription: A\nglobs: [metadata.yaml]\n---\n"),
            ("b", "---\nname: b\ndescription: B\nglobs: [tests/**]\n---\n"),
            ("c", "---\nname: c\ndescription: C unconditional\n---\n"),
        ]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(fm + "body\n")
        index = SkillsIndex(tmp_path)
        index.discover()
        return index

    def test_report_lists_loaded_and_skipped(self, tmp_path: pathlib.Path) -> None:
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        report = index.filtering_report(
            current_files=[charm_root / "metadata.yaml"],
            charm_path=charm_root,
        )
        assert report["loaded"] == ["a"]
        assert report["skipped"] == ["b"]
        # Unconditional skills are intentionally absent.
        assert "c" not in report["loaded"] and "c" not in report["skipped"]
        assert report["files"] == [str(charm_root / "metadata.yaml")]

    def test_report_no_match_skips_everything(self, tmp_path: pathlib.Path) -> None:
        charm_root = tmp_path / "charm"
        index = self._build_index(tmp_path)
        report = index.filtering_report(
            current_files=[charm_root / "src" / "charm.py"],
            charm_path=charm_root,
        )
        assert report["loaded"] == []
        assert sorted(report["skipped"]) == ["a", "b"]


# --------------------------------------------------------------------
# User-message file extraction
# --------------------------------------------------------------------


class TestExtractUserMentionedFiles:
    """``_extract_user_mentioned_files`` finds path-shaped tokens."""

    def test_picks_up_bare_charm_filenames(self) -> None:
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files(
            "Please update metadata.yaml and add an interface", charm
        )
        assert charm / "metadata.yaml" in out

    def test_picks_up_relative_paths(self) -> None:
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files("Edit src/charm.py to handle config-changed", charm)
        assert charm / "src/charm.py" in out

    def test_strips_backticks_and_quotes(self) -> None:
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files(
            "Look at `tests/integration/test_deploy.py` please", charm
        )
        assert charm / "tests/integration/test_deploy.py" in out

    def test_ignores_version_strings(self) -> None:
        # ``1.2.3`` is the classic false-positive.  Filter to known
        # extensions so version numbers and host:port tokens don't
        # pull skills in.
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files("We're on Juju 3.4.5 and ops 2.17.1 today", charm)
        assert out == []

    def test_ignores_arbitrary_words_with_dot(self) -> None:
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files("It works. Also, e.g. some text.", charm)
        assert out == []

    def test_dedupes_repeated_mentions(self) -> None:
        charm = pathlib.Path("/charms/foo")
        out = _extract_user_mentioned_files("metadata.yaml metadata.yaml metadata.yaml", charm)
        assert out == [charm / "metadata.yaml"]

    def test_empty_text(self) -> None:
        assert _extract_user_mentioned_files("", pathlib.Path("/charm")) == []


# --------------------------------------------------------------------
# Agent-level transcript event
# --------------------------------------------------------------------


class TestAgentEmitsSkillFilterEvent:
    """``CantripAgent._build_dynamic_context_message`` records a ``skill_filter`` event."""

    def test_event_recorded_on_first_filter(self, tmp_path: pathlib.Path) -> None:
        # Build an agent and replace its skills index with one that
        # has globbed skills.  ``process_message`` is heavy; we drive
        # ``_build_dynamic_context_message`` directly because that's where
        # the skills index (and its glob filter) is now rendered.
        provider = FakeProvider([Response(content="ok")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        skills_root = tmp_path / "_skills"
        skills_root.mkdir()
        for stub in [
            (
                "metadata-skill",
                "globs: [metadata.yaml]\n",
                "metadata-only",
            ),
            (
                "tests-skill",
                "globs: [tests/integration/**]\n",
                "tests-only",
            ),
        ]:
            name, glob_line, desc = stub
            d = skills_root / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {desc}\n{glob_line}---\n# b\n"
            )
        index = SkillsIndex(skills_root)
        index.discover()
        agent._skills_index_cache = index

        # Seed the conversation with a user message that names
        # ``metadata.yaml`` so the metadata skill loads but the
        # tests skill is filtered out.
        agent.state.messages.append(Message(role=Role.USER, content="edit metadata.yaml"))
        agent._ensure_store()
        assert agent._store is not None

        agent._build_dynamic_context_message()

        events = agent._store.load_events(event_type="skill_filter")
        assert len(events) == 1
        detail = events[0]["detail"]
        assert detail["loaded"] == ["metadata-skill"]
        assert detail["skipped"] == ["tests-skill"]

    def test_event_dedupes_unchanged_filters(self, tmp_path: pathlib.Path) -> None:
        provider = FakeProvider([Response(content="ok")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        skills_root = tmp_path / "_skills"
        skills_root.mkdir()
        d = skills_root / "metadata-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: metadata-skill\ndescription: m\nglobs: [metadata.yaml]\n---\n# b\n"
        )
        index = SkillsIndex(skills_root)
        index.discover()
        agent._skills_index_cache = index

        agent.state.messages.append(Message(role=Role.USER, content="edit metadata.yaml"))
        agent._ensure_store()
        assert agent._store is not None

        agent._build_dynamic_context_message()
        agent._build_dynamic_context_message()
        agent._build_dynamic_context_message()

        events = agent._store.load_events(event_type="skill_filter")
        # Only the *first* call records — subsequent identical
        # filter decisions are deduped on the in-memory signature.
        assert len(events) == 1

    def test_event_re_emits_when_filter_changes(self, tmp_path: pathlib.Path) -> None:
        provider = FakeProvider([Response(content="ok")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        skills_root = tmp_path / "_skills"
        skills_root.mkdir()
        for name, glob_line in [
            ("metadata-skill", "globs: [metadata.yaml]\n"),
            ("tests-skill", "globs: [tests/integration/**]\n"),
        ]:
            d = skills_root / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: d\n{glob_line}---\n# b\n"
            )
        index = SkillsIndex(skills_root)
        index.discover()
        agent._skills_index_cache = index

        agent._ensure_store()
        assert agent._store is not None

        # Turn 1: user mentions metadata.yaml.
        agent.state.messages.append(Message(role=Role.USER, content="edit metadata.yaml"))
        agent._build_dynamic_context_message()
        # Turn 2: user pivots to integration tests.
        agent.state.messages.append(
            Message(role=Role.USER, content="now write tests/integration/test_x.py")
        )
        agent._build_dynamic_context_message()

        events = agent._store.load_events(event_type="skill_filter")
        assert len(events) == 2
        first, second = events
        # Turn 1: only metadata.yaml is mentioned.
        assert first["detail"]["loaded"] == ["metadata-skill"]
        assert first["detail"]["skipped"] == ["tests-skill"]
        # Turn 2: predicate scans the recent message window, so both
        # the prior metadata.yaml mention *and* the new
        # tests/integration path are in scope — both skills load.
        assert sorted(second["detail"]["loaded"]) == ["metadata-skill", "tests-skill"]
        assert second["detail"]["skipped"] == []

    def test_no_event_when_no_skills_have_globs(self, tmp_path: pathlib.Path) -> None:
        provider = FakeProvider([Response(content="ok")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        skills_root = tmp_path / "_skills"
        skills_root.mkdir()
        d = skills_root / "broad"
        d.mkdir()
        # No ``globs:`` — unconditional, so the filter is a no-op
        # and the transcript stays clean.
        (d / "SKILL.md").write_text("---\nname: broad\ndescription: b\n---\n# b\n")
        index = SkillsIndex(skills_root)
        index.discover()
        agent._skills_index_cache = index

        agent._ensure_store()
        assert agent._store is not None

        agent._build_dynamic_context_message()

        events = agent._store.load_events(event_type="skill_filter")
        assert events == []
