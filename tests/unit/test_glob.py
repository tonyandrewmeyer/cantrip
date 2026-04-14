"""Tests for the GlobTool (file pattern matching)."""

import pytest

from cantrip.agent.tools.glob import (
    _ABSOLUTE_MAX_RESULTS,
    _DEFAULT_MAX_RESULTS,
    _SKIP_DIRS,
    GlobTool,
)


@pytest.fixture
def tool(tmp_path):
    """Create a GlobTool with base_path set to a temp directory."""
    return GlobTool(base_path=tmp_path)


@pytest.fixture
def _populate_tree(tmp_path):
    """Create a temp directory with a realistic file structure."""
    # Python files.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# main")
    (tmp_path / "src" / "utils.py").write_text("# utils")
    (tmp_path / "src" / "sub").mkdir()
    (tmp_path / "src" / "sub" / "helper.py").write_text("# helper")

    # YAML files.
    (tmp_path / "charmcraft.yaml").write_text("name: test")
    (tmp_path / "config.yaml").write_text("options: {}")

    # Tests.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("# test")
    (tmp_path / "tests" / "test_utils.py").write_text("# test")

    # Noise directories that should be skipped.
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-312.pyc").write_text("")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("")

    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("")


class TestGlobToolProperties:
    """Tests for tool metadata."""

    def test_name(self, tool):
        assert tool.name == "glob"

    def test_description(self, tool):
        assert "glob" in tool.description.lower()
        assert "pattern" in tool.description.lower()

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert params["type"] == "object"
        assert "pattern" in params["properties"]
        assert params["required"] == ["pattern"]
        assert "path" in params["properties"]
        assert "max_results" in params["properties"]


@pytest.mark.usefixtures("_populate_tree")
class TestGlobToolExecution:
    """Tests for glob execution."""

    @pytest.mark.anyio
    async def test_basic_glob(self, tool):
        result = await tool.execute(pattern="*.yaml")
        assert result.success
        assert "charmcraft.yaml" in result.output
        assert "config.yaml" in result.output

    @pytest.mark.anyio
    async def test_recursive_glob(self, tool):
        result = await tool.execute(pattern="**/*.py")
        assert result.success
        assert "src/main.py" in result.output
        assert "src/utils.py" in result.output
        assert "src/sub/helper.py" in result.output
        assert "tests/test_main.py" in result.output

    @pytest.mark.anyio
    async def test_no_matches(self, tool):
        result = await tool.execute(pattern="*.rs")
        assert result.success
        assert "No matching files found." in result.output
        assert result.data["match_count"] == 0

    @pytest.mark.anyio
    async def test_subdirectory_path(self, tool):
        result = await tool.execute(pattern="*.py", path="src")
        assert result.success
        assert "main.py" in result.output
        assert "utils.py" in result.output
        # Should not include test files.
        assert "test_main.py" not in result.output

    @pytest.mark.anyio
    async def test_skips_pycache(self, tool):
        result = await tool.execute(pattern="**/*.pyc")
        assert result.success
        assert "No matching files found." in result.output

    @pytest.mark.anyio
    async def test_skips_git_dir(self, tool):
        result = await tool.execute(pattern="**/*")
        assert result.success
        assert ".git" not in result.output

    @pytest.mark.anyio
    async def test_skips_venv(self, tool):
        result = await tool.execute(pattern="**/python")
        assert result.success
        assert "No matching files found." in result.output

    @pytest.mark.anyio
    async def test_nonexistent_path(self, tool):
        result = await tool.execute(pattern="*.py", path="nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_not_a_directory(self, tool):
        result = await tool.execute(pattern="*.py", path="charmcraft.yaml")
        assert not result.success
        assert "not a directory" in result.error.lower()

    @pytest.mark.anyio
    async def test_path_traversal(self, tool):
        result = await tool.execute(pattern="*.py", path="../../../etc")
        assert not result.success
        assert "outside" in result.error.lower()

    @pytest.mark.anyio
    async def test_max_results_clamped_low(self, tool):
        result = await tool.execute(pattern="**/*.py", max_results=0)
        assert result.success
        # Should clamp to 1, not crash.
        assert result.data["match_count"] >= 1

    @pytest.mark.anyio
    async def test_truncation(self, tool):
        result = await tool.execute(pattern="**/*.py", max_results=2)
        assert result.success
        assert result.data["truncated"]
        assert "truncated" in result.output

    @pytest.mark.anyio
    async def test_results_sorted_alphabetically(self, tool):
        result = await tool.execute(pattern="**/*.py")
        assert result.success
        lines = [
            line for line in result.output.strip().split("\n")
            if line and not line.startswith("(")
        ]
        assert lines == sorted(lines)

    @pytest.mark.anyio
    async def test_only_files_returned(self, tool):
        """Directories themselves should not appear in results."""
        result = await tool.execute(pattern="**/*")
        assert result.success
        # "src" and "tests" are directories — they should not appear as bare entries.
        lines = result.output.strip().split("\n")
        assert "src" not in lines
        assert "tests" not in lines


class TestGlobConstants:
    """Tests for module-level constants."""

    def test_default_max_results(self):
        assert _DEFAULT_MAX_RESULTS == 50

    def test_absolute_max_results(self):
        assert _ABSOLUTE_MAX_RESULTS == 200

    def test_skip_dirs_contains_essentials(self):
        assert ".git" in _SKIP_DIRS
        assert "__pycache__" in _SKIP_DIRS
        assert ".venv" in _SKIP_DIRS
        assert "node_modules" in _SKIP_DIRS
