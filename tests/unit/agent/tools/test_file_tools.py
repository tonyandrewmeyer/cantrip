"""Tests for file operation tools — path traversal, CRUD, and edge cases."""

import pytest

from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
    _did_you_mean_hint,
)


class TestPathAwareTool:
    """Path resolution and traversal prevention.

    Uses ReadFileTool as a concrete PathAwareTool subclass to test
    the shared _resolve_path logic.
    """

    def test_relative_path_resolved_against_base(self, tmp_path):
        """A relative path is resolved against the base directory."""
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path("subdir/file.txt")
        assert resolved == (tmp_path / "subdir" / "file.txt").resolve()

    def test_absolute_path_within_base_allowed(self, tmp_path):
        """An absolute path inside the base directory is permitted."""
        target = tmp_path / "inside.txt"
        target.touch()
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path(str(target))
        assert resolved == target.resolve()

    def test_traversal_via_dotdot_blocked(self, tmp_path):
        """A path using .. to escape the base directory is rejected."""
        tool = ReadFileTool(base_path=tmp_path)
        with pytest.raises(ValueError, match="outside allowed directory"):
            tool._resolve_path("../../../etc/passwd")

    def test_absolute_path_outside_base_blocked(self, tmp_path):
        """An absolute path outside the base directory is rejected."""
        tool = ReadFileTool(base_path=tmp_path)
        with pytest.raises(ValueError, match="outside allowed directory"):
            tool._resolve_path("/etc/passwd")

    def test_symlink_escape_blocked(self, tmp_path):
        """A symlink that points outside the base directory is rejected."""
        outside = tmp_path.parent / "outside_target.txt"
        outside.write_text("secret")
        link = tmp_path / "sneaky_link"
        link.symlink_to(outside)

        tool = ReadFileTool(base_path=tmp_path)
        with pytest.raises(ValueError, match="outside allowed directory"):
            tool._resolve_path("sneaky_link")

        outside.unlink()

    def test_no_base_path_allows_any(self):
        """Without a base path, any resolvable path is allowed."""
        tool = ReadFileTool(base_path=None)
        resolved = tool._resolve_path("/tmp/anything.txt")
        assert str(resolved) == "/tmp/anything.txt"

    def test_nested_dotdot_normalised(self, tmp_path):
        """A path like 'a/b/../../c' that stays within the base is fine."""
        (tmp_path / "c").touch()
        tool = ReadFileTool(base_path=tmp_path)
        resolved = tool._resolve_path("a/b/../../c")
        assert resolved == (tmp_path / "c").resolve()

    @pytest.mark.asyncio
    async def test_sibling_with_matching_prefix_blocked(self, tmp_path):
        """A sibling directory whose name shares a prefix is rejected.

        Guards against a string-prefix containment check: if the base is
        ``/tmp/abc`` then ``/tmp/abc-evil/secret`` must not be allowed.
        """
        evil_dir = tmp_path.parent / (tmp_path.name + "-evil")
        evil_dir.mkdir(exist_ok=True)
        evil_file = evil_dir / "secret.txt"
        evil_file.write_text("stolen")
        try:
            tool = ReadFileTool(base_path=tmp_path)
            result = await tool.execute(path=str(evil_file))
            assert not result.success
            assert "outside" in result.error.lower()
        finally:
            evil_file.unlink(missing_ok=True)
            evil_dir.rmdir()


