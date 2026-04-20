"""Tests for :mod:`cantrip.tui.screens.file_detail`.

Pure-logic tests cover the purpose / preview / stats helpers; Pilot
tests drive the modal's mount-populate-render cycle with
``subprocess.run`` mocked so no ``git`` call runs.
"""

import datetime
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from cantrip.tui.screens.file_detail import (
    FileDetailScreen,
    _fallback_purpose,
    _format_git_log,
    _format_relative_time,
    _format_size,
    _format_stats,
    _infer_purpose,
    _markdown_first_section,
    _python_module_docstring,
    _read_text_safely,
    _render_preview,
    _toml_description,
    _yaml_summary,
)

pytestmark = pytest.mark.tui


class _Host(App):
    """Minimal host for pushing a FileDetailScreen."""

    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestFormatSize:
    def test_bytes(self) -> None:
        assert _format_size(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert _format_size(2048) == "2.0 KB"

    def test_megabytes(self) -> None:
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"


class TestFormatRelativeTime:
    def test_just_now(self) -> None:
        now = datetime.datetime.now(tz=datetime.UTC)
        assert _format_relative_time(now) == "just now"

    def test_minutes(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(minutes=5)
        assert _format_relative_time(when) == "5 min ago"

    def test_hours_plural(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=3)
        assert _format_relative_time(when) == "3 hours ago"

    def test_single_hour_singular(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=1)
        assert _format_relative_time(when) == "1 hour ago"

    def test_days(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=4)
        assert _format_relative_time(when) == "4 days ago"

    def test_months(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=75)
        assert _format_relative_time(when) == "2 months ago"

    def test_years(self) -> None:
        when = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=800)
        assert _format_relative_time(when) == "2 years ago"


class TestFormatStats:
    def test_missing_file_noted(self, tmp_path: Path) -> None:
        assert "not readable" in _format_stats(tmp_path / "missing")

    def test_existing_file_includes_size_and_time(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("hi")
        line = _format_stats(f)
        assert "B" in line
        assert "modified" in line


class TestPythonDocstring:
    def test_extracts_module_docstring(self) -> None:
        source = '"""Top-level docstring.\n\nMore detail."""\n\nx = 1\n'
        assert _python_module_docstring(source) == "Top-level docstring.\n\nMore detail."

    def test_none_when_missing(self) -> None:
        assert _python_module_docstring("x = 1\n") is None

    def test_none_when_syntax_error(self) -> None:
        assert _python_module_docstring("def (\n") is None


class TestMarkdownFirstSection:
    def test_heading_plus_body(self) -> None:
        text = "# Title\n\nFirst paragraph line.\nContinuation.\n\nSecond paragraph.\n"
        result = _markdown_first_section(text)
        assert result is not None
        assert "**Title**" in result
        assert "First paragraph" in result
        assert "Second paragraph" not in result

    def test_heading_only(self) -> None:
        assert _markdown_first_section("# Only Title\n") == "**Only Title**"

    def test_paragraph_only_no_heading(self) -> None:
        assert _markdown_first_section("No heading here, just words.\n") == (
            "No heading here, just words."
        )

    def test_empty_returns_none(self) -> None:
        assert _markdown_first_section("\n\n") is None

    def test_stops_at_second_heading(self) -> None:
        text = "# First\n\nBody.\n\n## Second\n\nMore.\n"
        result = _markdown_first_section(text)
        assert result is not None
        assert "Second" not in result


class TestYamlSummary:
    def test_summary_only(self) -> None:
        text = "summary: Does one thing well\nother: x\n"
        assert _yaml_summary(text) == "Does one thing well"

    def test_description_only(self) -> None:
        text = "description: A thing.\n"
        assert _yaml_summary(text) == "A thing."

    def test_summary_and_description_combine(self) -> None:
        text = "summary: Short\ndescription: Long explanation.\n"
        result = _yaml_summary(text)
        assert result is not None
        assert "**Short**" in result
        assert "Long explanation." in result

    def test_quoted_value(self) -> None:
        text = 'summary: "Quoted value"\n'
        assert _yaml_summary(text) == "Quoted value"

    def test_folded_scalar(self) -> None:
        text = "summary: >\n  Folded\n  line one.\n\nother: x\n"
        assert _yaml_summary(text) == "Folded line one."

    def test_missing_returns_none(self) -> None:
        assert _yaml_summary("name: foo\n") is None


class TestTomlDescription:
    def test_quoted_description(self) -> None:
        text = '[project]\nname = "x"\ndescription = "A nice library"\n'
        assert _toml_description(text) == "A nice library"

    def test_missing(self) -> None:
        assert _toml_description("[project]\nname = 'x'\n") is None


class TestInferPurpose:
    def test_python_docstring(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text('"""Module purpose line."""\n')
        assert _infer_purpose(f) == "Module purpose line."

    def test_python_without_docstring_falls_back(self, tmp_path: Path) -> None:
        f = tmp_path / "nodoc.py"
        f.write_text("x = 1\n")
        assert "py file" in _infer_purpose(f)

    def test_markdown_heading(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# My Charm\n\nSome words.\n")
        result = _infer_purpose(f)
        assert "**My Charm**" in result

    def test_charmcraft_yaml_summary(self, tmp_path: Path) -> None:
        f = tmp_path / "charmcraft.yaml"
        f.write_text("name: my-charm\nsummary: One line summary.\n")
        assert "One line summary." in _infer_purpose(f)

    def test_non_metadata_yaml_falls_back(self, tmp_path: Path) -> None:
        # Non-charm YAMLs don't try to extract summary/description.
        f = tmp_path / "random.yaml"
        f.write_text("summary: ignored\n")
        assert "no structured summary" in _infer_purpose(f)

    def test_pyproject_toml(self, tmp_path: Path) -> None:
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\ndescription = "A TOML project"\n')
        assert "A TOML project" in _infer_purpose(f)

    def test_unknown_extension_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "file.bin"
        f.write_text("content")
        assert "bin file" in _fallback_purpose(f)

    def test_unreadable_file(self, tmp_path: Path) -> None:
        assert "Could not read" in _infer_purpose(tmp_path / "missing.py")


class TestReadTextSafely:
    def test_reads_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello")
        assert _read_text_safely(f, max_bytes=1024) == "hello"

    def test_rejects_binary(self, tmp_path: Path) -> None:
        f = tmp_path / "bin"
        f.write_bytes(b"\x00\x01\x02")
        assert _read_text_safely(f, max_bytes=1024) is None

    def test_truncates_to_max_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 2048)
        result = _read_text_safely(f, max_bytes=16)
        assert result is not None
        assert len(result) == 16

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.txt"
        # Byte 0xff is invalid UTF-8 but valid Latin-1 (ÿ).
        f.write_bytes(b"hello \xff")
        assert _read_text_safely(f, max_bytes=1024) == "hello ÿ"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _read_text_safely(tmp_path / "missing", max_bytes=1024) is None


class TestRenderPreview:
    def test_short_file_is_fully_rendered(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("line1\nline2\nline3\n")
        out = _render_preview(f)
        assert "1  line1" in out
        assert "3  line3" in out
        assert "…" not in out

    def test_long_file_is_truncated(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line{i}" for i in range(500)))
        out = _render_preview(f)
        assert "first 120 lines" in out

    def test_binary_file_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "blob.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
        assert "Binary" in _render_preview(f)

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert "Empty" in _render_preview(f)


class TestFormatGitLog:
    def test_renders_each_entry(self) -> None:
        raw = "abc123|2 days ago|Alice|Fix bug\ndef456|1 week ago|Bob|Add thing"
        out = _format_git_log(raw)
        assert "abc123" in out
        assert "Alice" in out
        assert "Add thing" in out

    def test_empty_raw(self) -> None:
        assert "No commits" in _format_git_log("")

    def test_malformed_line_passthrough(self) -> None:
        # Lines without the expected separator count are passed through.
        out = _format_git_log("not a proper line")
        assert "not a proper line" in out


# ---------------------------------------------------------------------------
# FileDetailScreen — Pilot integration tests
# ---------------------------------------------------------------------------


class TestFileDetailScreenInit:
    def test_display_path_relative_when_under_root(self, tmp_path: Path) -> None:
        f = tmp_path / "sub" / "file.py"
        f.parent.mkdir()
        f.write_text("x")
        screen = FileDetailScreen(f, charm_root=tmp_path)
        assert screen._display_path == "sub/file.py"

    def test_display_path_absolute_when_outside_root(self, tmp_path: Path) -> None:
        screen = FileDetailScreen(tmp_path / "file.py", charm_root=Path("/other"))
        assert screen._display_path == str(tmp_path / "file.py")

    def test_display_path_without_charm_root(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        screen = FileDetailScreen(f)
        assert screen._display_path == str(f)


class TestGitLogBlocking:
    def test_file_not_found_returns_marker(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "__error__:git not installed"

    def test_timeout_returns_marker(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=10),
        ):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "__error__:git log timed out"

    def test_nonzero_returns_stderr_marker(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="not a git repository", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert "not a git repository" in result
        assert result.startswith("__error__:")

    def test_success_returns_stdout(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="abc|2d|alice|fix", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "abc|2d|alice|fix"


class TestFileDetailScreenPilot:
    @pytest.mark.asyncio
    async def test_python_file_renders_docstring_and_preview(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text('"""Greets the world."""\n\ndef hi():\n    return "hi"\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)

                purpose = screen.query_one("#file-purpose", Static).render()
                preview = screen.query_one("#file-preview", Static).render()
                assert "Greets the world." in str(purpose)
                assert "def hi" in str(preview)

    @pytest.mark.asyncio
    async def test_git_log_error_is_rendered_as_dim_note(self, tmp_path: Path) -> None:
        f = tmp_path / "x.txt"
        f.write_text("content")
        mock_result = MagicMock(returncode=128, stderr="fatal: not a git repository", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = str(screen.query_one("#file-git-log", Static).render())
                assert "Not tracked by git" in log

    @pytest.mark.asyncio
    async def test_git_log_empty_output_is_no_commits_notice(self, tmp_path: Path) -> None:
        f = tmp_path / "x.txt"
        f.write_text("content")
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = str(screen.query_one("#file-git-log", Static).render())
                assert "No commits" in log

    @pytest.mark.asyncio
    async def test_git_log_renders_entries_on_success(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text('"""x"""\n')
        stdout = "abc123|2 days ago|Alice|Fix bug\ndef456|1 week ago|Bob|First"
        mock_result = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = str(screen.query_one("#file-git-log", Static).render())
                assert "abc123" in log
                assert "Alice" in log

    @pytest.mark.asyncio
    async def test_refresh_reruns_git_log(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text('"""x"""\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as run:
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                before = run.call_count
                screen.action_refresh()
                await pilot.pause(delay=0.3)
                assert run.call_count > before
