"""Integration tests: agent with real file tools.

These tests exercise CantripAgent with its actual file-operation tools
(no mocking), using FakeProvider for the LLM. Each test scripts a
sequence of Responses containing ToolCalls for real tools.
"""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider


@pytest.mark.integration
class TestAgentWithFileTools:
    """Exercise real file tools through the agent loop."""

    @pytest.mark.asyncio
    async def test_write_then_read(self, tmp_path: pathlib.Path):
        """Write a file via tool call, then read it back."""
        provider = FakeProvider(
            [
                # First call: write a file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={"path": "hello.txt", "content": "hello world"},
                        ),
                    ],
                ),
                # Second call: read it back.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="read_file",
                            name="read_file",
                            arguments={"path": "hello.txt"},
                        ),
                    ],
                ),
                # Final text response.
                Response(content="Done! The file says hello world."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        result = await agent.process_message("Write and read a file")

        assert result == "Done! The file says hello world."
        assert (tmp_path / "hello.txt").read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_list_directory_after_write(self, tmp_path: pathlib.Path):
        """Write a file then list the directory; filename should appear."""
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={"path": "app.py", "content": "print('hi')"},
                        ),
                    ],
                ),
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="list_directory",
                            name="list_directory",
                            arguments={"path": "."},
                        ),
                    ],
                ),
                Response(content="Listed."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Write and list")

        # The tool result from list_directory should contain "app.py".
        tool_messages = [m for m in agent.state.messages if m.role.value == "tool"]
        list_result = tool_messages[-1].tool_results[0]
        assert "app.py" in list_result.content

    @pytest.mark.asyncio
    async def test_edit_file_round_trip(self, tmp_path: pathlib.Path):
        """Write a file, edit it, then read to verify the edit."""
        provider = FakeProvider(
            [
                # Write initial file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={"path": "config.yaml", "content": "name: old-name"},
                        ),
                    ],
                ),
                # Edit the file.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="edit_file",
                            name="edit_file",
                            arguments={
                                "path": "config.yaml",
                                "old_string": "old-name",
                                "new_string": "new-name",
                            },
                        ),
                    ],
                ),
                # Read it back.
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="read_file",
                            name="read_file",
                            arguments={"path": "config.yaml"},
                        ),
                    ],
                ),
                Response(content="Updated."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Edit the config")

        assert (tmp_path / "config.yaml").read_text() == "name: new-name"

    @pytest.mark.asyncio
    async def test_path_traversal_prevented(self, tmp_path: pathlib.Path):
        """Reading a file with ../ should produce an error in the tool result."""
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="read_file",
                            name="read_file",
                            arguments={"path": "../../../etc/passwd"},
                        ),
                    ],
                ),
                Response(content="Access denied."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Try to read /etc/passwd")

        tool_messages = [m for m in agent.state.messages if m.role.value == "tool"]
        tool_result = tool_messages[0].tool_results[0]
        assert tool_result.is_error

    @pytest.mark.asyncio
    async def test_write_creates_subdirectories(self, tmp_path: pathlib.Path):
        """Writing to a nested path should create intermediate directories."""
        provider = FakeProvider(
            [
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="write_file",
                            name="write_file",
                            arguments={
                                "path": "src/charm/app.py",
                                "content": "# charm app",
                            },
                        ),
                    ],
                ),
                Response(content="Created."),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("Write nested file")

        target = tmp_path / "src" / "charm" / "app.py"
        assert target.exists()
        assert target.read_text() == "# charm app"
