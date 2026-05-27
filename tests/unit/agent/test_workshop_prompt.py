"""Tests for the workshop-environment prompt injection."""

import pathlib

import pytest

from cantrip.agent.prompts import system, workshop
from cantrip.agent.prompts.system import build_system_prompt


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """Point the probe at a fresh temp path and reset its cache.

    Each test gets a unique ``workshop-prompt.md`` location so file
    presence/absence is fully under the test's control.
    """
    monkeypatch.setattr(workshop, "_WORKSHOP_PROMPT_PATH", tmp_path / "workshop-prompt.md")
    workshop.reset_cache()
    yield
    workshop.reset_cache()


class TestWorkshopPromptText:
    """Tests for the workshop_prompt_text() probe."""

    def test_returns_none_when_file_absent(self):
        """No workshop-prompt.md means no workshop context."""
        assert workshop.workshop_prompt_text() is None

    def test_returns_file_contents_when_present(self, tmp_path: pathlib.Path):
        """The file body is returned verbatim."""
        body = "# Workshop guidance\n\nStay in your container.\n"
        (tmp_path / "workshop-prompt.md").write_text(body, encoding="utf-8")
        assert workshop.workshop_prompt_text() == body

    def test_result_is_cached(self, tmp_path: pathlib.Path):
        """Once probed, the result is cached and survives file edits in-process."""
        (tmp_path / "workshop-prompt.md").write_text("first", encoding="utf-8")
        assert workshop.workshop_prompt_text() == "first"
        (tmp_path / "workshop-prompt.md").write_text("second", encoding="utf-8")
        # Cache wins until reset_cache() is called.
        assert workshop.workshop_prompt_text() == "first"

    def test_reset_cache_picks_up_new_state(self, tmp_path: pathlib.Path):
        """reset_cache() forces a re-read on the next call."""
        assert workshop.workshop_prompt_text() is None
        (tmp_path / "workshop-prompt.md").write_text("body", encoding="utf-8")
        workshop.reset_cache()
        assert workshop.workshop_prompt_text() == "body"


class TestSystemPromptIntegration:
    """Tests for build_system_prompt() with workshop_prompt injected."""

    def test_section_absent_by_default(self):
        """Without workshop_prompt the dedicated section is omitted."""
        result = build_system_prompt()
        assert "## Workshop Environment" not in result

    def test_section_present_when_supplied(self):
        """workshop_prompt content lands inside the Workshop Environment section."""
        body = "# Cantrip Workshop Environment Instructions\n\nLine."
        result = build_system_prompt(workshop_prompt=body)
        assert "## Workshop Environment" in result
        assert "Cantrip Workshop Environment Instructions" in result
        assert "Line." in result

    def test_section_appears_before_event_watcher(self):
        """When both are present, Workshop precedes the Event Watcher section."""
        result = build_system_prompt(workshop_prompt="body", watcher_enabled=True)
        workshop_idx = result.index("## Workshop Environment")
        watcher_idx = result.index("## Event Watcher")
        assert workshop_idx < watcher_idx

    def test_jinja_syntax_is_stripped(self):
        """User-editable workshop-prompt.md is sanitised against template injection."""
        # Same sanitiser policy as memory_index: { } % are removed.
        result = build_system_prompt(workshop_prompt="hello {{evil}} world")
        assert "{{" not in result
        assert "}}" not in result
        # The surrounding text survives.
        assert "hello" in result and "world" in result

    def test_lazy_loaded_default_unaffected(self):
        """SYSTEM_PROMPT (the lazy default) must not include the workshop section."""
        # ``system`` import keeps the lazy SYSTEM_PROMPT object alive across the
        # test session; verify it still renders without a workshop block when
        # build_system_prompt is called with no args.
        assert "## Workshop Environment" not in str(system.SYSTEM_PROMPT)
