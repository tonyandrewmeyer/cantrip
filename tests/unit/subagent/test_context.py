"""Subagent tests: context."""

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    ExitState,
    SubagentContext,
    SubagentResult,
    _build_subagent_prompt,
)

# ===================================================================
# TestSubagentContext
# ===================================================================


class TestSubagentContext:
    """Tests for SubagentContext dataclass construction."""

    def test_defaults(self) -> None:
        task = AgentTask(id="t1", title="T", category=TaskCategory.RESEARCH)
        ctx = SubagentContext(task=task)

        assert ctx.task is task
        assert ctx.charm_name is None
        assert ctx.charm_path is None
        assert ctx.charm_type is None
        assert ctx.framework is None
        assert ctx.dev_model is None
        assert ctx.cos_model is None
        assert ctx.decisions == []
        assert ctx.prior_results == {}

    def test_full_construction(self) -> None:
        task = AgentTask(id="t2", title="Build", category=TaskCategory.BUILD)
        ctx = SubagentContext(
            task=task,
            charm_name="redis-k8s",
            charm_path="/tmp/redis-k8s",
            charm_type="k8s",
            framework="flask",
            dev_model="dev",
            cos_model="cos",
            decisions=[{"type": "path", "choice": "A"}],
            prior_results={"research": "Found docs"},
        )

        assert ctx.charm_name == "redis-k8s"
        assert ctx.prior_results == {"research": "Found docs"}


# ===================================================================
# TestSubagentResult
# ===================================================================


class TestSubagentResult:
    """Tests for the SubagentResult dataclass."""

    def test_text_returns_detail_when_present(self) -> None:
        r = SubagentResult(ExitState.COMPLETED, "summary", "full detail")
        assert r.text == "full detail"

    def test_text_falls_back_to_summary(self) -> None:
        r = SubagentResult(ExitState.COMPLETED, "summary")
        assert r.text == "summary"

    def test_frozen(self) -> None:
        r = SubagentResult(ExitState.COMPLETED, "done")
        with pytest.raises(AttributeError):
            r.exit_state = ExitState.FAILED  # type: ignore[misc]


# ===================================================================
# TestExitSignallingInPrompt
# ===================================================================


class TestExitSignallingInPrompt:
    """Tests that the subagent prompt includes exit signalling instructions."""

    def test_prompt_includes_exit_instructions(self) -> None:
        ctx = SubagentContext(
            task=AgentTask(title="Build charm", category=TaskCategory.BUILD),
        )
        prompt = _build_subagent_prompt(ctx)
        assert "[EXIT: completed]" in prompt
        assert "[EXIT: blocked]" in prompt
        assert "[EXIT: failed]" in prompt
        assert "[EXIT: noop]" in prompt
