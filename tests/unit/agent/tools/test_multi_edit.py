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
        result = await tool.execute(
            edits=[
                {"file": "a.py", "old": "def hello():", "new": "def greet():"},
            ]
        )
        assert result.success
        assert result.data["applied"] == 1
        assert "def greet():" in (tmp_path / "a.py").read_text()

    @pytest.mark.anyio
    async def test_multiple_edits_across_files(self, tool, tmp_path):
        result = await tool.execute(
            edits=[
                {"file": "a.py", "old": "def hello():", "new": "def greet():"},
                {"file": "b.py", "old": "def world():", "new": "def earth():"},
            ]
        )
        assert result.success
        assert result.data["applied"] == 2
        assert "def greet():" in (tmp_path / "a.py").read_text()
        assert "def earth():" in (tmp_path / "b.py").read_text()
        # Caption must reflect the actual file count.  The schema names
        # the per-edit field ``file``; previously the caption read
        # ``edit.get("file_path")`` and silently collapsed to "across 0
        # files" no matter how many files were edited.
        assert result.caption == "2 edits across 2 files"

    @pytest.mark.anyio
    async def test_caption_single_file_uses_filename(self, tool):
        """Single-file caption names the file, not just a count."""
        result = await tool.execute(
            edits=[{"file": "a.py", "old": "def hello():", "new": "def greet():"}],
        )
        assert result.success
        assert result.caption == "1 edit in a.py"

    @pytest.mark.anyio
    async def test_multiple_edits_same_file(self, tool, tmp_path):
        """Sequential edits to the same file work — each sees the previous edit's result."""
        result = await tool.execute(
            edits=[
                {"file": "a.py", "old": "def hello", "new": "def greet"},
                {"file": "a.py", "old": "'hello'", "new": "'hi'"},
            ]
        )
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
        result = await tool.execute(
            edits=[
                {"file": "nonexistent.py", "old": "x", "new": "y"},
            ]
        )
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_string_not_found(self, tool):
        result = await tool.execute(
            edits=[
                {"file": "a.py", "old": "nonexistent_string", "new": "replacement"},
            ]
        )
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_string_not_found_includes_did_you_mean(self, tool):
        """Phase 103.2: a near-miss attaches a unified-diff hint."""
        # ``a.py`` contains ``return 'hello'`` (single quotes); request
        # the double-quote variant to simulate post-resume drift.
        result = await tool.execute(
            edits=[
                {
                    "file": "a.py",
                    "old": 'return "hello"',
                    "new": 'return "world"',
                },
            ]
        )
        assert not result.success
        assert "Did you mean" in result.error
        # The diff should mention the actual on-disk single-quoted value.
        assert "'hello'" in result.error

    @pytest.mark.anyio
    async def test_relax_whitespace_per_edit(self, tool, tmp_path):
        """Phase 103.3: a per-edit ``relax_whitespace`` flag absorbs
        whitespace drift even inside a multi-edit batch."""
        (tmp_path / "c.py").write_text("def f():\n\treturn\t1\n")
        result = await tool.execute(
            edits=[
                {
                    "file": "c.py",
                    "old": "return 1",
                    "new": "return 2",
                    "relax_whitespace": True,
                },
            ]
        )
        assert result.success
        assert "return 2" in (tmp_path / "c.py").read_text()

    @pytest.mark.anyio
    async def test_relax_whitespace_off_by_default(self, tool, tmp_path):
        """Without the flag, whitespace drift still fails the edit."""
        (tmp_path / "c.py").write_text("def f():\n\treturn\t1\n")
        result = await tool.execute(
            edits=[
                {"file": "c.py", "old": "return 1", "new": "return 2"},
            ]
        )
        assert not result.success
        # File unchanged.
        assert "return\t1" in (tmp_path / "c.py").read_text()

    @pytest.mark.anyio
    async def test_ambiguous_match(self, tool, tmp_path):
        (tmp_path / "c.py").write_text("foo foo foo")
        result = await tool.execute(
            edits=[
                {"file": "c.py", "old": "foo", "new": "bar"},
            ]
        )
        assert not result.success
        assert "3 times" in result.error

    @pytest.mark.anyio
    async def test_partial_failure_reports_applied_count(self, tool, tmp_path):
        """First edit succeeds, second fails — error reports 1 applied."""
        result = await tool.execute(
            edits=[
                {"file": "a.py", "old": "def hello():", "new": "def greet():"},
                {"file": "nonexistent.py", "old": "x", "new": "y"},
            ]
        )
        assert not result.success
        assert "1 edit(s) applied" in result.error
        # First edit was persisted.
        assert "def greet():" in (tmp_path / "a.py").read_text()

    @pytest.mark.anyio
    async def test_non_utf8_file_returns_friendly_error(self, tool, tmp_path):
        """A binary / mis-encoded file errors cleanly instead of UnicodeDecodeError.

        Regression: ``read_text()`` on a non-UTF-8 file used to leak
        ``UnicodeDecodeError`` past the tool's narrow ``except OSError``.
        """
        (tmp_path / "binary.txt").write_bytes(b"hello \xff\xfe binary")
        result = await tool.execute(
            edits=[
                {"file": "binary.txt", "old": "hello", "new": "goodbye"},
            ]
        )
        assert not result.success
        assert "cannot read" in result.error.lower()
        # File was not modified.
        assert (tmp_path / "binary.txt").read_bytes().startswith(b"hello \xff\xfe")

    @pytest.mark.anyio
    async def test_path_traversal_blocked(self, tool):
        result = await tool.execute(
            edits=[
                {"file": "../../../etc/passwd", "old": "root", "new": "nope"},
            ]
        )
        assert not result.success
        assert "outside" in result.error.lower()

    @pytest.mark.anyio
    async def test_missing_file_field(self, tool):
        result = await tool.execute(
            edits=[
                {"file": "", "old": "x", "new": "y"},
            ]
        )
        assert not result.success
        assert "missing" in result.error.lower()
