"""Tests for the per-edit lint feedback loop (Phase 71.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cantrip.agent.tools.base import execute_tool
from cantrip.agent.tools.files import EditFileTool, WriteFileTool
from cantrip.agent.tools.multi_edit import MultiEditTool
from cantrip.agent.tools.post_edit_lint import (
    DiagnosticsReport,
    FileDiagnostic,
    _parse_ty_line,
    collect_touched_paths,
    run_post_edit_diagnostics,
)

if TYPE_CHECKING:
    import pathlib

# A Python source that ruff flags loudly — unsorted imports plus an
# unused import.  Keeps the fixture short and the diagnostics
# deterministic across ruff versions.
_BAD_PYTHON = "import sys\nimport os\n\nx = 1\n"

_CLEAN_PYTHON = '"""Module docstring."""\n\n\ndef foo() -> int:\n    return 1\n'


def _build_tools(base_path: pathlib.Path) -> dict[str, object]:
    """Construct the file-edit tools used by every integration test."""
    return {
        "write_file": WriteFileTool(base_path=base_path),
        "edit_file": EditFileTool(base_path=base_path),
        "multi_edit": MultiEditTool(base_path=base_path),
    }


class TestCollectTouchedPaths:
    """Pure function: extract resolved paths from edit-tool arguments."""

    def test_write_file_returns_single_path(self, tmp_path):
        paths = collect_touched_paths(
            "write_file", {"path": "src/foo.py", "content": "x = 1"}, tmp_path
        )
        assert paths == [(tmp_path / "src" / "foo.py").resolve()]

    def test_edit_file_returns_single_path(self, tmp_path):
        paths = collect_touched_paths(
            "edit_file",
            {"path": "metadata.yaml", "old_string": "a", "new_string": "b"},
            tmp_path,
        )
        assert paths == [(tmp_path / "metadata.yaml").resolve()]

    def test_multi_edit_returns_unique_paths(self, tmp_path):
        paths = collect_touched_paths(
            "multi_edit",
            {
                "edits": [
                    {"file": "a.py", "old": "x", "new": "y"},
                    {"file": "b.py", "old": "x", "new": "y"},
                    {"file": "a.py", "old": "y", "new": "z"},  # dedup
                ]
            },
            tmp_path,
        )
        names = {p.name for p in paths}
        assert names == {"a.py", "b.py"}
        assert len(paths) == 2

    def test_absolute_path_kept_as_absolute(self, tmp_path):
        target = tmp_path / "abs.py"
        paths = collect_touched_paths("write_file", {"path": str(target), "content": ""}, tmp_path)
        assert paths == [target.resolve()]

    def test_unknown_tool_returns_empty(self, tmp_path):
        assert collect_touched_paths("read_file", {"path": "x"}, tmp_path) == []

    def test_missing_path_returns_empty(self, tmp_path):
        assert collect_touched_paths("write_file", {"content": "x"}, tmp_path) == []
        assert collect_touched_paths("write_file", {"path": ""}, tmp_path) == []
        # A non-string path should not crash the collector.
        assert collect_touched_paths("write_file", {"path": 42}, tmp_path) == []

    def test_multi_edit_skips_malformed_entries(self, tmp_path):
        paths = collect_touched_paths(
            "multi_edit",
            {
                "edits": [
                    {"file": "a.py", "old": "x", "new": "y"},
                    "not-a-dict",
                    {"file": ""},
                    {"file": 7, "old": "x", "new": "y"},
                ]
            },
            tmp_path,
        )
        assert paths == [(tmp_path / "a.py").resolve()]


class TestParseTyLine:
    """Parser for ``ty check --output-format=concise`` output."""

    def test_typical_diagnostic(self):
        line = "/tmp/foo.py:4:15: error[invalid-syntax] Expected an expression"
        d = _parse_ty_line(line)
        assert d is not None
        assert d.tool == "ty"
        assert d.file == "/tmp/foo.py"
        assert d.line == 4
        assert d.column == 15
        assert d.severity == "error"
        assert d.code == "invalid-syntax"
        assert d.message == "Expected an expression"

    def test_warning_severity(self):
        line = "/x.py:1:1: warning[some-rule] something off"
        d = _parse_ty_line(line)
        assert d is not None
        assert d.severity == "warning"
        assert d.code == "some-rule"

    def test_summary_lines_filtered(self):
        assert _parse_ty_line("Found 1 diagnostic") is None
        assert _parse_ty_line("All checks passed!") is None
        assert _parse_ty_line("") is None

    def test_non_diagnostic_line_returns_none(self):
        assert _parse_ty_line("just a sentence") is None
        assert _parse_ty_line("/x.py:not-a-line:1: error stuff") is None


class TestDiagnosticsReportRendering:
    """Text and structured-data rendering of a populated report."""

    def test_empty_report_renders_to_empty_string(self):
        assert DiagnosticsReport().to_text() == ""
        assert DiagnosticsReport().is_empty() is True

    def test_skipped_only_report_includes_skipped_notes(self):
        report = DiagnosticsReport(skipped=["ruff: binary not found on PATH"])
        text = report.to_text()
        assert "Lint diagnostics" in text
        assert "[skipped] ruff: binary not found on PATH" in text
        assert report.is_empty() is False

    def test_diagnostic_render_includes_code_and_location(self):
        report = DiagnosticsReport(
            diagnostics=[
                FileDiagnostic(
                    tool="ruff",
                    file="src/foo.py",
                    severity="error",
                    code="F401",
                    message="`os` imported but unused",
                    line=2,
                    column=8,
                ),
            ]
        )
        text = report.to_text()
        assert "[ruff] src/foo.py:2:8" in text
        assert "F401" in text
        assert "imported but unused" in text

    def test_to_data_counts_by_severity(self):
        report = DiagnosticsReport(
            diagnostics=[
                FileDiagnostic("ruff", "a", "error", "X", "msg"),
                FileDiagnostic("ruff", "a", "warning", "Y", "msg"),
                FileDiagnostic("ty", "b", "warning", "Z", "msg"),
                FileDiagnostic("charmlint", "c", "info", "W", "msg"),
            ]
        )
        data = report.to_data()
        assert data["counts"] == {"total": 4, "errors": 1, "warnings": 2, "info": 1}
        assert len(data["diagnostics"]) == 4
        assert data["skipped"] == []


class TestRunPostEditDiagnostics:
    """End-to-end run of the diagnostics pipeline against real linters."""

    async def test_no_relevant_files_returns_empty(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("hello")
        report = await run_post_edit_diagnostics([readme], charm_path=tmp_path)
        assert report.is_empty()

    async def test_clean_python_file_produces_no_diagnostics(self, tmp_path):
        target = tmp_path / "clean.py"
        target.write_text(_CLEAN_PYTHON)
        report = await run_post_edit_diagnostics([target], charm_path=tmp_path)
        # Ruff and ty both clean.  We assert no diagnostics rather than
        # is_empty() because a missing ``ty`` binary on a future runner
        # would surface in ``skipped`` — that's still a "no problems".
        assert report.diagnostics == []

    async def test_python_with_ruff_violation_surfaces_diagnostic(self, tmp_path):
        target = tmp_path / "bad.py"
        target.write_text(_BAD_PYTHON)
        report = await run_post_edit_diagnostics([target], charm_path=tmp_path)
        ruff_hits = [d for d in report.diagnostics if d.tool == "ruff"]
        assert ruff_hits, f"expected ruff diagnostics, got: {report.to_text()!r}"
        # F401 = unused import.  Stable since ~ruff 0.0.x.
        assert any(d.code.startswith("F4") or "unused" in d.message for d in ruff_hits)

    async def test_charm_yaml_triggers_charmlint(self, tmp_path):
        # An almost-empty metadata.yaml is enough to draw missing-action
        # warnings from charmlint's library backend.
        meta = tmp_path / "metadata.yaml"
        meta.write_text("name: test\n")
        report = await run_post_edit_diagnostics([meta], charm_path=tmp_path)
        cl_hits = [d for d in report.diagnostics if d.tool == "charmlint"]
        assert cl_hits, f"expected charmlint diagnostics, got: {report.to_text()!r}"

    async def test_yaml_without_charm_path_skips_charmlint(self, tmp_path):
        meta = tmp_path / "metadata.yaml"
        meta.write_text("name: test\n")
        report = await run_post_edit_diagnostics([meta], charm_path=None)
        cl_hits = [d for d in report.diagnostics if d.tool == "charmlint"]
        assert cl_hits == []
        assert report.skipped == []

    async def test_missing_file_silently_dropped(self, tmp_path):
        ghost = tmp_path / "ghost.py"  # never created
        report = await run_post_edit_diagnostics([ghost], charm_path=tmp_path)
        assert report.is_empty()


class TestExecuteToolAutoLint:
    """Integration: execute_tool wires diagnostics into write/edit results."""

    async def test_auto_lint_off_skips_diagnostics(self, tmp_path):
        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools,
            "write_file",
            {"path": "bad.py", "content": _BAD_PYTHON},
            auto_lint=False,
            charm_path=tmp_path,
        )
        assert result.success is True
        assert "Lint diagnostics" not in result.output
        assert "diagnostics" not in result.data

    async def test_auto_lint_default_off_for_subagent_callers(self, tmp_path):
        # Subagents call execute_tool without keyword arguments — no
        # auto_lint, no charm_path.  The hook must stay quiet so
        # subagent transcripts don't bloat with lint addenda.
        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools, "write_file", {"path": "bad.py", "content": _BAD_PYTHON}
        )
        assert result.success is True
        assert "Lint diagnostics" not in result.output

    async def test_write_python_appends_ruff_diagnostics(self, tmp_path):
        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools,
            "write_file",
            {"path": "bad.py", "content": _BAD_PYTHON},
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is True
        assert "Wrote" in result.output  # original tool output preserved
        assert "Lint diagnostics" in result.output
        assert "ruff" in result.output
        assert "diagnostics" in result.data
        assert result.data["diagnostics"]["counts"]["total"] >= 1

    async def test_clean_write_produces_no_diagnostics_block(self, tmp_path):
        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools,
            "write_file",
            {"path": "clean.py", "content": _CLEAN_PYTHON},
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is True
        assert "Lint diagnostics" not in result.output
        assert "diagnostics" not in result.data

    async def test_failed_edit_does_not_run_lint(self, tmp_path):
        # No file at "missing.py" — edit_file fails before any write.
        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools,
            "edit_file",
            {"path": "missing.py", "old_string": "x", "new_string": "y"},
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is False
        assert "Lint diagnostics" not in (result.output or "")
        assert "diagnostics" not in result.data

    async def test_edit_file_lints_after_replacement(self, tmp_path):
        tools = _build_tools(tmp_path)
        target = tmp_path / "x.py"
        target.write_text(_CLEAN_PYTHON)
        result = await execute_tool(
            tools,
            "edit_file",
            {
                "path": "x.py",
                "old_string": '"""Module docstring."""',
                "new_string": "import sys\nimport os",
            },
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is True
        assert "Lint diagnostics" in result.output

    async def test_multi_edit_lints_all_touched_python_files(self, tmp_path):
        tools = _build_tools(tmp_path)
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("good = 1\n")
        b.write_text("good = 1\n")
        result = await execute_tool(
            tools,
            "multi_edit",
            {
                "edits": [
                    {"file": "a.py", "old": "good = 1", "new": "import sys\nimport os"},
                    {"file": "b.py", "old": "good = 1", "new": "import sys\nimport os"},
                ]
            },
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is True
        diagnostics = result.data.get("diagnostics", {}).get("diagnostics", [])
        files_flagged = {d["file"] for d in diagnostics}
        assert any(f.endswith("a.py") for f in files_flagged)
        assert any(f.endswith("b.py") for f in files_flagged)


class TestExecuteToolWithMissingBinary:
    """Skipped notes surface when an external linter is unavailable."""

    async def test_missing_ruff_binary_records_skip(self, tmp_path, monkeypatch):
        from cantrip.agent.tools import post_edit_lint

        original_which = post_edit_lint.shutil.which

        def fake_which(name: str) -> str | None:
            if name in ("ruff", "ty", "charmlint-rs"):
                return None
            return original_which(name)

        monkeypatch.setattr(post_edit_lint.shutil, "which", fake_which)

        tools = _build_tools(tmp_path)
        result = await execute_tool(
            tools,
            "write_file",
            {"path": "x.py", "content": _BAD_PYTHON},
            auto_lint=True,
            charm_path=tmp_path,
        )
        assert result.success is True
        # File-edit succeeded even though the lint hook had nothing
        # to run — the hook's job is feedback, not gating.
        assert "Wrote" in result.output

    async def test_charmlint_python_fallback_records_skip_when_uninstalled(
        self, tmp_path, monkeypatch
    ):
        from cantrip.agent.tools import post_edit_lint

        # No Rust binary, and force the Python-side import to look
        # like the library is missing.
        monkeypatch.setattr(post_edit_lint, "_find_charmlint_binary", lambda: None)

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args, **kwargs):
            if name == "charmlint":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        meta = tmp_path / "metadata.yaml"
        meta.write_text("name: test\n")
        report = await post_edit_lint.run_post_edit_diagnostics([meta], charm_path=tmp_path)
        assert report.diagnostics == []
        assert any("charmlint" in note for note in report.skipped)


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Run each test from ``tmp_path`` so relative resolution is predictable."""
    monkeypatch.chdir(tmp_path)
