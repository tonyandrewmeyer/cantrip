"""Integration tests: skills loading within the agent.

These tests verify that the skills infrastructure works end-to-end
when accessed through the agent's tool layer.
"""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider


@pytest.mark.integration
class TestSkillsInAgentContext:
    """Verify skills are discoverable and loadable through the agent."""

    @pytest.mark.asyncio
    async def test_load_skill_tool_works(self, tmp_path: pathlib.Path):
        """The load_skill tool returns content for a known skill."""
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="load_skill",
                            name="load_skill",
                            arguments={"skill_name": "scenario-tests"},
                        ),
                    ],
                ),
                Response(content="Loaded the skill."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Load the scenario-tests skill")

        assert result == "Loaded the skill."
        # The tool result should contain skill content (not an error).
        tool_messages = [m for m in agent.state.messages if m.role.value == "tool"]
        assert len(tool_messages) == 1
        tool_result = tool_messages[0].tool_results[0]
        assert not tool_result.is_error
        assert len(tool_result.content) > 0

    def test_dynamic_context_includes_skills(self, tmp_path: pathlib.Path):
        """The dynamic-context message references available skills.

        Skills moved out of the cached system prompt into a per-turn
        ephemeral context message so the system prompt stays byte-stable
        for prompt caching.
        """
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)

        # The static system prompt no longer carries the skills index.
        assert "Available Skills" not in agent._build_system_prompt()

        dynamic = agent._build_dynamic_context_message()
        assert dynamic is not None
        assert "Available Skills" in dynamic.content
        # At least one skill is rendered (assert on the stable XML shape
        # rather than a specific skill name, which churns over time).
        assert "<available_skills>" in dynamic.content
        assert "<skill" in dynamic.content
        assert dynamic.ephemeral is True
