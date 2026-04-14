"""Tests for the grep (content search) tool."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cantrip.agent.tools.grep import _ABSOLUTE_MAX_RESULTS, _DEFAULT_MAX_RESULTS, GrepTool


@pytest.fixture
def tool(tmp_path: Path) -> GrepTool:
    """GrepTool with a temp base path."""
    return GrepTool(base_path=tmp_path)


@pytest.fixture
def _populate_tree(tmp_path: Path) -> None:
    """Create a small file tree for searching."""
    (tmp_path / "hello.py").write_text("def hello():\n    print('hello world')\n")
    (tmp_path / "goodbye.py").write_text("def goodbye():\n    print('goodbye world')\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.py").write_text("import hello\nhello.hello()\n")
    (tmp_path / "data.yaml").write_text("key: value\n")


class TestGrepToolProperties:
    """Tests for tool metadata."""

    def test_name(self, tool: GrepTool):
        assert tool.name == "grep"

    def test_description(self, tool: GrepTool):
        assert "Search file contents" in tool.description

    def test_parameters_schema(self, tool: GrepTool):
        params = tool.parameters
        assert params["required"] == ["pattern"]
        props = params["properties"]
        assert "pattern" in props
        assert "path" in props
        assert "glob" in props
        assert "context_lines" in props
        assert "case_sensitive" in props
        assert "max_results" in props


@pytest.mark.usefixtures("_populate_tree")
class TestGrepToolExecution:
    """Tests for actual search execution."""

    @pytest.mark.asyncio
    async def test_basic_search(self, tool: GrepTool):
        result = await tool.execute(pattern="hello")
        assert result.success is True
        assert "hello" in result.output
        assert result.data["match_count"] > 0

    @pytest.mark.asyncio
    async def test_no_matches(self, tool: GrepTool):
        result = await tool.execute(pattern="nonexistent_string_xyz")
        assert result.success is True
        assert result.output == "No matches found."
        assert result.data["match_count"] == 0

    @pytest.mark.asyncio
    async def test_regex_pattern(self, tool: GrepTool):
        result = await tool.execute(pattern="def \\w+\\(")
        assert result.success is True
        assert "hello" in result.output
        assert "goodbye" in result.output

    @pytest.mark.asyncio
    async def test_glob_filter(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", glob="*.py")
        assert result.success is True
        assert "hello" in result.output
        # Should not search .yaml files.
        assert "yaml" not in result.output.lower()

    @pytest.mark.asyncio
    async def test_case_insensitive(self, tool: GrepTool):
        result = await tool.execute(pattern="HELLO", case_sensitive=False)
        assert result.success is True
        assert result.data["match_count"] > 0

    @pytest.mark.asyncio
    async def test_case_sensitive_no_match(self, tool: GrepTool):
        result = await tool.execute(pattern="HELLO", case_sensitive=True)
        assert result.success is True
        assert result.output == "No matches found."

    @pytest.mark.asyncio
    async def test_specific_path(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", path="sub")
        assert result.success is True
        assert "nested" in result.output

    @pytest.mark.asyncio
    async def test_path_not_found(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", path="nonexistent")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", path="../../etc")
        assert result.success is False
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_context_lines(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", path="hello.py", context_lines=1)
        assert result.success is True
        # With context, we should see the print line too.
        assert "print" in result.output

    @pytest.mark.asyncio
    async def test_max_results_clamped_to_absolute(self, tool: GrepTool):
        result = await tool.execute(pattern=".", max_results=9999)
        # Should succeed — max_results is clamped internally.
        assert result.success is True

    @pytest.mark.asyncio
    async def test_max_results_minimum_one(self, tool: GrepTool):
        result = await tool.execute(pattern="hello", max_results=0)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_truncation_reported(self, tool: GrepTool):
        result = await tool.execute(pattern=".", max_results=1)
        assert result.success is True
        if result.data.get("truncated"):
            assert "truncated" in result.output


class TestGrepCommandBuilding:
    """Tests for command construction."""

    def test_rg_command_basic(self):
        cmd = GrepTool._build_rg_command(
            "/usr/bin/rg", "pattern", Path("/tmp/test"),
            glob=None, context_lines=0, case_sensitive=True, max_results=50,
        )
        assert cmd[0] == "/usr/bin/rg"
        assert "pattern" in cmd
        assert "--ignore-case" not in cmd

    def test_rg_command_case_insensitive(self):
        cmd = GrepTool._build_rg_command(
            "/usr/bin/rg", "pattern", Path("/tmp/test"),
            glob=None, context_lines=0, case_sensitive=False, max_results=50,
        )
        assert "--ignore-case" in cmd

    def test_rg_command_with_glob(self):
        cmd = GrepTool._build_rg_command(
            "/usr/bin/rg", "pattern", Path("/tmp/test"),
            glob="*.py", context_lines=0, case_sensitive=True, max_results=50,
        )
        idx = cmd.index("--glob")
        assert cmd[idx + 1] == "*.py"

    def test_rg_command_with_context(self):
        cmd = GrepTool._build_rg_command(
            "/usr/bin/rg", "pattern", Path("/tmp/test"),
            glob=None, context_lines=3, case_sensitive=True, max_results=50,
        )
        idx = cmd.index("--context")
        assert cmd[idx + 1] == "3"

    def test_grep_command_basic(self):
        cmd = GrepTool._build_grep_command(
            "pattern", Path("/tmp/test"),
            glob=None, context_lines=0, case_sensitive=True, max_results=50,
        )
        assert "-rn" in cmd
        assert "pattern" in cmd
        assert "-i" not in cmd

    def test_grep_command_case_insensitive(self):
        cmd = GrepTool._build_grep_command(
            "pattern", Path("/tmp/test"),
            glob=None, context_lines=0, case_sensitive=False, max_results=50,
        )
        assert "-i" in cmd

    def test_grep_command_with_glob(self):
        cmd = GrepTool._build_grep_command(
            "pattern", Path("/tmp/test"),
            glob="*.py", context_lines=0, case_sensitive=True, max_results=50,
        )
        idx = cmd.index("--include")
        assert cmd[idx + 1] == "*.py"

    def test_grep_command_with_context(self):
        cmd = GrepTool._build_grep_command(
            "pattern", Path("/tmp/test"),
            glob=None, context_lines=2, case_sensitive=True, max_results=50,
        )
        idx = cmd.index("-C")
        assert cmd[idx + 1] == "2"


@pytest.mark.usefixtures("_populate_tree")
class TestGrepToolErrorHandling:
    """Tests for error conditions."""

    @pytest.mark.asyncio
    async def test_timeout_handling(self, tool: GrepTool):
        with patch(
            "cantrip.agent.tools.grep.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="rg", timeout=30),
        ):
            result = await tool.execute(pattern="hello")
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_error(self, tool: GrepTool):
        with patch(
            "cantrip.agent.tools.grep.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=2, stdout="", stderr="invalid regex"
            ),
        ):
            result = await tool.execute(pattern="[invalid")
        assert result.success is False
        assert "invalid regex" in result.error

    @pytest.mark.asyncio
    async def test_no_base_path(self, tmp_path: Path):
        """GrepTool works without a base_path (uses absolute paths)."""
        tool = GrepTool(base_path=None)
        (tmp_path / "test.txt").write_text("findme\n")
        result = await tool.execute(pattern="findme", path=str(tmp_path))
        assert result.success is True
        assert "findme" in result.output


class TestGrepConstants:
    """Tests for module constants."""

    def test_default_max_results(self):
        assert _DEFAULT_MAX_RESULTS == 50

    def test_absolute_max_results(self):
        assert _ABSOLUTE_MAX_RESULTS == 200
        assert _ABSOLUTE_MAX_RESULTS >= _DEFAULT_MAX_RESULTS
