"""Tests for virtual file tools."""

import pytest

from cantrip.agent.context.context import VirtualFileStore
from cantrip.agent.tools.virtual_files import VirtualFileReadTool, VirtualFileSearchTool


class TestVirtualFileReadTool:
    """Tests for VirtualFileReadTool."""

    def test_tool_metadata(self):
        """Tool exposes correct name and required parameters."""
        store = VirtualFileStore()
        tool = VirtualFileReadTool(store)

        assert tool.name == "virtual_file_read"
        assert "file_id" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_read_existing_file(self):
        """Reading an existing virtual file returns its full content."""
        store = VirtualFileStore()
        file_id = store.store("hello world", name="test.txt", source="test")
        tool = VirtualFileReadTool(store)

        result = await tool.execute(file_id=file_id)

        assert result.success is True
        assert result.output == "hello world"

    @pytest.mark.asyncio
    async def test_read_with_line_range(self):
        """Line range parameters return the correct slice."""
        store = VirtualFileStore()
        content = "line1\nline2\nline3\nline4\nline5"
        file_id = store.store(content, name="lines.txt", source="test")
        tool = VirtualFileReadTool(store)

        result = await tool.execute(file_id=file_id, start_line=2, end_line=4)

        assert result.success is True
        assert result.output == "line2\nline3"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        """Reading a nonexistent file returns an error."""
        store = VirtualFileStore()
        tool = VirtualFileReadTool(store)

        result = await tool.execute(file_id="vf_999")

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error


class TestVirtualFileSearchTool:
    """Tests for VirtualFileSearchTool."""

    def test_tool_metadata(self):
        """Tool exposes correct name and required parameters."""
        store = VirtualFileStore()
        tool = VirtualFileSearchTool(store)

        assert tool.name == "virtual_file_search"
        assert "pattern" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_matches_found(self):
        """Search returns matching lines formatted correctly."""
        store = VirtualFileStore()
        file_id = store.store("foo bar\nbaz qux\nfoo baz", name="f.txt", source="test")
        tool = VirtualFileSearchTool(store)

        result = await tool.execute(pattern="foo")

        assert result.success is True
        assert f"{file_id}:1: foo bar" in result.output
        assert f"{file_id}:3: foo baz" in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self):
        """Search returns a message when nothing matches."""
        store = VirtualFileStore()
        store.store("hello world", name="f.txt", source="test")
        tool = VirtualFileSearchTool(store)

        result = await tool.execute(pattern="zzz")

        assert result.success is True
        assert result.output == "No matches found."

    @pytest.mark.asyncio
    async def test_specific_file(self):
        """Search with file_id only searches that file."""
        store = VirtualFileStore()
        id1 = store.store("alpha\nbeta", name="a.txt", source="test")
        store.store("alpha\ngamma", name="b.txt", source="test")
        tool = VirtualFileSearchTool(store)

        result = await tool.execute(pattern="alpha", file_id=id1)

        assert result.success is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 1
        assert id1 in lines[0]

    @pytest.mark.asyncio
    async def test_invalid_regex(self):
        """Invalid regex returns an error."""
        store = VirtualFileStore()
        store.store("test", name="f.txt", source="test")
        tool = VirtualFileSearchTool(store)

        result = await tool.execute(pattern="[invalid")

        assert result.success is False
        assert result.error is not None
        assert "Invalid regex" in result.error

    @pytest.mark.asyncio
    async def test_max_matches_respected(self):
        """max_matches limits the number of results."""
        store = VirtualFileStore()
        content = "\n".join(f"match_{i}" for i in range(50))
        store.store(content, name="many.txt", source="test")
        tool = VirtualFileSearchTool(store)

        result = await tool.execute(pattern="match_", max_matches=3)

        assert result.success is True
        lines = result.output.strip().split("\n")
        assert len(lines) == 3
