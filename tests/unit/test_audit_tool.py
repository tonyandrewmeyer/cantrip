"""Tests for the charm audit tool."""

import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools.audit import (
    CharmAuditTool,
    _check_cos_relations,
    _check_fetch_libs,
    _check_listing_fields,
    _check_modern_patterns,
    _check_ops_tracing,
    _check_tests,
    _check_type_annotations,
    _collect_python_files,
    _scan_deprecated_apis,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def tool():
    return CharmAuditTool()


def _write_charmcraft_yaml(charm_dir: Path, extra: str = "") -> None:
    """Write a minimal charmcraft.yaml."""
    (charm_dir / "charmcraft.yaml").write_text(f"name: test-charm\ntype: charm\n{extra}")


# ===================================================================
# TestCheckCosRelations
# ===================================================================


class TestCheckCosRelations:
    """Tests for _check_cos_relations."""

    def test_no_relations(self) -> None:
        result = _check_cos_relations({"name": "test"})
        assert not any(result.values())

    def test_tracing_present(self) -> None:
        metadata = {
            "requires": {
                "tracing": {"interface": "tracing"},
            },
        }
        result = _check_cos_relations(metadata)
        assert result["tracing"] is True
        assert result["metrics-endpoint"] is False

    def test_all_cos_relations(self) -> None:
        metadata = {
            "requires": {
                "tracing": {"interface": "tracing"},
                "logging": {"interface": "logging"},
            },
            "provides": {
                "metrics": {"interface": "metrics-endpoint"},
                "dashboards": {"interface": "grafana-dashboard"},
            },
        }
        result = _check_cos_relations(metadata)
        assert result["tracing"] is True
        assert result["logging"] is True
        assert result["metrics-endpoint"] is True
        assert result["grafana-dashboard"] is True


# ===================================================================
# TestCheckListingFields
# ===================================================================


class TestCheckListingFields:
    """Tests for _check_listing_fields."""

    def test_empty_metadata(self) -> None:
        result = _check_listing_fields({})
        assert not any(result.values())

    def test_partial_fields(self) -> None:
        result = _check_listing_fields(
            {
                "display-name": "My Charm",
                "summary": "A test charm",
            }
        )
        assert result["display-name"] is True
        assert result["summary"] is True
        assert result["description"] is False


# ===================================================================
# TestCheckTests
# ===================================================================


class TestCheckTests:
    """Tests for _check_tests."""

    def test_no_tests_directory(self, temp_dir) -> None:
        result = _check_tests(temp_dir)
        assert result["unit_tests"] is False
        assert result["integration_tests"] is False

    def test_unit_tests_present(self, temp_dir) -> None:
        unit_dir = temp_dir / "tests" / "unit"
        unit_dir.mkdir(parents=True)
        (unit_dir / "test_charm.py").write_text("def test_install(): pass\n")

        result = _check_tests(temp_dir)
        assert result["unit_tests"] is True

    def test_empty_test_dir_not_counted(self, temp_dir) -> None:
        """A test directory with no test_*.py files is not counted."""
        (temp_dir / "tests" / "unit").mkdir(parents=True)
        result = _check_tests(temp_dir)
        assert result["unit_tests"] is False

    def test_integration_tests_present(self, temp_dir) -> None:
        integ_dir = temp_dir / "tests" / "integration"
        integ_dir.mkdir(parents=True)
        (integ_dir / "test_charm.py").write_text("def test_deploy(): pass\n")

        result = _check_tests(temp_dir)
        assert result["integration_tests"] is True


# ===================================================================
# TestCheckOpsTracing
# ===================================================================


class TestCheckOpsTracing:
    """Tests for _check_ops_tracing."""

    def test_not_present(self, temp_dir) -> None:
        assert _check_ops_tracing(temp_dir, []) is False

    def test_in_requirements_txt(self, temp_dir) -> None:
        (temp_dir / "requirements.txt").write_text("ops>=2.0\nops-tracing>=1.0\n")
        assert _check_ops_tracing(temp_dir, []) is True

    def test_in_source_code(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        charm_py = src / "charm.py"
        charm_py.write_text("import ops_tracing\nops_tracing.setup(self)\n")
        assert _check_ops_tracing(temp_dir, [charm_py]) is True


# ===================================================================
# TestCollectPythonFiles
# ===================================================================


class TestCollectPythonFiles:
    """Tests for _collect_python_files."""

    def test_empty_dir(self, temp_dir) -> None:
        assert _collect_python_files(temp_dir) == []

    def test_finds_src_files(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("pass\n")
        (src / "helpers.py").write_text("pass\n")

        result = _collect_python_files(temp_dir)
        names = {p.name for p in result}
        assert "charm.py" in names
        assert "helpers.py" in names


# ===================================================================
# TestScanDeprecatedApis
# ===================================================================


class TestScanDeprecatedApis:
    """Tests for _scan_deprecated_apis."""

    def test_no_deprecated_apis(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text("import ops\nclass MyCharm(ops.CharmBase): pass\n")
        assert _scan_deprecated_apis([f]) == []

    def test_detects_stored_state(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text("from ops.framework import StoredState\n")

        result = _scan_deprecated_apis([f])
        assert len(result) == 1
        assert result[0]["api"] == "StoredState"

    def test_detects_harness(self, temp_dir) -> None:
        tests_dir = temp_dir / "tests"
        tests_dir.mkdir()
        f = tests_dir / "test_charm.py"
        f.write_text("from ops.testing import Harness\n")

        result = _scan_deprecated_apis([f])
        assert any(r["api"] == "Harness" for r in result)

    def test_deduplicates(self, temp_dir) -> None:
        """Each deprecated API is reported at most once."""
        src = temp_dir / "src"
        src.mkdir()
        f1 = src / "charm.py"
        f1.write_text("x = StoredState()\n")
        f2 = src / "helpers.py"
        f2.write_text("y = StoredState()\n")

        result = _scan_deprecated_apis([f1, f2])
        stored = [r for r in result if r["api"] == "StoredState"]
        assert len(stored) == 1


# ===================================================================
# TestCharmAuditTool
# ===================================================================


class TestCharmAuditTool:
    """Integration tests for CharmAuditTool.execute."""

    @pytest.mark.asyncio
    async def test_missing_metadata(self, tool, temp_dir) -> None:
        """Returns error when no charmcraft.yaml is present."""
        result = await tool.execute(path=str(temp_dir))
        assert not result.success
        assert "charmcraft.yaml" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tool) -> None:
        result = await tool.execute(path="/nonexistent/path")
        assert not result.success

    @pytest.mark.asyncio
    async def test_minimal_charm(self, tool, temp_dir) -> None:
        """A minimal charm has many findings."""
        _write_charmcraft_yaml(temp_dir)

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "test-charm"
        assert result.data["total_issues"] > 0
        # Should flag missing tests, COS, README, etc.
        assert result.data["gaps"]["unit_tests"] is True
        assert result.data["gaps"]["cos_tracing"] is True
        assert result.data["gaps"]["readme"] is True

    @pytest.mark.asyncio
    async def test_well_equipped_charm(self, tool, temp_dir) -> None:
        """A charm with COS, tests, and metadata has fewer issues."""
        _write_charmcraft_yaml(
            temp_dir,
            extra=(
                "display-name: Test Charm\n"
                "summary: A test charm\n"
                "description: Detailed description\n"
                "docs: https://docs.example.com\n"
                "issues: https://github.com/test/issues\n"
                "source: https://github.com/test/charm\n"
                "tags:\n  - testing\n"
                "requires:\n"
                "  tracing:\n    interface: tracing\n"
                "  logging:\n    interface: logging\n"
                "provides:\n"
                "  metrics-endpoint:\n    interface: metrics-endpoint\n"
                "  grafana-dashboard:\n    interface: grafana-dashboard\n"
            ),
        )
        # Add tests.
        unit_dir = temp_dir / "tests" / "unit"
        unit_dir.mkdir(parents=True)
        (unit_dir / "test_charm.py").write_text("pass\n")
        integ_dir = temp_dir / "tests" / "integration"
        integ_dir.mkdir(parents=True)
        (integ_dir / "test_charm.py").write_text("pass\n")
        # Add README and LICENSE.
        (temp_dir / "README.md").write_text("# Test Charm\n")
        (temp_dir / "LICENSE").write_text("Apache-2.0\n")
        # Add requirements with ops-tracing.
        (temp_dir / "requirements.txt").write_text("ops>=2.0\nops-tracing>=1.0\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["gaps"]["unit_tests"] is False
        assert result.data["gaps"]["integration_tests"] is False
        assert result.data["gaps"]["cos_tracing"] is False
        assert result.data["gaps"]["readme"] is False
        assert result.data["gaps"]["licence"] is False

    @pytest.mark.asyncio
    async def test_output_is_markdown(self, tool, temp_dir) -> None:
        """The output is a formatted Markdown audit report."""
        _write_charmcraft_yaml(temp_dir)

        result = await tool.execute(path=str(temp_dir))

        assert result.output.startswith("# Audit Report:")

    @pytest.mark.asyncio
    async def test_legacy_metadata_yaml(self, tool, temp_dir) -> None:
        """Falls back to metadata.yaml when charmcraft.yaml is absent."""
        (temp_dir / "metadata.yaml").write_text("name: legacy-charm\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "legacy-charm"

    @pytest.mark.asyncio
    async def test_deprecated_apis_in_data(self, tool, temp_dir) -> None:
        """Deprecated APIs are reported in the data dict."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from ops.framework import StoredState\nclass MyCharm:\n    _stored = StoredState()\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert len(result.data["deprecated_apis"]) >= 1
        assert result.data["deprecated_apis"][0]["api"] == "StoredState"

    @pytest.mark.asyncio
    async def test_fetch_libs_in_data(self, tool, temp_dir) -> None:
        """Fetch-libs findings are reported in the data dict."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert len(result.data["fetch_libs"]) >= 1
        assert result.data["fetch_libs"][0]["lib_prefix"] == "data_platform_libs"
        assert result.data["fetch_libs"][0]["pypi_package"] == "data-platform-libs"

    @pytest.mark.asyncio
    async def test_fetch_libs_in_report(self, tool, temp_dir) -> None:
        """Fetch-libs with known PyPI equivalents appear in the report."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert "grafana-k8s-lib" in result.output


# ===================================================================
# TestCheckFetchLibs
# ===================================================================


class TestCheckFetchLibs:
    """Tests for _check_fetch_libs — detect charm library imports with PyPI equivalents."""

    def test_no_fetch_libs(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text("import ops\nclass MyCharm(ops.CharmBase): pass\n")
        assert _check_fetch_libs([f]) == []

    def test_detects_known_lib(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text("from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires\n")

        result = _check_fetch_libs([f])

        assert len(result) == 1
        assert result[0]["lib_prefix"] == "data_platform_libs"
        assert result[0]["pypi_package"] == "data-platform-libs"

    def test_detects_unknown_lib(self, temp_dir) -> None:
        """Unknown charm libs are flagged without a specific PyPI package."""
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text("from charms.some_unknown_lib.v1.helpers import do_thing\n")

        result = _check_fetch_libs([f])

        assert len(result) == 1
        assert result[0]["lib_prefix"] == "some_unknown_lib"
        assert result[0]["pypi_package"] == ""
        assert "check pypi" in result[0]["advice"].lower()

    def test_deduplicates_same_prefix(self, temp_dir) -> None:
        """Multiple imports from the same charm lib produce one finding."""
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text(
            "from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider\n"
            "from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider\n"
        )

        result = _check_fetch_libs([f])

        assert len(result) == 1
        assert result[0]["lib_prefix"] == "grafana_k8s"

    def test_multiple_libs_detected(self, temp_dir) -> None:
        """Different charm libs each produce a finding."""
        src = temp_dir / "src"
        src.mkdir()
        f = src / "charm.py"
        f.write_text(
            "from charms.grafana_k8s.v0.grafana_dashboard import X\n"
            "from charms.loki_k8s.v1.loki_push_api import Y\n"
        )

        result = _check_fetch_libs([f])

        prefixes = {r["lib_prefix"] for r in result}
        assert "grafana_k8s" in prefixes


# ===================================================================
# TestCheckTypeAnnotations
# ===================================================================


class TestCheckTypeAnnotations:
    """Tests for _check_type_annotations — detect type hint usage."""

    def test_has_annotations(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name: str) -> str:\n    return name\n")
        assert _check_type_annotations([src / "charm.py"]) is True

    def test_no_annotations(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name):\n    return name\n")
        assert _check_type_annotations([src / "charm.py"]) is False

    def test_empty_files(self) -> None:
        assert _check_type_annotations([]) is False

    def test_skips_lib_files(self, temp_dir) -> None:
        lib = temp_dir / "lib"
        lib.mkdir()
        (lib / "helper.py").write_text("def foo() -> int:\n    return 1\n")
        assert _check_type_annotations([lib / "helper.py"]) is False


# ===================================================================
# TestCheckModernPatterns
# ===================================================================


class TestCheckModernPatterns:
    """Tests for _check_modern_patterns — detect modern Ops patterns."""

    def test_reconcile_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _reconcile(self):\n    pass\n")
        result = _check_modern_patterns([src / "charm.py"])
        assert result["holistic_status"] is True

    def test_config_changed_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _on_config_changed(self, event):\n    pass\n")
        result = _check_modern_patterns([src / "charm.py"])
        assert result["config_reconciliation"] is True

    def test_pebble_readiness_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "if container.can_connect():\n    container.push(...)\n"
        )
        result = _check_modern_patterns([src / "charm.py"])
        assert result["pebble_readiness"] is True

    def test_nothing_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')\n")
        result = _check_modern_patterns([src / "charm.py"])
        assert all(not v for v in result.values())

    def test_skips_lib_files(self, temp_dir) -> None:
        lib = temp_dir / "lib"
        lib.mkdir()
        (lib / "helper.py").write_text("def _reconcile(self):\n    pass\n")
        result = _check_modern_patterns([lib / "helper.py"])
        assert result["holistic_status"] is False


# ===================================================================
# TestAuditToolModernisation
# ===================================================================


class TestAuditToolModernisation:
    """Tests for type annotation and modern pattern gaps in audit output."""

    @pytest.fixture
    def tool(self) -> CharmAuditTool:
        return CharmAuditTool()

    @pytest.mark.asyncio
    async def test_type_annotation_gap_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name):\n    return name\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["type_annotations"] is True
        assert "type annotation" in result.output.lower()

    @pytest.mark.asyncio
    async def test_type_annotation_gap_not_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name: str) -> str:\n    return name\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["type_annotations"] is False

    @pytest.mark.asyncio
    async def test_modern_patterns_gap_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["modern_patterns"] is True
        assert "modern pattern" in result.output.lower()

    @pytest.mark.asyncio
    async def test_modern_patterns_in_data(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _reconcile(self):\n    pass\n")

        result = await tool.execute(path=str(temp_dir))

        assert "modern_patterns" in result.data
        assert result.data["modern_patterns"]["holistic_status"] is True
