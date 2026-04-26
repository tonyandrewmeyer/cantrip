"""End-to-end scenario tests.

Multi-turn conversation scenarios using FakeProvider with scripted
responses. These exercise the full loop: user message → system prompt
→ tool execution → state mutation → response.
"""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider


@pytest.mark.e2e
class TestScenarios:
    """Full agent-loop scenarios."""

    @pytest.mark.asyncio
    async def test_scaffold_flask_charm(self, tmp_path: pathlib.Path):
        """Simulate scaffolding a Flask charm: analyse → write → respond."""
        # Seed the project with a requirements.txt so analyse_framework has
        # something to detect.
        (tmp_path / "requirements.txt").write_text("flask>=3.0\n")

        provider = FakeProvider(
            [
                # First turn: agent calls analyse_framework.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="analyse_framework",
                            name="analyse_framework",
                            arguments={"path": "."},
                        ),
                    ],
                ),
                # Second turn: agent writes a charm.py file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={
                                "path": "src/charm.py",
                                "content": "# Flask charm\nimport ops\n",
                            },
                        ),
                    ],
                ),
                # Final text response.
                Response(content="Your Flask charm is ready!"),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Build a charm for my Flask app")

        assert result == "Your Flask charm is ready!"
        assert (tmp_path / "src" / "charm.py").exists()
        # user + assistant(tool) + tool + assistant(tool) + tool + assistant(final) = 6
        assert len(agent.state.messages) == 6

    @pytest.mark.asyncio
    async def test_multi_turn_with_state(self, tmp_path: pathlib.Path):
        """Two user messages; second turn writes a file."""
        provider = FakeProvider(
            [
                # First turn: simple text response.
                Response(content="Sure, I can help."),
                # Second turn: write a file then respond.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={
                                "path": "metadata.yaml",
                                "content": "name: my-charm\n",
                            },
                        ),
                    ],
                ),
                Response(content="Created metadata.yaml."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Help me build a charm")
        await agent.process_message("Create the metadata file")

        # First turn: user + assistant = 2
        # Second turn: user + assistant(tool) + tool + assistant(final) = 4
        # Total: 6
        assert len(agent.state.messages) == 6
        assert (tmp_path / "metadata.yaml").exists()

    @pytest.mark.asyncio
    async def test_tool_failure_recovery(self, tmp_path: pathlib.Path):
        """A tool returning an error should not raise; the agent recovers."""
        provider = FakeProvider(
            [
                # Agent tries to read a non-existent file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="read_file",
                            name="read_file",
                            arguments={"path": "does_not_exist.txt"},
                        ),
                    ],
                ),
                # Agent recovers gracefully.
                Response(content="That file doesn't exist. Let me create it instead."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Read my config file")

        assert "doesn't exist" in result
        # The tool result should be marked as an error.
        tool_messages = [m for m in agent.state.messages if m.role.value == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_results[0].is_error

    @pytest.mark.asyncio
    async def test_state_round_trip_across_sessions(self, tmp_path: pathlib.Path):
        """State persists across two separate agent sessions."""
        # Session 1: process a message, set state, save.
        provider1 = FakeProvider([Response(content="Got it.")])
        agent1 = CantripAgent(provider=provider1, charm_path=tmp_path)
        await agent1.process_message("Hello")
        agent1.state.charm_name = "my-flask-charm"
        agent1.state.charm_type = "k8s"
        agent1.save_state()

        # Session 2: new agent, load state, process another message.
        provider2 = FakeProvider([Response(content="Welcome back!")])
        agent2 = CantripAgent(provider=provider2, charm_path=tmp_path)
        loaded = agent2.load_state()

        assert loaded is True
        assert agent2.state.charm_name == "my-flask-charm"
        assert agent2.state.charm_type == "k8s"

        result = await agent2.process_message("Continue")
        assert result == "Welcome back!"