class TestReadFileTool:
    """Tests for ReadFileTool."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path):
        """Successfully reads file content."""
        target = tmp_path / "hello.txt"
        target.write_text("hello world")
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="hello.txt")

        assert result.success is True
        assert result.output == "hello world"
        assert result.data["size"] == 11

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        """Returns error for missing file."""
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="nope.txt")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_directory_returns_error(self, tmp_path):
        """Attempting to read a directory returns an error."""
        (tmp_path / "subdir").mkdir()
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="subdir")

        assert result.success is False
        assert "directory" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_binary_file_returns_error(self, tmp_path):
        """Reading a file with invalid UTF-8 returns an error."""
        target = tmp_path / "binary.bin"
        target.write_bytes(b"\x80\x81\x82\xff")
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="binary.bin")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_read_traversal_blocked(self, tmp_path):
        """Path traversal in read is blocked."""
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="../../etc/passwd")

        assert result.success is False
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_empty_file(self, tmp_path):
        """Reading an empty file succeeds with empty content."""
        target = tmp_path / "empty.txt"
        target.write_text("")
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="empty.txt")

        assert result.success is True
        assert result.output == ""
        assert result.data["size"] == 0

    @pytest.mark.asyncio
    async def test_read_nested_path(self, tmp_path):
        """Reads files in nested directories."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        target = nested / "deep.txt"
        target.write_text("deep content")
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="a/b/c/deep.txt")

        assert result.success is True
        assert result.output == "deep content"

    @pytest.mark.asyncio
    async def test_read_range_caption_counts_lines_without_trailing_newline(
        self, tmp_path
    ) -> None:
        """The "Read N lines" caption must count slice length, not ``\\n`` runs.

        Regression: a partial read used ``content.count("\\n")``, which
        under-reports by one for any file whose last line lacks a trailing
        newline (common in legacy text and most code files) — the final
        element from ``splitlines(keepends=True)`` carries no ``\\n``.
        """
        target = tmp_path / "no_trailing_nl.txt"
        # Three lines, last one has no trailing newline.
        target.write_text("alpha\nbeta\ngamma")
        tool = ReadFileTool(base_path=tmp_path)

        result = await tool.execute(path="no_trailing_nl.txt", start_line=1, end_line=3)

        assert result.success is True
        assert result.output == "alpha\nbeta\ngamma"
        assert result.caption == "Read 3 lines from no_trailing_nl.txt"


