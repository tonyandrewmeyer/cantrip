"""Tests for system prompt rendering."""

from cantrip.agent.prompts.system import SYSTEM_PROMPT, build_system_prompt


class TestDefaultSystemPrompt:
    """Tests for the pre-rendered SYSTEM_PROMPT constant."""

    def test_default_prompt_is_non_empty(self):
        """SYSTEM_PROMPT should behave like a non-empty string."""
        assert len(SYSTEM_PROMPT) > 0
        assert "Cantrip" in SYSTEM_PROMPT

    def test_default_prompt_contains_core_sections(self):
        """The default prompt should contain key sections from the template."""
        assert "Cantrip" in SYSTEM_PROMPT
        assert "Core Principles" in SYSTEM_PROMPT
        assert "Three Paths" in SYSTEM_PROMPT


class TestBuildSystemPromptNoContext:
    """Tests for build_system_prompt() with no context injected."""

    def test_no_context_matches_default(self):
        """Calling with no arguments should match SYSTEM_PROMPT."""
        result = build_system_prompt()
        assert result == SYSTEM_PROMPT

    def test_no_context_excludes_current_context(self):
        """Without context fields, the 'Current Context' section is absent."""
        result = build_system_prompt()
        assert "Current Context" not in result


class TestBuildSystemPromptCharmContext:
    """Tests for charm context injection."""

    def test_charm_name_injected(self):
        """The charm name should appear in the rendered output."""
        result = build_system_prompt(charm_name="my-charm")
        assert "**Charm**: my-charm" in result

    def test_charm_path_injected(self):
        """The charm path should appear in the rendered output."""
        result = build_system_prompt(charm_path="/tmp/my-charm")
        assert "**Path**: /tmp/my-charm" in result

    def test_framework_injected(self):
        """The framework should appear in the rendered output."""
        result = build_system_prompt(charm_name="web", framework="flask")
        assert "**Framework**: flask" in result

    def test_all_charm_context_fields(self):
        """All charm context fields should appear together."""
        result = build_system_prompt(
            charm_name="my-charm",
            charm_path="/tmp/my-charm",
            charm_type="k8s",
            framework="flask",
        )
        assert "**Charm**: my-charm" in result
        assert "**Path**: /tmp/my-charm" in result
        assert "**Type**: k8s" in result
        assert "**Framework**: flask" in result


class TestBuildSystemPromptModels:
    """Tests for model name injection."""

    def test_dev_model_injected(self):
        """The dev model should appear in the rendered output."""
        result = build_system_prompt(dev_model="dev")
        assert "Dev: dev" in result

    def test_both_models(self):
        """Both dev and COS models should appear when provided."""
        result = build_system_prompt(dev_model="dev", cos_model="cos")
        assert "Dev: dev" in result
        assert "COS: cos" in result


class TestBuildSystemPromptDecisions:
    """Tests for decision injection."""

    def test_single_decision(self):
        """A single decision should render type, choice, and reason."""
        decisions = [{"type": "path", "choice": "12-factor", "reason": "Flask detected"}]
        result = build_system_prompt(charm_name="x", recent_decisions=decisions)
        assert "path: 12-factor (Flask detected)" in result

    def test_decision_without_reason(self):
        """A decision without a reason should render without parenthetical."""
        decisions = [{"type": "path", "choice": "12-factor"}]
        result = build_system_prompt(charm_name="x", recent_decisions=decisions)
        assert "path: 12-factor" in result
        assert "()" not in result

    def test_only_last_five_decisions(self):
        """Only the last 5 of 7 decisions should be rendered."""
        decisions = [{"type": f"d{i}", "choice": f"c{i}", "reason": f"r{i}"} for i in range(7)]
        result = build_system_prompt(charm_name="x", recent_decisions=decisions)
        # First two decisions should be absent.
        assert "d0" not in result
        assert "d1" not in result
        # Last five should be present.
        for i in range(2, 7):
            assert f"d{i}" in result


class TestBuildSystemPromptSkillsIndex:
    """Tests for skills index injection."""

    def test_skills_index_injected(self):
        """The 'Available Skills' section should appear when skills_index is set."""
        result = build_system_prompt(skills_index="<available_skills>...</available_skills>")
        assert "Available Skills" in result
        assert "<available_skills>...</available_skills>" in result

    def test_skills_index_none_excluded(self):
        """The 'Available Skills' section should be absent when skills_index is None."""
        result = build_system_prompt(skills_index=None)
        assert "Available Skills" not in result


class TestWorkloadResearchPrompt:
    """Tests for workload research content in the system prompt."""

    def test_workload_research_section_present(self):
        """The 'Workload Research' section should appear in the rendered prompt."""
        result = build_system_prompt()
        assert "## Workload Research" in result

    def test_research_in_how_you_work(self):
        """'Research the workload' should appear as a step in How You Work."""
        result = build_system_prompt()
        assert "Research the workload" in result

    def test_workload_md_documented(self):
        """WORKLOAD.md sections should be documented in the prompt."""
        result = build_system_prompt()
        assert "WORKLOAD.md" in result
        for section in (
            "Purpose",
            "Source",
            "Dependencies",
            "Configuration",
            "Networking",
            "Storage",
            "Health",
            "Operational Notes",
        ):
            assert f"## {section}" in result


class TestCompletionChecklist:
    """Tests for completion checklist content in the system prompt."""

    def test_completion_checklist_section_present(self):
        """The 'Completion Checklist' section should appear in the rendered prompt."""
        result = build_system_prompt()
        assert "Completion Checklist" in result

    def test_charm_validate_referenced(self):
        """The prompt should reference charm_validate."""
        result = build_system_prompt()
        assert "charm_validate" in result
