"""Unit tests for ``quickpack.jujuignore``."""

import pathlib

from quickpack import jujuignore


class TestJujuignore:
    """Tests for jujuignore pattern matching."""

    def test_default_ignores(self) -> None:
        ignore = jujuignore.JujuIgnore()
        assert ignore.match(".git", is_dir=True)
        assert ignore.match(".tox", is_dir=True)
        assert ignore.match("build", is_dir=True)
        assert ignore.match(".jujuignore", is_dir=False)

    def test_custom_pattern(self) -> None:
        ignore = jujuignore.JujuIgnore(["*.pyc"])
        assert ignore.match("module.pyc", is_dir=False)
        assert not ignore.match("module.py", is_dir=False)

    def test_negation(self) -> None:
        ignore = jujuignore.JujuIgnore(["*.log", "!important.log"])
        # The negation inverts — important.log should NOT be ignored.
        assert not ignore.match("important.log", is_dir=False)
        assert ignore.match("debug.log", is_dir=False)

    def test_directory_only(self) -> None:
        ignore = jujuignore.JujuIgnore(["cache/"])
        assert ignore.match("cache", is_dir=True)
        assert not ignore.match("cache", is_dir=False)

    def test_doublestar(self) -> None:
        ignore = jujuignore.JujuIgnore(["**/__pycache__"])
        assert ignore.match("src/__pycache__", is_dir=True)
        assert ignore.match("deep/nested/__pycache__", is_dir=True)

    def test_leading_slash(self) -> None:
        """A pattern with a leading / only matches at the root."""
        ignore = jujuignore.JujuIgnore(["/build/"])
        assert ignore.match("build", is_dir=True)
        # Should NOT match build in a subdirectory.
        assert not ignore.match("src/build", is_dir=True)

    def test_from_file(self, tmp_path: pathlib.Path) -> None:
        ignore_file = tmp_path / ".jujuignore"
        ignore_file.write_text("*.bak\n# comment\n\ntmp/\n")
        ignore = jujuignore.JujuIgnore.from_file(str(ignore_file))
        assert ignore.match("foo.bak", is_dir=False)
        assert ignore.match("tmp", is_dir=True)

    def test_from_file_missing(self, tmp_path: pathlib.Path) -> None:
        """Missing file should use only defaults."""
        ignore = jujuignore.JujuIgnore.from_file(str(tmp_path / ".jujuignore"))
        assert ignore.match(".git", is_dir=True)
        assert not ignore.match("src", is_dir=True)

    def test_venv_ignored(self) -> None:
        ignore = jujuignore.JujuIgnore()
        assert ignore.match("venv", is_dir=True)

    def test_comment_and_blank_lines(self) -> None:
        ignore = jujuignore.JujuIgnore(["# comment", "", "   ", "*.tmp"])
        assert ignore.match("foo.tmp", is_dir=False)
        # Comments and blanks should not create matchers.
        assert not ignore.match("# comment", is_dir=False)
