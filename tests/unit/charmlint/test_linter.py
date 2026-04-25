"""Tests for charmlint.linter."""

from pathlib import Path

from charmlint.config import LintConfig
from charmlint.linter import build_context, lint
from charmlint.models import Severity
from tests.unit.charmlint.conftest import (
    make_full_charm,
    write_charm_source,
    write_charmcraft_yaml,
)


class TestBuildContext:
    """Tests for context loading."""

    def test_loads_metadata(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "my-charm"})
        ctx = build_context(tmp_charm)
        assert ctx.metadata["name"] == "my-charm"

    def test_loads_actions(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {"name": "test", "actions": {"backup": {"description": "Run backup"}}},
        )
        ctx = build_context(tmp_charm)
        assert "backup" in ctx.actions

    def test_loads_python_sources(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(tmp_charm, "import ops\n")
        ctx = build_context(tmp_charm)
        assert len(ctx.python_files) == 1
        assert len(ctx.python_sources) == 1

    def test_detects_tests(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        ctx = build_context(tmp_charm)
        assert ctx.has_tests_unit is True
        assert ctx.has_tests_integration is True

    def test_no_tests(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        ctx = build_context(tmp_charm)
        assert ctx.has_tests_unit is False
        assert ctx.has_tests_integration is False


class TestLintFiltering:
    """Tests for config-based rule filtering."""

    def test_select_categories(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        config = LintConfig(select=["META"])
        report = lint(tmp_charm, config)
        for d in report.diagnostics:
            assert d.rule_id.startswith("META"), f"Unexpected rule: {d.rule_id}"

    def test_ignore_rules(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        config = LintConfig(ignore=["TEST001"])
        report = lint(tmp_charm, config)
        assert "TEST001" not in {d.rule_id for d in report.diagnostics}

    def test_severity_override(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        config = LintConfig(severity_overrides={"COS001": "error"})
        report = lint(tmp_charm, config)
        cos001 = [d for d in report.diagnostics if d.rule_id == "COS001"]
        assert cos001
        assert cos001[0].severity == Severity.ERROR

    def test_disable_rule(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        config = LintConfig(severity_overrides={"COS001": "off"})
        report = lint(tmp_charm, config)
        assert "COS001" not in {d.rule_id for d in report.diagnostics}

    def test_min_severity_filter(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        config = LintConfig(min_severity=Severity.ERROR)
        report = lint(tmp_charm, config)
        for d in report.diagnostics:
            assert d.severity == Severity.ERROR

    def test_no_metadata_returns_fatal(self, tmp_path: Path):
        charm_dir = tmp_path / "empty"
        charm_dir.mkdir()
        report = lint(charm_dir)
        assert report.error_count == 1
        assert report.diagnostics[0].rule_id == "FATAL"
        assert "No charmcraft.yaml" in report.diagnostics[0].message

    def test_malformed_charmcraft_yaml_returns_parse_error(self, tmp_path: Path):
        charm_dir = tmp_path / "broken"
        charm_dir.mkdir()
        # Mapping value with a colon at top level confuses safe_load.
        (charm_dir / "charmcraft.yaml").write_text("name: foo\nbad: this: that\n")
        report = lint(charm_dir)
        assert report.error_count == 1
        diag = report.diagnostics[0]
        assert diag.rule_id == "FATAL"
        # The misleading "No charmcraft.yaml" text must NOT appear when
        # the file is right there but malformed.
        assert "No charmcraft.yaml" not in diag.message
        assert "Could not parse charmcraft.yaml" in diag.message
