"""Tests for charmlint rules."""

from pathlib import Path

from charmlint.linter import lint
from charmlint.models import Severity
from tests.unit.charmlint.conftest import (
    make_full_charm,
    write_charm_source,
    write_charmcraft_yaml,
)


class TestMetadataRules:
    """Tests for metadata field checks."""

    def test_missing_name_is_error(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"display-name": "X"})
        report = lint(tmp_charm)
        ids = {d.rule_id for d in report.diagnostics}
        assert "META001" in ids
        meta001 = [d for d in report.diagnostics if d.rule_id == "META001"][0]
        assert meta001.severity == Severity.ERROR

    def test_full_metadata_no_meta_diagnostics(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        meta_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("META")}
        assert not meta_ids


class TestObservabilityRules:
    """Tests for COS and ops-tracing checks."""

    def test_missing_cos_relations(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        report = lint(tmp_charm)
        cos_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("COS")}
        assert {"COS001", "COS002", "COS003", "COS004", "COS005"} <= cos_ids

    def test_cos_present_no_diagnostics(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        cos_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("COS")}
        assert not cos_ids

    def test_ops_tracing_in_requirements(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        (tmp_charm / "requirements.txt").write_text("ops\nops-tracing\n")
        report = lint(tmp_charm)
        assert "COS005" not in {d.rule_id for d in report.diagnostics}


class TestTestingRules:
    """Tests for test presence and framework usage."""

    def test_no_tests_detected(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        report = lint(tmp_charm)
        ids = {d.rule_id for d in report.diagnostics}
        assert "TEST001" in ids
        assert "TEST002" in ids

    def test_with_tests_present(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        test_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("TEST")}
        assert not test_ids

    def test_harness_detected(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        (tmp_charm / "tests").mkdir()
        (tmp_charm / "tests" / "test_charm.py").write_text("from ops.testing import Harness\n")
        report = lint(tmp_charm)
        assert "TEST003" in {d.rule_id for d in report.diagnostics}


class TestDeprecatedRules:
    """Tests for deprecated API detection."""

    def test_stored_state_detected(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(tmp_charm, "class MyCharm:\n    _stored = StoredState()\n")
        report = lint(tmp_charm)
        dep_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("DEP")}
        assert "DEP001" in dep_ids

    def test_clean_source_no_deprecated(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(tmp_charm, "import ops\n\nclass MyCharm(ops.CharmBase): pass\n")
        report = lint(tmp_charm)
        dep_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("DEP")}
        assert not dep_ids


class TestLibraryRules:
    """Tests for fetch-libs PyPI checks."""

    def test_known_pypi_detected(self, tmp_charm: Path):
        """tls_certificates_interface has a real PyPI replacement."""
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(
            tmp_charm,
            (
                "from charms.tls_certificates_interface.v3.tls_certificates "
                "import TLSCertificatesRequiresV3\n"
            ),
        )
        report = lint(tmp_charm)
        diagnostics = {d.rule_id: d.message for d in report.diagnostics}
        assert "LIB001" in diagnostics
        # Ensure the new import hint is surfaced to the user.
        assert "charmlibs-interfaces-tls-certificates" in diagnostics["LIB001"]
        assert "from charmlibs.interfaces import tls_certificates" in diagnostics["LIB001"]

    def test_operator_libs_linux_submodule_detected(self, tmp_charm: Path):
        """``operator_libs_linux`` splits by submodule — ``apt`` → ``charmlibs-apt``."""
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(
            tmp_charm, "from charms.operator_libs_linux.v0.apt import DebianPackage\n"
        )
        report = lint(tmp_charm)
        diagnostics = {d.rule_id: d.message for d in report.diagnostics}
        assert "LIB001" in diagnostics
        assert "charmlibs-apt" in diagnostics["LIB001"]

    def test_observability_libs_still_need_fetch_libs(self, tmp_charm: Path):
        """grafana_k8s has no PyPI equivalent yet — LIB002, not LIB001."""
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(
            tmp_charm, "from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboard\n"
        )
        report = lint(tmp_charm)
        rule_ids = {d.rule_id for d in report.diagnostics}
        assert "LIB002" in rule_ids
        assert "LIB001" not in rule_ids

    def test_unknown_lib_detected(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        write_charm_source(tmp_charm, "from charms.my_custom_lib.v1.module import Foo\n")
        report = lint(tmp_charm)
        assert "LIB002" in {d.rule_id for d in report.diagnostics}


class TestActionRules:
    """Tests for action quality checks."""

    def test_missing_expected_actions(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        report = lint(tmp_charm)
        act_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("ACT")}
        assert {"ACT001", "ACT002", "ACT003"} <= act_ids

    def test_action_aliases_accepted(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {
                "name": "test",
                "actions": {
                    "health-check": {"description": "Check health"},
                    "stop": {"description": "Stop"},
                    "start": {"description": "Start"},
                },
            },
        )
        report = lint(tmp_charm)
        act_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("ACT")}
        # Aliases should satisfy ACT001, ACT002, ACT003.
        assert "ACT001" not in act_ids
        assert "ACT002" not in act_ids
        assert "ACT003" not in act_ids

    def test_action_missing_description(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {"name": "test", "actions": {"backup": {}}},
        )
        report = lint(tmp_charm)
        assert "ACT004" in {d.rule_id for d in report.diagnostics}


class TestConfigRules:
    """Tests for config option quality checks."""

    def test_config_missing_fields(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {"name": "test", "config": {"options": {"port": {}}}},
        )
        report = lint(tmp_charm)
        cfg_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("CFG")}
        assert {"CFG001", "CFG002", "CFG003"} <= cfg_ids

    def test_config_complete_no_diagnostics(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        cfg_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("CFG")}
        assert not cfg_ids


class TestSecurityRules:
    """Tests for security checks."""

    def test_secret_in_plain_config(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {
                "name": "test",
                "config": {
                    "options": {
                        "admin-password": {"type": "string", "description": "Admin password"},
                    },
                },
            },
        )
        write_charm_source(tmp_charm, "import ops\n")
        report = lint(tmp_charm)
        assert "SEC001" in {d.rule_id for d in report.diagnostics}

    def test_secret_with_juju_secrets_ok(self, tmp_charm: Path):
        write_charmcraft_yaml(
            tmp_charm,
            {
                "name": "test",
                "config": {
                    "options": {
                        "admin-password": {"type": "string", "description": "Password"},
                    },
                },
            },
        )
        write_charm_source(tmp_charm, "import ops\n# Uses juju secret API\nSecretChanged\n")
        report = lint(tmp_charm)
        assert "SEC001" not in {d.rule_id for d in report.diagnostics}


class TestStructureRules:
    """Tests for structure/file presence checks."""

    def test_missing_files_detected(self, tmp_charm: Path):
        write_charmcraft_yaml(tmp_charm, {"name": "test"})
        report = lint(tmp_charm)
        str_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("STR")}
        assert {"STR001", "STR002", "STR003"} <= str_ids

    def test_all_files_present(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        str_ids = {d.rule_id for d in report.diagnostics if d.rule_id.startswith("STR")}
        assert not str_ids


class TestFullCharm:
    """Integration test — a well-formed charm should have minimal diagnostics."""

    def test_full_charm_minimal_issues(self, tmp_charm: Path):
        make_full_charm(tmp_charm)
        report = lint(tmp_charm)
        # A full charm should have very few issues, if any.
        assert report.error_count == 0
        # The remaining diagnostics should only be info-level items
        # that the full charm doesn't cover (TLS, some docs topics).
        for d in report.diagnostics:
            assert d.severity != Severity.ERROR, f"Unexpected error: {d.rule_id} {d.message}"
