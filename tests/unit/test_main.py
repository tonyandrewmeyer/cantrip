"""Tests for the ``cantrip`` CLI entry point.

The module dispatches to ``run`` or ``export-transcript`` subcommands
after argparse resolution.  The tests stub the heavyweight
implementations (``run_web``, ``run_cli``, ``CantripApp``, transcript
renderers) so we can verify the dispatch and validation logic without
launching any actual mode.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip import main as cantrip_main


def _set_argv(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["cantrip", *argv])


class TestParseArgs:
    """``parse_args`` has a bit of bespoke behaviour beyond argparse."""

    def test_defaults_to_run_when_no_subcommand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch)
        args = cantrip_main.parse_args()
        assert args.command == "run"
        assert args.provider == "gemini"
        assert args.no_tui is False
        assert args.web is False
        assert args.path == pathlib.Path.cwd()

    def test_bare_path_is_treated_as_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _set_argv(monkeypatch, str(tmp_path))
        args = cantrip_main.parse_args()
        assert args.command == "run"
        assert args.path == tmp_path

    def test_flag_only_invocation_becomes_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch, "--no-tui")
        args = cantrip_main.parse_args()
        assert args.command == "run"
        assert args.no_tui is True

    def test_run_subcommand_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(
            monkeypatch,
            "run",
            "--provider",
            "claude",
            "--model",
            "opus-4",
            "--no-tui",
            "--concurrency",
            "5",
            "--theme",
            "ubuntu",
        )
        args = cantrip_main.parse_args()
        assert args.provider == "claude"
        assert args.model == "opus-4"
        assert args.no_tui is True
        assert args.concurrency == 5
        assert args.theme == "ubuntu"

    def test_web_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch, "--web", "--web-port", "9090")
        args = cantrip_main.parse_args()
        assert args.web is True
        assert args.web_port == 9090

    def test_improve_flag_takes_a_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        target = tmp_path / "existing-charm"
        target.mkdir()
        _set_argv(monkeypatch, "--improve", str(target))
        args = cantrip_main.parse_args()
        assert args.improve == target

    def test_light_provider_choices_enforced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch, "--light-provider", "nope")
        with pytest.raises(SystemExit):
            cantrip_main.parse_args()

    def test_compare_subcommand(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        left = tmp_path / "a"
        right = tmp_path / "b"
        _set_argv(monkeypatch, "compare", str(left), str(right))
        args = cantrip_main.parse_args()
        assert args.command == "compare"
        assert args.left == left
        assert args.right == right

    def test_docs_subcommand_is_not_rewritten_as_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``docs`` must reach its own parser, not fall through to ``run``.

        Regression: the argv fall-through used to omit ``docs`` from its
        known-subcommand allowlist, so ``cantrip docs index --site ops``
        got rewritten as ``cantrip run docs index ...`` and exited with
        an "unrecognized arguments" error.
        """
        _set_argv(monkeypatch, "docs", "list")
        args = cantrip_main.parse_args()
        assert args.command == "docs"
        assert args.docs_command == "list"

    def test_audit_list_subcommand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch, "audit", "list", "--action", "denied", "--tool", "read_file")
        args = cantrip_main.parse_args()
        assert args.command == "audit"
        assert args.audit_command == "list"
        assert args.action == "denied"
        assert args.tool == "read_file"
        assert args.task_id is None
        assert args.audit_path is None

    def test_audit_export_csv_subcommand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_argv(monkeypatch, "audit", "export", "--format", "csv")
        args = cantrip_main.parse_args()
        assert args.command == "audit"
        assert args.audit_command == "export"
        assert args.format == "csv"

    def test_export_transcript_subcommand(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        _set_argv(
            monkeypatch,
            "export-transcript",
            str(tmp_path),
            "--format",
            "markdown",
            "--task",
            "build-1",
            "--phase",
            "build",
            "--since",
            "2026-01-01T00:00:00",
            "--output",
            str(tmp_path / "out.md"),
        )
        args = cantrip_main.parse_args()
        assert args.command == "export-transcript"
        assert args.path == tmp_path
        assert args.fmt == "markdown"
        assert args.filter_task == "build-1"
        assert args.filter_phase == "build"
        assert args.filter_since == "2026-01-01T00:00:00"
        assert args.output == tmp_path / "out.md"


class TestInstallUnraisableHook:
    def test_hook_swallows_event_loop_closed_runtime_errors(self) -> None:
        cantrip_main._install_unraisable_hook()
        # The hook must swallow the exact "Event loop is closed" RuntimeError
        # and still delegate for unrelated ones.  Build a fake unraisable
        # carrying each exception in turn.
        swallowed = SimpleNamespace(exc_value=RuntimeError("Event loop is closed"))
        passthrough = SimpleNamespace(exc_value=RuntimeError("something else"))

        import sys

        calls: list[object] = []
        sys.unraisablehook = lambda obj: calls.append(obj)
        cantrip_main._install_unraisable_hook()

        sys.unraisablehook(swallowed)
        sys.unraisablehook(passthrough)

        assert swallowed not in calls
        assert passthrough in calls


class TestIsCantripSourceTree:
    def test_returns_false_without_pyproject(self, tmp_path: pathlib.Path) -> None:
        assert cantrip_main._is_cantrip_source_tree(tmp_path) is False

    def test_returns_true_for_cantrip_pyproject(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "juju-cantrip"\n\n[project.scripts]\ncantrip = "cantrip.main:main"\n'
        )
        assert cantrip_main._is_cantrip_source_tree(tmp_path) is True

    def test_returns_false_for_other_pyproject(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "some-charm"\n')
        assert cantrip_main._is_cantrip_source_tree(tmp_path) is False

    def test_returns_false_on_unreadable_pyproject(self, tmp_path: pathlib.Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("ignored")
        with mock.patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            assert cantrip_main._is_cantrip_source_tree(tmp_path) is False


def _run_args(tmp_path: pathlib.Path, **overrides: object) -> SimpleNamespace:
    """Build a namespace mirroring the ``run`` sub-parser defaults."""
    base = {
        "command": "run",
        "provider": "gemini",
        "model": None,
        "snap": "gemma3",
        "light_model": None,
        "light_snap": None,
        "light_provider": None,
        "no_tui": False,
        "web": False,
        "web_port": 8471,
        "watcher": False,
        "concurrency": None,
        "improve": None,
        "theme": None,
        "path": tmp_path,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRun:
    """``_run`` validates the target path then dispatches."""

    def test_refuses_cantrip_source_tree(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "juju-cantrip"\n\n[project.scripts]\ncantrip = "cantrip.main:main"\n'
        )
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        rc = cantrip_main._run(_run_args(tmp_path))
        out = capsys.readouterr().out
        assert rc == 1
        assert "refusing to use the cantrip source tree" in out

    def test_improve_requires_directory(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing = tmp_path / "not-a-dir"
        rc = cantrip_main._run(_run_args(tmp_path, improve=missing))
        out = capsys.readouterr().out
        assert rc == 1
        assert "is not a directory" in out

    def test_missing_gemini_api_key(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        rc = cantrip_main._run(_run_args(tmp_path))
        out = capsys.readouterr().out
        assert rc == 1
        assert "GEMINI_API_KEY" in out

    def test_missing_anthropic_api_key(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rc = cantrip_main._run(_run_args(tmp_path, provider="claude"))
        out = capsys.readouterr().out
        assert rc == 1
        assert "ANTHROPIC_API_KEY" in out

    def test_inference_snap_needs_no_key(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with (
            mock.patch("cantrip.cli.run_cli", return_value=0) as run_cli,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path, provider="inference-snap", no_tui=True))
        assert rc == 0
        run_cli.assert_called_once()

    def test_web_mode_dispatches_to_run_web(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        with (
            mock.patch("cantrip.web.server.run_web", return_value=0) as run_web,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path, web=True))
        assert rc == 0
        run_web.assert_called_once()

    def test_web_mode_refuses_improve(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        improve_dir = tmp_path / "existing-charm"
        improve_dir.mkdir()
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        with (
            mock.patch("cantrip.web.server.run_web", return_value=0) as run_web,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path, web=True, improve=improve_dir))
        err = capsys.readouterr().err
        assert rc == 2
        assert "--improve is not supported with --web" in err
        run_web.assert_not_called()

    def test_no_tui_dispatches_to_run_cli(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        with (
            mock.patch("cantrip.cli.run_cli", return_value=0) as run_cli,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path, no_tui=True))
        assert rc == 0
        run_cli.assert_called_once()

    def test_print_with_empty_string_routes_to_print_mode(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--print ""`` must select print mode, not silently fall through.

        A truthy check (``if args.print_goal``) treats the empty string
        as "no print flag" and drops the user into the interactive REPL,
        which is surprising and clobbers any redirected stdin in CI.
        Print mode itself surfaces the empty-goal error with exit 2.
        """
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        with (
            mock.patch("cantrip.print_mode.run_print", return_value=2) as run_print,
            mock.patch("cantrip.cli.run_cli", return_value=0) as run_cli,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path, no_tui=True, print_goal=""))
        assert rc == 2
        run_print.assert_called_once()
        run_cli.assert_not_called()

    def test_tui_mode_launches_cantrip_app(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        fake_app = mock.MagicMock()
        with (
            mock.patch("cantrip.tui.app.CantripApp", return_value=fake_app) as cls,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            rc = cantrip_main._run(_run_args(tmp_path))
        assert rc == 0
        cls.assert_called_once()
        fake_app.run.assert_called_once()

    def test_improve_overrides_positional_path(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        improve_dir = tmp_path / "existing-charm"
        improve_dir.mkdir()
        fake_app = mock.MagicMock()
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        with (
            mock.patch("cantrip.tui.app.CantripApp", return_value=fake_app) as cls,
            mock.patch("cantrip.main._install_unraisable_hook"),
        ):
            cantrip_main._run(_run_args(tmp_path / "other", improve=improve_dir))
        kwargs = cls.call_args.kwargs
        assert kwargs["improve_path"] == improve_dir
        assert kwargs["charm_path"] == improve_dir

    def test_tui_dispatch_prints_update_panel(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_run`` consults ``CantripApp.pending_update_info`` after ``app.run()``."""
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        fake_app = mock.MagicMock()
        fake_app.pending_update_info = "sentinel"
        with (
            mock.patch("cantrip.tui.app.CantripApp", return_value=fake_app),
            mock.patch("cantrip.main._install_unraisable_hook"),
            mock.patch("cantrip.main._print_update_panel") as panel,
        ):
            cantrip_main._run(_run_args(tmp_path))
        panel.assert_called_once_with("sentinel")


class TestPrintUpdatePanel:
    """``_print_update_panel`` handles ``None`` and renders real UpdateInfo."""

    def test_noop_when_info_is_none(self, capsys: pytest.CaptureFixture[str]) -> None:
        cantrip_main._print_update_panel(None)
        assert capsys.readouterr().out == ""

    def test_noop_when_info_is_wrong_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        cantrip_main._print_update_panel("not an UpdateInfo")
        assert capsys.readouterr().out == ""

    def test_renders_known_installer(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cantrip import update

        info = update.UpdateInfo(
            current="0.1.0",
            latest="0.2.0",
            pypi_url="https://pypi.org/project/juju-cantrip/0.2.0/",
            release_timestamp=None,
            release_notes_markdown="## 0.2.0\n\n- New feature.\n",
        )
        with mock.patch(
            "cantrip.update.detect_install_method",
            return_value=update.InstallMethod.UV_TOOL,
        ):
            cantrip_main._print_update_panel(info)
        out = capsys.readouterr().out
        assert "0.2.0" in out
        assert "uv tool upgrade juju-cantrip" in out

    def test_yanked_variant_mentions_yanked(self, capsys: pytest.CaptureFixture[str]) -> None:
        from cantrip import update

        info = update.UpdateInfo(
            current="0.1.0",
            latest="0.2.0",
            pypi_url="https://pypi.org/project/juju-cantrip/0.2.0/",
            release_timestamp=None,
            installed_yanked=True,
        )
        with mock.patch(
            "cantrip.update.detect_install_method",
            return_value=update.InstallMethod.UV_TOOL,
        ):
            cantrip_main._print_update_panel(info)
        assert "yanked" in capsys.readouterr().out

    def test_truncate_notes_caps_long_changelog(self) -> None:
        body = "\n".join(str(i) for i in range(100))
        truncated = cantrip_main._truncate_notes(body, line_cap=10)
        # Cap produces 10 lines plus a trailer about the PyPI URL.
        assert truncated.splitlines()[:10] == [str(i) for i in range(10)]
        assert "PyPI URL" in truncated


class TestExportTranscript:
    def test_error_when_no_cantrip_file(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = SimpleNamespace(path=tmp_path, fmt="html", output=None)
        rc = cantrip_main._export_transcript(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "no .cantrip file" in out

    def test_unknown_format_errors(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".cantrip").write_text("")
        args = SimpleNamespace(path=tmp_path, fmt="xml", output=None)
        with mock.patch(
            "cantrip.transcript.export.load_transcript",
            return_value=SimpleNamespace(messages=[], tasks=[]),
        ):
            rc = cantrip_main._export_transcript(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "unknown format" in out

    def test_corrupt_cantrip_file_yields_friendly_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A non-SQLite ``.cantrip`` file must error cleanly, not traceback.

        Regression: ``load_transcript`` propagated ``sqlite3.DatabaseError``
        out of the CLI, dumping a stack trace at users who pointed at a
        truncated or hand-edited session file.
        """
        (tmp_path / ".cantrip").write_text("not a sqlite database\n")
        args = SimpleNamespace(
            path=tmp_path,
            fmt="html",
            output=None,
            filter_task=None,
            filter_phase=None,
            filter_since=None,
            filter_branch=None,
        )
        rc = cantrip_main._export_transcript(args)
        captured = capsys.readouterr()
        assert rc == 1
        assert "not a valid Cantrip session file" in captured.err

    @pytest.mark.parametrize(
        "fmt, expected_suffix, renderer",
        [
            ("html", ".html", "cantrip.transcript.html.render_html"),
            ("jsonl", ".jsonl", "cantrip.transcript.jsonl.render_jsonl"),
            ("markdown", ".md", "cantrip.transcript.markdown.render_markdown"),
        ],
    )
    def test_writes_output_in_selected_format(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        fmt: str,
        expected_suffix: str,
        renderer: str,
    ) -> None:
        (tmp_path / ".cantrip").write_text("")
        args = SimpleNamespace(path=tmp_path, fmt=fmt, output=None)
        with (
            mock.patch(
                "cantrip.transcript.export.load_transcript",
                return_value=SimpleNamespace(messages=[], tasks=[]),
            ),
            mock.patch(renderer, return_value=f"CONTENT-{fmt}"),
        ):
            rc = cantrip_main._export_transcript(args)
        assert rc == 0
        out_file = tmp_path / f"transcript{expected_suffix}"
        assert out_file.exists()
        assert out_file.read_text() == f"CONTENT-{fmt}"
        assert "exported to" in capsys.readouterr().out

    def test_explicit_output_path_is_respected(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".cantrip").write_text("")
        target = tmp_path / "custom.md"
        args = SimpleNamespace(path=tmp_path, fmt="markdown", output=target)
        with (
            mock.patch(
                "cantrip.transcript.export.load_transcript",
                return_value=SimpleNamespace(messages=[], tasks=[]),
            ),
            mock.patch("cantrip.transcript.markdown.render_markdown", return_value="hi"),
        ):
            cantrip_main._export_transcript(args)
        assert target.read_text() == "hi"

    def test_paginated_html(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".cantrip").write_text("")
        args = SimpleNamespace(
            path=tmp_path,
            fmt="html",
            output=None,
            page_size=5,
            filter_task=None,
            filter_phase=None,
            filter_since=None,
        )
        pages = [
            ("transcript-1.html", "<html>page1</html>"),
            ("transcript-2.html", "<html>page2</html>"),
        ]
        with (
            mock.patch(
                "cantrip.transcript.export.load_transcript",
                return_value=SimpleNamespace(messages=[], tasks=[]),
            ),
            mock.patch(
                "cantrip.transcript.html.render_html_paginated",
                return_value=pages,
            ),
        ):
            rc = cantrip_main._export_transcript(args)
        assert rc == 0
        assert (tmp_path / "transcript-1.html").read_text() == "<html>page1</html>"
        assert (tmp_path / "transcript-2.html").read_text() == "<html>page2</html>"
        assert "2 pages" in capsys.readouterr().out

    def test_paginated_html_respects_output_file_stem(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--output page.html`` with ``--page-size`` uses page's stem."""
        (tmp_path / ".cantrip").write_text("")
        output = tmp_path / "out" / "my-session.html"
        output.parent.mkdir()
        args = SimpleNamespace(
            path=tmp_path,
            fmt="html",
            output=output,
            page_size=2,
            filter_task=None,
            filter_phase=None,
            filter_since=None,
        )

        captured: dict[str, object] = {}

        def _fake_paginated(_data: object, page_size: int, stem: str):
            captured["stem"] = stem
            captured["page_size"] = page_size
            return [(f"{stem}-1.html", "<html>hi</html>")]

        with (
            mock.patch(
                "cantrip.transcript.export.load_transcript",
                return_value=SimpleNamespace(messages=[], tasks=[]),
            ),
            mock.patch(
                "cantrip.transcript.html.render_html_paginated",
                side_effect=_fake_paginated,
            ),
        ):
            cantrip_main._export_transcript(args)

        assert captured["stem"] == "my-session"
        assert captured["page_size"] == 2


class TestCheckpointsCli:
    """Behaviour of ``cantrip checkpoints`` for malformed session files."""

    def test_corrupt_cantrip_file_yields_friendly_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A non-SQLite ``.cantrip`` must error cleanly, not traceback.

        Regression: ``SessionStore.open()`` raised ``sqlite3.DatabaseError``
        out of ``_checkpoints``, dumping a stack trace at users who pointed
        the CLI at a truncated or hand-edited session file.
        """
        db = tmp_path / ".cantrip"
        db.write_text("not a sqlite database\n")
        args = SimpleNamespace(
            db=db,
            checkpoints_command="list",
            task_id=None,
        )
        rc = cantrip_main._checkpoints(args)
        captured = capsys.readouterr()
        assert rc == 2
        assert "not a valid Cantrip session file" in captured.err


class TestMain:
    def test_dispatches_export_transcript(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        args = SimpleNamespace(command="export-transcript", path=tmp_path)
        with (
            mock.patch.object(cantrip_main, "parse_args", return_value=args),
            mock.patch.object(cantrip_main, "_export_transcript", return_value=42) as exp,
        ):
            rc = cantrip_main.main()
        assert rc == 42
        exp.assert_called_once_with(args)

    def test_dispatches_run(self, tmp_path: pathlib.Path) -> None:
        args = SimpleNamespace(command="run", path=tmp_path)
        with (
            mock.patch.object(cantrip_main, "parse_args", return_value=args),
            mock.patch.object(cantrip_main, "_run", return_value=7) as run_fn,
        ):
            rc = cantrip_main.main()
        assert rc == 7
        run_fn.assert_called_once_with(args)

    def test_dispatches_compare(self, tmp_path: pathlib.Path) -> None:
        args = SimpleNamespace(command="compare", left=tmp_path / "a", right=tmp_path / "b")
        with (
            mock.patch.object(cantrip_main, "parse_args", return_value=args),
            mock.patch.object(cantrip_main, "_compare_charms", return_value=3) as cmp_fn,
        ):
            rc = cantrip_main.main()
        assert rc == 3
        cmp_fn.assert_called_once_with(args)

    def test_dispatches_audit(self, tmp_path: pathlib.Path) -> None:
        args = SimpleNamespace(command="audit", audit_command="list")
        with (
            mock.patch.object(cantrip_main, "parse_args", return_value=args),
            mock.patch.object(cantrip_main, "_audit", return_value=5) as audit_fn,
        ):
            rc = cantrip_main.main()
        assert rc == 5
        audit_fn.assert_called_once_with(args)


class TestAuditEntry:
    """``_audit`` reads the JSONL file, filters, and formats."""

    def _write_audit_file(self, path: pathlib.Path) -> None:
        from cantrip.agent.audit import AuditAction, AuditWriter, make_entry

        writer = AuditWriter(path)
        writer.write(
            make_entry(
                tool="juju_status",
                action=AuditAction.ALLOWED,
                policy_name="org-wide+category:build",
                reason="",
                arguments={"model": "dev"},
                task_id="t1",
            )
        )
        writer.write(
            make_entry(
                tool="juju_destroy_model",
                action=AuditAction.DENIED,
                policy_name="org-wide+category:infra",
                reason="policy blocks",
                arguments={"model": "dev"},
                task_id="t2",
            )
        )

    def test_list_returns_error_when_file_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = SimpleNamespace(
            audit_command="list",
            audit_path=tmp_path / "missing.jsonl",
            task_id=None,
            action=None,
            tool=None,
        )
        rc = cantrip_main._audit(args)
        assert rc == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_list_emits_jsonl_per_line(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / ".cantrip-audit.jsonl"
        self._write_audit_file(path)
        args = SimpleNamespace(
            audit_command="list",
            audit_path=path,
            task_id=None,
            action=None,
            tool=None,
        )
        rc = cantrip_main._audit(args)
        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 2
        parsed = [cantrip_main.json.loads(line) for line in out]
        assert {row["tool"] for row in parsed} == {"juju_status", "juju_destroy_model"}

    def test_list_filters_by_action(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / ".cantrip-audit.jsonl"
        self._write_audit_file(path)
        args = SimpleNamespace(
            audit_command="list",
            audit_path=path,
            task_id=None,
            action="denied",
            tool=None,
        )
        rc = cantrip_main._audit(args)
        assert rc == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1
        assert "juju_destroy_model" in lines[0]

    def test_list_filters_by_task_id(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / ".cantrip-audit.jsonl"
        self._write_audit_file(path)
        args = SimpleNamespace(
            audit_command="list",
            audit_path=path,
            task_id="t1",
            action=None,
            tool=None,
        )
        rc = cantrip_main._audit(args)
        assert rc == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1
        assert "t1" in lines[0]

    def test_export_csv(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / ".cantrip-audit.jsonl"
        self._write_audit_file(path)
        args = SimpleNamespace(
            audit_command="export",
            audit_path=path,
            format="csv",
        )
        rc = cantrip_main._audit(args)
        assert rc == 0
        out = capsys.readouterr().out
        # CSV header + two rows.
        lines = out.strip().splitlines()
        assert len(lines) == 3
        assert lines[0].split(",")[0] == "timestamp"
        assert "juju_status" in out
        assert "juju_destroy_model" in out


class TestCompareCharmsEntry:
    """The ``_compare_charms`` CLI entry-point validates paths and prints the report."""

    def test_missing_left_path_returns_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = SimpleNamespace(left=tmp_path / "nope", right=tmp_path)
        rc = cantrip_main._compare_charms(args)
        assert rc == 1
        assert "left charm path is not a directory" in capsys.readouterr().out

    def test_missing_right_path_returns_error(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a").mkdir()
        args = SimpleNamespace(left=tmp_path / "a", right=tmp_path / "nope")
        rc = cantrip_main._compare_charms(args)
        assert rc == 1
        assert "right charm path is not a directory" in capsys.readouterr().out

    def test_prints_report(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "charmcraft.yaml").write_text("name: alpha\n")
        (b / "charmcraft.yaml").write_text("name: beta\n")
        args = SimpleNamespace(left=a, right=b)
        rc = cantrip_main._compare_charms(args)
        assert rc == 0
        output = capsys.readouterr().out
        assert "alpha" in output
        assert "beta" in output
        assert "Comparing" in output
