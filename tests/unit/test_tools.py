"""Tests for agent tools."""

import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)


class TestReadFileTool:
    """Tests for ReadFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return ReadFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tool, temp_dir):
        """Test reading an existing file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello world")

        result = await tool.execute(path="test.txt")

        assert result.success
        assert result.output == "hello world"
        assert result.data["size"] == 11

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tool):
        """Test reading a file that doesn't exist."""
        result = await tool.execute(path="nonexistent.txt")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_directory_fails(self, tool, temp_dir):
        """Test that reading a directory fails."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()

        result = await tool.execute(path="subdir")

        assert not result.success
        assert "directory" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, temp_dir):
        """Test that path traversal is blocked."""
        tool = ReadFileTool(base_path=temp_dir)

        result = await tool.execute(path="../../../etc/passwd")

        assert not result.success
        assert "outside" in result.error.lower()


class TestWriteFileTool:
    """Tests for WriteFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return WriteFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool, temp_dir):
        """Test writing a new file."""
        result = await tool.execute(path="new.txt", content="test content")

        assert result.success
        assert (temp_dir / "new.txt").read_text() == "test content"

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, tool, temp_dir):
        """Test that writing creates parent directories."""
        result = await tool.execute(path="sub/dir/file.txt", content="nested")

        assert result.success
        assert (temp_dir / "sub/dir/file.txt").read_text() == "nested"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tool, temp_dir):
        """Test that writing overwrites existing files."""
        existing = temp_dir / "existing.txt"
        existing.write_text("old content")

        result = await tool.execute(path="existing.txt", content="new content")

        assert result.success
        assert existing.read_text() == "new content"


class TestListDirectoryTool:
    """Tests for ListDirectoryTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return ListDirectoryTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tool, temp_dir):
        """Test listing an empty directory."""
        result = await tool.execute(path=".")

        assert result.success
        assert "empty" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_directory_contents(self, tool, temp_dir):
        """Test listing directory with contents."""
        (temp_dir / "file.txt").write_text("content")
        (temp_dir / "subdir").mkdir()

        result = await tool.execute(path=".")

        assert result.success
        assert "file: file.txt" in result.output
        assert "dir: subdir" in result.output
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tool):
        """Test listing a nonexistent directory."""
        result = await tool.execute(path="nonexistent")

        assert not result.success
        assert "not found" in result.error.lower()


class TestEditFileTool:
    """Tests for EditFileTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self, temp_dir):
        """Create tool with base path."""
        return EditFileTool(base_path=temp_dir)

    @pytest.mark.asyncio
    async def test_edit_replaces_string(self, tool, temp_dir):
        """Test that edit replaces a string."""
        test_file = temp_dir / "test.py"
        test_file.write_text("def hello():\n    return 'world'")

        result = await tool.execute(
            path="test.py",
            old_string="'world'",
            new_string="'universe'",
        )

        assert result.success
        assert test_file.read_text() == "def hello():\n    return 'universe'"

    @pytest.mark.asyncio
    async def test_edit_string_not_found(self, tool, temp_dir):
        """Test that edit fails if string not found."""
        test_file = temp_dir / "test.py"
        test_file.write_text("some content")

        result = await tool.execute(
            path="test.py",
            old_string="nonexistent",
            new_string="replacement",
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_ambiguous_match(self, tool, temp_dir):
        """Test that edit fails on ambiguous matches."""
        test_file = temp_dir / "test.py"
        test_file.write_text("foo bar foo")

        result = await tool.execute(
            path="test.py",
            old_string="foo",
            new_string="baz",
        )

        assert not result.success
        assert "2 times" in result.error
