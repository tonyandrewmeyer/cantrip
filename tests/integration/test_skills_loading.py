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

    def test_system_prompt_includes_skills(self, tmp_path: pathlib.Path):
        """The built system prompt should reference available skills."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)

        prompt = agent._build_system_prompt()

        assert "Available Skills" in prompt
        assert "scenario-tests" in prompt
