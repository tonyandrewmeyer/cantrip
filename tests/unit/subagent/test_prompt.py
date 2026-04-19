"""Subagent tests: prompt."""

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    _CATEGORY_GUIDANCE,
    _CATEGORY_TOOLS,
    _build_subagent_prompt,
    _task_instruction,
)
from tests.unit.subagent.conftest import _make_context

# ===================================================================
# TestBuildSubagentPrompt
# ===================================================================


class TestBuildSubagentPrompt:
    """Tests for _build_subagent_prompt — system prompt construction."""

    def test_contains_role_preamble(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "autonomous subagent" in prompt

    def test_contains_task_title(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "Test task" in prompt

    def test_contains_task_category(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "build" in prompt

    def test_contains_task_description(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "A test task description." in prompt

    def test_contains_charm_context(self) -> None:
        ctx = _make_context(
            charm_name="redis-k8s",
            charm_path="/tmp/redis-k8s",
            charm_type="k8s",
            framework="flask",
            dev_model="dev-model",
            cos_model="cos-model",
        )
        prompt = _build_subagent_prompt(ctx)

        assert "redis-k8s" in prompt
        assert "/tmp/redis-k8s" in prompt
        assert "k8s" in prompt
        assert "flask" in prompt
        assert "dev-model" in prompt
        assert "cos-model" in prompt

    def test_omits_none_charm_context(self) -> None:
        ctx = _make_context(charm_name=None, charm_path=None)
        prompt = _build_subagent_prompt(ctx)
        assert "Charm context" not in prompt

    def test_contains_category_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Guidance" in prompt
        assert "Cite sources" in prompt

    def test_contains_prior_results(self) -> None:
        ctx = _make_context(prior_results={"research-task": "Found Redis docs at..."})
        prompt = _build_subagent_prompt(ctx)
        assert "Prior task results" in prompt
        assert "research-task" in prompt
        assert "Found Redis docs at..." in prompt

    def test_omits_prior_results_when_empty(self) -> None:
        ctx = _make_context(prior_results={})
        prompt = _build_subagent_prompt(ctx)
        assert "Prior task results" not in prompt

    def test_contains_decisions(self) -> None:
        ctx = _make_context(
            decisions=[
                {"type": "substrate", "choice": "k8s", "reason": "Modern deployment"},
            ],
        )
        prompt = _build_subagent_prompt(ctx)
        assert "Decisions" in prompt
        assert "substrate" in prompt
        assert "k8s" in prompt
        assert "Modern deployment" in prompt

    def test_omits_decisions_when_empty(self) -> None:
        ctx = _make_context(decisions=[])
        prompt = _build_subagent_prompt(ctx)
        assert "Decisions" not in prompt

    def test_contains_completion_instruction(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "Completion" in prompt
        assert "summary" in prompt


# ===================================================================
# TestTaskInstruction
# ===================================================================


class TestTaskInstruction:
    """Tests for _task_instruction — user message formatting."""

    def test_title_only(self) -> None:
        task = AgentTask(id="t", title="Do something", category=TaskCategory.BUILD)
        result = _task_instruction(task)
        assert result == "Do something"

    def test_title_and_description(self) -> None:
        task = AgentTask(
            id="t",
            title="Research Redis",
            category=TaskCategory.RESEARCH,
            description="Clone the repo and analyse the framework.",
        )
        result = _task_instruction(task)
        assert "Research Redis" in result
        assert "Clone the repo" in result
        assert "\n\n" in result

    def test_empty_description_omitted(self) -> None:
        task = AgentTask(id="t", title="Deploy", category=TaskCategory.DEPLOY, description="")
        result = _task_instruction(task)
        assert result == "Deploy"


# ===================================================================
# TestResearchGuidance
# ===================================================================


class TestResearchGuidance:
    """Tests for the enhanced RESEARCH category guidance."""

    def test_cite_sources_in_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Cite sources" in prompt

    def test_unknown_markers_in_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "[UNKNOWN]" in prompt

    def test_operational_story_questions(self) -> None:
        task = AgentTask(
            id="od",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
        )
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Storage" in prompt
        assert "Clustering" in prompt
        assert "Health" in prompt
        assert "Failure modes" in prompt
        assert "Observability" in prompt


# ===================================================================
# TestDesignContentInjection
# ===================================================================


class TestDesignContentInjection:
    """Tests for design content injection into the subagent prompt."""

    def test_design_content_in_build_prompt(self) -> None:
        """Design content appears in the prompt when set."""
        task = AgentTask(id="b", title="Build charm", category=TaskCategory.BUILD)
        ctx = _make_context(
            task=task,
            design_content="## Substrate\nK8s\n## Integrations\n- COS\n- TLS",
        )
        prompt = _build_subagent_prompt(ctx)
        assert "Approved design" in prompt
        assert "## Substrate" in prompt
        assert "- COS" in prompt

    def test_design_content_omitted_when_none(self) -> None:
        """When design_content is None, the section is absent."""
        task = AgentTask(id="b", title="Build charm", category=TaskCategory.BUILD)
        ctx = _make_context(task=task, design_content=None)
        prompt = _build_subagent_prompt(ctx)
        assert "Approved design" not in prompt


# ===================================================================
# TestCommitAfterBuild
# ===================================================================


class TestCommitAfterBuild:
    """Tests for commit-after-build guidance and tool allowlists."""

    def test_build_guidance_mentions_git_commit(self) -> None:
        """BUILD guidance instructs the subagent to commit its work."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "git_commit" in guidance

    def test_debug_guidance_mentions_git_commit(self) -> None:
        """DEBUG guidance instructs the subagent to commit fixes."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.DEBUG]
        assert "git_commit" in guidance

    def test_git_add_in_debug_tools(self) -> None:
        """git_add is in the DEBUG tool allowlist."""
        assert "git_add" in _CATEGORY_TOOLS[TaskCategory.DEBUG]

    def test_git_commit_in_debug_tools(self) -> None:
        """git_commit is in the DEBUG tool allowlist."""
        assert "git_commit" in _CATEGORY_TOOLS[TaskCategory.DEBUG]


# ===================================================================
# TestSelfVerification
# ===================================================================


class TestSelfVerification:
    """Tests for lightweight self-verification in BUILD subagents."""

    def test_charm_validate_in_build_tools(self) -> None:
        """charm_validate is in the BUILD tool allowlist."""
        assert "charm_validate" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_run_charm_tests_in_build_tools(self) -> None:
        """run_charm_tests is in the BUILD tool allowlist."""
        assert "run_charm_tests" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_build_guidance_mentions_charm_validate(self) -> None:
        """BUILD guidance instructs the subagent to run charm_validate."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "charm_validate" in guidance


# ===================================================================
# TestRedGreenBuildGuidance
# ===================================================================


class TestRedGreenBuildGuidance:
    """Tests for red/green (integration-tests-first) build guidance."""

    def test_build_guidance_mentions_red_green(self) -> None:
        """BUILD guidance includes the red/green cycle instruction."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Red/green cycle" in guidance

    def test_build_guidance_mentions_integration_tests_first(self) -> None:
        """BUILD guidance instructs writing integration tests before charm code."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "integration tests do not exist yet" in guidance

    def test_build_guidance_mentions_jubilant(self) -> None:
        """BUILD guidance references Jubilant for integration test patterns."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Jubilant" in guidance

    def test_build_guidance_mentions_pattern_parameter(self) -> None:
        """BUILD guidance mentions the pattern parameter for targeted test runs."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "pattern" in guidance

    def test_build_guidance_mentions_scenario_for_unit_tests(self) -> None:
        """BUILD guidance still includes Scenario for unit tests as a second pass."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Scenario" in guidance

    def test_build_guidance_unit_tests_for_edge_cases(self) -> None:
        """BUILD guidance positions unit tests for edge cases and error paths."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "BlockedStatus" in guidance
        assert "WaitingStatus" in guidance

    def test_test_guidance_mentions_combined_validation(self) -> None:
        """TEST guidance includes combined unit + integration validation gate."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.TEST]
        assert "unit tests and integration tests" in guidance
        assert "combined" in guidance.lower()


# ===================================================================
# TestDemoGeneration
# ===================================================================


class TestDemoGeneration:
    """Tests for demo generation support in BUILD subagents."""

    def test_juju_status_in_build_tools(self) -> None:
        """juju_status is available for demo subagents to capture deployment state."""
        assert "juju_status" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_run_action_in_build_tools(self) -> None:
        """juju_run_action is available for demo subagents to exercise actions."""
        assert "juju_run_action" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_config_in_build_tools(self) -> None:
        """juju_config is available for demo subagents to capture config."""
        assert "juju_config" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_debug_log_in_build_tools(self) -> None:
        """juju_debug_log is available for demo subagents to capture logs."""
        assert "juju_debug_log" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_demo_guidance_injected_for_demo_task(self) -> None:
        """Demo-specific guidance is injected when task title contains 'demo'."""
        from cantrip.agent.queue import AgentTask

        context = _make_context(
            task=AgentTask(
                title="Generate demo artefacts",
                category=TaskCategory.BUILD,
            ),
        )
        prompt = _build_subagent_prompt(context)
        assert "Demo guidance" in prompt
        assert "DEMO.md" in prompt
        assert "demo.sh" in prompt
        assert "TUTORIAL.md" in prompt

    def test_demo_guidance_not_injected_for_regular_build(self) -> None:
        """Regular BUILD tasks do not get demo guidance."""
        from cantrip.agent.queue import AgentTask

        context = _make_context(
            task=AgentTask(
                title="Build charm for Redis",
                category=TaskCategory.BUILD,
            ),
        )
        prompt = _build_subagent_prompt(context)
        assert "Demo guidance" not in prompt
