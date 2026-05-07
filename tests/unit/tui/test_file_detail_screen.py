"""Tests for :mod:`cantrip.tui.screens.file_detail`.

Pure-logic tests cover the purpose / preview / stats helpers; Pilot
tests drive the modal's mount-populate-render cycle with
``subprocess.run`` mocked so no ``git`` call runs.
"""

import datetime
import pathlib
import subprocess
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console, Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cantrip.tui.screens.file_detail import (
    FileDetailScreen,
    _cantrip_artefact_purpose,
    _fallback_purpose,
    _format_git_log,
    _format_relative_time,
    _format_size,
    _format_stats,
    _guess_lexer,
    _infer_purpose,
    _markdown_first_section,
    _python_module_docstring,
    _read_text_safely,
    _render_preview,
    _toml_description,
    _yaml_summary,
)


def _render_rich(renderable: object) -> str:
    """Render a Rich renderable to a plain string for content assertions."""
    console = Console(
        file=StringIO(),
        force_terminal=False,
        color_system=None,
        width=200,
    )
    console.print(renderable)
    return console.file.getvalue()


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
    def test_missing_file_noted(self, tmp_path: pathlib.Path) -> None:
        assert "not readable" in _format_stats(tmp_path / "missing")

    def test_existing_file_includes_size_and_time(self, tmp_path: pathlib.Path) -> None:
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
        # A file with no module / class / function docstrings.
        assert _python_module_docstring("x = 1\ny = 2\n") is None

    def test_falls_back_to_first_class_docstring(self) -> None:
        source = 'import os\n\n\nclass Foo:\n    """Foo does something useful."""\n    pass\n'
        result = _python_module_docstring(source)
        assert result is not None
        assert "Foo does something useful" in result
        assert "class Foo" in result

    def test_falls_back_to_first_function_docstring(self) -> None:
        source = '\ndef bar():\n    """Bar returns a thing."""\n    return 1\n'
        result = _python_module_docstring(source)
        assert result is not None
        assert "Bar returns a thing" in result
        assert "function bar" in result

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
    def test_python_docstring(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text('"""Module purpose line."""\n')
        assert _infer_purpose(f) == "Module purpose line."

    def test_python_without_docstring_falls_back(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "nodoc.py"
        f.write_text("x = 1\n")
        assert "py file" in _infer_purpose(f)

    def test_markdown_heading(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# My Charm\n\nSome words.\n")
        result = _infer_purpose(f)
        assert "**My Charm**" in result

    def test_charmcraft_yaml_summary(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "charmcraft.yaml"
        f.write_text("name: my-charm\nsummary: One line summary.\n")
        assert "One line summary." in _infer_purpose(f)

    def test_non_metadata_yaml_falls_back(self, tmp_path: pathlib.Path) -> None:
        # Non-charm YAMLs don't try to extract summary/description.
        f = tmp_path / "random.yaml"
        f.write_text("summary: ignored\n")
        assert "no structured summary" in _infer_purpose(f)

    def test_pyproject_toml(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\ndescription = "A TOML project"\n')
        assert "A TOML project" in _infer_purpose(f)

    def test_unknown_extension_fallback(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "file.bin"
        f.write_text("content")
        assert "bin file" in _fallback_purpose(f)

    def test_unreadable_file(self, tmp_path: pathlib.Path) -> None:
        assert "Could not read" in _infer_purpose(tmp_path / "missing.py")


class TestCantripArtefactPurpose:
    """Cantrip-owned ``.cantrip*`` files override content-based inference."""

    def test_session_store(self, tmp_path: pathlib.Path) -> None:
        # The SQLite session is binary so content inference yields the
        # generic fallback; the artefact rule must fire first.
        f = tmp_path / ".cantrip"
        f.write_bytes(b"SQLite format 3\x00more-binary-bytes")
        result = _infer_purpose(f)
        assert "Cantrip session store" in result

    def test_audit_log(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip-audit.jsonl"
        f.write_text('{"event": "tool_call"}\n')
        assert "Cantrip audit log" in _infer_purpose(f)

    def test_repomap_cache(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip-repomap.json"
        f.write_text("{}\n")
        assert "Cantrip repomap cache" in _infer_purpose(f)

    def test_session_backup_with_timestamp(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip.bak-20260101_120000"
        f.write_bytes(b"\x00")
        assert "Cantrip session backup" in _infer_purpose(f)

    def test_session_backup_plain(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip.bak"
        f.write_bytes(b"\x00")
        assert "Cantrip session backup" in _infer_purpose(f)

    def test_migration_tmp(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip.tmp"
        f.write_bytes(b"\x00")
        assert "migration scratch" in _infer_purpose(f)

    def test_corrupt_marker(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".cantrip.corrupt"
        f.write_text("legacy\n")
        assert "salvaged session" in _infer_purpose(f)

    def test_permissions_yaml(self, tmp_path: pathlib.Path) -> None:
        cantrip_dir = tmp_path / ".cantrip"
        cantrip_dir.mkdir()
        f = cantrip_dir / "permissions.yaml"
        f.write_text("allow: []\n")
        assert "permission rules" in _infer_purpose(f)

    def test_team_sync_decisions(self, tmp_path: pathlib.Path) -> None:
        shared = tmp_path / ".cantrip-shared"
        shared.mkdir()
        f = shared / "decisions.jsonl"
        f.write_text('{"decision": "x"}\n')
        assert "team-sync decisions" in _infer_purpose(f)

    def test_check_definition(self, tmp_path: pathlib.Path) -> None:
        checks = tmp_path / ".cantrip" / "checks"
        checks.mkdir(parents=True)
        f = checks / "lint.md"
        f.write_text("# Lint passes\n")
        # Bucket description wins over the markdown-heading inference
        # because Cantrip-owned artefacts run first.
        assert "acceptance check" in _infer_purpose(f)

    def test_custom_command(self, tmp_path: pathlib.Path) -> None:
        commands = tmp_path / ".cantrip" / "commands"
        commands.mkdir(parents=True)
        f = commands / "deploy.md"
        f.write_text("Deploy the charm.\n")
        assert "custom slash command" in _infer_purpose(f)

    def test_team_sync_memory(self, tmp_path: pathlib.Path) -> None:
        memory = tmp_path / ".cantrip-shared" / "memory"
        memory.mkdir(parents=True)
        f = memory / "note.md"
        f.write_text("# Reminder\nbody\n")
        assert "team-sync memory" in _infer_purpose(f)

    def test_worktree_contents_use_content_inference(self, tmp_path: pathlib.Path) -> None:
        # A charmcraft.yaml inside a per-subagent worktree is a real
        # charm file — its own content describes it.  The artefact
        # override must NOT swallow it with a worktree-shaped message.
        worktree = tmp_path / ".cantrip-worktrees" / "task-001"
        worktree.mkdir(parents=True)
        f = worktree / "charmcraft.yaml"
        f.write_text("name: my-charm\nsummary: Real summary.\n")
        assert "Real summary." in _infer_purpose(f)

    def test_unrelated_checks_directory_unaffected(self, tmp_path: pathlib.Path) -> None:
        # A ``checks/`` directory that isn't nested under a ``.cantrip*``
        # ancestor should fall through to normal inference.
        unrelated = tmp_path / "src" / "checks"
        unrelated.mkdir(parents=True)
        f = unrelated / "thing.md"
        f.write_text("# Plain heading\n")
        assert "Plain heading" in _infer_purpose(f)

    def test_helper_returns_none_for_unknown(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "regular.py"
        assert _cantrip_artefact_purpose(f) is None


class TestReadTextSafely:
    def test_reads_utf8(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello")
        assert _read_text_safely(f, max_bytes=1024) == "hello"

    def test_rejects_binary(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "bin"
        f.write_bytes(b"\x00\x01\x02")
        assert _read_text_safely(f, max_bytes=1024) is None

    def test_truncates_to_max_bytes(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 2048)
        result = _read_text_safely(f, max_bytes=16)
        assert result is not None
        assert len(result) == 16

    def test_latin1_fallback(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "latin.txt"
        # Byte 0xff is invalid UTF-8 but valid Latin-1 (ÿ).
        f.write_bytes(b"hello \xff")
        assert _read_text_safely(f, max_bytes=1024) == "hello ÿ"

    def test_missing_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        assert _read_text_safely(tmp_path / "missing", max_bytes=1024) is None


class TestRenderPreview:
    def test_short_file_returns_syntax_with_content(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("line1\nline2\nline3\n")
        out = _render_preview(f)
        assert isinstance(out, Syntax)
        assert "line1" in out.code
        assert "line3" in out.code
        # Line numbers are rendered by Rich, not embedded in .code.
        rendered = _render_rich(out)
        assert "line1" in rendered
        assert "1 " in rendered and "3 " in rendered

    def test_long_file_is_truncated_with_notice(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line{i}" for i in range(500)))
        out = _render_preview(f)
        assert isinstance(out, Group)
        rendered = _render_rich(out)
        assert "first 120 lines" in rendered
        # Only the first 120 lines are in the highlighted body.
        assert "line0" in rendered
        assert "line119" in rendered
        assert "line120" not in rendered

    def test_binary_file_shows_notice(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "blob.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
        out = _render_preview(f)
        assert isinstance(out, Text)
        assert "Binary" in str(out)

    def test_empty_file_shows_notice(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        out = _render_preview(f)
        assert isinstance(out, Text)
        assert "Empty" in str(out)


class TestGuessLexer:
    """Smoke-test that common file types get the expected Pygments lexer."""

    def test_python(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("def f():\n    return 1\n")
        assert _guess_lexer(f, f.read_text()) == "python"

    def test_yaml(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "charmcraft.yaml"
        f.write_text("name: x\nsummary: y\n")
        assert _guess_lexer(f, f.read_text()) == "yaml"

    def test_shell_by_extension(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "script.sh"
        f.write_text("echo hi\n")
        lexer = _guess_lexer(f, f.read_text())
        assert lexer in {"bash", "sh", "shell"}

    def test_markdown(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# hi\n")
        assert _guess_lexer(f, f.read_text()) in {"md", "markdown"}

    def test_toml(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\nname = "x"\n')
        assert _guess_lexer(f, f.read_text()) == "toml"

    def test_json(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}\n')
        assert _guess_lexer(f, f.read_text()) == "json"

    def test_rust(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "lib.rs"
        f.write_text("fn main() {}\n")
        assert _guess_lexer(f, f.read_text()) in {"rust", "rs"}

    def test_unknown_falls_back(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "weirdfile.xyznope"
        f.write_text("some text\n")
        # Pygments returns the default text lexer when it can't match.
        lexer = _guess_lexer(f, f.read_text())
        assert lexer == "default"


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
    def test_display_path_relative_when_under_root(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "sub" / "file.py"
        f.parent.mkdir()
        f.write_text("x")
        screen = FileDetailScreen(f, charm_root=tmp_path)
        assert screen._display_path == "sub/file.py"

    def test_display_path_absolute_when_outside_root(self, tmp_path: pathlib.Path) -> None:
        screen = FileDetailScreen(tmp_path / "file.py", charm_root=pathlib.Path("/other"))
        assert screen._display_path == str(tmp_path / "file.py")

    def test_display_path_without_charm_root(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.py"
        screen = FileDetailScreen(f)
        assert screen._display_path == str(f)


class TestGitLogBlocking:
    def test_file_not_found_returns_marker(self, tmp_path: pathlib.Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "__error__:git not installed"

    def test_timeout_returns_marker(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=10),
        ):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "__error__:git log timed out"

    def test_nonzero_returns_stderr_marker(self, tmp_path: pathlib.Path) -> None:
        mock_result = MagicMock(returncode=128, stderr="not a git repository", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert "not a git repository" in result
        assert result.startswith("__error__:")

    def test_success_returns_stdout(self, tmp_path: pathlib.Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="abc|2d|alice|fix", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = FileDetailScreen._git_log_blocking(tmp_path / "x.py")
        assert result == "abc|2d|alice|fix"


def _rendered(screen: FileDetailScreen) -> str:
    """Return the concatenated rendered text of the output RichLog."""
    output = screen.query_one("#file-output", RichLog)
    return " ".join(line.text for line in output.lines)


class TestFileDetailScreenPilot:
    @pytest.mark.asyncio
    async def test_container_fills_most_of_the_screen(self, tmp_path: pathlib.Path) -> None:
        """Regression: the modal's output area must have a usable size.

        The first version of this screen wrapped the container in
        ``Center()``, which collapsed the Vertical's ``height: 90%`` to
        its children's intrinsic height — one row — leaving the user
        with an empty blue box.  Guard against that by asserting the
        RichLog actually covers a useful slice of the screen.
        """
        f = tmp_path / "hello.py"
        f.write_text('"""Hi."""\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test(size=(120, 40)) as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)

                output = screen.query_one("#file-output", RichLog)
                # Height should be most of the screen, not collapsed to 1.
                assert output.region.height > 10, (
                    f"RichLog collapsed to {output.region.height} rows — "
                    "check the Vertical container's height sizing."
                )

    @pytest.mark.asyncio
    async def test_python_file_renders_docstring_and_preview(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text('"""Greets the world."""\n\ndef hi():\n    return "hi"\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                text = _rendered(screen)
                assert "Purpose" in text
                assert "Greets the world." in text
                assert "def hi" in text
                assert "Content preview" in text

    @pytest.mark.asyncio
    async def test_git_log_error_is_rendered_as_dim_note(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.txt"
        f.write_text("content")
        mock_result = MagicMock(returncode=128, stderr="fatal: not a git repository", stdout="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = _rendered(screen)
                assert "Not tracked by git" in log

    @pytest.mark.asyncio
    async def test_git_log_empty_output_is_no_commits_notice(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.txt"
        f.write_text("content")
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = _rendered(screen)
                assert "No commits" in log

    @pytest.mark.asyncio
    async def test_git_log_renders_entries_on_success(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x.py"
        f.write_text('"""x"""\n')
        stdout = "abc123|2 days ago|Alice|Fix bug\ndef456|1 week ago|Bob|First"
        mock_result = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                log = _rendered(screen)
                assert "abc123" in log
                assert "Alice" in log

    @pytest.mark.asyncio
    async def test_refresh_reruns_git_log(self, tmp_path: pathlib.Path) -> None:
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

    @pytest.mark.asyncio
    async def test_clicking_refresh_button_reruns_git_log(self, tmp_path: pathlib.Path) -> None:
        """Clicking the ``[ r Refresh ]`` footer triggers a refresh too.

        Regression for "the buttons don't work" — the visible labels
        looked like buttons but only the keybindings were wired up;
        clicking did nothing.
        """
        f = tmp_path / "x.py"
        f.write_text('"""x"""\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as run:
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                before = run.call_count
                await pilot.click("#file-refresh-btn")
                await pilot.pause(delay=0.3)
                assert run.call_count > before

    @pytest.mark.asyncio
    async def test_clicking_close_button_dismisses(self, tmp_path: pathlib.Path) -> None:
        """Clicking the ``[ Esc Close ]`` footer dismisses the modal."""
        f = tmp_path / "x.py"
        f.write_text('"""x"""\n')
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            async with _Host().run_test() as pilot:
                screen = FileDetailScreen(f, charm_root=tmp_path)
                await pilot.app.push_screen(screen)
                await pilot.pause(delay=0.3)
                await pilot.click("#file-close-btn")
                await pilot.pause(delay=0.3)
                assert pilot.app.screen is not screen
