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
        # Pin the absence of an empty parenthetical on the decisions line
        # specifically — looking for "()" anywhere in the prompt is too
        # broad now that the tracing recipe quotes ``super().__init__``.
        assert "path: 12-factor ()" not in result
        assert "12-factor (\n" not in result

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


class TestJubilantIntegrationTestPrompt:
    """Tests for Jubilant integration test content in the system prompt."""

    def test_jubilant_tests_skill_referenced(self):
        """The prompt should reference the jubilant-tests skill."""
        result = build_system_prompt()
        assert "jubilant-tests" in result

    def test_integration_conftest_referenced(self):
        """The prompt should reference the integration conftest file."""
        result = build_system_prompt()
        assert "tests/integration/conftest.py" in result

    def test_integration_test_file_referenced(self):
        """The prompt should reference the integration test file."""
        result = build_system_prompt()
        assert "tests/integration/test_charm.py" in result

    def test_integration_tests_excluded_from_validate(self):
        """The prompt should state integration tests are not included in charm_validate."""
        result = build_system_prompt()
        assert "not included in `charm_validate`" in result


class TestPathBPrompt:
    """Tests for Path B (Custom Applications) content in the system prompt."""

    def test_custom_charm_skill_referenced(self):
        """The prompt should reference the custom-charm skill."""
        result = build_system_prompt()
        assert "custom-charm" in result

    def test_substrate_decision_heuristics(self):
        """The prompt should contain substrate decision heuristics."""
        result = build_system_prompt()
        assert "Dockerfile or OCI image" in result
        assert "bare metal/GPU/kernel modules" in result
        assert "default to K8s" in result

    def test_custom_app_example_interaction(self):
        """The prompt should contain a custom app example interaction."""
        result = build_system_prompt()
        assert "Example Interaction: Custom App" in result
        assert "Path B" in result
        assert "workload_hints" in result


class TestGitPushConfirmation:
    """Tests for git push confirmation guidance in the system prompt."""

    def test_push_confirmation_section_present(self):
        """The 'Git push' section should appear in the rendered prompt."""
        result = build_system_prompt()
        assert "### Git push" in result

    def test_confirm_before_pushing(self):
        """The prompt should instruct the agent to confirm before pushing."""
        result = build_system_prompt()
        assert "confirm before pushing" in result.lower()

    def test_confirmed_true_referenced(self):
        """The prompt should reference confirmed: true."""
        result = build_system_prompt()
        assert "confirmed: true" in result


class TestCompactPrompt:
    """Tests for compact system prompt (used by local models)."""

    def test_compact_is_shorter(self):
        """Compact prompt should be significantly shorter than the full prompt."""
        full = build_system_prompt()
        compact = build_system_prompt(compact=True)
        assert len(compact) < len(full) // 3

    def test_compact_contains_core_identity(self):
        """Compact prompt should identify Cantrip and its purpose."""
        result = build_system_prompt(compact=True)
        assert "Cantrip" in result
        assert "Juju charms" in result

    def test_compact_contains_charm_paths(self):
        """Compact prompt should mention the three charm paths."""
        result = build_system_prompt(compact=True)
        assert "12-Factor" in result
        assert "Custom" in result
        assert "Infrastructure" in result

    def test_compact_includes_context(self):
        """Compact prompt should include charm context when provided."""
        result = build_system_prompt(compact=True, charm_name="my-charm", dev_model="dev")
        assert "my-charm" in result
        assert "dev" in result

    def test_compact_excludes_verbose_sections(self):
        """Compact prompt should not contain verbose sections from the full prompt."""
        result = build_system_prompt(compact=True)
        assert "WORKLOAD.md" not in result
        assert "DESIGN.md" not in result
        assert "Example Interaction" not in result


class TestWatcherPrompt:
    """Tests for watcher-related content in the system prompt."""

    def test_watcher_section_present_when_enabled(self):
        """The 'Event Watcher' section appears when watcher_enabled is True."""
        result = build_system_prompt(watcher_enabled=True)
        assert "## Event Watcher" in result
        assert "[Watcher]" in result

    def test_watcher_section_absent_when_disabled(self):
        """The 'Event Watcher' section is absent when watcher_enabled is False."""
        result = build_system_prompt(watcher_enabled=False)
        assert "## Event Watcher" not in result

    def test_watcher_section_absent_when_none(self):
        """The 'Event Watcher' section is absent when watcher_enabled is None."""
        result = build_system_prompt(watcher_enabled=None)
        assert "## Event Watcher" not in result

    def test_watcher_instructions_include_investigation_steps(self):
        """The watcher section includes investigation instructions."""
        result = build_system_prompt(watcher_enabled=True)
        assert "Investigate" in result
        assert "Diagnose" in result
        assert "observability" in result.lower()