class TestWriteFileTool:
    """Tests for WriteFileTool."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path):
        """Creates a new file with content."""
        tool = WriteFileTool(base_path=tmp_path)

        result = await tool.execute(path="new.txt", content="hello")

        assert result.success is True
        assert (tmp_path / "new.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_write_creates_parent_directories(self, tmp_path):
        """Parent directories are created automatically."""
        tool = WriteFileTool(base_path=tmp_path)

        result = await tool.execute(path="a/b/c/file.txt", content="nested")

        assert result.success is True
        assert (tmp_path / "a" / "b" / "c" / "file.txt").read_text() == "nested"

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tmp_path):
        """Overwrites an existing file."""
        target = tmp_path / "existing.txt"
        target.write_text("old")
        tool = WriteFileTool(base_path=tmp_path)

        result = await tool.execute(path="existing.txt", content="new")

        assert result.success is True
        assert target.read_text() == "new"

    @pytest.mark.asyncio
    async def test_write_traversal_blocked(self, tmp_path):
        """Path traversal in write is blocked."""
        tool = WriteFileTool(base_path=tmp_path)

        result = await tool.execute(path="../escape.txt", content="bad")

        assert result.success is False
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_reports_byte_count(self, tmp_path):
        """Output message includes byte count."""
        tool = WriteFileTool(base_path=tmp_path)

        result = await tool.execute(path="sized.txt", content="12345")

        assert result.success is True
        assert "5" in result.output

    @pytest.mark.asyncio
    async def test_write_to_read_only_directory(self, tmp_path):
        """Writing to a read-only directory reports an OS error."""
        read_only = tmp_path / "readonly"
        read_only.mkdir()
        read_only.chmod(0o444)
        try:
            tool = WriteFileTool(base_path=read_only)
            result = await tool.execute(path="file.txt", content="data")
            assert not result.success
            assert result.error
        finally:
            read_only.chmod(0o755)


class TestListDirectoryTool:
    """Tests for ListDirectoryTool."""

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        """Lists files and directories correctly."""
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path=".")

        assert result.success is True
        assert "file: file.txt" in result.output
        assert "bytes)" in result.output
        assert "dir:  subdir/" in result.output
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tmp_path):
        """Empty directory returns placeholder message."""
        empty = tmp_path / "empty"
        empty.mkdir()
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path="empty")

        assert result.success is True
        assert "empty directory" in result.output

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tmp_path):
        """Nonexistent directory returns error."""
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path="nope")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_file_not_directory(self, tmp_path):
        """Listing a file (not directory) returns error."""
        (tmp_path / "file.txt").touch()
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path="file.txt")

        assert result.success is False
        assert "not a directory" in result.error.lower()

    @pytest.mark.asyncio
    async def test_list_default_path(self, tmp_path):
        """Default path '.' lists the base directory."""
        (tmp_path / "a.txt").touch()
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute()

        assert result.success is True
        assert "file: a.txt" in result.output

    @pytest.mark.asyncio
    async def test_list_traversal_blocked(self, tmp_path):
        """Path traversal in list is blocked."""
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path="../../")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_sorted_output(self, tmp_path):
        """Entries are sorted alphabetically."""
        (tmp_path / "zebra.txt").touch()
        (tmp_path / "alpha.txt").touch()
        (tmp_path / "middle.txt").touch()
        tool = ListDirectoryTool(base_path=tmp_path)

        result = await tool.execute(path=".")

        lines = result.output.strip().split("\n")
        names = [line.split(": ", 1)[1] for line in lines]
        assert names == sorted(names)


class TestEditFileTool:
    """Tests for EditFileTool."""

    @pytest.mark.asyncio
    async def test_edit_replaces_string(self, tmp_path):
        """Replaces a unique string in the file."""
        target = tmp_path / "code.py"
        target.write_text("def hello():\n    return 'hello'\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="code.py",
            old_string="return 'hello'",
            new_string="return 'world'",
        )

        assert result.success is True
        assert "return 'world'" in target.read_text()

    @pytest.mark.asyncio
    async def test_edit_string_not_found(self, tmp_path):
        """Returns error when old_string is not found."""
        target = tmp_path / "code.py"
        target.write_text("def hello(): pass\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="code.py",
            old_string="nonexistent",
            new_string="replacement",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_string_not_found_includes_did_you_mean_hint(self, tmp_path):
        """Phase 103.2: failed edit pairs the preview with a unified diff."""
        target = tmp_path / "code.py"
        target.write_text("def greet():\n    return 'hello world'\n")
        tool = EditFileTool(base_path=tmp_path)

        # Drift the bytes the model thinks it remembers — single-quote vs
        # double-quote string is the classic post-resume mismatch.
        result = await tool.execute(
            path="code.py",
            old_string='return "hello world"',
            new_string='return "goodbye"',
        )

        assert result.success is False
        assert "Did you mean" in result.error
        # The diff should mention the actual on-disk text so the next
        # round can target it.
        assert "hello world" in result.error
        # Unified-diff markers should be present.
        assert "---" in result.error
        assert "+++" in result.error

    @pytest.mark.asyncio
    async def test_edit_string_not_found_omits_hint_for_unrelated_text(self, tmp_path):
        """No diff is added when the file shares nothing with the requested text."""
        target = tmp_path / "code.py"
        target.write_text("alpha\nbeta\ngamma\n")
        tool = EditFileTool(base_path=tmp_path)

        # ``zzz`` has no overlap whatsoever with the file content, so the
        # closest-match search returns nothing useful.  An all-add diff
        # in that case would be misleading rather than helpful.
        result = await tool.execute(
            path="code.py",
            old_string="zzz",
            new_string="qqq",
        )

        assert result.success is False
        assert "Did you mean" not in result.error

    @pytest.mark.asyncio
    async def test_edit_ambiguous_match(self, tmp_path):
        """Returns error when old_string appears multiple times."""
        target = tmp_path / "code.py"
        target.write_text("foo\nfoo\nbar\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="code.py",
            old_string="foo",
            new_string="baz",
        )

        assert result.success is False
        assert "2 times" in result.error

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, tmp_path):
        """Returns error for missing file."""
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="nope.py",
            old_string="x",
            new_string="y",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_traversal_blocked(self, tmp_path):
        """Path traversal in edit is blocked."""
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="../../etc/passwd",
            old_string="root",
            new_string="hacked",
        )

        assert result.success is False
        assert "outside" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_preserves_surrounding_content(self, tmp_path):
        """Edit only replaces the target string, preserving the rest."""
        content = "line1\nline2\nline3\n"
        target = tmp_path / "code.py"
        target.write_text(content)
        tool = EditFileTool(base_path=tmp_path)

        await tool.execute(path="code.py", old_string="line2", new_string="replaced")

        assert target.read_text() == "line1\nreplaced\nline3\n"

    @pytest.mark.asyncio
    async def test_edit_multiline_replacement(self, tmp_path):
        """Supports multiline old_string and new_string."""
        target = tmp_path / "code.py"
        target.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="code.py",
            old_string="def foo():\n    pass",
            new_string="def foo():\n    return 42",
        )

        assert result.success is True
        assert "return 42" in target.read_text()
        # bar() should be unchanged.
        assert "def bar():\n    pass" in target.read_text()


class TestEditFileRelaxWhitespace:
    """Tests for the Phase 103.3 ``relax_whitespace`` fallback on EditFileTool.

    The fallback is opt-in — by default ``edit_file`` still requires an
    exact match.  When the model passes ``relax_whitespace=True``, runs
    of whitespace in ``old_string`` collapse into ``\\s+`` so the
    obvious drift patterns (``"\\n\\n"`` vs ``"\\n  \\n"``, tab/space,
    extra trailing newline) match without a re-read.  An ambiguous
    relaxed match still refuses the edit so we can't overwrite the
    wrong instance.
    """

    @pytest.mark.asyncio
    async def test_off_by_default(self, tmp_path):
        """Whitespace drift is not absorbed when the flag is omitted."""
        target = tmp_path / "f.py"
        target.write_text("def f():\n    return    1\n")  # extra spaces
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="f.py",
            old_string="return 1",
            new_string="return 2",
        )

        assert result.success is False
        assert "1" in target.read_text()  # unchanged

    @pytest.mark.asyncio
    async def test_collapses_inline_whitespace_when_enabled(self, tmp_path):
        """Tabs / multi-space gaps in the file are absorbed by ``\\s+``."""
        target = tmp_path / "f.py"
        target.write_text("def f():\n\treturn\t1\n")  # tabs in file
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="f.py",
            old_string="return 1",  # single space in request
            new_string="return 2",
            relax_whitespace=True,
        )

        assert result.success is True
        # The line indent (``\t``) precedes ``old_string`` so it survives
        # the replacement; only the matched ``return\t1`` window is swapped.
        assert target.read_text() == "def f():\n\treturn 2\n"

    @pytest.mark.asyncio
    async def test_blank_line_with_stray_whitespace(self, tmp_path):
        """``"\\n\\n"`` matches a blank line that picked up trailing spaces."""
        target = tmp_path / "f.py"
        # File has trailing whitespace on the blank line.
        target.write_text("alpha\n  \nbeta\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="f.py",
            old_string="alpha\n\nbeta",
            new_string="alpha\nGAMMA\nbeta",
            relax_whitespace=True,
        )

        assert result.success is True
        assert target.read_text() == "alpha\nGAMMA\nbeta\n"

    @pytest.mark.asyncio
    async def test_ambiguous_relaxed_match_refused(self, tmp_path):
        """Refuses the relaxed edit when the pattern matches multiple times.

        ``old_string`` doesn't exist verbatim in the file, but its
        whitespace-collapsed regex would match both lines.  The tool
        must refuse rather than overwrite an arbitrary one.
        """
        target = tmp_path / "f.py"
        # File contains two whitespace variants; ``old_string`` matches
        # neither verbatim, but the relaxed pattern ``foo\s+bar`` would
        # match both.
        target.write_text("foo bar\nfoo\tbar\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="f.py",
            old_string="foo  bar",  # two spaces — matches no line exactly
            new_string="foo BAZ",
            relax_whitespace=True,
        )

        assert result.success is False
        assert target.read_text() == "foo bar\nfoo\tbar\n"  # unchanged

    @pytest.mark.asyncio
    async def test_relax_does_not_match_unrelated_content(self, tmp_path):
        """Whitespace tolerance does not bridge wholly different bytes."""
        target = tmp_path / "f.py"
        target.write_text("def hello():\n    return 'hello'\n")
        tool = EditFileTool(base_path=tmp_path)

        result = await tool.execute(
            path="f.py",
            old_string="def goodbye():",
            new_string="def farewell():",
            relax_whitespace=True,
        )

        assert result.success is False
        assert "def hello" in target.read_text()  # unchanged


class TestDidYouMeanHint:
    """Tests for the Phase 103.2 ``_did_you_mean_hint`` helper.

    The helper produces a unified-diff snippet between the model's
    requested ``old_string`` and the closest substring on disk, so a
    failed ``edit_file`` round comes back with directly-actionable
    bytes rather than just a 50-character preview of what the model
    asked for.
    """

    def test_returns_diff_for_close_match(self):
        """A small drift produces a unified diff between expected and actual."""
        old_string = '    return "hello world"'
        content = "def greet():\n    return 'hello world'\n"

        hint = _did_you_mean_hint(old_string, content)

        assert hint is not None
        assert "expected" in hint
        assert "actual" in hint
        # Should show the actual bytes the model is missing.
        assert "'hello world'" in hint
        # And the model's expected single-line entry should appear too,
        # marked with a leading ``-`` in the diff.
        assert '-    return "hello world"' in hint or '"hello world"' in hint

    def test_returns_none_for_no_overlap(self):
        """Completely unrelated text returns ``None`` rather than a useless diff."""
        assert _did_you_mean_hint("zzz", "alpha\nbeta\ngamma\n") is None

    def test_returns_none_for_empty_inputs(self):
        """Empty arguments don't produce a hint."""
        assert _did_you_mean_hint("", "anything") is None
        assert _did_you_mean_hint("anything", "") is None

    def test_diff_is_capped(self):
        """The diff body is capped at the configured line budget.

        Build an *almost* identical pair so the helper's minimum-overlap
        gate passes — the only drift is on the first line — but the
        diff itself runs many lines because the matcher emits surrounding
        context.
        """
        # The first line drifts; the rest of the bytes are identical so
        # the longest match is large relative to ``old_string``.  With
        # ``max_lines`` set low, the truncation marker should fire on
        # the resulting unified diff.
        common_lines = "".join(f"line {i}\n" for i in range(20))
        old_string = "drifted prefix\n" + common_lines
        content = "actual prefix\n" + common_lines

        hint = _did_you_mean_hint(old_string, content, max_lines=2)

        assert hint is not None
        # Cap is on body lines; truncation marker fires when the diff
        # would have exceeded the cap.
        assert "truncated" in hint

    def test_diff_picks_window_around_match(self):
        """Match window is anchored near the longest matching line block."""
        old_string = "def greet():\n    return 'hi'\n"
        content = (
            "import logging\n\n"
            "def unrelated():\n    pass\n\n"
            "def greet():\n    return 'hello'\n\n"
            "def other():\n    return None\n"
        )

        hint = _did_you_mean_hint(old_string, content)

        assert hint is not None
        # The hint should target the matching ``def greet()`` block, not
        # the ``def unrelated`` opener.
        assert "def greet" in hint
        assert "'hello'" in hint
