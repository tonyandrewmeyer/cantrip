"""Planner tests: prompts."""

from cantrip.agent.planner import (
    PlanningContext,
    _build_day2_to_build_prompt,
    _build_design_to_build_prompt,
    _build_planning_prompt,
    _build_replanning_prompt,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

# ===================================================================
# TestPlanningPrompt
# ===================================================================


class TestPlanningPrompt:
    """Tests for prompt construction helpers."""

    def test_includes_charm_name(self) -> None:
        context = PlanningContext(intent="test", charm_name="redis-k8s")
        prompt = _build_planning_prompt(context)
        assert "redis-k8s" in prompt

    def test_includes_environment_not_ready(self) -> None:
        context = PlanningContext(intent="test", environment_ready=False)
        prompt = _build_planning_prompt(context)
        assert "not yet provisioned" in prompt

    def test_includes_environment_ready(self) -> None:
        context = PlanningContext(intent="test", environment_ready=True)
        prompt = _build_planning_prompt(context)
        assert "ready" in prompt.lower()

    def test_replanning_prompt_includes_existing(self) -> None:
        existing = [
            AgentTask(
                id="done-task",
                title="Already done",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
            ),
        ]
        context = PlanningContext(
            intent="test",
            existing_tasks=existing,
        )
        prompt = _build_replanning_prompt(context)
        assert "done-task" in prompt
        assert "Already done" in prompt
        assert "Existing tasks" in prompt

    def test_includes_all_categories(self) -> None:
        context = PlanningContext(intent="test")
        prompt = _build_planning_prompt(context)
        for cat in ("research", "build", "deploy", "test", "debug", "infra", "confirm"):
            assert cat in prompt

    def test_includes_research_decomposition_guide(self) -> None:
        """Verify the research-first decomposition guidance is present."""
        context = PlanningContext(intent="test")
        prompt = _build_planning_prompt(context)
        assert "source-analysis" in prompt
        assert "web-research" in prompt
        assert "charmhub-survey" in prompt
        assert "operational-discovery" in prompt
        assert "confirm-design" in prompt

    def test_includes_source_url(self) -> None:
        context = PlanningContext(
            intent="test",
            source_url="https://github.com/example/repo",
        )
        prompt = _build_planning_prompt(context)
        assert "https://github.com/example/repo" in prompt


# ===================================================================
# TestDesignToBuildPrompt
# ===================================================================


class TestDesignToBuildPrompt:
    """Tests for the design-to-build prompt builder."""

    def test_includes_categories(self) -> None:
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        for cat in ("build", "deploy", "test"):
            assert cat in prompt

    def test_includes_context(self) -> None:
        context = PlanningContext(
            intent="test",
            charm_name="redis-k8s",
            dev_model="dev",
        )
        prompt = _build_design_to_build_prompt(context)
        assert "redis-k8s" in prompt
        assert "dev" in prompt

    def test_mentions_companion_charms(self) -> None:
        """The design-to-build prompt instructs the LLM to handle companion charms."""
        context = PlanningContext(intent="test")
        prompt = _build_design_to_build_prompt(context)
        assert "companion" in prompt.lower()
        assert "Companion charms" in prompt


# ===================================================================
# TestDay2ToBuildPrompt
# ===================================================================


class TestDay2ToBuildPrompt:
    """Tests for the day-2 to build prompt builder."""

    def test_includes_categories(self) -> None:
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        for cat in ("build", "test"):
            assert cat in prompt

    def test_includes_context(self) -> None:
        ctx = PlanningContext(intent="test", charm_name="redis-k8s", dev_model="dev")
        prompt = _build_day2_to_build_prompt(ctx)
        assert "redis-k8s" in prompt
        assert "dev" in prompt

    def test_mentions_operational_areas(self) -> None:
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        prompt_lower = prompt.lower()
        assert "backup" in prompt_lower
        assert "scaling" in prompt_lower
        assert "security" in prompt_lower
        assert "upgrade" in prompt_lower

    def test_mentions_edit_not_rewrite(self) -> None:
        """Day-2 tasks should modify existing charm, not rewrite from scratch."""
        ctx = PlanningContext(intent="test")
        prompt = _build_day2_to_build_prompt(ctx)
        assert "edit_file" in prompt
        assert "NOT rewrite" in prompt
