"""Tests for the MultiEditTool (batch file editing)."""

import pytest

from cantrip.agent.tools.multi_edit import MultiEditTool


@pytest.fixture
def tool(tmp_path):
    return MultiEditTool(base_path=tmp_path)


@pytest.fixture
def _populate(tmp_path):
    (tmp_path / "a.py").write_text("def hello():\n    return 'hello'\n")
    (tmp_path / "b.py").write_text("def world():\n    return 'world'\n")


class TestMultiEditToolProperties:
    """Tests for tool metadata."""

    def test_name(self, tool):
        assert tool.name == "multi_edit"

    def test_required_params(self, tool):
        assert "edits" in tool.parameters["required"]

    def test_edits_is_array(self, tool):
        assert tool.parameters["properties"]["edits"]["type"] == "array"


@pytest.mark.usefixtures("_populate")
class TestMultiEditExecution:
    """Tests for multi_edit execution."""

    @pytest.mark.anyio
    async def test_single_edit(self, tool, tmp_path):
        result = await tool.execute(edits=[
            {"file": "a.py", "old": "def hello():", "new": "def greet():"},
        ])
        assert result.success
        assert result.data["applied"] == 1
        assert "def greet():" in (tmp_path / "a.py").read_text()

    @pytest.mark.anyio
    async def test_multiple_edits_across_files(self, tool, tmp_path):
        result = await tool.execute(edits=[
            {"file": "a.py", "old": "def hello():", "new": "def greet():"},
            {"file": "b.py", "old": "def world():", "new": "def earth():"},
        ])
        assert result.success
        assert result.data["applied"] == 2
        assert "def greet():" in (tmp_path / "a.py").read_text()
        assert "def earth():" in (tmp_path / "b.py").read_text()

    @pytest.mark.anyio
    async def test_multiple_edits_same_file(self, tool, tmp_path):
        """Sequential edits to the same file work — each sees the previous edit's result."""
        result = await tool.execute(edits=[
            {"file": "a.py", "old": "def hello", "new": "def greet"},
            {"file": "a.py", "old": "'hello'", "new": "'hi'"},
        ])
        assert result.success
        assert result.data["applied"] == 2
        content = (tmp_path / "a.py").read_text()
        assert "def greet" in content
        assert "'hi'" in content

    @pytest.mark.anyio
    async def test_empty_edits(self, tool):
        result = await tool.execute(edits=[])
        assert not result.success
        assert "No edits" in result.error

    @pytest.mark.anyio
    async def test_file_not_found(self, tool):
        result = await tool.execute(edits=[
            {"file": "nonexistent.py", "old": "x", "new": "y"},
        ])
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_string_not_found(self, tool):
        result = await tool.execute(edits=[
            {"file": "a.py", "old": "nonexistent_string", "new": "replacement"},
        ])
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_ambiguous_match(self, tool, tmp_path):
        (tmp_path / "c.py").write_text("foo foo foo")
        result = await tool.execute(edits=[
            {"file": "c.py", "old": "foo", "new": "bar"},
        ])
        assert not result.success
        assert "3 times" in result.error

    @pytest.mark.anyio
    async def test_partial_failure_reports_applied_count(self, tool, tmp_path):
        """First edit succeeds, second fails — error reports 1 applied."""
        result = await tool.execute(edits=[
            {"file": "a.py", "old": "def hello():", "new": "def greet():"},
            {"file": "nonexistent.py", "old": "x", "new": "y"},
        ])
        assert not result.success
        assert "1 edit(s) applied" in result.error
        # First edit was persisted.
        assert "def greet():" in (tmp_path / "a.py").read_text()

    @pytest.mark.anyio
    async def test_path_traversal_blocked(self, tool):
        result = await tool.execute(edits=[
            {"file": "../../../etc/passwd", "old": "root", "new": "nope"},
        ])
        assert not result.success
        assert "outside" in result.error.lower()

    @pytest.mark.anyio
    async def test_missing_file_field(self, tool):
        result = await tool.execute(edits=[
            {"file": "", "old": "x", "new": "y"},
        ])
        assert not result.success
        assert "missing" in result.error.lower()
